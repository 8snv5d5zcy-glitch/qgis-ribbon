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


def test_plugin_commands_in_galleries_survive_missing_plugin():
    """Plugin-Befehle in einer Galerie bleiben als Platzhalter erhalten."""
    gal = {"label": "Grundkarte", "kind": "control", "source": {"type": "custom", "id": "ribbon.grundkarten"},
           "gallery": {"display": "dropdown", "items": ["a"]}}
    with_gallery = lambda: definition(commands={  # noqa: E731
        "a": {"label": "Alpha", "source": {"type": "qgis_action", "object_name": "mA"}}, "grund": gal})
    start = FOUND[2]
    base = ext.extend(with_gallery(), FOUND)
    arr = cz.standard(base)
    cz.set_gallery_ids(arr, base, "grund", ["a", ext.plugin_id(start.key)])
    data = cz.to_dict(arr, base)
    assert ext.referenced_ids(data) == {ext.plugin_id(start.key)}
    later = ext.extend(with_gallery(), (), (), referenced=ext.referenced_ids(data))
    arr2, warnings = cz.from_dict(data, later)
    assert warnings == []
    items = cz.apply(later, arr2).commands["grund"].gallery.items
    assert [c.id for c in items] == ["a", ext.plugin_id(start.key)]
    assert items[1] == ext.placeholder(ext.plugin_id(start.key))


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


def test_deleted_plugin_group_stays_deleted():
    full = ext.extend(definition(), FOUND)
    arr = cz.standard(full)
    tab = arr.tab("erweiterungen")
    group = tab.groups[0]
    cz.remove_group(tab, group, arr)
    data = cz.to_dict(arr, full)
    assert data["removed"] == [group.ref]
    # Plugin beim nächsten Start nicht geladen: der Verweis bleibt gelöscht
    arr, _w = cz.from_dict(data, ext.extend(definition()))
    data = cz.to_dict(arr, ext.extend(definition()))
    arr, _w = cz.from_dict(data, full)
    assert group.ref not in [g.ref for g in arr.tab("erweiterungen").groups]
    assert len(arr.tab("erweiterungen").groups) == len(full.tab("erweiterungen").groups) - 1


def _orphaned_arrangement():
    """Eigener Tab mit Skript und Plugin-Befehl, Galerie und Schnellzugriff; danach beide verschwunden."""
    gal = {"label": "Grundkarte", "kind": "control", "source": {"type": "custom", "id": "ribbon.grundkarten"},
           "gallery": {"display": "dropdown", "items": ["a"]}}
    make = lambda: definition(commands={  # noqa: E731
        "a": {"label": "Alpha", "source": {"type": "qgis_action", "object_name": "mA"}}, "grund": gal})
    base = ext.extend(make(), FOUND, [SCRIPT])
    arr = cz.standard(base)
    tab = cz.new_tab(arr, base)
    mixed = cz.new_group(arr, base, tab, label="Gemischt")
    mixed.items += [cz.ItemEntry("verarbeitung:script:mein_werkzeug", "large"), cz.ItemEntry("a", "large")]
    only = cz.new_group(arr, base, tab, label="Nur Plugin")
    only.items.append(cz.ItemEntry(ext.plugin_id(FOUND[2].key), "medium"))
    cz.set_gallery_ids(arr, base, "grund", ["a", ext.plugin_id(FOUND[2].key)])
    data = cz.to_dict(arr, base)
    qat = ["a", "verarbeitung:script:mein_werkzeug"]
    later = ext.extend(make(), (), (), referenced=ext.referenced_ids(data, ",".join(qat)))
    arr2, _warnings = cz.from_dict(data, later)
    return later, arr2, tab.id, qat


def test_placeholders_are_marked_and_hidden_in_the_ribbon():
    later, arr, tab_id, _qat = _orphaned_arrangement()
    placeholder = later.commands["verarbeitung:script:mein_werkzeug"]
    assert ext.is_placeholder(placeholder) and not ext.is_placeholder(later.commands["a"])
    eff = cz.apply(later, arr)
    assert [g.label for g in eff.tab(tab_id).groups] == ["Gemischt", "Nur Plugin"]
    shown = ext.visible(eff)
    groups = shown.tab(tab_id).groups
    assert [g.label for g in groups] == ["Gemischt"]          # leere Gruppe fällt weg
    assert [e.command.id for e in groups[0].elements] == ["a"]
    assert placeholder.id in shown.commands                    # Daten bleiben
    # Galerie: der Platzhalter fehlt dort, wo sie in einer Gruppe steht
    grund = eff.commands["grund"]
    assert [c.id for c in grund.gallery.items] == ["a", ext.plugin_id(FOUND[2].key)]
    assert [c.id for c in ext._command(grund).gallery.items] == ["a"]


def test_quick_access_hides_placeholders_but_keeps_them_stored():
    from qgis_ribbon.core import quick_access
    later, arr, _tab_id, qat = _orphaned_arrangement()
    eff = ext.visible(cz.apply(later, arr))
    stored = ",".join(qat)
    assert [c.id for c in quick_access.effective(eff, stored)] == ["a"]
    keep = quick_access.hidden(eff, stored)
    assert keep == ["verarbeitung:script:mein_werkzeug"]
    # Ändern im Ribbon (hier: leeren) verliert den ausgeblendeten Eintrag nicht
    assert quick_access.serialize((), keep) == "verarbeitung:script:mein_werkzeug"


