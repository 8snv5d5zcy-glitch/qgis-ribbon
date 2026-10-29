"""Aktionen anderer Plugins (Tab „Erweiterungen“) und Werkzeuge des Werkzeugkastens."""
import json
import sys
import types

import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QAction, QDialog, QMenu, QToolBar, QToolButton

from qgis_ribbon.core import extensions as ext
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration.user_settings import KEY_LAYOUT, KEY_QUICK_ACCESS
from qgis_ribbon.ui.ribbon_editor import RibbonEditor

from test_plugin import settle, snapshot  # noqa: E402 (gleicher Ordner, ohne Paket)


def plugin_menu(mw):
    """Menü „Erweiterungen“ wie in QGIS: eigene Einträge von QGIS, je Plugin ein Untermenü."""
    menu = QMenu("Erweiterungen", mw)
    menu.setObjectName("mPluginMenu")
    manage = QAction("Erweiterungen verwalten …", mw)
    manage.setObjectName("mActionManagePlugins")
    menu.addAction(manage)
    mw.menuBar().addMenu(menu)
    return menu


def add_plugin(mw, menu, name, texts, toolbar=None):
    """Plugin „laden“: Untermenü mit Aktionen, die erste auch als Button in ``toolbar``."""
    sub = menu.addMenu(name)
    acts = []
    for text in texts:
        act = QAction(text, mw)
        sub.addAction(act)
        acts.append(act)
    if toolbar is not None:
        toolbar.addAction(acts[0])
    return sub, acts


@pytest.fixture
def with_plugins(fake_iface):
    mw = fake_iface.mainWindow()
    menu = plugin_menu(mw)
    plugin_tb = mw.findChild(QToolBar, "mPluginToolBar")
    _sub, reload_acts = add_plugin(mw, menu, "Plugin Reloader", ["Plugin neu laden", "Konfigurieren"],
                                   toolbar=plugin_tb)
    own = QToolBar("Vermessung", mw)
    own.setObjectName("VermessungToolbar")
    start = QAction("Messung starten", mw)
    start.setCheckable(True)
    own.addAction(start)
    mw.addToolBar(own)
    settle()
    return {"menu": menu, "reload": reload_acts, "toolbar": own, "start": start}


@pytest.fixture
def plugin(fake_iface, settings, with_plugins):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


def group_labels(p):
    return [g.label for g in p.ribbon.tab("erweiterungen").groups]


def button(p, cid):
    p.widget.ensure_built(p.widget.tab_ids().index("erweiterungen"))
    return p.widget.findChild(QToolButton, "ribbon_btn_" + cid)


def reload_id():
    return ext.plugin_id(ext.key("mPluginMenu", "Plugin Reloader", "Plugin neu laden"))


def test_plugin_actions_appear_in_extension_tab(plugin, with_plugins):
    assert group_labels(plugin) == ["Plugin Reloader", "Vermessung"]
    group = plugin.ribbon.tab("erweiterungen").groups[0]
    assert [e.command.label for e in group.elements] == ["Plugin neu laden", "Konfigurieren"]
    # Eintrag von QGIS selbst und die Werkzeugkiste (steht schon in der Definition) fehlen
    labels = {c.label for c in plugin.ribbon.commands.values() if ext.is_plugin(c.id)}
    assert "Erweiterungen verwalten …" not in labels and "Werkzeugkiste" not in labels

    fired = []
    with_plugins["reload"][0].triggered.connect(lambda: fired.append(1))
    btn = button(plugin, reload_id())
    assert btn is not None and btn.isEnabled()
    btn.defaultAction().trigger()
    assert fired == [1]


def test_checkable_plugin_button_mirrors_state(plugin, with_plugins):
    cid = ext.plugin_id(ext.key("toolbar", "VermessungToolbar", "Messung starten"))
    act = button(plugin, cid).defaultAction()
    assert act.isCheckable() and not act.isChecked()
    with_plugins["start"].setChecked(True)
    assert act.isChecked()
    with_plugins["start"].setEnabled(False)
    assert not act.isEnabled()


