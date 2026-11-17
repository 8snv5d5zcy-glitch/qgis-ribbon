"""Aktionen anderer Plugins (Tab „Erweiterungen“) und Werkzeuge des Werkzeugkastens."""
import json
import os
import sys
import types

import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QAction, QDialog, QLabel, QMenu, QPushButton, QToolBar, QToolButton

from qgis_ribbon.core import extensions as ext
from qgis_ribbon.core.model import CommandRef, Menu, SubMenu
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration.user_settings import KEY_LAYOUT, KEY_QUICK_ACCESS
from qgis_ribbon.ui.ribbon_editor import RibbonEditor

from test_plugin import settle, snapshot  # noqa: E402 (gleicher Ordner, ohne Paket)


def native(*objs):
    """Wie QGIS erzeugt markieren (conftest: ``NATIVE``), zählt nicht als Plugin-Aktion."""
    for obj in objs:
        obj.setProperty("ribbonTestNative", True)
    return objs[0]


def plugin_menu(mw):
    """Menü „Erweiterungen“ wie in QGIS: eigene Einträge von QGIS, je Plugin ein Untermenü."""
    menu = QMenu("Erweiterungen", mw)
    menu.setObjectName("mPluginMenu")
    manage = QAction("Erweiterungen verwalten …", mw)
    manage.setObjectName("mActionManagePlugins")
    native(menu, manage)
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
        # gelöschtes Skript: im Ribbon ausgeblendet, in der Anordnung bleibt es (Editor räumt auf)
        assert [e.command.label for e in group.elements][1:] == ["Plugin neu laden"]
        assert "verarbeitung:script:geloescht" in p.ribbon.commands
        p.widget.select_tab("eigener_tab_1")
        settle()
        buffer = p.widget.findChild(QToolButton, "ribbon_btn_verarbeitung:native:buffer")
        assert p.widget.findChild(QToolButton, "ribbon_btn_verarbeitung:script:geloescht") is None
        assert buffer.isEnabled()
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


# -- Plugin-Aktionen an ungewöhnlichen Orten ---------------------------------------

def fake_plugin(**attrs):
    """Objekt wie ein geladenes Plugin: hält seine Aktionen als Attribute."""
    obj = type("Plugin", (), {})()
    for name, value in attrs.items():
        setattr(obj, name, value)
    return obj


def found_keys(p):
    return [f.key for f in p.catalog.found]


def test_plugin_action_with_qgis_like_name_is_found(fake_iface, settings, with_plugins, monkeypatch):
    """Plugin meldet seine Aktion beim Tastenkürzel-Manager als ``mAction…`` an (wie Layout Panel)."""
    from qgis import utils
    mw = fake_iface.mainWindow()
    sub, acts = add_plugin(mw, with_plugins["menu"], "Layout Panel", ["Layout Panel"],
                           toolbar=mw.findChild(QToolBar, "mPluginToolBar"))
    acts[0].setObjectName("mActionLayoutPanel")
    monkeypatch.setattr(utils, "plugins", {"layout_panel": fake_plugin(action=acts[0])})
    settle()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        cid = ext.plugin_id(ext.key("mPluginMenu", "Layout Panel", "Layout Panel"))
        assert cid in p.ribbon.commands
        assert "Layout Panel" in group_labels(p)
        # QGIS selbst (gehört keinem Plugin) bleibt draußen
        labels = {c.label for c in p.ribbon.commands.values() if ext.is_plugin(c.id)}
        assert "Erweiterungen verwalten …" not in labels
        fired = []
        acts[0].triggered.connect(lambda: fired.append(1))
        button(p, cid).defaultAction().trigger()
        assert fired == [1]
    finally:
        p.unload()
        settle()


