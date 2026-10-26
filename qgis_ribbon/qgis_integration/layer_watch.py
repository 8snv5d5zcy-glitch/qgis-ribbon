"""Aktiver Layer und dessen Darstellung für die Steuerelemente (ereignisgesteuert).

Steuerelemente im Ribbon (Deckkraft, Maßstab, Beschriftung ...) zeigen
Eigenschaften des aktiven Layers. ``LayerWatch`` meldet ihnen, wenn der
aktive Layer wechselt oder sich seine Darstellung ändert. Es gibt genau einen
Beobachter für alle Steuerelemente, damit am Layer nur wenige Verbindungen
hängen, egal wie viele Steuerelemente gebaut sind.

Signalverbindungen wie bei ``ContextState``: ``iface`` über den zentralen
``SignalHub``, der aktive Layer über einen eigenen Hub, der bei jedem
Layerwechsel geleert wird. Mehrere Signale in schneller Folge (z. B.
``styleChanged`` und ``repaintRequested`` nach einer Änderung) werden per
``QTimer`` (Intervall 0) zu einer Meldung zusammengefasst.

Gruppen: Ist in der Layerliste eine Gruppe gewählt (kein aktiver Layer),
liefert ``group()`` sie, und beobachtet wird ihre Gruppenebene, falls sie als
Gruppe dargestellt wird. Steuerelemente, die auch für Gruppen gelten
(Deckkraft, Mischmodus, Sichtbarkeitsbereich), lesen und schreiben dann die
Gruppenebene. Ein Wechsel von Gruppe zu Gruppe löst kein
``currentLayerChanged`` aus; deshalb hört der Beobachter auch auf den
aktuellen Knoten der Layerliste.
"""

import time

from qgis.core import QgsVectorLayer
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer

from . import kontext_ops
from .context_state import current_group, watch_tree_selection
from .signals import SignalHub

# Signale des aktiven Layers, nach denen die Steuerelemente neu lesen.
# Maßstabsbereich und Beschriftung haben kein eigenes Signal; Änderungen
# darüber (Layereigenschaften, Layer-Styling, Legende) lösen styleChanged
# bzw. repaintRequested aus. Die Bearbeitungssignale schalten Befehle wie
# „Verwerfen“ für den aktiven Layer frei.
LAYER_SIGNALS = ("opacityChanged", "blendModeChanged", "rendererChanged", "styleChanged",
                 "repaintRequested")
VECTOR_SIGNALS = ("featureBlendModeChanged", "editingStarted", "editingStopped", "layerModified",
                  "afterRollBack", "afterCommitChanges")


class LayerWatch(object):
    def __init__(self, iface, hub):
        self.iface = iface
        self.hub = hub
        self.layer_hub = SignalHub()
        self.layer = None
        self._group = None
        self.notifications = 0          # Zähler für Tests und Messung
        self.last_notify_ms = None      # Messpunkt: alle Steuerelemente lesen neu
        self._listeners = []
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._notify)
        self._running = False

    def start(self):
        self._running = True
        self.hub.connect(self.iface, "currentLayerChanged", self._on_layer_changed)
        watch_tree_selection(self.iface, self.hub, self._on_tree_changed)
        self._watch(self.iface.activeLayer())

    def stop(self):
        self._running = False
        self._timer.stop()
        self.layer_hub.disconnect_all()
        self.layer = None
        self._group = None
        self._listeners = []

    def subscribe(self, listener):
        """``listener(layer)`` bei Wechsel oder Änderung des aktiven Layers."""
        self._listeners.append(listener)

    def unsubscribe(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def active_layer(self):
        return self.layer

    def group(self):
        """Gewählte Gruppe (``QgsLayerTreeGroup``), wenn kein Layer aktiv ist, sonst None."""
        if self._group is not None and sip.isdeleted(self._group):
            self._group = None
        return self._group

    def ensure_group_layer(self):
        """Gewählte Gruppe als Gruppe darstellen; deren Gruppenebene (None ohne Gruppe)."""
        group = self.group()
        if group is None:
            return None
        had = group.groupLayer() is not None
        layer = kontext_ops.ensure_group_layer(group)
        if not had:
            self.rewatch()
        return layer

    def rewatch(self):
        """Neu verbinden, z. B. nachdem eine Gruppenebene angelegt oder entfernt wurde."""
        self._watch(self.iface.activeLayer())
        self.schedule()

    def _watch(self, layer):
        self.layer_hub.disconnect_all()
        if layer is not None and sip.isdeleted(layer):
            layer = None
        self.layer = layer
        self._group = current_group(self.iface) if layer is None else None
        target = layer if layer is not None else kontext_ops.group_layer(self._group)
        if target is None:
            return
        self.layer_hub.connect(target, "willBeDeleted", self._on_layer_deleted)
        names = LAYER_SIGNALS + (VECTOR_SIGNALS if isinstance(target, QgsVectorLayer) else ())
        for name in names:
            if getattr(target, name, None) is not None:
                self.layer_hub.connect(target, name, self.schedule)

    def _on_layer_changed(self, layer):
        if layer is not self.layer:
            self._watch(layer)
        self.schedule()

    def _on_tree_changed(self, *_args):
        self._watch(self.iface.activeLayer())
        self.schedule()

    def _on_layer_deleted(self):
        self.layer_hub.disconnect_all()
        self.layer = None
        self.schedule()

    def schedule(self, *_args):
        if self._running and not self._timer.isActive():
            self._timer.start()

    def notify_now(self):
        """Sofort melden (z. B. nach einer eigenen Änderung, damit der Ribbon gleich stimmt)."""
        self._timer.stop()
        self._notify()

    def _notify(self):
        if not self._running:
            return
        start = time.perf_counter()
        self.notifications += 1
        for listener in list(self._listeners):
            listener(self.layer)
        self.last_notify_ms = (time.perf_counter() - start) * 1000.0
