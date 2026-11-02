"""Ribbon im Layout-Fenster: Aufbau, Abbau, Schalter, Einstieg im Hauptfenster.

Einen echten Designer gibt es hier nicht, weil er ``QgisApp`` braucht. Das Fenster
ist eine Attrappe mit den Namen aus ``ribbon_layout.yaml``. Fensterzustand im echten
QGIS, Bericht und Beenden prüft eine eigene Sonde außerhalb der Tests.
"""
import json
import os

import pytest
from qgis.core import (QgsApplication, QgsLayoutItemPage, QgsLayoutItemRegistry, QgsPrintLayout, QgsProject,
                       QgsReport)
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeySequence, QPalette
from qgis.PyQt.QtWidgets import (QAction, QApplication, QDialog, QDockWidget, QInputDialog, QMainWindow, QMenu,
                                 QToolBar, QToolButton, QWidget)

from qgis_ribbon.core import config_loader
from qgis_ribbon.core import customization as cz
from qgis_ribbon.designer_ribbon import TOOLBAR_NAME, DesignerRibbons
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration import action_resolver, builtin_commands, layout_ops
from qgis_ribbon.qgis_integration.arrangements import Arrangements
from qgis_ribbon.qgis_integration.toolbar_manager import SETTINGS_KEY, ToolbarManager
from qgis_ribbon.qgis_integration.user_settings import LAYOUT_SCOPE, UserSettings
from qgis_ribbon.core.model import Command, Source
from qgis_ribbon.ui.controls import layout_item as layout_item_controls

BARS = ["mLayoutToolbar", "mNavigationToolbar", "mActionsToolbar", "mAtlasToolbar"]
ALL_BARS = BARS + ["mToolsToolbar"]
ITEMS = [  # wie die Registry im echten QGIS: (Typname, Gruppe)
    ("LayoutMap", ""), ("LayoutPicture", ""), ("LayoutLabel", ""), ("LayoutLegend", ""), ("LayoutScaleBar", ""),
    ("LayoutPicture", ""), ("LayoutShape", "shapes"), ("LayoutShape", "shapes"), ("LayoutShape", "shapes"),
    ("LayoutMarker", ""), ("LayoutPolyline", ""), ("LayoutPolygon", "nodes"), ("LayoutPolyline", "nodes"),
    ("LayoutHtml", ""), ("LayoutAttributeTable", ""), ("LayoutManualTable", ""), ("LayoutElevationProfile", ""),
    ("Layout3DMap", ""),
]


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)
    QgsApplication.processEvents()


class _Meta(object):
    def __init__(self, type_name, group):
        value = getattr(QgsLayoutItemRegistry.ItemType, type_name)
        self._type = int(getattr(value, "value", value))
        self._group = group

    def type(self):
        return self._type

    def groupId(self):  # noqa: N802 (QGIS)
        return self._group


class _Registry(object):
    def itemMetadataIds(self):  # noqa: N802 (QGIS)
        return list(range(len(ITEMS)))

    def itemMetadata(self, i):  # noqa: N802 (QGIS)
        return _Meta(*ITEMS[i])


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setattr(action_resolver, "_item_registry", _Registry)


def build_window(with_dynamic_text=True):
    """Layout-Fenster mit denselben Namen wie im echten QGIS."""
    win = QMainWindow()
    win.setCentralWidget(QWidget(win))
    win.resize(1400, 900)
    ribbon = config_loader.load(config_loader.LAYOUT_CONFIG)
    bars = {}
    docks = []
    for name in ALL_BARS + ["mReportToolbar"]:
        bars[name] = QToolBar(name, win)
        bars[name].setObjectName(name)
        area = Qt.ToolBarArea.LeftToolBarArea if name == "mToolsToolbar" else Qt.ToolBarArea.TopToolBarArea
        win.addToolBar(area, bars[name])
    bars["mReportToolbar"].hide()
    for cmd in ribbon.commands.values():
        if cmd.source.type == "designer_action":
            act = QAction(cmd.label, win)
            act.setObjectName(cmd.source.get("object_name"))
            act.setCheckable(cmd.id in ("gitter", "lineale", "layout_verschieben"))
            if len(bars["mLayoutToolbar"].actions()) < 5:
                bars["mLayoutToolbar"].addAction(act)
        elif cmd.source.type == "dock":
            dock = QDockWidget(cmd.label, win)
            dock.setObjectName(cmd.source.get("object_name"))
            win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            if docks:
                win.tabifyDockWidget(docks[0], dock)
            docks.append(dock)
    bar = win.menuBar()
    edit = bar.addMenu("Bearbeiten")
    edit.setObjectName("menuEdit")
    for key in (QKeySequence.StandardKey.Undo, QKeySequence.StandardKey.Redo, None, QKeySequence.StandardKey.Cut,
                QKeySequence.StandardKey.Copy, QKeySequence.StandardKey.Paste):
        if key is None:
            edit.addSeparator()
            continue
        act = QAction(str(key), win)
        act.setShortcuts(key)
        edit.addAction(act)
    named = QAction("Löschen", win)
    named.setObjectName("mActionAnders")
    edit.addAction(named)
    items = bar.addMenu("Element hinzufügen")
    items.setObjectName("mItemMenu")
    shapes = None
    for i, (_type_name, group) in enumerate(ITEMS):
        target = items
        if group == "shapes":
            shapes = shapes or items.addMenu("Form")
            target = shapes
        act = QAction("Element %d" % i, win)
        act.setData(i)
        act.setCheckable(True)
        target.addAction(act)
        if i == 2 and with_dynamic_text:
            items.addMenu("Dynamischer Text")
    layouts = bar.addMenu("Layouts")
    layouts.setObjectName("mLayoutsMenu")
    preview = bar.addMenu("Vorschau")
    preview.setObjectName("menuPreview")
    return win