def test_plugin_action_in_qgis_menu_and_toolbar_is_found(plugin, fake_iface, monkeypatch):
    """Plugin legt seine Aktion unter Layer hinzufügen und in eine QGIS-Leiste (wie Spreadsheet Layers)."""
    from qgis import utils
    mw = fake_iface.mainWindow()
    add_menu = mw.findChild(QMenu, "mAddLayerMenu")
    file_tb = mw.findChild(QToolBar, "mFileToolBar")
    sheet = QAction("Tabellenlayer hinzufügen …", mw)
    shipped = QAction("Werkzeug von QGIS", mw)       # Plugin, das mit QGIS kommt
    own = QAction("Ribbon-Schalter", mw)             # der Ribbon selbst
    stray = QAction("Ohne Besitzer", mw)             # aus Python, ohne Attribut: zählt auch
    qgis = native(QAction("Von QGIS", mw))           # von QGIS selbst erzeugt
    for act in (sheet, shipped, own, stray, qgis):
        add_menu.addAction(act)
    file_tb.addAction(sheet)
    file_tb.addAction(shipped)
    core_dir = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins", "kernplugin")
    monkeypatch.setitem(sys.modules, "kernplugin", types.SimpleNamespace(__file__=os.path.join(core_dir, "x.py")))
    monkeypatch.setattr(utils, "plugins", {"SpreadsheetLayers": fake_plugin(action=sheet),
                                           "kernplugin": fake_plugin(action=shipped),
                                           "qgis_ribbon": fake_plugin(view_action=own),
                                           "andere": fake_plugin(text="kein QAction")})
    settle()   # nach dem Laden des Ribbons: ActionAdded an Menü und Leiste von QGIS
    keys = found_keys(plugin)
    cid = ext.plugin_id(ext.key("mAddLayerMenu", "Tabellenlayer hinzufügen"))
    assert ext.key("mAddLayerMenu", "Tabellenlayer hinzufügen") in keys
    assert not [k for k in keys if "Werkzeug von QGIS" in k or "Ribbon-Schalter" in k or "Von QGIS" in k]
    # Ohne Besitzer: Gruppe ist der Titel des Menüs
    stray_found = [f for f in plugin.catalog.found if f.label == "Ohne Besitzer"]
    assert [f.group for f in stray_found] == ["Layer hinzufügen"]
    assert not [k for k in keys if k.startswith("toolbar/mFileToolBar")]   # Menü vor Leiste, nur einmal
    assert "SpreadsheetLayers" in group_labels(plugin)
    runs = []
    sheet.triggered.connect(lambda: runs.append(1))
    button(plugin, cid).defaultAction().trigger()
    assert runs == [1]
    # Plugin entladen: Eintrag weg
    add_menu.removeAction(sheet)
    file_tb.removeAction(sheet)
    settle()
    assert ext.key("mAddLayerMenu", "Tabellenlayer hinzufügen") not in found_keys(plugin)


def test_embedded_button_without_action_gets_stand_in(fake_iface, settings):
    """Plugin legt einen Button ohne Aktion in seine Leiste und hängt nur an ``clicked`` (wie Theme Switcher)."""
    mw = fake_iface.mainWindow()
    tb = QToolBar("Theme switcher", mw)   # iface.addToolBar setzt keinen objectName

    class ThemeButton(QToolButton):
        pass

    first, second = ThemeButton(tb), ThemeButton(tb)
    first.setText("Choose theme")
    second.setText("Zweiter")
    clicks = []
    first.clicked.connect(lambda: (clicks.append(1), first.setText("Thema %d" % len(clicks))))
    tb.addWidget(first)
    tb.addWidget(second)
    tb.addWidget(QToolButton(tb))          # ohne Text, Tooltip und Leistentitel wäre er leer: Titel der Leiste
    mw.addToolBar(tb)
    settle()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        cid = ext.plugin_id(ext.key("toolbar", "Theme switcher", "ThemeButton"))
        assert ext.key("toolbar", "Theme switcher", "ThemeButton#2") in found_keys(p)
        assert p.ribbon.commands[cid].label == "Choose theme"
        assert "Theme switcher" in group_labels(p) and tb.isHidden()
        built = p.widget
        btn = button(p, cid)
        btn.defaultAction().trigger()
        settle()
        assert clicks == [1] and first.text() == "Thema 1"
        # Text wechselt: Schlüssel und Beschriftung bleiben, kein Neuaufbau
        assert p.widget is built and p.ribbon.commands[cid].label == "Choose theme"
        first.setEnabled(False)
        assert not btn.defaultAction().isEnabled()
        btn.defaultAction().trigger()
        assert clicks == [1]
        first.setEnabled(True)
        assert btn.defaultAction().isEnabled()
        # Button weg: Eintrag weg
        tb.removeAction(tb.actions()[0])
        settle()
        assert ext.key("toolbar", "Theme switcher", "ThemeButton") in found_keys(p)   # der zweite rückt auf
        assert ext.key("toolbar", "Theme switcher", "ThemeButton#2") not in found_keys(p)
    finally:
        p.unload()
        settle()
    assert not tb.isHidden()


def test_plugin_names_skip_deleted_widgets(monkeypatch):
    """Ein Plugin hält eine Combobox, die C++ schon gelöscht hat: kein RuntimeError beim Suchen."""
    from qgis import utils
    from qgis.PyQt import sip
    from qgis.PyQt.QtWidgets import QComboBox

    from qgis_ribbon.qgis_integration.extensions import _owners
    act = QAction("Öffnen", None)
    combo = QComboBox()
    sip.delete(combo)
    obj = type("Plugin", (), {})()
    obj.combo = combo
    obj.widgets = [combo, act]
    monkeypatch.setattr(utils, "plugins", {"demo_plugin": obj})
    assert _owners() == {id(act): ("demo_plugin", False)}


