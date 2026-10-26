"""Anpassung (Editor siehe test_ribbon_editor.py), Anordnungen speichern/laden/teilen, Galerie anpassen, klassische Oberfläche."""
import copy
import json

import pytest
import yaml
from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar

from qgis_ribbon.core import customization as cz
from qgis_ribbon.plugin import TOOLBAR_NAME, VIEW_ACTION_NAME, RibbonPlugin
from qgis_ribbon.qgis_integration import custom_commands
from qgis_ribbon.qgis_integration.user_settings import (KEY_CLASSIC, KEY_LAYOUT, KEY_SAVED,
                                                         UserSettings)
from qgis_ribbon.ui import arrangement_menu
from qgis_ribbon.ui.controls.gallery import RibbonGallery
from qgis_ribbon.ui.customize_dialog import GalleryDialog

from test_plugin import snapshot  # noqa: E402 (gleicher Ordner, ohne Paket)


def qa(name):
    return {"type": "qgis_action", "object_name": name}


DEFINITION = {
    "version": 1,
    "quick_access": ["neu"],
    "hide_toolbars": ["mFileToolBar", "mMapNavToolBar"],
    "commands": {
        "neu": {"label": "Neues Projekt", "source": qa("mActionNewProject")},
        "speichern": {"label": "Speichern", "source": qa("mActionSaveProject")},
        "verschieben": {"label": "Verschieben", "source": qa("mActionPan")},
        "zoomen": {"label": "Hineinzoomen", "source": qa("mActionZoomIn")},
        "deckkraft": {"label": "Deckkraft", "kind": "control",
                      "source": {"type": "custom", "id": "ribbon.deckkraft"}},
    },
    "tabs": [
        {"id": "karte", "label": "Karte", "groups": [
            {"id": "nav", "label": "Navigieren", "items": [{"command": "verschieben"},
                                                           {"command": "zoomen"}]}]},
        {"id": "projekt", "label": "Projekt", "groups": [
            {"id": "datei", "label": "Datei", "items": [{"command": "neu"}, {"command": "speichern"}]}]},
    ],
}


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)  # deleteLater ausführen
    QgsApplication.processEvents()


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ribbon.yaml"
    path.write_text(yaml.safe_dump(copy.deepcopy(DEFINITION), allow_unicode=True), encoding="utf-8")
    return str(path)


@pytest.fixture
def plugin(fake_iface, settings, config):
    p = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


@pytest.fixture
def no_dialogs(monkeypatch):
    """Rückfragen des Menüs „Anordnungen“ ersetzen (modale Dialoge blockieren Tests)."""
    calls = []
    answers = {"confirm": True}
    monkeypatch.setattr(arrangement_menu, "confirm",
                        lambda parent, title, text: calls.append(("confirm", text)) or answers["confirm"])
    monkeypatch.setattr(arrangement_menu, "inform",
                        lambda parent, title, text, warning=False: calls.append(("inform", text)))
    return calls, answers


def tab_ids(plugin):
    return [t.id for t in plugin.widget.ribbon.tabs]


# -- Anpassung und Neuaufbau -------------------------------------------------

def test_customization_rebuilds_ribbon_and_survives_restart(fake_iface, settings, config, plugin):
    old = plugin.widget
    plugin.widget.select_tab("projekt")
    arr = plugin.arrangements.current()
    tab = cz.new_tab(arr, plugin.base, after=0, label="Mein Tab")
    group = cz.new_group(arr, plugin.base, tab, label="Häufig")
    cz.add_command(group, "speichern")
    cz.add_command(group, "deckkraft", "medium")
    arr.tab("karte").groups[0].visible = False
    plugin.arrangements.set_current(arr)
    assert plugin.widget is old  # Neuaufbau erst nach der Ereignisschleife
    settle()
    assert plugin.widget is not old
    assert tab_ids(plugin) == ["karte", "eigener_tab_1", "projekt"]
    assert plugin.widget.current_tab() == "projekt"  # gewählter Tab bleibt
    plugin.widget.select_tab("eigener_tab_1")
    page = plugin.widget.page("eigener_tab_1")
    assert [g.group.label for g in page.groups] == ["Häufig"]
    assert plugin.widget.page("karte") is None or not plugin.widget.page("karte").groups
    assert len(plugin.hub) > 0
    assert settings.value(KEY_LAYOUT)

    # Neustart: die Anpassung gilt weiter
    plugin.unload()
    settle()
    again = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    again.initGui()
    try:
        assert tab_ids(again) == ["karte", "eigener_tab_1", "projekt"]
    finally:
        again.unload()
        settle()
    plugin.initGui()  # für die Fixture


