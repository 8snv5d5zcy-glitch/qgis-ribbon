"""Erweiterte Digitalisierung: Hilfen schalten ohne Panel, Panel ohne Hilfen."""
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QAction, QApplication, QDockWidget, QMainWindow

from qgis_ribbon.qgis_integration import builtin_commands
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.signals import SignalHub


def settle():
    for _ in range(3):
        QApplication.processEvents()


class FakeCad(QDockWidget):
    """Verhält sich wie QGIS 3.44 (gemessen): Einschalten blendet das Panel ein,
    auch beim Werkzeugwechsel mit aktiver Sitzung; Ein-/Ausblenden schaltet nichts."""

    cadEnabledChanged = pyqtSignal(bool)

    def __init__(self, parent):
        QDockWidget.__init__(self, "Advanced Digitizing", parent)
        self.setObjectName("AdvancedDigitizingTools")
        self.enabled = False
        self.session = False
        self.action = QAction("Enable", self)
        self.action.setCheckable(True)
        self.action.triggered.connect(self.activate)

    def enableAction(self):
        return self.action

    def activate(self, on):
        self.session = on
        if on and not self.isVisible():
            self.show()
        self.set_enabled(on)

    def set_enabled(self, on):
        self.enabled = on
        self.action.setChecked(on)
        self.cadEnabledChanged.emit(on)

    def tool_without_cad(self):
        self.set_enabled(False)

    def tool_with_cad(self):
        if self.session:
            self.activate(True)


class FakeIface(object):
    def __init__(self, cad):
        self.cad = cad

    def cadDockWidget(self):
        return self.cad

    def activeLayer(self):
        return None


def test_aids_toggle_without_panel_and_panel_without_aids():
    window = QMainWindow()
    cad = FakeCad(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, cad)
    window.show()
    cad.hide()
    settle()
    hub = SignalHub()
    env = CommandEnv(FakeIface(cad), None, None, hub)
    try:
        act = builtin_commands.konstruktionshilfen(env, type("C", (), {"label": "Advanced Digitizing"})())
        assert not act.isChecked()
        act.trigger()
        settle()
        assert cad.enabled and act.isChecked() and not cad.isVisible()
        # Werkzeugwechsel: QGIS blendet das Panel wieder ein, der Ribbon nimmt das zurück
        cad.tool_without_cad()
        cad.tool_with_cad()
        settle()
        assert cad.enabled and not cad.isVisible()
        # Panel ein- und ausblenden ändert die Hilfen nicht
        cad.show()
        settle()
        assert cad.isVisible() and cad.enabled
        cad.hide()
        settle()
        assert cad.enabled
        # bei sichtbarem Panel bleibt es sichtbar
        cad.show()
        settle()
        act.trigger()
        settle()
        assert not cad.enabled and not act.isChecked() and cad.isVisible()
        act.trigger()
        settle()
        assert cad.enabled and cad.isVisible()
        cad.tool_without_cad()
        cad.tool_with_cad()
        settle()
        assert cad.isVisible()
        # nach dem Entladen gilt wieder das Verhalten von QGIS
        hub.disconnect_all()
        cad.hide()
        settle()
        cad.tool_without_cad()
        cad.tool_with_cad()
        settle()
        assert cad.isVisible()
    finally:
        hub.disconnect_all()
        env.close()
        window.close()
        window.deleteLater()
        settle()
