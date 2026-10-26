"""Erweiterungen: Plugin-Aktionen und Werkzeuge als Laufzeitbefehle."""
import pytest

from qgis_ribbon.core import config_loader
from qgis_ribbon.core import customization as cz
from qgis_ribbon.core import extensions as ext
from qgis_ribbon.core.model import ExtensionSources


def definition(**extra):
    data = {
        "version": 1,
        "extensions": {"menus": ["mPluginMenu"], "toolbars": ["mPluginToolBar"],
                       "qgis_toolbars": ["mFileToolBar"]},
        "tabs": [
            {"id": "karte", "label": "Karte",
             "groups": [{"id": "g", "label": "G", "items": [{"command": "a"}]}]},
            {"id": "erweiterungen", "label": "Erweiterungen", "dynamic": "erweiterungen"},
        ],
        "commands": {"a": {"label": "Alpha", "source": {"type": "qgis_action", "object_name": "mA"}}},
    }
    data.update(extra)
    return config_loader.parse(data)


FOUND = (
    ext.FoundAction(key=ext.key("mPluginMenu", "Reloader", "Neu laden"), label="Neu laden", group="Reloader"),
    ext.FoundAction(key=ext.key("mPluginMenu", "Reloader", "Konfigurieren"), label="Konfigurieren",
                    group="Reloader"),
    ext.FoundAction(key=ext.key("toolbar", "MeinPlugin", "Start"), label="Start", group="Mein Plugin"),
    ext.FoundAction(key=ext.key("toolbar", "ProcessingAlgorithms", "native:buffer"), label="Puffer",
                    group="Werkzeuge", algorithm="native:buffer"),
)
BUFFER = ext.Algorithm(id="native:buffer", label="Puffer", provider="native", provider_label="QGIS",
                       group="Vektorgeometrie")
SCRIPT = ext.Algorithm(id="script:mein_werkzeug", label="Mein Werkzeug", provider="script",
                       provider_label="Skripte", group="Eigene")


def test_loader_reads_dynamic_tab_and_sources():
    base = definition()
    tab = base.tab("erweiterungen")
    assert tab.dynamic == "erweiterungen" and tab.groups == ()
    assert base.extensions == ExtensionSources(menus=("mPluginMenu",), toolbars=("mPluginToolBar",),
                                               qgis_toolbars=("mFileToolBar",), hide=True)
    assert base.extensions.plugin_toolbar("MeinPlugin")
    assert not base.extensions.plugin_toolbar("mPluginToolBar")
    assert not base.extensions.plugin_toolbar("mFileToolBar")


def test_loader_rejects_wrong_dynamic_tabs():
    with pytest.raises(config_loader.ConfigError) as exc:
        definition(tabs=[
            {"id": "karte", "label": "Karte",
             "groups": [{"id": "g", "label": "G", "items": [{"command": "a"}]}]},
            {"id": "x", "label": "X", "dynamic": "unbekannt"},
            {"id": "y", "label": "Y", "dynamic": "erweiterungen",
             "groups": [{"id": "g", "label": "G", "items": [{"command": "a"}]}]},
        ], extensions={"menus": "kein Liste", "hide": "ja"})
    text = str(exc.value)
    assert "dynamic 'unbekannt' unbekannt" in text
    assert "keine festen groups" in text
    assert "menus muss eine Liste sein" in text
    assert "extensions.hide" in text


def test_key_masks_comma_and_slash():
    k = ext.key("toolbar", "A/B", "x, y %")
    assert "," not in k and k.count("/") == 2
    assert [ext.unescape(p) for p in k.split("/")] == ["toolbar", "A/B", "x, y %"]