def test_owner_found_in_sub_objects_of_the_plugin(monkeypatch):
    """Aktion nur in einem Unterobjekt des Plugins (``self.steuerung.aktionen``), mit Zyklus."""
    from qgis import utils

    from qgis_ribbon.qgis_integration.extensions import _owners
    deep = QAction("Tief", None)
    foreign = QAction("Fremd", None)
    too_deep = QAction("Zu tief", None)
    steuerung = type("Steuerung", (), {"__module__": "demo_plugin.steuerung"})()
    steuerung.aktionen = {"tief": deep}
    steuerung.zurueck = steuerung                     # Zyklus
    other = type("Fremd", (), {"__module__": "anderes_paket"})()
    other.action = foreign                            # Objekt aus fremdem Paket: nicht durchsuchen
    obj = type("Plugin", (), {})()
    obj.steuerung = steuerung
    obj.fremd = other
    obj.tief = [[[too_deep]]]                         # Tiefe 4
    monkeypatch.setattr(utils, "plugins", {"demo_plugin": obj})
    owners = _owners()
    assert owners.get(id(deep)) == ("demo_plugin", False)
    assert id(foreign) not in owners and id(too_deep) not in owners


# -- Verschwundene Quellen und verwaiste Einträge --------------------------------------

def reloader_menu(with_plugins):
    return next(a.menu() for a in with_plugins["menu"].actions() if a.text() == "Plugin Reloader")


def critical_messages(fake_iface):
    from qgis.core import Qgis
    return [i.text() for i in fake_iface.messageBar().items() if i.level() == Qgis.MessageLevel.Critical]


@pytest.fixture
def hooks(monkeypatch):
    """Ausnahmen in Slots sammeln statt sie nur auszugeben."""
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: seen.append(exc))
    return seen


def test_deleted_plugin_action_is_not_an_error(plugin, fake_iface, with_plugins, hooks):
    """Plugin entladen oder neu geladen: Klick auf den alten Button meldet nichts, Button wird grau."""
    from qgis.PyQt import sip
    btn = button(plugin, reload_id())
    act = btn.defaultAction()
    sip.delete(with_plugins["reload"][0])
    act.trigger()
    assert hooks == [] and critical_messages(fake_iface) == []
    assert not act.isEnabled()
    settle()
    # neuer Katalog: der Befehl ist weg, „Konfigurieren“ bleibt
    group = plugin.ribbon.tab("erweiterungen").groups[0]
    assert [e.command.label for e in group.elements] == ["Konfigurieren"]


def test_replaced_plugin_action_is_mirrored(plugin, fake_iface, with_plugins, hooks):
    """Plugin legt seine Aktion neu an (gleicher Text): der Button löst die neue aus."""
    from qgis.PyQt import sip
    act = button(plugin, reload_id()).defaultAction()
    sub = reloader_menu(with_plugins)
    sip.delete(with_plugins["reload"][0])
    new = QAction("Plugin neu laden", fake_iface.mainWindow())
    sub.insertAction(sub.actions()[0], new)
    fired = []
    new.triggered.connect(lambda: fired.append(1))
    act.trigger()
    assert fired == [1] and hooks == [] and critical_messages(fake_iface) == []
    settle()
    btn = button(plugin, reload_id())
    btn.defaultAction().trigger()
    assert fired == [1, 1]


def test_unloaded_plugin_leaves_no_search_hit(plugin, fake_iface, with_plugins, hooks):
    search = plugin.widget.search
    assert any(e.label == "Plugin neu laden" for e in search.results("neu laden"))
    from qgis.PyQt import sip
    sub = reloader_menu(with_plugins)
    with_plugins["menu"].removeAction(sub.menuAction())
    for a in sub.actions():
        sip.delete(a)
    sip.delete(sub)
    settle()
    search = plugin.widget.search
    assert not any(e.label == "Plugin neu laden" for e in search.results("neu laden"))
    search.update_results("neu laden")
    search.completer.popup().hide()
    assert hooks == []