def test_plugin_toolbars_hidden_and_restored_exactly(fake_iface, settings, with_plugins):
    mw = fake_iface.mainWindow()
    unnamed = QToolBar("Ohne Namen", mw)
    unnamed.addAction(QAction("Etwas", mw))
    mw.addToolBar(unnamed)
    settle()
    before = snapshot(mw)
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    assert with_plugins["toolbar"].isHidden() and unnamed.isHidden()
    assert mw.findChild(QToolBar, "mPluginToolBar").isHidden()
    assert "Ohne Namen" in group_labels(p)
    p.unload()
    settle()
    assert not with_plugins["toolbar"].isHidden() and not unnamed.isHidden()
    after = snapshot(mw)
    for key in before:
        assert after[key] == before[key], key


def test_plugin_loaded_later_rebuilds_ribbon(plugin, fake_iface, with_plugins):
    mw = fake_iface.mainWindow()
    _sub, acts = add_plugin(mw, with_plugins["menu"], "Neues Plugin", ["Neu tun"])
    settle()
    # Menü-Gruppen vor den Gruppen eigener Leisten
    assert group_labels(plugin) == ["Plugin Reloader", "Neues Plugin", "Vermessung"]
    # neue eigene Leiste eines Plugins: übernommen und ausgeblendet
    later = QToolBar("Später", mw)
    later.setObjectName("SpaeterToolbar")
    later.addAction(QAction("Spät", mw))
    mw.addToolBar(later)
    settle()
    assert "Später" in group_labels(plugin) and later.isHidden()
    # Plugin entladen: Gruppe weg, Leiste kommt beim Entladen des Ribbons nicht zurück (gelöscht)
    with_plugins["menu"].removeAction(_sub.menuAction())
    settle()
    assert "Neues Plugin" not in group_labels(plugin)


def test_no_rebuild_without_change(plugin, fake_iface):
    built = plugin.widget
    dlg = QDialog(fake_iface.mainWindow())   # neues Kind-Widget, aber keine neue Plugin-Aktion
    settle()
    assert plugin.widget is built
    dlg.deleteLater()
    settle()
    assert plugin.widget is built


def test_rebuild_waits_for_modal_dialog(plugin, fake_iface, with_plugins):
    mw = fake_iface.mainWindow()
    built = plugin.widget
    seen = {}

    def during():
        add_plugin(mw, with_plugins["menu"], "Aus der Verwaltung", ["Installiert"])
        settle()
        seen["widget"] = plugin.widget
        dlg.accept()

    dlg = QDialog(mw)
    QTimer.singleShot(0, during)
    dlg.exec()
    settle()
    assert seen["widget"] is built                      # kein Abbau unter dem Dialog
    assert plugin.widget is not built                   # danach neu aufgebaut
    assert "Aus der Verwaltung" in group_labels(plugin)