def test_rebuild_and_unload_restore_main_window_exactly(fake_iface, settings, config):
    mw = fake_iface.mainWindow()
    settle()
    before = snapshot(mw)
    plugin = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    plugin.initGui()
    settle()
    for _ in range(3):
        arr = plugin.arrangements.current()
        cz.new_tab(arr, plugin.base)
        plugin.arrangements.set_current(arr)
        settle()
    assert len(tab_ids(plugin)) == 5
    assert mw.findChildren(QToolBar, TOOLBAR_NAME) == [plugin.toolbar]
    plugin.unload()
    settle()
    assert len(plugin.hub) == 0
    assert custom_commands.registered() == []
    after = snapshot(mw)
    for key in before:
        assert after[key] == before[key], key


def test_broken_saved_layout_falls_back_to_definition(fake_iface, settings, config):
    settings.setValue(KEY_LAYOUT, "{kein json")
    plugin = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    plugin.initGui()
    try:
        assert tab_ids(plugin) == ["karte", "projekt"]
    finally:
        plugin.unload()
        settle()
    settings.setValue(KEY_LAYOUT, json.dumps({"tabs": [{"tab": "weg"}, {"tab": "projekt"}]}))
    plugin = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    plugin.initGui()
    try:
        assert tab_ids(plugin) == ["projekt", "karte"]
        assert plugin.arrangements.warnings
    finally:
        plugin.unload()
        settle()


# -- Klassische Oberfläche ---------------------------------------------------

def test_classic_interface_and_back(fake_iface, settings, config, monkeypatch):
    messages = []
    # Meldungen der Meldungsleiste nur merken (ihre Widgets löscht QGIS erst später)
    monkeypatch.setattr(fake_iface.messageBar(), "pushMessage", lambda *a, **k: messages.append(a))
    mw = fake_iface.mainWindow()
    settle()
    before = snapshot(mw)
    plugin = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    plugin.initGui()
    settle()
    view = mw.findChild(QAction, VIEW_ACTION_NAME)
    assert view is not None and view.isChecked()
    assert view in fake_iface.viewMenu().actions()
    menu = plugin.widget.context_menu(None)
    classic = next(a for a in menu.actions() if a.text() == "Klassische QGIS-Oberfläche")
    classic.trigger()
    settle()
    assert plugin.widget is None
    assert mw.findChild(QToolBar, TOOLBAR_NAME) is None
    assert not mw.findChild(QToolBar, "mFileToolBar").isHidden()
    assert not view.isChecked()
    assert settings.value(KEY_CLASSIC) == "true"
    assert "Ansicht › Ribbon-Oberfläche" in messages[-1][1]
    now = snapshot(mw)
    assert now["state"] == before["state"] and now["toolbars"] == before["toolbars"]
    # Neustart in der klassischen Oberfläche: kein Ribbon, nur der Umschalter
    plugin.unload()
    settle()
    plugin = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    plugin.initGui()
    settle()
    assert plugin.widget is None
    view = mw.findChild(QAction, VIEW_ACTION_NAME)
    assert not view.isChecked()
    view.trigger()  # Ansicht › Ribbon-Oberfläche
    settle()
    assert plugin.widget is not None and view.isChecked()
    assert mw.findChild(QToolBar, "mFileToolBar").isHidden()
    assert settings.value(KEY_CLASSIC) is None
    plugin.unload()
    settle()
    after = snapshot(mw)
    for key in before:
        assert after[key] == before[key], key


def test_unload_in_classic_mode_restores_exactly(fake_iface, settings, config):
    mw = fake_iface.mainWindow()
    settle()
    before = snapshot(mw)
    UserSettings(settings).set_classic(True)
    plugin = RibbonPlugin(fake_iface, config_path=config, settings=settings)
    plugin.initGui()
    settle()
    plugin.unload()
    settle()
    assert snapshot(mw) == before


# -- Gespeicherte Anordnungen ------------------------------------------------

def test_save_load_delete_arrangements(plugin, settings, no_dialogs, monkeypatch):
    calls, answers = no_dialogs
    arrs = plugin.arrangements
    assert arrs.is_standard() and arrs.active_name() is None
    monkeypatch.setattr(arrangement_menu, "ask_name", lambda *a: "Bearbeitung")
    # Anpassung: Projekt-Tab ausblenden, Schnellzugriff ändern
    arr = arrs.current()
    arr.tab("projekt").visible = False
    arrs.set_current(arr)
    settle()
    plugin.widget.add_to_quick_access(plugin.ribbon.commands["speichern"])
    assert arrs.is_unsaved()
    assert arrangement_menu.save_as(plugin.widget) == "Bearbeitung"
    assert arrs.names() == ["Bearbeitung"] and arrs.active_name() == "Bearbeitung"
    assert json.loads(settings.value(KEY_SAVED))["Bearbeitung"]["quick_access"] == ["neu", "speichern"]

    # Standard laden, dann die gespeicherte Anordnung wieder
    assert arrangement_menu.reset(plugin.widget)
    settle()
    assert tab_ids(plugin) == ["karte", "projekt"]
    assert [c.id for c in plugin.widget.quick.commands] == ["neu"]
    assert arrangement_menu.load(plugin.widget, "Bearbeitung")
    settle()
    assert tab_ids(plugin) == ["karte"]
    assert [c.id for c in plugin.widget.quick.commands] == ["neu", "speichern"]
    assert not [c for c in calls if c[0] == "confirm"]  # nichts ging verloren, keine Rückfrage

    # Ungespeicherte Anpassung: Laden fragt nach
    arr = arrs.current()
    cz.new_tab(arr, plugin.base)
    arrs.set_current(arr)
    settle()
    answers["confirm"] = False
    assert not arrangement_menu.reset(plugin.widget)
    assert calls[-1] == ("confirm", arrangement_menu.UNSAVED)
    answers["confirm"] = True
    assert arrangement_menu.delete(plugin.widget, "Bearbeitung")
    assert arrs.names() == []


