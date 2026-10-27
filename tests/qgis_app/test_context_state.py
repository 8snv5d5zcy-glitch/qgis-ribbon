"""Kontext-Zustand aus QGIS-Signalen: Snapshot, Debounce, Trennen beim Layerwechsel."""
from qgis.core import QgsApplication
from qgis.PyQt import sip

from qgis_ribbon.core.conditions import Snapshot
from qgis_ribbon.qgis_integration.context_state import ContextState, snapshot
from qgis_ribbon.qgis_integration.signals import SignalHub

ALL = frozenset({"add", "delete", "rename"})  # Speicherlayer können alle Feldänderungen


class Recorder(object):
    def __init__(self):
        self.calls = []

    def __call__(self, snap, events):
        self.calls.append((snap, events))

    @property
    def last(self):
        return self.calls[-1]


def settle():
    for _ in range(3):
        QgsApplication.processEvents()


def start(fake_iface):
    hub, rec = SignalHub(), Recorder()
    state = ContextState(fake_iface, hub, rec)
    state.start()
    return state, hub, rec


def test_snapshot_of_layer_kinds(layers):
    assert snapshot(None) == Snapshot()
    assert snapshot(layers["vector"]) == Snapshot("vector", field_caps=ALL)
    assert snapshot(layers["table"]) == Snapshot("table", field_caps=ALL)
    assert snapshot(layers["raster"]) == Snapshot("raster")
    v = layers["vector"]
    v.selectByIds([v.allFeatureIds()[0]])
    v.startEditing()
    assert snapshot(v) == Snapshot("vector", editable=True, has_selection=True, field_caps=ALL)
    v.rollBack()
    v.removeSelection()


def test_start_delivers_initial_state_immediately(fake_iface, layers):
    fake_iface.active_layer = layers["table"]
    state, hub, rec = start(fake_iface)
    assert rec.calls == [(Snapshot("table", field_caps=ALL), ())]
    state.stop()
    hub.disconnect_all()


def test_signals_in_quick_succession_are_coalesced(fake_iface, layers):
    state, hub, rec = start(fake_iface)
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    v.selectByIds(v.allFeatureIds()[:1])
    v.selectByIds(v.allFeatureIds()[:2])
    v.startEditing()
    assert len(rec.calls) == 1  # noch nichts, erst in der Ereignisschleife
    settle()
    assert len(rec.calls) == 2
    assert rec.last == (Snapshot("vector", editable=True, has_selection=True, field_caps=ALL), ("editing_started",))
    v.commitChanges()
    settle()
    assert rec.last == (Snapshot("vector", has_selection=True, field_caps=ALL), ())
    v.removeSelection()
    state.stop()
    hub.disconnect_all()


def test_layer_change_disconnects_previous_layer(fake_iface, layers):
    state, hub, rec = start(fake_iface)
    v, t = layers["vector"], layers["table"]
    for _ in range(50):
        fake_iface.set_active_layer(v)
        fake_iface.set_active_layer(t)
    settle()
    assert len(hub) == 2                 # nur currentLayerChanged und aktueller Knoten der Layerliste
    assert len(state.layer_hub) == 4     # willBeDeleted, Bearbeitung an/aus, Auswahl der Tabelle
    assert rec.last[0] == Snapshot("table", field_caps=ALL)
    n = len(rec.calls)
    v.selectByIds(v.allFeatureIds())     # alter Layer: keine Aktualisierung mehr
    v.startEditing()
    settle()
    assert len(rec.calls) == n
    v.rollBack()
    v.removeSelection()
    fake_iface.set_active_layer(layers["raster"])
    assert len(state.layer_hub) == 1     # Raster: nur willBeDeleted
    state.stop()
    hub.disconnect_all()


def test_deleted_active_layer(fake_iface, tmp_path):
    from qgis.core import QgsVectorLayer
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "weg", "memory")
    state, hub, rec = start(fake_iface)
    fake_iface.set_active_layer(layer)
    settle()
    sip.delete(layer)
    settle()
    assert state.layer is None and len(state.layer_hub) == 0
    assert rec.last == (Snapshot(), ())
    state.stop()
    hub.disconnect_all()


def test_stop_ends_updates(fake_iface, layers):
    state, hub, rec = start(fake_iface)
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    state.stop()
    hub.disconnect_all()
    n = len(rec.calls)
    v.selectByIds(v.allFeatureIds())
    fake_iface.set_active_layer(layers["table"])
    settle()
    assert len(rec.calls) == n
    assert len(state.layer_hub) == 0
    v.removeSelection()
