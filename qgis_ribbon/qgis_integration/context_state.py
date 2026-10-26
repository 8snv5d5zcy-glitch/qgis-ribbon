"""Kontext-Zustand aus QGIS-Signalen (ereignisgesteuert, kein Polling).

``ContextState`` hört auf den Wechsel des aktiven Layers und auf die
Signale dieses einen Layers (Bearbeitung, Auswahl). Mehrere Signale in
schneller Folge werden mit einem ``QTimer`` (Intervall 0) zu einer
Aktualisierung zusammengefasst. Der Empfänger bekommt den neuen
``Snapshot`` und die seitdem eingetretenen Ereignisse.

Signalverbindungen:

- zu ``iface`` über den zentralen ``SignalHub`` des Plugins;
- zum aktiven Layer über einen eigenen Hub, der bei jedem Layerwechsel
  und beim Entladen geleert wird. So hängen nie Verbindungen an Layern,
  die nicht mehr aktiv sind (keine Lecks, keine Doppelaufrufe).
"""

import time

from qgis.core import QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QTimer

from ..core.conditions import Snapshot
from .signals import SignalHub


def layer_kind(layer):
    if layer is None:
        return None
    if isinstance(layer, QgsVectorLayer):
        return "vector" if layer.isSpatial() else "table"
    if isinstance(layer, QgsRasterLayer):
        return "raster"
    return "other"


def snapshot(layer):
    """QGIS-Layer -> ``Snapshot``."""
    kind = layer_kind(layer)
    if kind in ("vector", "table"):
        return Snapshot(layer_kind=kind, editable=layer.isEditable(),
                        has_selection=layer.selectedFeatureCount() > 0)
    return Snapshot(layer_kind=kind)


class ContextState(object):
    def __init__(self, iface, hub, listener):
        self.iface = iface
        self.hub = hub
        self.listener = listener        # listener(snapshot, events)
        self.layer_hub = SignalHub()    # nur Signale des aktiven Layers
        self.layer = None
        self.events = []
        self.updates = 0                # Zähler für Tests und Messung
        self.last_update_ms = None      # Messpunkt
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._flush)
        self._running = False

    def start(self):
        """Signale verbinden und den Ausgangszustand sofort liefern."""
        self._running = True
        self.hub.connect(self.iface.currentLayerChanged, self._on_layer_changed)
        self._watch(self.iface.activeLayer())
        self._flush()

    def stop(self):
        self._running = False
        self._timer.stop()
        self.layer_hub.disconnect_all()
        self.layer = None
        self.events = []

    # Signale
    def _watch(self, layer):
        self.layer_hub.disconnect_all()
        self.layer = layer
        if layer is None:
            return
        self.layer_hub.connect(layer.willBeDeleted, self._on_layer_deleted)
        if isinstance(layer, QgsVectorLayer):
            self.layer_hub.connect(layer.editingStarted, self._on_editing_started)
            self.layer_hub.connect(layer.editingStopped, self.schedule)
            self.layer_hub.connect(layer.selectionChanged, self.schedule)

    def _on_layer_changed(self, layer):
        if layer is not self.layer:
            self._watch(layer)
        self.schedule()

    def _on_layer_deleted(self):
        self.layer_hub.disconnect_all()
        self.layer = None
        self.schedule()

    def _on_editing_started(self):
        self.events.append("editing_started")
        self.schedule()

    def schedule(self, *_args):
        """Aktualisierung anstoßen; mehrere Aufrufe bis zur Ereignisschleife zählen einmal."""
        if self._running and not self._timer.isActive():
            self._timer.start()

    def _flush(self):
        if not self._running:
            return
        start = time.perf_counter()
        events, self.events = tuple(self.events), []
        self.listener(snapshot(self.layer), events)
        self.updates += 1
        self.last_update_ms = (time.perf_counter() - start) * 1000.0