def test_arrangements_menu_entries(plugin, no_dialogs, monkeypatch):
    arrs = plugin.arrangements
    arrs.save_as("Eins")
    arr = arrs.current()
    arr.tab("karte").visible = False
    arrs.set_current(arr)
    arrs.save_as("Zwei")
    settle()
    menu = QMenu()
    sub = arrangement_menu.add_submenu(menu, plugin.widget)
    texts = [a.text() for a in sub.actions() if not a.isSeparator()]
    assert texts[:2] == ["Eins", "Zwei"]
    checked = [a.text() for a in sub.actions() if a.isChecked()]
    assert checked == ["Zwei"]
    assert arrangement_menu.TEXT_EXPORT in texts and arrangement_menu.TEXT_IMPORT in texts
    # Laden über das Menü
    next(a for a in sub.actions() if a.text() == "Eins").trigger()
    settle()
    assert tab_ids(plugin) == ["karte", "projekt"]
    # Menü ▾ der Schnellzugriffsleiste und Kontextmenü enthalten die Einträge
    plugin.widget.quick.menu.aboutToShow.emit()
    qat_texts = [a.text() for a in plugin.widget.quick.menu.actions()]
    assert "Ribbon anpassen …" in qat_texts and arrangement_menu.TITLE in qat_texts
    ctx_texts = [a.text() for a in plugin.widget.context_menu(None).actions()]
    assert "Ribbon anpassen …" in ctx_texts and "Klassische QGIS-Oberfläche" in ctx_texts
    menu.deleteLater()


def test_export_and_import_share_arrangement(plugin, tmp_path, no_dialogs, monkeypatch, fake_iface,
                                             settings, config):
    calls, _answers = no_dialogs
    arrs = plugin.arrangements
    arr = arrs.current()
    tab = cz.new_tab(arr, plugin.base, label="Für Kollegen")
    cz.add_command(cz.new_group(arr, plugin.base, tab, label="Projekt"), "speichern")
    arrs.set_current(arr)
    plugin.user.set_keytips({"tab:karte": "A"})
    settle()
    path = str(tmp_path / "geteilt")
    monkeypatch.setattr(arrangement_menu, "ask_save_path", lambda *a: path)
    exported = arrangement_menu.export(plugin.widget)
    assert exported == path + ".json"
    data = json.loads(open(exported, encoding="utf-8").read())
    assert data["format"] == cz.FORMAT and data["keytips"] == {"tab:karte": "A"}

    # Ein anderer Nutzer (eigene Einstellungen) importiert die Datei
    from qgis.core import QgsSettings
    from qgis.PyQt.QtCore import QSettings
    other = QgsSettings(str(tmp_path / "andere.ini"), QSettings.IniFormat)
    plugin.unload()
    settle()
    colleague = RibbonPlugin(fake_iface, config_path=config, settings=other)
    colleague.initGui()
    try:
        monkeypatch.setattr(arrangement_menu, "ask_open_path", lambda *a: exported)
        name = arrangement_menu.import_file(colleague.widget)
        settle()
        assert name == "geteilt"
        assert [t.label for t in colleague.widget.ribbon.tabs] == ["Karte", "Projekt", "Für Kollegen"]
        assert colleague.user.keytips() == {"tab:karte": "A"}
        assert colleague.arrangements.active_name() == "geteilt"
        # Erneuter Import derselben Anordnung: kein zweiter Eintrag
        assert arrangement_menu.import_file(colleague.widget) == "geteilt"
        assert colleague.arrangements.names() == ["geteilt"]
        # Andere Anordnung mit gleichem Namen bekommt einen neuen Namen
        colleague.arrangements.reset()
        colleague.arrangements.save_as("geteilt")
        assert arrangement_menu.import_file(colleague.widget) == "geteilt (2)"
        # Kaputte Datei: Meldung, nichts geändert
        bad = tmp_path / "kaputt.json"
        bad.write_text('{"format": "etwas"}', encoding="utf-8")
        monkeypatch.setattr(arrangement_menu, "ask_open_path", lambda *a: str(bad))
        assert arrangement_menu.import_file(colleague.widget) is None
        assert calls[-1][0] == "inform" and "Keine Ribbon-Anordnung" in calls[-1][1]
    finally:
        colleague.unload()
        settle()
    plugin.initGui()