class FakeView(QObject):
    layoutSet = pyqtSignal(object)

    def __init__(self):
        QObject.__init__(self)
        self.zoomed = 0
        self.layout = None
        self.page = 0
        self.layoutSet.connect(self._set)

    def _set(self, layout):
        self.layout = layout

    def currentLayout(self):  # noqa: N802 (QGIS)
        return self.layout

    def currentPage(self):  # noqa: N802 (QGIS)
        return self.page

    def zoomFull(self):  # noqa: N802 (QGIS)
        self.zoomed += 1


class FakeDesigner(QObject):
    def __init__(self, master=None, window=None):
        QObject.__init__(self)
        self._window = window if window is not None else build_window()
        self._master = master if master is not None else QgsPrintLayout(QgsProject.instance())
        self._view = FakeView()

    def window(self):
        return self._window

    def masterLayout(self):  # noqa: N802 (QGIS)
        return self._master

    master = masterLayout

    def layout(self):
        return self._master if isinstance(self._master, QgsPrintLayout) else None

    def view(self):
        return self._view

    def atlasPreviewEnabled(self):  # noqa: N802 (QGIS)
        return self.atlas_preview

    atlas_preview = False


class Host(object):
    def __init__(self, settings=None):
        self.calls = []
        self.arrangements = Arrangements(None, UserSettings(settings))

    def lightness(self):
        return 255

    def set_classic(self, on):
        self.calls.append(("classic", on))

    def menubar_toggled(self, on):
        self.calls.append(("menubar", on))

    def switch_toggled(self, on):
        self.calls.append(("switch", on))

    def theme_changed(self):
        self.calls.append(("theme",))


@pytest.fixture
def designer_iface(fake_iface):
    return fake_iface


@pytest.fixture
def designer():
    d = FakeDesigner()
    d.window().show()
    QgsApplication.processEvents()
    yield d
    d.window().close()
    d.window().deleteLater()
    settle()


@pytest.fixture
def ribbons(designer_iface, settings):
    builtin_commands.register_all()      # sonst das Plugin
    layout_item_controls.register_all()
    r = DesignerRibbons(designer_iface, settings, Host(settings))
    yield r
    r.close()
    settle()
    layout_item_controls.unregister_all()
    builtin_commands.unregister_all()


def snapshot(win):
    return {
        "state": bytes(win.saveState()),
        "bars": sorted((tb.objectName(), tb.isHidden()) for tb in win.findChildren(QToolBar)),
        "actions": sorted((a.objectName(), a.isEnabled(), a.isChecked()) for a in win.findChildren(QAction)
                          if a.objectName()),
        "widgets": len(win.findChildren(QWidget)),
        "stylesheet": win.styleSheet(),
        "menu_height": (win.menuBar().minimumHeight(), win.menuBar().maximumHeight()),
    }


def test_build_hides_bars_and_teardown_restores_window_exactly(ribbons, designer, settings):
    settle()
    before = snapshot(designer.window())
    ribbons.start()
    ribbons.opened(designer)
    settle()
    win = designer.window()
    assert win.findChild(QToolBar, TOOLBAR_NAME) is not None
    assert all(win.findChild(QToolBar, name).isHidden() for name in ALL_BARS)
    assert ribbons.ribbons[win].toolbars.hidden and settings.value(SETTINGS_KEY) is None

    ribbon = ribbons.ribbons[win]
    ribbons.closing(designer)
    settle()
    assert not ribbons.ribbons and len(ribbon.hub) == 0
    after = snapshot(win)
    for key in before:
        assert after[key] == before[key], key


