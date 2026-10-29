"""QGIS-Menüleiste ausblenden, Dropdown „QGIS-Menüs“ und Befehle für Einstellungsfenster."""
import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAction, QApplication, QMenu, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration import builtin_commands, menu_bar
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.user_settings import UserSettings


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)
    QgsApplication.processEvents()


def layout(mw):
    mw.layout().activate()
    settle()


def heights(bar):
    return bar.minimumHeight(), bar.maximumHeight()


def widget_count(iface):
    """Widgets des Hauptfensters ohne die Meldungsleiste (deren Hinweise gehören QGIS und laufen ab)."""
    mw = iface.mainWindow()
    return len(mw.findChildren(QWidget)) - len(iface.messageBar().findChildren(QWidget))


def test_hidden_menu_bar_has_no_height_but_stays_visible(main_window):
    bar = main_window.menuBar()
    layout(main_window)
    before = heights(bar)
    assert bar.height() > 0
    hider = menu_bar.MenuBarHider(main_window)
    hider.hide()
    hider.hide()  # zweimal: die Werte von vorher bleiben gemerkt
    layout(main_window)
    assert hider.hidden
    assert bar.height() == 0
    assert bar.isVisible()  # sonst schaltet Qt die Kürzel der Menüaktionen ab
    hider.restore()
    layout(main_window)
    assert not hider.hidden
    assert heights(bar) == before
    assert bar.height() > 0


def test_shortcut_of_a_menu_action_works_with_hidden_menu_bar(main_window):
    act = QAction("Nur im Menü", main_window)
    act.setShortcut(QKeySequence("Ctrl+Shift+F12"))
    main_window.findChild(QMenu, "mViewMenu").addAction(act)
    fired = []
    act.triggered.connect(lambda: fired.append(True))
    hider = menu_bar.MenuBarHider(main_window)
    hider.hide()
    layout(main_window)
    main_window.activateWindow()
    settle()
    if QApplication.activeWindow() is not main_window:
        hider.restore()
        pytest.skip("Hauptfenster wird in dieser Umgebung nicht aktiv")
    QTest.keyClick(main_window, Qt.Key.Key_F12,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    settle()
    hider.restore()
    assert fired


def test_fill_menu_lists_the_menus_of_the_menu_bar(main_window):
    bar = main_window.menuBar()
    counts = [len(a.menu().actions()) for a in bar.actions() if a.menu() is not None]
    menu = QMenu()
    menu_bar.fill_menu(menu, main_window)
    menu_bar.fill_menu(menu, main_window)  # neu gefüllt, nicht angehängt
    assert [a.text() for a in menu.actions()] == [a.text() for a in bar.actions() if a.menu() is not None]
    assert all(a.menu() is not None for a in menu.actions())
    menu.clear()
    menu.deleteLater()
    settle()
    # QGIS-Menüs unverändert und nicht gelöscht
    assert [len(a.menu().actions()) for a in bar.actions() if a.menu() is not None] == counts


def test_qgis_menus_command_is_a_dropdown(fake_iface, settings):
    builtin_commands.register_all()
    resolver = ActionResolver(fake_iface, CommandEnv(fake_iface, settings=settings))
    try:
        ribbon = config_loader.load()
        res = resolver.resolve(ribbon.commands["qgis_menues"])
        assert res.available
        assert isinstance(res.menu, QMenu)
        res.menu.aboutToShow.emit()
        titles = [a.text() for a in res.menu.actions()]
        assert titles == [a.text() for a in fake_iface.mainWindow().menuBar().actions()]
    finally:
        resolver.clear()
        builtin_commands.unregister_all()


def test_option_page_commands_open_their_page(fake_iface, settings):
    resolver = ActionResolver(fake_iface, CommandEnv(fake_iface, settings=settings))
    ribbon = config_loader.load()
    for cid in ("optionen_allgemein", "optionen_darstellung", "optionen_python_konsole", "sucheinstellungen"):
        cmd = ribbon.commands[cid]
        assert resolver.trigger(cmd), cid
        assert fake_iface.calls[-1] == ("showOptionsDialog", None, cmd.source.get("args")[1]), cid
    resolver.clear()


def test_plugin_hides_menu_bar_and_restores_it(fake_iface, settings):
    mw = fake_iface.mainWindow()
    bar = mw.menuBar()
    layout(mw)
    before = heights(bar)
    widgets = widget_count(fake_iface)
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    assert not plugin.widget.menus_button.isVisibleTo(plugin.widget)
    menu = QMenu()
    plugin.widget.add_customize_actions(menu)
    act = menu.findChild(QAction, "ribbon_hide_menubar")
    assert act is not None and act.isCheckable() and not act.isChecked()
    act.trigger()
    menu.deleteLater()
    layout(mw)
    assert bar.height() == 0
    assert UserSettings(settings).menubar_hidden()
    assert plugin.widget.menus_button.isVisibleTo(plugin.widget)

    # Neuaufbau: bleibt ausgeblendet
    plugin.request_rebuild()
    settle()
    layout(mw)
    assert bar.height() == 0 and plugin.widget.menubar_hidden

    # Klassische Oberfläche: Menüleiste zurück, beim Ribbon wieder weg
    plugin.set_classic(True)
    settle()
    layout(mw)
    assert heights(bar) == before and bar.height() > 0
    plugin.set_classic(False)
    settle()
    layout(mw)
    assert bar.height() == 0

    plugin.unload()
    settle()
    layout(mw)
    assert heights(bar) == before and bar.height() > 0
    assert widget_count(fake_iface) == widgets
    assert UserSettings(settings).menubar_hidden()  # Einstellung bleibt für den nächsten Start

    # Nächster Start mit ausgeblendeter Menüleiste, dann wieder einblenden
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    layout(mw)
    assert bar.height() == 0 and plugin.widget.menus_button.isVisibleTo(plugin.widget)
    plugin.widget.request_menubar_hidden(False)
    layout(mw)
    assert heights(bar) == before
    assert not UserSettings(settings).menubar_hidden()
    plugin.unload()
    settle()