def test_import_reports_unknown_entries(plugin, tmp_path, no_dialogs, monkeypatch):
    calls, _answers = no_dialogs
    path = tmp_path / "fremd.json"
    path.write_text(json.dumps(cz.make_bundle(
        {"tabs": [{"tab": "karte"}, {"tab": "unbekannt"}]}, ["neu", "gibtsnicht"], name="Fremd")),
        encoding="utf-8")
    monkeypatch.setattr(arrangement_menu, "ask_open_path", lambda *a: str(path))
    assert arrangement_menu.import_file(plugin.widget) == "Fremd"
    settle()
    text = calls[-1][1]
    assert "unbekannt" in text and "gibtsnicht" in text
    assert [c.id for c in plugin.widget.quick.commands] == ["neu"]


# -- Galerie anpassen und mitgelieferte Definition ---------------------------

@pytest.fixture
def shipped(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


def test_gallery_customize_command_and_dialog(shipped):
    plugin = shipped
    cmd = plugin.ribbon.commands["editor_galerie_anpassen"]
    assert plugin.resolver.resolve(cmd).available
    assert plugin.resolver.resolve(plugin.ribbon.commands["analyse_galerie_anpassen"]).available
    dlg = GalleryDialog(plugin.arrangements, "editor_galerie")
    try:
        standard = dlg.ids()
        assert standard[:2] == ["verschieben", "umformen"]
        dlg.list.setCurrentRow(0)
        assert dlg.remove() == "verschieben"
        dlg.list.setCurrentRow(0)
        assert dlg.move(1) == 1
        dlg.picker.select("command", "puffer")
        dlg.list.setCurrentRow(-1)
        assert dlg.add() == "puffer"
        # Steuerelemente stehen nicht zur Wahl
        with pytest.raises(KeyError):
            dlg.picker.select("command", "deckkraft")
        ids = dlg.ids()
        assert dlg.save()
    finally:
        dlg.deleteLater()
    settle()
    assert plugin.arrangements.gallery_items("editor_galerie") == ids
    plugin.widget.select_tab("bearbeiten")
    gallery = next(g for g in plugin.widget.findChildren(RibbonGallery)
                   if g.objectName() == "ribbon_gallery_editor_galerie")
    assert [t.defaultAction().command.id for t in gallery.grid.tiles][:3] == ids[:3]
    # Standard wiederherstellen speichert keine Anpassung
    dlg = GalleryDialog(plugin.arrangements, "editor_galerie")
    try:
        dlg.reset()
        assert dlg.ids() == standard
        dlg.list.clear()
        assert not dlg.save()  # Galerie im Ribbon braucht Einträge
        dlg.reset()
        assert dlg.save()
    finally:
        dlg.deleteLater()
    settle()
    assert plugin.user.layout() is None


def test_gallery_customize_command_opens_dialog(shipped, monkeypatch):
    from qgis_ribbon.ui import customize_dialog
    opened = []
    monkeypatch.setattr(customize_dialog.GalleryDialog, "exec_", lambda self: opened.append(
        (self.gallery_id, self.windowTitle())))
    plugin = shipped
    plugin.resolver.trigger(plugin.ribbon.commands["analyse_galerie_anpassen"])
    assert opened == [("processing_galerie", "Galerie anpassen: Analysewerkzeuge")]


def test_every_command_builds_in_a_custom_group(shipped, layers, fake_iface):
    """Jeder Befehl der Definition lässt sich in eine eigene Gruppe legen und baut."""
    plugin = shipped
    arr = plugin.arrangements.current()
    tab = cz.new_tab(arr, plugin.base, label="Alles")
    for i, cid in enumerate(sorted(plugin.base.commands)):
        if i % 40 == 0:
            group = cz.new_group(arr, plugin.base, tab, label="Teil %d" % (i // 40 + 1))
        cz.add_command(group, cid, cz.default_size(plugin.base.commands[cid]))
    plugin.arrangements.set_current(arr)
    settle()
    fake_iface.set_active_layer(layers["vector"])
    plugin.widget.select_tab(tab.id)
    settle()
    assert plugin.widget.is_built(tab.id)
    targets = plugin.widget.targets(tab.id)
    assert len(targets) >= len(plugin.base.commands)
    fake_iface.set_active_layer(None)
    settle()