def test_editor_removes_orphaned_entries(fake_iface, settings, with_plugins, monkeypatch):
    """Gelöschtes Skript und Befehl eines nicht geladenen Plugins: im Ribbon weg, im Editor aufräumbar."""
    from qgis_ribbon.ui import ribbon_editor
    gone_plugin = ext.plugin_id(ext.key("mPluginMenu", "Fehlt", "Weg"))
    settings.setValue(KEY_LAYOUT, json.dumps(tool_layout("verarbeitung:native:buffer",
                                                         "verarbeitung:script:geloescht", gone_plugin)))
    settings.setValue(KEY_QUICK_ACCESS, "neues_projekt,%s" % gone_plugin)
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        assert [e.command.id for e in p.ribbon.tab("eigener_tab_1").groups[0].elements] == \
            ["verarbeitung:native:buffer"]
        assert gone_plugin not in [c.id for c in p.widget.quick.commands]
        dlg = RibbonEditor(p.arrangements, p.widget.window())
        try:
            assert dlg.orphans_button.isVisibleTo(dlg)
            assert set(dlg.editor.orphans()) == {"verarbeitung:script:geloescht", gone_plugin}
            offered = []
            monkeypatch.setattr(ribbon_editor, "choose_orphans",
                                lambda parent, entries: offered.extend(entries) or [c for c, _l, _r in entries])
            assert dlg.remove_orphans() == 2
            assert {c for c, _l, _r in offered} == {"verarbeitung:script:geloescht", gone_plugin}
            assert dlg.editor.orphans() == [] and not dlg.orphans_button.isVisibleTo(dlg)
            assert gone_plugin not in dlg.editor.qat
            dlg.editor.undo()
            assert set(dlg.editor.orphans()) == {"verarbeitung:script:geloescht", gone_plugin}
        finally:
            dlg.editor._undo = []
            dlg.deleteLater()
            settle()
    finally:
        p.unload()
        settle()


# -- Icons fremder Plugins ------------------------------------------------------------

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
       '<rect width="16" height="16" fill="#c00"/></svg>')


def test_plugin_icons_keep_their_size_in_large_buttons(fake_iface, settings, with_plugins, tmp_path):
    """SVG skaliert auf die Größe des großen Buttons; Pixelbilder bleiben in ihrer Größe (nie vergrößert)."""
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor, QIcon, QPixmap
    from qgis_ribbon.ui import theme
    svg = tmp_path / "icon.svg"
    svg.write_text(SVG)
    png = tmp_path / "icon16.png"
    pix = QPixmap(16, 16)
    pix.fill(QColor("#0a0"))
    pix.save(str(png))
    mw = fake_iface.mainWindow()
    icons = {"Aus SVG": QIcon(str(svg)), "SVG als Bild": QIcon(QPixmap(str(svg))), "Kleines PNG": QIcon(str(png))}
    for text, icon in icons.items():
        sub = with_plugins["menu"].addMenu("Plugin " + text)
        sub.addAction(QAction(icon, text, mw))
    mw.resize(6000, 800)
    settle()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        large = QSize(theme.LARGE_ICON, theme.LARGE_ICON)
        expected = {"Aus SVG": large, "SVG als Bild": QSize(16, 16), "Kleines PNG": QSize(16, 16)}
        for mode in ("hell", "dunkel"):
            p.themes.set("mode", mode)
            settle()
            for text, size in expected.items():
                btn = button(p, ext.plugin_id(ext.key("mPluginMenu", "Plugin " + text, text)))
                assert btn.iconSize() == large, text
                assert btn.icon().actualSize(large) == size, (mode, text)
    finally:
        p.unload()
        settle()


def test_plugin_rich_text_tooltip_is_clean_everywhere(fake_iface, settings, with_plugins):
    """Rich-Text-Tooltip eines Plugins: im Ribbon, in der Suche und im Editor ohne Tags und kaputte Entitäten."""
    mw = fake_iface.mainWindow()
    sub = with_plugins["menu"].addMenu("Formatiert")
    act = QAction("Formatiert tun", mw)
    act.setToolTip("<p><b>Formatiert</b> tun:<br>Punkte&nbsp;&amp;&nbsp;Linien</p>")
    sub.addAction(act)
    settle()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    dlg = None
    try:
        cid = ext.plugin_id(ext.key("mPluginMenu", "Formatiert", "Formatiert tun"))
        assert p.ribbon.commands[cid].description == "Formatiert tun:\nPunkte & Linien"
        tip = button(p, cid).defaultAction().toolTip()
        assert "Formatiert tun:<br>Punkte &amp; Linien" in tip
        assert "&lt;" not in tip and "nbsp" not in tip
        hit = next(e for e in p.widget.search.results("formatiert") if e.label == "Formatiert tun")
        assert "<" not in hit.description and "nbsp" not in hit.description
        dlg = RibbonEditor(p.arrangements, p.widget.window())
        item = dlg.palette_box.select("command", cid)
        assert "Punkte &amp; Linien" in item.toolTip() and "&lt;" not in item.toolTip()
    finally:
        if dlg is not None:
            dlg.editor._undo = []
            dlg.deleteLater()
        p.unload()
        settle()