def test_no_plugins_no_extension_tab(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        assert "erweiterungen" not in p.widget.tab_ids()
    finally:
        p.unload()
        settle()


def tool_layout(*ids):
    return {"tabs": [{"tab": "karte"}, {"id": "eigener_tab_1", "label": "Meine Werkzeuge", "groups": [
        {"id": "eigene_gruppe_1", "label": "Skripte",
         "items": [{"command": c, "size": "large"} for c in ids]}]}]}


def test_toolbox_tools_in_own_group_and_quick_access(fake_iface, settings, with_plugins, monkeypatch):
    settings.setValue(KEY_LAYOUT, json.dumps(tool_layout("verarbeitung:native:buffer",
                                                         "verarbeitung:script:geloescht", reload_id())))
    settings.setValue(KEY_QUICK_ACCESS, "neues_projekt,verarbeitung:native:centroids")
    calls = []
    monkeypatch.setitem(sys.modules, "processing",
                        types.SimpleNamespace(execAlgorithmDialog=lambda alg_id: calls.append(alg_id)))
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        group = p.ribbon.tab("eigener_tab_1").groups[0]
        assert [e.command.label for e in group.elements][1:] == ["geloescht", "Plugin neu laden"]
        p.widget.select_tab("eigener_tab_1")
        settle()
        buffer = p.widget.findChild(QToolButton, "ribbon_btn_verarbeitung:native:buffer")
        gone = p.widget.findChild(QToolButton, "ribbon_btn_verarbeitung:script:geloescht")
        assert buffer.isEnabled() and not gone.isEnabled()
        assert not buffer.icon().isNull()
        buffer.defaultAction().trigger()
        assert calls == ["native:buffer"]
        assert "verarbeitung:native:centroids" in [c.id for c in p.widget.quick.commands]
    finally:
        p.unload()
        settle()


def test_new_script_makes_missing_tool_available(fake_iface, settings, tmp_path):
    from qgis.core import QgsProcessingAlgorithm, QgsProcessingProvider

    class Tool(QgsProcessingAlgorithm):
        def name(self):
            return "neu"

        def displayName(self):  # noqa: N802
            return "Neues Werkzeug"

        def createInstance(self):  # noqa: N802
            return Tool()

        def initAlgorithm(self, config=None):  # noqa: N802
            pass

        def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
            return {}

    class Provider(QgsProcessingProvider):
        def id(self):
            return "testskripte"

        def name(self):
            return "Testskripte"

        def loadAlgorithms(self):  # noqa: N802
            if self.ready:
                self.addAlgorithm(Tool())

    settings.setValue(KEY_LAYOUT, json.dumps(tool_layout("verarbeitung:testskripte:neu")))
    reg = QgsApplication.processingRegistry()
    provider = Provider()
    provider.ready = False
    reg.addProvider(provider)
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        assert not p.resolver.resolve(p.ribbon.commands["verarbeitung:testskripte:neu"]).available
        built = p.widget
        provider.ready = True
        provider.refreshAlgorithms()     # wie beim Speichern eines neuen Skripts
        settle()
        assert p.widget is not built
        cmd = p.ribbon.commands["verarbeitung:testskripte:neu"]
        assert cmd.label == "Neues Werkzeug" and p.resolver.resolve(cmd).available
    finally:
        p.unload()
        settle()
        reg.removeProvider(provider)


def test_editor_palette_offers_plugins_and_toolbox(plugin):
    dlg = RibbonEditor(plugin.arrangements, plugin.widget.window())
    try:
        palette = dlg.palette_box
        filters = [palette.filter.itemData(i) for i in range(palette.filter.count())]
        assert {"plugins", "toolbox"} <= set(filters)
        visible = lambda: {v for k, v in palette.visible_values()}  # noqa: E731
        assert "verarbeitung:native:buffer" not in visible()   # „Alle“: nur eigene Werkzeuge
        # Kacheln der QGIS-Werkzeuge entstehen erst mit dem Filter „Werkzeugkasten“
        own = palette.list.count()
        palette.filter.setCurrentIndex(filters.index("toolbox"))
        assert "verarbeitung:native:buffer" in visible() and palette.list.count() > own + 200
        palette.filter.setCurrentIndex(filters.index("plugins"))
        assert reload_id() in visible() and not any(ext.is_toolbox(v) for v in visible())
        palette.select("command", reload_id())
        palette.filter.setCurrentIndex(filters.index("all"))
        palette.search.setText("buffer")
        palette.filter.setCurrentIndex(filters.index("toolbox"))
        assert "verarbeitung:native:buffer" in visible()
    finally:
        dlg.editor._undo = []
        dlg.deleteLater()
        settle()


def test_editor_adds_tool_and_ribbon_shows_it(plugin):
    dlg = RibbonEditor(plugin.arrangements, plugin.widget.window())
    try:
        arr = dlg.editor.arr
        from qgis_ribbon.core import customization as cz
        tab = cz.new_tab(arr, dlg.base)
        group = cz.new_group(arr, dlg.base, tab)
        group.items.append(cz.ItemEntry("verarbeitung:native:buffer", "large"))
        plugin.arrangements.save_editor(arr, None)
    finally:
        dlg.editor._undo = []
        dlg.deleteLater()
        settle()
    settle()
    assert "verarbeitung:native:buffer" in plugin.ribbon.commands
    assert [e.command.id for e in plugin.ribbon.tab(tab.id).groups[0].elements] == ["verarbeitung:native:buffer"]



def test_editor_selects_tool_before_toolbox_filter(plugin):
    dlg = RibbonEditor(plugin.arrangements, plugin.widget.window())
    try:
        item = dlg.palette_box.select("command", "verarbeitung:native:buffer")
        assert item is not None and not item.icon().isNull()
    finally:
        dlg.editor._undo = []
        dlg.deleteLater()
        settle()


def test_embedded_dropdown_buttons_become_split_buttons(fake_iface, settings):
    """Plugin legt Werkzeuge als eingebettete Buttons mit Dropdown in seine Leiste (``addWidget``)."""
    mw = fake_iface.mainWindow()
    tb = QToolBar("Beschriftung", mw)
    tb.setObjectName("BeschriftungToolbar")
    tools = []
    for text in ("Einzeln (1 Klick)", "Kreuzung (3 Klicks)"):
        btn = QToolButton(tb)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        tool = QAction(text, tb)
        tool.setCheckable(True)
        options = QAction("Optionen …", tb)
        btn.addAction(tool)
        btn.addAction(options)
        btn.setDefaultAction(tool)
        tb.addWidget(btn)
        tools.append((tool, options))
    menu_btn = QToolButton(tb)            # Button mit Menü, ohne Hauptaktion
    drop = QMenu(menu_btn)
    drop.addAction(QAction("Nur im Menü", tb))
    menu_btn.setMenu(drop)
    tb.addWidget(menu_btn)
    tb.addAction(QAction("Automatisch", tb))
    mw.addToolBar(tb)
    settle()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        from qgis_ribbon.core.model import CommandRef, Split
        group = p.ribbon.tab("erweiterungen").groups[-1]
        assert group.label == "Beschriftung"
        kinds = [(type(e).__name__, e.command.label) for e in group.elements]
        assert kinds == [("Split", "Einzeln (1 Klick)"), ("Split", "Kreuzung (3 Klicks)"),
                         ("CommandRef", "Nur im Menü"), ("CommandRef", "Automatisch")]
        assert [c.label for c in group.elements[0].items] == ["Optionen"]
        # Hauptaktion auslösen und Zustand spiegeln
        p.widget.ensure_built(p.widget.tab_ids().index("erweiterungen"))
        proxy = p.widget.findChild(QAction, "ribbon_" + group.elements[1].command.id)
        assert proxy is not None and proxy.isCheckable()
        fired = []
        tools[1][0].triggered.connect(lambda: fired.append(1))
        proxy.trigger()
        assert fired == [1] and tools[1][0].isChecked() and proxy.isChecked()
        opened = []
        tools[0][1].triggered.connect(lambda: opened.append(1))
        p.resolver.trigger(group.elements[0].items[0])
        assert opened == [1]
        assert tb.isHidden()
        # Viel Platz: Plugin-Dropdowns klappen nicht auf (kein loses „Optionen“ neben dem Button)
        p.widget.select_tab("erweiterungen")
        settle()
        assert not [w for w in p.widget.findChildren(QToolButton)
                    if w.isVisible() and w.objectName().startswith("ribbon_inline_")]
    finally:
        p.unload()
        settle()
    assert not tb.isHidden()


def test_plugin_names_skip_deleted_widgets(monkeypatch):
    """Ein Plugin hält eine Combobox, die C++ schon gelöscht hat: kein RuntimeError beim Suchen."""
    from qgis import utils
    from qgis.PyQt import sip
    from qgis.PyQt.QtWidgets import QComboBox

    from qgis_ribbon.qgis_integration.extensions import _plugin_names
    act = QAction("Öffnen", None)
    combo = QComboBox()
    sip.delete(combo)
    obj = type("Plugin", (), {})()
    obj.combo = combo
    obj.widgets = [combo, act]
    monkeypatch.setattr(utils, "plugins", {"demo_plugin": obj})
    assert _plugin_names() == {id(act): "demo_plugin"}