def test_every_command_resolves_in_the_window(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    ribbon = ribbons.ribbons[designer.window()]
    missing = [c.id for c in ribbons.base.commands.values() if not ribbon.resolver.resolve(c).available]
    assert missing == []
    for tab in ribbon.widget.tab_ids():
        ribbon.widget.select_tab(tab)
    settle()


def test_buttons_mirror_actions_of_the_layout_window_not_the_main_window(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    ribbon = ribbons.ribbons[designer.window()]
    ribbon.widget.select_tab("ansicht")
    settle()
    source = designer.window().findChild(QAction, "mActionShowGrid")
    btn = ribbon.widget.findChild(QToolButton, "ribbon_btn_gitter")
    btn.click()
    assert source.isChecked() and btn.isChecked()
    source.setChecked(False)
    assert not btn.isChecked()


@pytest.mark.parametrize("command, index", [("element_bild", 1), ("element_nordpfeil", 5), ("element_dreieck", 8),
                                            ("element_pfeil", 10), ("element_polylinie", 12)])
def test_item_tools_are_found_by_type_group_and_number(ribbons, designer, command, index):
    ribbons.start()
    ribbons.opened(designer)
    ribbon = ribbons.ribbons[designer.window()]
    res = ribbon.resolver.resolve(ribbons.base.commands[command])
    assert res.available and res.action.data() == index


def test_dynamic_text_is_the_menu_behind_the_label_tool(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    ribbon = ribbons.ribbons[designer.window()]
    res = ribbon.resolver.resolve(ribbons.base.commands["element_dynamischer_text"])
    assert res.available and res.menu.title() == "Dynamischer Text"


def test_dynamic_text_without_menu_is_grayed_out(designer_iface):
    win = build_window(with_dynamic_text=False)
    resolver = action_resolver.ActionResolver(designer_iface, window=win)
    res = resolver.resolve(Command("x", "X", Source("designer_item", {"item": "LayoutLabel", "submenu": True})))
    assert not res.available
    win.deleteLater()


def test_unknown_item_type_is_grayed_out(designer_iface):
    win = build_window()
    resolver = action_resolver.ActionResolver(designer_iface, window=win)
    assert not resolver.resolve(Command("x", "X", Source("designer_item", {"item": "LayoutGibtsNicht"}))).available
    win.deleteLater()


def test_edit_actions_by_standard_key_and_by_position(designer_iface):
    win = build_window()
    edit = win.findChild(QMenu, "menuEdit")
    unnamed = [a for a in edit.actions() if not a.objectName() and not a.isSeparator()]
    roles = ["undo", "redo", "cut", "copy", "paste"]
    for role, act in zip(roles, unnamed):
        assert action_resolver._edit_action(win, role) is act
    # Der Nutzer hat die Kürzel geändert: dann zählt die Lage im Menü
    for act in unnamed:
        act.setShortcuts([QKeySequence("Ctrl+Shift+F%d" % (unnamed.index(act) + 1))])
    for role, act in zip(roles, unnamed):
        assert action_resolver._edit_action(win, role) is act
    assert action_resolver._edit_action(win, "nein") is None
    win.deleteLater()


@pytest.fixture
def report():
    d = FakeDesigner(QgsReport(QgsProject.instance()))
    d.window().findChild(QToolBar, "mReportToolbar").show()
    d.window().findChild(QToolBar, "mAtlasToolbar").hide()
    d.window().show()
    QgsApplication.processEvents()
    yield d
    d.window().close()
    d.window().deleteLater()
    settle()


def _visible_tabs(widget):
    return {t for t in widget.tab_ids() if widget.tabbar.isTabVisible(widget.tab_ids().index(t))}


def test_report_gets_the_ribbon_and_its_own_tab(ribbons, report):
    ribbons.start()
    ribbons.opened(report)
    ribbon = ribbons.ribbons[report.window()]
    visible = _visible_tabs(ribbon.widget)
    assert "bericht" in visible and "atlas" not in visible and "teilen" not in visible
    assert report.window().findChild(QToolBar, "mReportToolbar").isHidden()
    ribbon.widget.select_tab("bericht")
    settle()
    assert ribbon.resolver.resolve(ribbons.base.commands["bericht_export_pdf"]).available


def test_layout_has_no_report_tab(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    visible = _visible_tabs(ribbons.ribbons[designer.window()].widget)
    assert "bericht" not in visible and {"atlas", "teilen"} <= visible


def test_report_teardown_restores_its_bars_exactly(ribbons, report):
    settle()
    before = snapshot(report.window())
    ribbons.start()
    ribbons.opened(report)
    settle()
    ribbons.closing(report)
    settle()
    after = snapshot(report.window())
    for key in before:
        assert after[key] == before[key], key
    assert not report.window().findChild(QToolBar, "mReportToolbar").isHidden()


def _select_first_item(layout):
    from qgis.core import QgsLayoutItemLabel
    item = QgsLayoutItemLabel(layout)
    layout.addLayoutItem(item)
    layout.setSelectedItem(item)
    return item


def test_report_follows_the_section_shown(ribbons, report):
    ribbons.start()
    ribbons.opened(report)
    old = ribbons.ribbons[report.window()]
    assert old.selection.layout is None and old.selection.items() == []
    old.widget.select_tab("bericht")
    first = QgsPrintLayout(QgsProject.instance())
    first.initializeDefaults()
    report.view().layoutSet.emit(first)
    assert old.selection.layout is first     # sofort, der Neuaufbau kommt danach
    settle()
    # Rückgängig und Wiederholen sind neue Aktionen: neu aufgebaut, Tab bleibt
    ribbon = ribbons.ribbons[report.window()]
    assert ribbon is not old and ribbon.widget.current_tab() == "bericht"
    assert ribbon.selection.layout is first
    _select_first_item(first)
    settle()
    assert len(ribbon.selection.items()) == 1
    assert "layout_format" in _visible_tabs(ribbon.widget)
    # Anderer Abschnitt: Die Auswahl des alten Abschnitts zählt nicht mehr
    second = QgsPrintLayout(QgsProject.instance())
    second.initializeDefaults()
    report.view().layoutSet.emit(second)
    settle()
    ribbon = ribbons.ribbons[report.window()]
    assert ribbon.selection.layout is second and ribbon.selection.items() == []
    assert "layout_format" not in _visible_tabs(ribbon.widget)
    # Der alte Abschnitt hängt nicht mehr am Ribbon
    first.deselectAll()
    _select_first_item(first)
    settle()
    assert ribbon.selection.items() == []


def test_report_has_no_atlas_for_the_controls(report):
    assert layout_ops.atlas_of(report) is None
    report.atlas_preview = True
    assert not layout_ops.atlas_preview_on(report)


def test_start_takes_over_open_windows_and_signals_build(ribbons, designer_iface, designer):
    designer_iface.designers_open.append(designer)
    ribbons.start()
    assert designer.window() in ribbons.ribbons
    second = FakeDesigner()
    designer_iface.signals.layoutDesignerOpened.emit(second)
    assert second.window() in ribbons.ribbons
    designer_iface.signals.layoutDesignerWillBeClosed.emit(second)
    assert second.window() not in ribbons.ribbons
    second.window().deleteLater()


def test_closing_one_window_keeps_the_other_connected(ribbons, designer):
    other = FakeDesigner()
    ribbons.start()
    ribbons.opened(designer)
    ribbons.opened(other)
    ribbon = ribbons.ribbons[designer.window()]
    connected = len(ribbon.hub)
    assert connected
    ribbons.closing(other)
    settle()
    assert len(ribbon.hub) == connected
    source = designer.window().findChild(QAction, "mActionShowRulers")
    ribbon.widget.select_tab("ansicht")
    settle()
    source.setChecked(True)
    assert ribbon.widget.findChild(QToolButton, "ribbon_btn_lineale").isChecked()
    other.window().deleteLater()


def test_failed_build_leaves_the_window_usable(ribbons, designer, monkeypatch):
    before = snapshot(designer.window())
    ribbons.start()

    def broken(*_args, **_kwargs):
        raise RuntimeError("kaputt")
    monkeypatch.setattr("qgis_ribbon.designer_ribbon.RibbonWidget", broken)
    ribbons.opened(designer)
    settle()
    assert not ribbons.ribbons
    assert snapshot(designer.window()) == before


def test_broken_definition_builds_nothing(designer_iface, settings, tmp_path, designer):
    path = tmp_path / "kaputt.yaml"
    path.write_text("version: 1\ntabs: []\n", encoding="utf-8")
    ribbons = DesignerRibbons(designer_iface, settings, Host(settings), config_path=str(path))
    ribbons.start()
    ribbons.opened(designer)
    assert not ribbons.ribbons
    assert designer.window().findChild(QToolBar, TOOLBAR_NAME) is None
    # Anordnungen laufen trotzdem: Der Teil des Layout-Fensters fehlt nur beim Anwenden
    assert ribbons.arrangements.apply_part(cz.read_bundle(cz.make_bundle(None))) == []
    ribbons.close()


def test_menu_offers_the_switch_and_the_editor(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    widget = ribbons.ribbons[designer.window()].widget
    menu = widget.context_menu(widget)
    texts = [a.text() for a in menu.actions()]
    assert [t for t in texts if "KeyTips" in t or "Kürzel" in t]
    assert [t for t in texts if "Customize the Ribbon" in t or "Ribbon anpassen" in t]
    switch = [a for a in menu.actions() if a.objectName() == "ribbon_designer_ribbon"]
    assert switch and switch[0].isChecked()
    switch[0].trigger()
    assert ("switch", False) in ribbons.host.calls
    menu.deleteLater()


def test_settings_are_separate_from_the_main_window(settings):
    main, layout = UserSettings(settings), UserSettings(settings, LAYOUT_SCOPE)
    layout.set_quick_access("a,b")
    layout.set_minimized(True)
    layout.set_keytips({"x": "Y"})
    layout.set_layout({"tabs": []})
    assert main.quick_access() is None and not main.minimized() and main.keytips() == {} and main.layout() is None
    main.set_quick_access("c")
    assert layout.quick_access() == "a,b"
    # Design, klassische Oberfläche und Menüleiste gelten für beide
    main.set_menubar_hidden(True)
    main.set_design("mode", "dark")
    assert layout.menubar_hidden() and layout.design()["mode"] == "dark"
    assert main.designer_ribbon() and layout.designer_ribbon()
    layout.set_designer_ribbon(False)
    assert not main.designer_ribbon()
    main.set_designer_ribbon(True)
    assert settings.value("qgis_ribbon/layout/ribbon") is None


def test_toolbar_manager_without_memory_writes_no_settings(designer, settings):
    tm = ToolbarManager(designer.window(), settings, remember=False)
    tm.hide(["mLayoutToolbar"])
    assert tm.hidden == ["mLayoutToolbar"]
    assert settings.value(SETTINGS_KEY) is None
    tm.restore()
    assert not designer.window().findChild(QToolBar, "mLayoutToolbar").isHidden()
    tm.deleteLater()


# Mit dem Plugin
@pytest.fixture
def plugin(designer_iface, settings):
    p = RibbonPlugin(designer_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    if p.designers is not None or p.widget is not None:
        p.unload()
    settle()


def _open(iface, designer):
    iface.designers_open.append(designer)
    iface.signals.layoutDesignerOpened.emit(designer)
    settle()


def test_switch_is_on_by_default(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    assert plugin.designers.active
    assert designer.window().findChild(QToolBar, TOOLBAR_NAME) is not None


def test_definition_loads_with_the_first_window_not_at_startup(plugin, designer_iface, designer):
    assert plugin.designers.base is None
    _open(designer_iface, designer)
    assert plugin.designers.base is not None


def test_switch_removes_and_builds_in_open_window(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    plugin.switch_toggled(False)
    settle()
    assert designer.window().findChild(QToolBar, TOOLBAR_NAME) is None
    assert all(not designer.window().findChild(QToolBar, n).isHidden() for n in ALL_BARS)
    plugin.switch_toggled(True)
    settle()
    assert designer.window().findChild(QToolBar, TOOLBAR_NAME) is not None


def test_rebuild_of_the_main_ribbon_keeps_the_layout_ribbon(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    kept = plugin.designers.ribbons[designer.window()]
    plugin.request_rebuild()
    settle()
    assert plugin.designers.ribbons[designer.window()] is kept
    assert kept.widget is not None


def test_classic_interface_switches_the_layout_window_back(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    plugin.set_classic(True)
    settle()
    assert designer.window().findChild(QToolBar, TOOLBAR_NAME) is None
    assert not plugin.designers.active
    plugin.set_classic(False)
    settle()
    assert designer.window().findChild(QToolBar, TOOLBAR_NAME) is not None


def test_unload_restores_the_open_window_exactly(plugin, designer_iface, designer):
    settle()
    before = snapshot(designer.window())
    _open(designer_iface, designer)
    plugin.unload()
    settle()
    after = snapshot(designer.window())
    for key in before:
        assert after[key] == before[key], key


def test_menu_bar_setting_applies_to_all_windows(plugin, designer_iface, designer, main_window):
    _open(designer_iface, designer)
    ribbon = plugin.designers.ribbons[designer.window()]
    ribbon.widget.request_menubar_hidden(True)
    assert designer.window().menuBar().maximumHeight() == 0
    assert main_window.menuBar().maximumHeight() == 0
    assert plugin.widget.menubar_hidden and plugin.user.menubar_hidden()
    plugin.widget.request_menubar_hidden(False)
    assert designer.window().menuBar().maximumHeight() > 0
    assert not ribbon.widget.menubar_hidden


def test_theme_change_reaches_all_windows_without_loop(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    ribbon = plugin.designers.ribbons[designer.window()]
    seen = []
    plugin.themes.changed.connect(lambda: seen.append("haupt"))
    ribbon.themes.changed.connect(lambda: seen.append("layout"))
    ribbon.themes.set("mode", "dark")
    assert plugin.themes.tokens == ribbon.themes.tokens
    assert seen.count("haupt") == 1 and seen.count("layout") == 1
    seen.clear()
    plugin.themes.set("mode", "light")
    assert plugin.themes.tokens == ribbon.themes.tokens
    assert seen.count("haupt") == 1 and seen.count("layout") == 1


# Gesamtbild
def test_whole_theme_styles_each_window_and_restores_it(plugin, designer_iface, designer):
    settle()
    designer.window().setStyleSheet("QMainWindow {}")
    palette = QPalette(QApplication.palette())
    _open(designer_iface, designer)
    ribbon = plugin.designers.ribbons[designer.window()]
    ribbon.themes.set("whole", True)
    settle()
    assert designer.window().styleSheet() not in ("", "QMainWindow {}")
    assert plugin.iface.mainWindow().styleSheet()
    ribbon.themes.set("whole", False)
    settle()
    assert designer.window().styleSheet() == "QMainWindow {}"
    assert QApplication.palette() == palette


def test_whole_theme_is_taken_back_on_close(plugin, designer_iface, designer):
    settle()
    _open(designer_iface, designer)
    plugin.themes.set("whole", True)
    settle()
    assert designer.window().styleSheet()
    designer_iface.signals.layoutDesignerWillBeClosed.emit(designer)
    settle()
    assert designer.window().styleSheet() == ""


# KeyTips, Suche
def test_keytips_work_in_the_layout_window(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    ribbon = ribbons.ribbons[designer.window()]
    keytips = ribbon.keytips
    assert keytips is not None
    keytips.start()
    settle()
    assert keytips.active
    keytips.exit()
    assert not keytips.active
    ribbons.closing(designer)
    assert ribbon.keytips is None


def test_keytips_do_not_offer_hidden_tabs(ribbons, report):
    ribbons.start()
    ribbons.opened(report)
    keytips = ribbons.ribbons[report.window()].keytips
    shown = {item.tab_id for item in keytips.level0_items() if item.tab_id}
    assert "bericht" in shown and "atlas" not in shown


def test_search_finds_commands_and_actions_of_this_window(ribbons, designer, main_window):
    ribbons.start()
    ribbons.opened(designer)
    widget = ribbons.ribbons[designer.window()].widget
    # Nur dieses Fenster liefert die Aktion, nicht das Hauptfenster
    extra = designer.window().findChild(QMenu, "menuEdit").addAction("Nur im Layout-Fenster")
    foreign = main_window.menuBar().addMenu("Fremd").addAction("Nur im Hauptfenster")
    index = widget.search.build_index()
    assert [e.label for e in index.search("Nur im Layout", 5)] == [extra.text()]
    assert not index.search("Nur im Hauptfenster", 5)
    # Was der Ribbon spiegelt, steht einmal in der Liste: als Befehl des Ribbons
    assert [e.ribbon for e in index.search("Reference", 5) if e.label == "Reference"] in ([True], [])
    assert foreign is not None


# Anordnungen
def _set_quick(arrangements, ids):
    arrangements.save_editor(cz.from_dict(arrangements.user.layout(), arrangements.base)[0], ids)


def test_editor_in_the_layout_window_leaves_the_main_window_alone(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    plugin.designers.arrangements.save_editor(
        cz.from_dict(None, plugin.designers.arrangements.base)[0], ["rueckgaengig"])
    settle()
    assert plugin.designers.arrangements.user.quick_access() == "rueckgaengig"
    assert plugin.user.quick_access() is None
    ribbon = plugin.designers.ribbons[designer.window()]
    assert [c.id for c in ribbon.widget.quick.commands] == ["rueckgaengig"]


def test_saved_arrangement_and_file_contain_both_windows(plugin, designer_iface, designer, tmp_path):
    _open(designer_iface, designer)
    layout = plugin.designers.arrangements
    _set_quick(layout, ["wiederholen"])
    settle()
    path = str(tmp_path / "anordnung.json")
    layout.export(path, "Beide")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["layout_window"]["quick_access"] == ["wiederholen"]
    plugin.arrangements.save_as("Beide")
    _set_quick(layout, ["rueckgaengig"])
    settle()
    assert plugin.arrangements.is_modified()
    plugin.arrangements.load("Beide")
    settle()
    assert layout.user.quick_access() == "wiederholen"
    ribbon = plugin.designers.ribbons[designer.window()]
    assert [c.id for c in ribbon.widget.quick.commands] == ["wiederholen"]
    assert not plugin.arrangements.is_modified() and plugin.arrangements.current_name() == "Beide"
    # Datei wieder einlesen: stellt beide her
    _set_quick(layout, ["rueckgaengig"])
    name, warnings = plugin.arrangements.import_file(path)
    settle()
    assert not warnings and layout.user.quick_access() == "wiederholen"
    assert os.path.isfile(path) and name


def test_older_arrangement_leaves_the_layout_window_untouched(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    layout = plugin.designers.arrangements
    _set_quick(layout, ["wiederholen"])
    settle()
    old = {"format": cz.FORMAT, "version": 4, "layout": None, "quick_access": None, "keytips": {}}
    assert plugin.arrangements.apply_bundle(old) == []
    settle()
    assert layout.user.quick_access() == "wiederholen"
    assert plugin.arrangements.bundle()["layout_window"]["quick_access"] == ["wiederholen"]


def test_reset_covers_both_windows(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    layout = plugin.designers.arrangements
    assert plugin.arrangements.is_standard()
    _set_quick(layout, ["wiederholen"])
    settle()
    assert not plugin.arrangements.is_standard()
    plugin.arrangements.reset()
    settle()
    assert layout.user.quick_access() is None and plugin.arrangements.is_standard()


def test_rebuild_waits_for_an_open_dialog_and_keeps_the_tab(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    old = plugin.designers.ribbons[designer.window()]
    old.widget.select_tab("ansicht")
    dialog = QDialog(designer.window())
    dialog.setModal(True)
    dialog.show()
    QgsApplication.processEvents()
    assert QApplication.activeModalWidget() is dialog
    _set_quick(plugin.designers.arrangements, ["wiederholen"])
    settle()
    assert plugin.designers.ribbons[designer.window()] is old
    dialog.close()
    settle()
    built = plugin.designers.ribbons[designer.window()]
    assert built is not old and built.widget.current_tab() == "ansicht"
    assert [c.id for c in built.widget.quick.commands] == ["wiederholen"]
    dialog.deleteLater()


def test_closing_during_a_pending_rebuild_is_harmless(plugin, designer_iface, designer):
    _open(designer_iface, designer)
    _set_quick(plugin.designers.arrangements, ["wiederholen"])
    designer_iface.signals.layoutDesignerWillBeClosed.emit(designer)
    settle()
    assert not plugin.designers.ribbons


# Tab Erweiterungen
def _plugin_action(window, name="mein_plugin_aktion", bar="mLayoutToolbar"):
    act = QAction("Mein Werkzeug", window)
    act.setObjectName(name)
    window.findChild(QToolBar, bar).addAction(act)
    return act


def test_extensions_tab_only_with_plugin_actions(ribbons, designer):
    ribbons.start()
    ribbons.opened(designer)
    widget = ribbons.ribbons[designer.window()].widget
    assert "erweiterungen" not in widget.tab_ids()


def test_plugin_action_in_a_bar_appears_and_rebuilds_only_this_window(ribbons, designer):
    other = FakeDesigner()
    ribbons.start()
    ribbons.opened(designer)
    ribbons.opened(other)
    kept = ribbons.ribbons[other.window()]
    _plugin_action(designer.window())
    settle()
    widget = ribbons.ribbons[designer.window()].widget
    assert "erweiterungen" in widget.tab_ids()
    assert ribbons.ribbons[other.window()] is kept
    assert "erweiterungen" not in kept.widget.tab_ids()
    ribbons.closing(other)
    other.window().deleteLater()


def test_plugin_action_present_at_start_shows_and_removing_rebuilds(ribbons, designer):
    act = _plugin_action(designer.window())
    ribbons.start()
    ribbons.opened(designer)
    assert "erweiterungen" in ribbons.ribbons[designer.window()].widget.tab_ids()
    designer.window().findChild(QToolBar, "mLayoutToolbar").removeAction(act)
    settle()
    assert "erweiterungen" not in ribbons.ribbons[designer.window()].widget.tab_ids()


def test_own_toolbar_of_a_plugin_stays_visible(ribbons, designer):
    own = QToolBar("Mein Plugin", designer.window())
    own.setObjectName("meinPluginToolbar")
    designer.window().addToolBar(own)
    own.show()
    ribbons.start()
    ribbons.opened(designer)
    assert not own.isHidden()


def test_undo_of_qgis_in_the_bar_is_no_extension(ribbons, designer):
    bar = designer.window().findChild(QToolBar, "mLayoutToolbar")
    bar.addAction(designer.window().findChild(QMenu, "menuEdit").actions()[0])
    ribbons.start()
    ribbons.opened(designer)
    kept = ribbons.ribbons[designer.window()]
    assert "erweiterungen" not in kept.widget.tab_ids()
    # Später hinzugekommen (Bericht, neuer Abschnitt): auch nicht
    bar.addAction(designer.window().findChild(QMenu, "menuEdit").actions()[1])
    settle()
    assert ribbons.ribbons[designer.window()] is kept


def test_item_tools_of_qgis_do_not_count_as_extensions(ribbons, designer):
    tools = designer.window().findChild(QToolBar, "mToolsToolbar")
    act = QAction("Karte", designer.window())
    act.setData(0)        # Registry-ID eines Elements von QGIS
    tools.addAction(act)
    ribbons.start()
    ribbons.opened(designer)
    assert "erweiterungen" not in ribbons.ribbons[designer.window()].widget.tab_ids()


# Seitengröße
def _page_size(layout):
    size = layout.pageCollection().page(0).pageSize()
    return round(size.width()), round(size.height())


def _a4():
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    return layout


def test_page_size_is_one_undo_step():
    layout = _a4()
    before = _page_size(layout)
    count = layout.undoStack().stack().count()
    page = layout.pageCollection().page(0)
    assert layout_ops.set_page_size(layout, page, "A3", "portrait")
    assert _page_size(layout) == (297, 420)
    assert page.orientation() == QgsLayoutItemPage.Orientation.Portrait
    assert layout.undoStack().stack().count() == count + 1
    layout.undoStack().stack().undo()
    assert _page_size(layout) == before


def test_unknown_page_size_adds_no_undo_step():
    layout = _a4()
    count = layout.undoStack().stack().count()
    assert not layout_ops.set_page_size(layout, layout.pageCollection().page(0), "Gibts nicht", "portrait")
    assert layout.undoStack().stack().count() == count


def test_page_size_menu_changes_the_shown_page(ribbons, designer):
    designer.master().initializeDefaults()
    ribbons.start()
    ribbons.opened(designer)
    ribbon = ribbons.ribbons[designer.window()]
    menu = layout_ops.page_size_menu(ribbon.env, ribbons.base.commands["seitengroesse"])
    menu.aboutToShow.emit()
    entries = [a for a in menu.actions() if not a.isSeparator()]
    assert len(entries) == 2 * len(layout_ops.PAGE_SIZES)
    entries[2].trigger()      # A3 quer
    assert _page_size(designer.master()) == (420, 297)


def test_page_size_menu_without_a_section_offers_nothing(ribbons, report):
    ribbons.start()
    ribbons.opened(report)
    ribbon = ribbons.ribbons[report.window()]
    menu = layout_ops.page_size_menu(ribbon.env, ribbons.base.commands["seitengroesse"])
    menu.aboutToShow.emit()
    assert [a.isEnabled() for a in menu.actions()] == [False]


# Vorlagen
TEMPLATE = '''<Layout name="Vorlage" printResolution="300" units="mm">
 <PageCollection>
  <LayoutItem type="65638" size="148,210,mm" position="0,0,mm" positionOnPage="0,0,mm"/>
 </PageCollection>
</Layout>
'''


@pytest.fixture
def template(tmp_path):
    path = tmp_path / "Meine Vorlage.qpt"
    path.write_text(TEMPLATE, encoding="utf-8")
    return str(path)


def _clear_layouts():
    manager = QgsProject.instance().layoutManager()
    for layout in manager.layouts():
        manager.removeLayout(layout)


def test_template_files_are_listed_sorted(tmp_path, monkeypatch, template):
    (tmp_path / "anders.qpt").write_text(TEMPLATE, encoding="utf-8")
    (tmp_path / "keine.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(QgsApplication, "layoutTemplatePaths", lambda: [str(tmp_path), str(tmp_path / "fehlt")])
    assert [name for name, _path in layout_ops.template_files()] == ["anders", "Meine Vorlage"]


def test_new_from_template_creates_and_opens_the_layout(designer_iface, template, monkeypatch):
    _clear_layouts()
    opened = []
    designer_iface.openLayoutDesigner = opened.append
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Aus Vorlage", True))
    layout = layout_ops.new_from_template(designer_iface, template)
    assert layout is not None and opened == [layout]
    assert layout.name() == "Aus Vorlage"
    assert QgsProject.instance().layoutManager().layoutByName("Aus Vorlage") is layout
    assert layout.undoStack().stack().count() == 0
    _clear_layouts()


def test_new_from_template_cancelled_creates_nothing(designer_iface, template, monkeypatch):
    _clear_layouts()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    assert layout_ops.new_from_template(designer_iface, template) is None
    assert not QgsProject.instance().layoutManager().layouts()


def test_new_from_template_keeps_names_unique(designer_iface, template, monkeypatch):
    _clear_layouts()
    existing = _a4()
    existing.setName("Doppelt")
    QgsProject.instance().layoutManager().addLayout(existing)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Doppelt", True))
    assert layout_ops.new_from_template(designer_iface, template) is None
    assert len(QgsProject.instance().layoutManager().layouts()) == 1
    _clear_layouts()


def test_broken_template_is_reported(designer_iface, tmp_path, monkeypatch):
    _clear_layouts()
    path = tmp_path / "kaputt.qpt"
    path.write_text("<nicht", encoding="utf-8")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Kaputt", True))
    assert layout_ops.new_from_template(designer_iface, str(path)) is None
    assert not QgsProject.instance().layoutManager().layouts()


def test_template_menu_lists_files_and_a_chooser(designer_iface, tmp_path, monkeypatch):
    from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
    env = CommandEnv(designer_iface)
    command = Command("x", "X", Source("custom", {"id": "ribbon.layout_aus_vorlage"}))
    (tmp_path / "a.qpt").write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(QgsApplication, "layoutTemplatePaths", lambda: [str(tmp_path)])
    menu = layout_ops.new_from_template_menu(env, command)
    menu.aboutToShow.emit()
    assert [a.text() for a in menu.actions() if not a.isSeparator()][0] == "a"
    monkeypatch.setattr(QgsApplication, "layoutTemplatePaths", lambda: [])
    menu.aboutToShow.emit()
    first = menu.actions()[0]
    assert not first.isEnabled()
    env.close()


# Einstieg im Hauptfenster
def test_main_ribbon_offers_layouts_and_page_sizes():
    ribbon = config_loader.load()
    project = next(g for g in ribbon.tab("einfuegen").groups if g.id == "projekt")
    split = next(e for e in project.elements if getattr(getattr(e, "command", None), "id", "") == "neues_layout")
    assert [c.id for c in split.items] == ["neues_layout_a4_quer", "neues_layout_a4_hoch", "neues_layout_a3_quer",
                                           "neues_layout_a3_hoch"]
    assert "layout_oeffnen" in [getattr(getattr(e, "command", None), "id", "") for e in project.elements]
    share = [getattr(getattr(e, "command", None), "id", "") for g in ribbon.tab("teilen").groups for e in g.elements]
    assert "layout_oeffnen" in share
    assert ribbon.commands["drucken"].source.get("object_name") == "mActionShowLayoutManager"


def _new_layout_action(iface, designer=None):
    act = QAction("Neu", iface.mainWindow())
    act.setObjectName(layout_ops.NEW_LAYOUT_ACTION)
    if designer is not None:
        act.triggered.connect(lambda: iface.layoutDesignerOpened.emit(designer))
    return act


def test_new_layout_sets_page_after_the_qgis_action(designer_iface):
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    designer = FakeDesigner(layout)
    _new_layout_action(designer_iface, designer)
    layout_ops.new_layout(designer_iface, "A3", "portrait")
    size = layout.pageCollection().page(0).pageSize()
    assert (round(size.width()), round(size.height())) == (297, 420)
    assert designer.view().zoomed == 1
    assert layout.undoStack().stack().count() == 0
    designer.window().deleteLater()


def test_cancelled_name_dialog_changes_nothing(designer_iface):
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    size = layout.pageCollection().page(0).pageSize()
    other = FakeDesigner(layout)
    _new_layout_action(designer_iface)    # QGIS öffnet kein Fenster
    layout_ops.new_layout(designer_iface, "A3", "portrait")
    # Der Handler ist wieder getrennt: Ein später geöffnetes Fenster behält seine Seite
    designer_iface.layoutDesignerOpened.emit(other)
    assert layout.pageCollection().page(0).pageSize() == size
    other.window().deleteLater()


def test_new_layout_without_action_reports_error(designer_iface):
    with pytest.raises(RuntimeError):
        layout_ops.new_layout(designer_iface, "A4", "landscape")


def test_unknown_page_size_keeps_the_page():
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    size = layout.pageCollection().page(0).pageSize()
    assert layout_ops.set_first_page(layout, "Gibts nicht", "landscape") is False
    assert layout.pageCollection().page(0).pageSize() == size


def test_main_window_command_raises_the_window(designer_iface, main_window):
    main_window.showMinimized()
    QgsApplication.processEvents()
    layout_ops.show_main_window(designer_iface)
    QgsApplication.processEvents()
    assert not main_window.isMinimized()