# -- Suche über alle Werkzeuge ---------------------------------------------------------

def tool_hits(p, text):
    from qgis_ribbon.core import search
    return [e for e in p.widget.search.results(text) if e.tier in (search.TIER_OWN_TOOL, search.TIER_TOOL)]


def test_search_finds_and_runs_any_toolbox_tool(plugin, monkeypatch):
    """Werkzeug ohne Ort im Ribbon und ohne Menüeintrag: über Namen und internen Namen zu finden."""
    from qgis_ribbon.ui import search_box
    calls = []
    monkeypatch.setitem(sys.modules, "processing",
                        types.SimpleNamespace(execAlgorithmDialog=lambda alg_id: calls.append(alg_id)))
    alg = QgsApplication.processingRegistry().algorithmById("native:fixgeometries")
    search = plugin.widget.search
    hits = [e for e in search.results(alg.displayName()) if e.ref[0].id == "verarbeitung:native:fixgeometries"]
    assert len(hits) == 1
    assert [e.ref[0].id for e in tool_hits(plugin, "fixgeometries")] == ["verarbeitung:native:fixgeometries"]
    search.update_results("fixgeometries")
    assert search.model.item(0).isEnabled() and not search.model.item(0).icon().isNull()
    assert search.execute(search.model.item(0).data(search_box.ROLE_ENTRY))
    assert calls == ["native:fixgeometries"]
    # Werkzeug mit Ort im Ribbon nur einmal
    buffer = QgsApplication.processingRegistry().algorithmById("native:buffer").displayName()
    ids = [e.ref[0].id if e.ribbon else None for e in search.results(buffer)]
    assert ids.count("verarbeitung:native:buffer") <= 1


def test_search_follows_new_and_deleted_scripts(plugin):
    from qgis.core import QgsProcessingAlgorithm, QgsProcessingProvider

    class Tool(QgsProcessingAlgorithm):
        def name(self):
            return "suchbar"

        def displayName(self):  # noqa: N802
            return "Suchbares Skriptwerkzeug"

        def createInstance(self):  # noqa: N802
            return Tool()

        def initAlgorithm(self, config=None):  # noqa: N802
            pass

        def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
            return {}

    class Provider(QgsProcessingProvider):
        def id(self):
            return "suchskripte"

        def name(self):
            return "Suchskripte"

        def loadAlgorithms(self):  # noqa: N802
            if self.ready:
                self.addAlgorithm(Tool())

    reg = QgsApplication.processingRegistry()
    provider = Provider()
    provider.ready = False
    reg.addProvider(provider)
    try:
        settle()
        assert tool_hits(plugin, "suchbares") == []
        built = plugin.widget
        provider.ready = True
        provider.refreshAlgorithms()     # wie beim Speichern eines neuen Skripts
        settle()
        assert plugin.widget is built    # kein Umbau des Ribbons für ein neues Werkzeug
        assert [e.label for e in tool_hits(plugin, "suchbares")] == ["Suchbares Skriptwerkzeug"]
        provider.ready = False
        provider.refreshAlgorithms()     # Skript gelöscht
        settle()
        assert tool_hits(plugin, "suchbares") == []
    finally:
        reg.removeProvider(provider)
        settle()


# -- Symbol für eigene Skripte ---------------------------------------------------------

def _script_provider(with_icon_path):
    """Anbieter „script“ wie die Skripte von QGIS: ein Werkzeug ohne, eines mit eigenem Icon."""
    from qgis.core import QgsProcessingAlgorithm, QgsProcessingProvider
    from qgis.PyQt.QtGui import QIcon

    class Plain(QgsProcessingAlgorithm):
        def name(self):
            return "ohne_icon"

        def displayName(self):  # noqa: N802
            return "Skript ohne Icon"

        def createInstance(self):  # noqa: N802
            return Plain()

        def initAlgorithm(self, config=None):  # noqa: N802
            pass

        def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
            return {}

    class Own(Plain):
        def name(self):
            return "mit_icon"

        def displayName(self):  # noqa: N802
            return "Skript mit Icon"

        def createInstance(self):  # noqa: N802
            return Own()

        def icon(self):
            return QIcon(with_icon_path)

    class Provider(QgsProcessingProvider):
        def id(self):
            return "script"

        def name(self):
            return "Skripte"

        def loadAlgorithms(self):  # noqa: N802
            self.addAlgorithm(Plain())
            self.addAlgorithm(Own())

    return Provider()


