"""SignalHub: Trennen beim Entladen, auch wenn C++ den Sender schon gelöscht hat."""
from qgis.PyQt.QtWidgets import QAction, QMenu

from qgis_ribbon.qgis_integration.signals import SignalHub


def test_disconnect_all_separates_live_senders():
    hub, calls = SignalHub(), []
    action = QAction("a")
    hub.connect(action, "changed", lambda: calls.append(1))
    action.setText("b")
    hub.disconnect_all()
    action.setText("c")
    assert calls == [1] and len(hub) == 0


def test_disconnect_all_skips_senders_deleted_by_cpp():
    # Wie eine Aktion eines C++-Plugins, das QGIS beim Beenden vor dem Ribbon
    # entlädt: QMenu.clear() löscht die Aktion in C++. Ein disconnect darauf
    # stürzte ab (Zugriffsverletzung) statt eine Ausnahme zu werfen.
    hub = SignalHub()
    menu = QMenu()
    action = menu.addAction("x")
    hub.connect(action, "changed", lambda: None)
    hub.connect(menu, "aboutToShow", lambda: None)
    menu.clear()
    hub.disconnect_all()
    assert len(hub) == 0
