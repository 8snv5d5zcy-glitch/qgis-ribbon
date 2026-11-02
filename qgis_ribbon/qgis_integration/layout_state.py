"""Auswahl im Layout-Fenster als Kontext und als Quelle der Steuerelemente (ereignisgesteuert).

``LayoutSelection`` hört auf ``selectionChanged`` des Layouts, auf die Signale der
gewählten Elemente und auf den Rückgängig-Verlauf. Mehrere Signale in schneller
Folge (QGIS meldet beim Wählen Zwischenzustände) fasst ein ``QTimer`` mit
Intervall 0 zusammen. Gemeldet wird zweierlei:

- der Kontext (``listener(snapshot, events)``) nur, wenn sich die Zahl der gewählten
  Elemente oder die Art des einzigen Elements ändert; daraus bestimmt
  ``core.context.ContextLogic`` die Kontext-Tabs;
- den Steuerelementen (``subscribe``) bei jeder Änderung, damit sie ihre Werte neu lesen.

Die Signale der Elemente hängen an einem eigenen Hub, der bei jeder Auswahl geleert
wird; so bleiben keine Verbindungen an Elementen, die nicht mehr gewählt sind. Bei
einer Tabelle ist das gewählte Element ein Rahmen, ihre Werte stehen am Multiframe.
Auch der Atlas meldet über denselben Weg (Vorschau, aktuelles Objekt, Objektliste).

Berichte: Das Fenster zeigt je Abschnitt ein anderes Layout, zu Beginn oft keines. Der
``DesignerRibbon`` meldet den Wechsel über ``set_layout``; das Layout selbst hat dann keinen
Atlas, und es kann mit seinem Abschnitt gelöscht werden.
"""

import time

from qgis.core import (QgsLayoutFrame, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
                       QgsLayoutItemMarker, QgsLayoutItemPicture, QgsLayoutItemPolygon, QgsLayoutItemPolyline,
                       QgsLayoutItemScaleBar, QgsLayoutItemShape, QgsLayoutTable)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer

from ..core.conditions import Snapshot
from .signals import SignalHub

# Signale eines gewählten Elements, nach denen die Steuerelemente neu lesen
ITEM_SIGNALS = ("sizePositionChanged", "rotationChanged", "frameChanged", "backgroundColorChanged",
                "lockChanged", "changed", "extentChanged", "mapRotationChanged", "themeChanged",
                "layerStyleOverridesChanged", "pictureRotationChanged")
MULTIFRAME_SIGNALS = ("changed", "contentsChanged")
ATLAS_SIGNALS = ("toggled", "changed", "coverageLayerChanged", "featureChanged", "numberFeaturesChanged",
                 "renderBegun", "renderEnded")
KINDS = ((QgsLayoutItemMap, "map"), (QgsLayoutItemLabel, "label"), (QgsLayoutItemLegend, "legend"),
         (QgsLayoutItemScaleBar, "scalebar"), (QgsLayoutItemPicture, "picture"),
         ((QgsLayoutItemShape, QgsLayoutItemMarker, QgsLayoutItemPolygon, QgsLayoutItemPolyline), "shape"))


def multi_frame(item):
    """Multiframe eines Rahmens (Tabelle, HTML); sonst None."""
    return item.multiFrame() if isinstance(item, QgsLayoutFrame) else None


def kind_of(item):
    """Elementart nach ``core.conditions.ITEM_KINDS``."""
    if isinstance(multi_frame(item), QgsLayoutTable):
        return "table"
    for classes, kind in KINDS:
        if isinstance(item, classes):
            return kind
    return "other"


def snapshot(items, report=False):
    return Snapshot(selected_items=len(items), item_kind=kind_of(items[0]) if len(items) == 1 else None,
                    layout_report=report)


class LayoutSelection(object):
    def __init__(self, layout, hub, listener=None, report=False):
        self.layout = layout            # None: Bericht ohne gezeigtes Layout
        self.hub = hub
        self.listener = listener        # listener(snapshot, events)
        self.report = report
        self.item_hub = SignalHub()     # nur Signale der gewählten Elemente
        self.layout_hub = SignalHub()   # nur Signale des gezeigten Layouts
        self._items = []
        self._context = None
        self.notifications = 0          # Zähler für Tests und Messung
        self.last_notify_ms = None      # Messpunkt: alle Steuerelemente lesen neu
        self._listeners = []
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._flush)
        self._running = False

    def start(self):
        """Signale verbinden und den Ausgangszustand sofort liefern."""
        self._running = True
        self._connect_layout()
        self._watch()
        self._flush()

    def _connect_layout(self):
        self.layout_hub.disconnect_all()
        if self.layout is None:
            return
        self.layout_hub.connect(self.layout, "selectionChanged", self.schedule)
        self.layout_hub.connect(self.layout.undoStack().stack(), "indexChanged", self.schedule)
        if self.report:
            return
        atlas = self.layout.atlas()
        for name in ATLAS_SIGNALS:
            self.layout_hub.connect(atlas, name, self.schedule)

    def set_layout(self, layout):
        """Bericht: Das Fenster zeigt jetzt dieses Layout (eines Abschnitts)."""
        if layout is self.layout:
            return
        self.layout = layout
        self.item_hub.disconnect_all()
        self._items = []
        self._connect_layout()
        self.notify_now()

    def stop(self):
        self._running = False
        self._timer.stop()
        self.item_hub.disconnect_all()
        self.layout_hub.disconnect_all()
        self._items = []
        self._listeners = []

    def subscribe(self, listener):
        """``listener(items)`` bei Änderung der Auswahl oder ihrer Werte."""
        self._listeners.append(listener)

    def unsubscribe(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def items(self):
        """Gewählte Elemente (ohne Seiten), in der Reihenfolge von QGIS."""
        return [i for i in self._items if not sip.isdeleted(i)]

    def schedule(self, *_args):
        """Aktualisierung anstoßen; mehrere Aufrufe bis zur Ereignisschleife zählen einmal."""
        if self._running and not self._timer.isActive():
            self._timer.start()

    def notify_now(self):
        """Sofort melden (z. B. nach einer eigenen Änderung)."""
        self._timer.stop()
        self._flush()

    def _selected(self):
        if self.layout is None or sip.isdeleted(self.layout):   # Abschnitt des Berichts gelöscht
            return []
        return list(self.layout.selectedLayoutItems())

    def _watch(self):
        self.item_hub.disconnect_all()
        self._items = self._selected()
        for item in self._items:
            for name in ITEM_SIGNALS:
                signal = getattr(item, name, None)
                if signal is not None:
                    self.item_hub.connect(item, name, self.schedule)
            multi = multi_frame(item)
            if multi is not None:
                for name in MULTIFRAME_SIGNALS:
                    self.item_hub.connect(multi, name, self.schedule)

    def _flush(self):
        if not self._running:
            return
        start = time.perf_counter()
        if self._selected() != self._items:
            self._watch()
        self.notifications += 1
        state = snapshot(self._items, self.report)
        if state != self._context:
            self._context = state
            if self.listener is not None:
                self.listener(state, [])
        for listener in list(self._listeners):
            listener(self.items())
        self.last_notify_ms = (time.perf_counter() - start) * 1000.0