def test_scripts_without_own_icon_get_the_kontur_motif(fake_iface, settings, tmp_path):
    from qgis.PyQt.QtGui import QColor, QIcon, QPixmap
    from qgis_ribbon.qgis_integration.extensions import uses_default_icon
    from qgis_ribbon.ui import icons
    red = tmp_path / "rot.png"
    pix = QPixmap(32, 32)
    pix.fill(QColor("#ff0000"))
    pix.save(str(red))
    reg = QgsApplication.processingRegistry()
    old = reg.providerById("script")
    if old is not None:
        reg.removeProvider(old)
    provider = _script_provider(str(red))
    reg.addProvider(provider)
    settings.setValue(KEY_LAYOUT, json.dumps(tool_layout(
        "verarbeitung:script:ohne_icon", "verarbeitung:script:mit_icon", "verarbeitung:native:buffer")))
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    try:
        assert uses_default_icon("script:ohne_icon") and not uses_default_icon("script:mit_icon")
        cmds = p.ribbon.commands
        assert icons.runtime_motif(cmds["verarbeitung:native:buffer"]) is None     # QGIS-Werkzeug: QGIS-Icon
        assert icons.runtime_motif(cmds["verarbeitung:script:ohne_icon"]) == "skript_werkzeug"
        assert icons.runtime_motif(cmds["verarbeitung:script:mit_icon"]) is None
        p.widget.select_tab("eigener_tab_1")
        settle()

        def shown(cid):
            img = p.widget.findChild(QToolButton, "ribbon_btn_" + cid).icon().pixmap(32, 32).toImage()
            return {img.pixelColor(x, y).name() for x in range(32) for y in range(32)
                    if img.pixelColor(x, y).alpha() > 200}

        gear = QIcon(reg.algorithmById("script:ohne_icon").icon())
        assert shown("verarbeitung:script:mit_icon") == {"#ff0000"}           # eigenes Icon bleibt
        from qgis_ribbon.ui import theme
        assert theme.current()["text"].lower()[:7] in shown("verarbeitung:script:ohne_icon")   # Kontur-Motiv
        # Eigene Icons aus: QGIS-Icon (Zahnrad) statt Motiv
        p.themes.set("icons", False)
        settle()
        img = gear.pixmap(32, 32).toImage()
        qgis = {img.pixelColor(x, y).name() for x in range(32) for y in range(32)
                if img.pixelColor(x, y).alpha() > 200}
        assert shown("verarbeitung:script:ohne_icon") == qgis
        p.themes.set("icons", True)
    finally:
        p.unload()
        settle()
        reg.removeProvider(provider)
        if old is not None:
            from processing.script.ScriptAlgorithmProvider import ScriptAlgorithmProvider
            reg.addProvider(ScriptAlgorithmProvider())


# -- Plugins vollständig finden --------------------------------------------------------

def plugin_main_menu(mw, entries=30):
    """Plugin mit eigenem Hauptmenü (wie HCMGIS): Untermenüs mit ``addMenu(QMenu)``, ohne Elternteil."""
    main = QMenu("Geo-Werkzeuge", mw)
    main.setObjectName("GeoWerkzeugeMenu")
    about = QAction("Über", mw)
    main.addAction(about)
    basemaps = QMenu("Grundkarten")                       # kein Kind des Hauptmenüs
    maps = [QAction("Karte %d" % i, mw) for i in range(entries)]
    for act in maps:
        basemaps.addAction(act)
    main.addMenu(basemaps)
    deeper = QMenu("Weitere")
    deeper.addAction(QAction("Tief A", mw))
    deeper.addAction(QAction("Tief B", mw))
    basemaps.addMenu(deeper)
    single = QMenu("Einzeln")
    lone = QAction("Allein", mw)
    single.addAction(lone)
    main.addMenu(single)
    mw.menuBar().addMenu(main)
    # Untermenüs ohne Elternteil am Leben halten (wie das Plugin über seine Attribute)
    mw._test_menus = [basemaps, deeper, single]
    return {"main": main, "about": about, "basemaps": basemaps, "maps": maps, "deeper": deeper, "lone": lone}


def ext_group(p, label):
    return next(g for g in p.ribbon.tab("erweiterungen").groups if g.label == label)