def test_ids_and_own_tools():
    assert ext.is_runtime("plugin:x") and ext.is_runtime("verarbeitung:native:buffer")
    assert not ext.is_runtime("puffer") and not ext.is_runtime(None)
    assert ext.own_tool("verarbeitung:script:a") and ext.own_tool("verarbeitung:model:b")
    assert ext.own_tool("verarbeitung:project:c")
    assert not ext.own_tool("verarbeitung:native:buffer") and not ext.own_tool("plugin:script:a")


def test_plugin_groups_one_per_plugin_with_unique_ids():
    found = FOUND + (ext.FoundAction(key="k", label="Doppelt", group="Reloader"),
                     ext.FoundAction(key=FOUND[0].key, label="schon da", group="Anders"),
                     ext.FoundAction(key="m", label="M", group="Mein-Plugin"))
    groups = ext.plugin_groups(found)
    assert [(g[0], g[1]) for g in groups] == [
        ("erw_reloader", "Reloader"), ("erw_mein_plugin", "Mein Plugin"), ("erw_werkzeuge", "Werkzeuge"),
        ("erw_mein_plugin_2", "Mein-Plugin")]
    assert groups[0][2] == [ext.plugin_id(FOUND[0].key), ext.plugin_id(FOUND[1].key), "plugin:k"]
    assert groups[2][2] == ["verarbeitung:native:buffer"]


def test_extend_fills_dynamic_tab_and_adds_commands():
    base = definition()
    out = ext.extend(base, FOUND, [BUFFER])
    tab = out.tab("erweiterungen")
    assert [g.label for g in tab.groups] == ["Reloader", "Mein Plugin", "Werkzeuge"]
    assert [e.size for e in tab.groups[0].elements] == ["large", "large"]
    start = out.commands[ext.plugin_id(FOUND[2].key)]
    assert start.label == "Start" and start.source.type == "extension"
    assert start.source.get("key") == FOUND[2].key
    buffer = out.commands["verarbeitung:native:buffer"]
    assert buffer.source.type == "processing" and buffer.source.get("algorithm") == "native:buffer"
    assert buffer.description == "Werkzeugkasten › QGIS › Vektorgeometrie"
    assert out.tab("karte") is base.tab("karte")
    assert out.extensions == base.extensions
    assert "a" in out.commands and len(base.commands) == 1   # Definition bleibt unverändert


def test_large_groups_get_medium_buttons():
    found = tuple(ext.FoundAction(key="k%d" % i, label="L%d" % i, group="Viel") for i in range(5))
    out = ext.extend(definition(), found)
    assert {e.size for e in out.tab("erweiterungen").groups[0].elements} == {"medium"}


def test_placeholders_for_missing_runtime_commands():
    out = ext.extend(definition(), (), (), referenced={"verarbeitung:script:weg", "plugin:mPluginMenu/X/Y%2C z",
                                                       "unbekannt"})
    tool = out.commands["verarbeitung:script:weg"]
    assert tool.label == "weg" and tool.source.get("algorithm") == "script:weg"
    plug = out.commands["plugin:mPluginMenu/X/Y%2C z"]
    assert plug.label == "Y, z" and plug.source.get("key") == "mPluginMenu/X/Y%2C z"
    assert "unbekannt" not in out.commands
    assert out.tab("erweiterungen").groups == ()
    assert [t.id for t in ext.visible(out).tabs] == ["karte"]
    assert ext.visible(ext.extend(definition(), FOUND)).tab("erweiterungen").groups


def test_referenced_ids_in_layout_quick_access_and_saved():
    layout = {"tabs": [{"id": "eigener_tab_1", "label": "Meins", "groups": [
        {"id": "eigene_gruppe_1", "label": "W", "items": [
            {"command": "verarbeitung:script:a", "size": "large"}, {"command": "a"}]}]}]}
    saved = {"Arbeit": {"layout": {"tabs": [{"id": "t", "groups": [{"items": [{"command": "plugin:x"}]}]}]},
                        "quick_access": ["verarbeitung:model:m", "a"]}}
    ids = ext.referenced_ids(layout, "a,plugin:q,verarbeitung:native:buffer", saved, None)
    assert ids == {"verarbeitung:script:a", "plugin:x", "verarbeitung:model:m", "plugin:q",
                   "verarbeitung:native:buffer"}