def test_without_placeholders_drops_emptied_custom_tab_but_keeps_a_main_tab():
    base = ext.extend(definition(), (), (), referenced={"plugin:mPluginMenu/X/Y"})
    arr = cz.standard(base)
    tab = cz.new_tab(arr, base)
    cz.new_group(arr, base, tab).items.append(cz.ItemEntry("plugin:mPluginMenu/X/Y", "large"))
    eff = cz.apply(base, arr)
    assert tab.id in [t.id for t in eff.tabs]
    assert tab.id not in [t.id for t in ext.visible(eff).tabs]
    assert ext.without_placeholders(definition()) is not None
    clean = ext.extend(definition(), FOUND[:3])
    assert ext.without_placeholders(clean) is clean


def test_orphans_are_listed_and_removed_in_one_step():
    from qgis_ribbon.core import editor as ed
    later, arr, tab_id, qat = _orphaned_arrangement()
    editor = ed.Editor(later, arr, qat)
    orphans = editor.orphans()
    assert orphans == ["verarbeitung:script:mein_werkzeug", ext.plugin_id(FOUND[2].key)]   # nach Beschriftung
    assert editor.remove_orphans(["verarbeitung:script:mein_werkzeug", "a"]) == 1
    assert editor.qat == ["a"]
    groups = editor.arr.tab(tab_id).groups
    assert [i.command for i in groups[0].items] == ["a"]
    assert editor.orphans() == [ext.plugin_id(FOUND[2].key)]
    assert editor.remove_orphans(editor.orphans()) == 1
    assert groups[1].items == [] and cz.gallery_ids(editor.arr, later, "grund") == ["a"]
    assert editor.orphans() == []
    editor.undo()
    editor.undo()
    assert len(editor.orphans()) == 2 and editor.qat == qat


def test_unique_keys_count_up_and_first_keeps_its_key():
    taken = {}
    keys = []
    for _i in range(3):
        k = ext.unique_key(ext.key("toolbar", "Clipper", "Clipper"), taken)
        taken[k] = True
        keys.append(k)
    assert keys == ["toolbar/Clipper/Clipper", "toolbar/Clipper/Clipper#2", "toolbar/Clipper/Clipper#3"]
    assert ext.unique_key("frei", taken) == "frei"


def plugin_menu_found():
    """Plugin mit eigenem Hauptmenü: Eintrag direkt, Untermenü mit Unteruntermenü."""
    top = ("menubar", "HCM")
    basemaps = ext.key(*top, "Grundkarten")
    google = ext.key(*top, "Grundkarten", "Google")
    return (
        ext.FoundAction(key=ext.key(*top, "Über"), label="Über", group="HCM"),
        ext.FoundAction(key=basemaps, label="Grundkarten", group="HCM", menu=True,
                        items=(ext.key(*top, "Grundkarten", "OSM"), google)),
        ext.FoundAction(key=ext.key(*top, "Grundkarten", "OSM"), label="OSM", group="HCM", parent=basemaps),
        ext.FoundAction(key=google, label="Google", group="HCM", menu=True, parent=basemaps,
                        items=(ext.key(*top, "Grundkarten", "Google", "Satellit"),
                               ext.key(*top, "Grundkarten", "Google", "Straße"))),
        ext.FoundAction(key=ext.key(*top, "Grundkarten", "Google", "Satellit"), label="Satellit", group="HCM",
                        parent=google),
        ext.FoundAction(key=ext.key(*top, "Grundkarten", "Google", "Straße"), label="Straße", group="HCM",
                        parent=google),
    )


def test_plugin_submenu_becomes_dropdown_with_submenus():
    from qgis_ribbon.core.model import CommandRef, Menu, SubMenu
    found = plugin_menu_found()
    out = ext.extend(definition(), found)
    group = out.tab("erweiterungen").groups[0]
    assert group.label == "HCM"
    about, menu = group.elements
    assert isinstance(about, CommandRef) and about.command.label == "Über"
    assert isinstance(menu, Menu) and menu.label == "Grundkarten"
    assert menu.key == ext.menu_id(found[1].key)
    osm, google = menu.items
    assert osm.id == ext.plugin_id(found[2].key)
    assert isinstance(google, SubMenu) and [c.label for c in google.items] == ["Satellit", "Straße"]
    # Jeder Eintrag bleibt ein eigener Befehl, das Menü ist keiner
    for f in found:
        assert (ext.plugin_id(f.key) in out.commands) != f.menu
    # Schlüssel des Elements für Anpassungen ist sprachunabhängig und eindeutig
    assert cz.element_key(menu, "erweiterungen/erw_hcm").endswith(ext.menu_id(found[1].key))


def test_plugin_menu_entries_survive_arrangement_round_trip():
    full = ext.extend(definition(), plugin_menu_found())
    arr = cz.standard(full)
    data = cz.to_dict(arr, full)
    again, warnings = cz.from_dict(data, full)
    assert not warnings
    assert cz.to_dict(again, full) == data