def loaded(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    return p


def test_plugin_main_menu_with_parentless_submenus(fake_iface, settings):
    mw = fake_iface.mainWindow()
    made = plugin_main_menu(mw)
    settle()
    p = loaded(fake_iface, settings)
    try:
        group = ext_group(p, "Geo-Werkzeuge")
        about, dropdown, lone = group.elements
        assert isinstance(about, CommandRef) and about.command.label == "Über"
        # 30 Einträge im Untermenü: ein Dropdown, tiefere Ebene als Untermenü darin
        assert isinstance(dropdown, Menu) and dropdown.label == "Grundkarten"
        assert len([i for i in dropdown.items if not isinstance(i, SubMenu)]) == 30
        sub = [i for i in dropdown.items if isinstance(i, SubMenu)]
        assert [s.label for s in sub] == ["Weitere"] and [c.label for c in sub[0].items] == ["Tief A", "Tief B"]
        # Untermenü mit einem Eintrag: der Eintrag ist ein Button
        assert isinstance(lone, CommandRef) and lone.command.label == "Allein"
        assert lone.command.id == ext.plugin_id(ext.key("menubar", "GeoWerkzeugeMenu", "Einzeln", "Allein"))
        # Jeder Eintrag ein eigener, auslösbarer Befehl
        cid = ext.plugin_id(ext.key("menubar", "GeoWerkzeugeMenu", "Grundkarten", "Karte 7"))
        assert cid in p.ribbon.commands
        fired = []
        made["maps"][7].triggered.connect(lambda: fired.append(7))
        p.resolver.resolve(p.ribbon.commands[cid]).action.trigger()
        assert fired == [7]
        # Das Dropdown im Ribbon zeigt die Einträge
        p.widget.ensure_built(p.widget.tab_ids().index("erweiterungen"))
        menus = [b.menu() for b in p.widget.findChildren(QToolButton) if b.menu() is not None]
        texts = [[a.text() for a in m.actions()] for m in menus]
        assert any("Karte 0" in t and "Weitere" in t for t in texts)
        # Später ins Untermenü gelegte Aktion: Neuaufbau
        widget = p.widget
        made["deeper"].addAction(QAction("Tief C", mw))
        settle()
        assert p.widget is not widget
        assert ext.plugin_id(ext.key("menubar", "GeoWerkzeugeMenu", "Grundkarten", "Weitere", "Tief C")) \
            in p.ribbon.commands
    finally:
        p.unload()
        settle()


def test_processing_menu_and_qgis_menus_stay_out(fake_iface, settings):
    mw = fake_iface.mainWindow()
    processing = QMenu("Verarbeitung", mw)                # in Python erzeugt, aber ausgenommen
    processing.setObjectName("processing")
    processing.addAction(QAction("Werkzeugkiste öffnen", mw))
    mw.menuBar().addMenu(processing)
    settle()
    p = loaded(fake_iface, settings)
    try:
        labels = {c.label for c in p.ribbon.commands.values() if ext.is_plugin(c.id)}
        assert "Werkzeugkiste öffnen" not in labels
        # Eigene Aktionen des Ribbons (Ansicht, Hilfe) und QGIS selbst bleiben draußen
        assert p.view_action is not None and p.help_action is not None
        assert not [f for f in p.catalog.found if f.label in (p.view_action.text(), p.help_action.text(),
                                                              "Volle Ausdehnung")]
    finally:
        p.unload()
        settle()


def test_same_text_in_one_toolbar_gives_three_buttons(fake_iface, settings):
    """Drei Leistenknöpfe mit gleichem Text (wie Clipper): alle im Ribbon, jeder löst seine Aktion aus."""
    mw = fake_iface.mainWindow()
    tb = QToolBar("Zuschnitt", mw)
    tb.setObjectName("ZuschnittToolbar")
    acts = [QAction("Zuschnitt", mw) for _i in range(3)]
    for act in acts:
        tb.addAction(act)
    mw.addToolBar(tb)
    settle()
    p = loaded(fake_iface, settings)
    try:
        base = ext.key("toolbar", "ZuschnittToolbar", "Zuschnitt")
        ids = [ext.plugin_id(k) for k in (base, base + "#2", base + "#3")]
        assert [e.command.id for e in ext_group(p, "Zuschnitt").elements] == ids
        fired = []
        for i, act in enumerate(acts):
            act.triggered.connect(lambda _c=False, i=i: fired.append(i))
        for cid in reversed(ids):
            button(p, cid).defaultAction().trigger()
        assert fired == [2, 1, 0]
    finally:
        p.unload()
        settle()


def test_action_in_sub_object_and_without_owner_in_qgis_places(plugin, fake_iface, monkeypatch):
    """Aktion nur in einem Unterobjekt des Plugins (QGIS-Menü) und eine ohne Attribut (QGIS-Leiste)."""
    from qgis import utils
    mw = fake_iface.mainWindow()
    add_menu = mw.findChild(QMenu, "mAddLayerMenu")
    file_tb = mw.findChild(QToolBar, "mFileToolBar")
    deep = QAction("Tief versteckt", mw)
    loose = QAction("Ohne Attribut", mw)
    add_menu.addAction(deep)
    file_tb.addAction(loose)
    steuerung = type("Steuerung", (), {"__module__": "tiefplugin.steuerung"})()
    steuerung.aktionen = [deep]
    monkeypatch.setattr(utils, "plugins", {"tiefplugin": fake_plugin(steuerung=steuerung)})
    settle()
    found = {f.label: f for f in plugin.catalog.found}
    assert found["Tief versteckt"].group == "tiefplugin"
    assert found["Ohne Attribut"].group == "Projekt"         # Titel der Leiste
    assert found["Ohne Attribut"].key == ext.key("toolbar", "mFileToolBar", "Ohne Attribut")
    fired = []
    loose.triggered.connect(lambda: fired.append(1))
    button(plugin, ext.plugin_id(found["Ohne Attribut"].key)).defaultAction().trigger()
    assert fired == [1]


def test_editor_shows_plugin_dropdown(fake_iface, settings):
    from qgis_ribbon.core import customization as cz
    from qgis_ribbon.core.editor import Place
    mw = fake_iface.mainWindow()
    plugin_main_menu(mw, entries=3)
    settle()
    p = loaded(fake_iface, settings)
    dlg = RibbonEditor(p.arrangements, p.widget.window())
    try:
        tab = next(t for t in dlg.editor.arr.tabs if t.id == "erweiterungen")
        gi = next(i for i, g in enumerate(tab.groups) if g.label == "Geo-Werkzeuge")
        ii = next(i for i, it in enumerate(cz.group_items(dlg.base, tab.groups[gi]))
                  if isinstance(cz.item_element(dlg.base, it), Menu))
        dlg.select(("item", Place("erweiterungen", gi, ii)), focus=True)
        texts = [w.text() for w in dlg.props.findChildren(QLabel)]
        assert any("Karte 0" in t for t in texts)
        # Inhalt bestimmt das Plugin: kein „Dropdown anpassen …“
        assert not [b for b in dlg.props.findChildren(QPushButton) if b.objectName() == "ribbon_editor_gallery"]
        # Einträge einzeln in der Palette
        palette = dlg.palette_box
        filters = [palette.filter.itemData(i) for i in range(palette.filter.count())]
        palette.filter.setCurrentIndex(filters.index("plugins"))
        visible = {v for _k, v in palette.visible_values()}
        assert ext.plugin_id(ext.key("menubar", "GeoWerkzeugeMenu", "Grundkarten", "Karte 1")) in visible
    finally:
        dlg.editor._undo = []
        dlg.deleteLater()
        settle()
        p.unload()
        settle()


def test_menu_refilled_with_same_entries_does_not_rebuild(plugin, fake_iface, with_plugins, hooks):
    """Plugin füllt sein Menü neu (gleiche Texte, neue Aktionen): kein Neuaufbau, Klick löst die neue aus."""
    mw = fake_iface.mainWindow()
    sub, _acts = add_plugin(mw, with_plugins["menu"], "Füller", ["Erster", "Zweiter"])
    settle()
    widget = plugin.widget
    fired = []
    texts = [a.text() for a in sub.actions()]
    sub.clear()
    fresh = []
    for text in texts:
        act = QAction(text, mw)
        act.triggered.connect(lambda _c=False, t=text: fired.append(t))
        sub.addAction(act)
        fresh.append(act)
    settle()
    assert plugin.widget is widget
    button(plugin, ext.plugin_id(ext.key("mPluginMenu", "Füller", "Erster"))).defaultAction().trigger()
    assert fired == ["Erster"] and hooks == []
    # Neuer Eintrag: Neuaufbau
    sub.addAction(QAction("Ganz neu", mw))
    settle()
    assert plugin.widget is not widget


def test_rebuild_waits_for_open_menu(plugin, fake_iface, with_plugins):
    """Ein offenes Menü (z. B. aus dem Ribbon geöffnet) klappt nicht durch einen Neuaufbau zu."""
    from qgis.PyQt.QtWidgets import QApplication
    widget = plugin.widget
    popup = QMenu(widget)
    popup.addAction("Eintrag")
    popup.popup(widget.mapToGlobal(widget.rect().center()))
    settle()
    assert QApplication.activePopupWidget() is popup
    reloader_menu(with_plugins).addAction(QAction("Neu dazu", fake_iface.mainWindow()))
    settle()
    assert plugin.widget is widget and popup.isVisible()
    popup.close()
    settle()
    assert plugin.widget is not widget