def test_arrangement_keeps_runtime_commands_while_missing():
    base = ext.extend(definition(), FOUND, [SCRIPT])
    arr = cz.standard(base)
    tab = cz.new_tab(arr, base)
    group = cz.new_group(arr, base, tab)
    group.items.append(cz.ItemEntry("verarbeitung:script:mein_werkzeug", "large"))
    group.items.append(cz.ItemEntry(ext.plugin_id(FOUND[0].key), "medium"))
    data = cz.to_dict(arr, base)
    eff = cz.apply(base, arr)
    assert [c.command.id for c in eff.tab(tab.id).groups[0].elements] == [
        "verarbeitung:script:mein_werkzeug", ext.plugin_id(FOUND[0].key)]

    # Skript gelöscht, Plugin entladen: Platzhalter, nichts geht verloren
    later = ext.extend(definition(), (), (), referenced=ext.referenced_ids(data))
    arr2, warnings = cz.from_dict(data, later)
    assert warnings == []
    assert cz.to_dict(arr2, later) == data
    assert cz.apply(later, arr2).commands["verarbeitung:script:mein_werkzeug"].label == "mein_werkzeug"


def test_dynamic_groups_follow_plugins_in_arrangement():
    base = ext.extend(definition(), FOUND)
    arr = cz.standard(base)
    arr.tab("erweiterungen").groups[0].visible = False
    data = cz.to_dict(arr, base)
    # Neues Plugin dazu: erscheint hinten, die ausgeblendete Gruppe bleibt ausgeblendet
    more = FOUND + (ext.FoundAction(key="n", label="Neu", group="Neues Plugin"),)
    arr2, warnings = cz.from_dict(data, ext.extend(definition(), more))
    assert warnings == []
    groups = arr2.tab("erweiterungen").groups
    assert [(g.label, g.visible) for g in groups] == [
        ("Reloader", False), ("Mein Plugin", True), ("Werkzeuge", True), ("Neues Plugin", True)]


def test_with_algorithms_and_placeholders_keep_tabs():
    base = ext.extend(definition(), FOUND)
    full = ext.with_algorithms(base, [BUFFER, SCRIPT])
    assert full.tabs == base.tabs and "verarbeitung:script:mein_werkzeug" in full.commands
    assert ext.with_placeholders(base, ["a"]) is base
    more = ext.with_placeholders(base, ["plugin:neu", "nichts"])
    assert "plugin:neu" in more.commands and "nichts" not in more.commands and more.tabs == base.tabs


def test_dropdown_button_becomes_split():
    main = ext.key("toolbar", "Leiste", "Werkzeug A")
    opts = ext.key("toolbar", "Leiste", "Werkzeug A", "Optionen")
    found = (ext.FoundAction(key=main, label="Werkzeug A", group="Leiste", items=(opts, "fehlt")),
             ext.FoundAction(key=opts, label="Optionen", group="Leiste", parent=main),
             ext.FoundAction(key="b", label="Werkzeug B", group="Leiste"))
    assert [g[2] for g in ext.plugin_groups(found)] == [[ext.plugin_id(main), "plugin:b"]]
    from qgis_ribbon.core.model import CommandRef, Split
    elements = ext.extend(definition(), found).tab("erweiterungen").groups[0].elements
    assert isinstance(elements[0], Split) and isinstance(elements[1], CommandRef)
    assert elements[0].command.id == ext.plugin_id(main)
    assert [c.id for c in elements[0].items] == [ext.plugin_id(opts)]
    # Einzeln (Palette, eigene Gruppen) gibt es beide Befehle auch
    out = ext.extend(definition(), found)
    assert ext.plugin_id(opts) in out.commands
