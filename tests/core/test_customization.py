"""Anordnung des Ribbons anpassen, speichern, laden und teilen."""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core import config_loader, customization as cz  # noqa: E402
from qgis_ribbon.core.context import ContextLogic  # noqa: E402
from qgis_ribbon.core.model import CommandRef, Menu, iter_commands  # noqa: E402


def qa(name):
    return {"type": "qgis_action", "object_name": name}


DEFINITION = {
    "version": 1,
    "quick_access": ["neu"],
    "commands": {
        "neu": {"label": "Neu", "source": qa("mActionNewProject")},
        "speichern": {"label": "Speichern", "source": qa("mActionSaveProject")},
        "zoomen": {"label": "Zoomen", "source": qa("mActionZoomIn")},
        "verschieben": {"label": "Verschieben", "source": qa("mActionPan")},
        "drehen": {"label": "Drehen", "source": qa("mActionRotateFeature")},
        "loeschen": {"label": "Löschen", "source": qa("mActionDeleteSelected"),
                     "enabled_when": ["active_layer_is_editable"]},
        "deckkraft": {"label": "Deckkraft", "kind": "control",
                      "source": {"type": "custom", "id": "ribbon.deckkraft"}},
        "werkzeuge": {"label": "Werkzeuge", "kind": "control",
                      "source": {"type": "custom", "id": "ribbon.editor_galerie"},
                      "gallery": {"display": "ribbon", "columns": 2,
                                  "items": ["verschieben", "drehen"]}},
    },
    "tabs": [
        {"id": "karte", "label": "Karte", "groups": [
            {"id": "nav", "label": "Navigieren", "items": [{"command": "zoomen"}]},
            {"id": "projekt", "label": "Projekt", "items": [{"command": "neu"},
                                                            {"command": "speichern"}]}]},
        {"id": "bearbeiten", "label": "Bearbeiten", "groups": [
            {"id": "nav", "label": "Navigieren", "items": [{"command": "verschieben"}]},
            {"id": "werkzeuge", "label": "Werkzeuge", "items": [
                {"menu": "Werkzeuge", "gallery": "werkzeuge", "items": ["loeschen"]}]}]},
    ],
    "contextual_tabs": [
        {"id": "vektor", "label": "Darstellung", "context": "Vektorlayer",
         "visible_when": ["active_layer_is_vector"], "groups": [
             {"id": "effekte", "label": "Effekte", "items": [{"command": "deckkraft"}]}]},
    ],
}


@pytest.fixture
def base():
    return config_loader.parse(copy.deepcopy(DEFINITION))


def layout(ribbon):
    return [(t.id, [g.id for g in t.groups]) for t in ribbon.tabs]


def test_standard_is_unchanged_definition(base):
    arr = cz.standard(base)
    assert cz.is_standard(arr, base)
    assert cz.to_dict(arr, base) is None
    assert cz.apply(base, arr) is base
    assert cz.from_dict(None, base) == (arr, [])


def test_hide_and_reorder_tabs_and_groups(base):
    arr = cz.standard(base)
    assert cz.move_tab(arr, 1, -1) == 0
    arr.tab("karte").groups[0].visible = False
    assert cz.move_in_list(arr.tab("karte").groups, 1, -1) == 0
    eff = cz.apply(base, arr)
    assert layout(eff) == [("bearbeiten", ["nav", "werkzeuge"]), ("karte", ["projekt"]),
                           ("vektor", ["effekte"])]
    # Kontext-Tabs bleiben hinter den Haupt-Tabs
    assert cz.move_tab(arr, 1, 1) is None
    assert cz.move_tab(arr, 2, -1) is None


def test_roundtrip_keeps_only_differences(base):
    arr = cz.standard(base)
    arr.tab("bearbeiten").visible = False
    data = cz.to_dict(arr, base)
    assert data == {"tabs": [{"tab": "karte"}, {"tab": "bearbeiten", "visible": False},
                             {"tab": "vektor"}]}
    data = json.loads(json.dumps(data))
    again, warnings = cz.from_dict(data, base)
    assert again == arr and warnings == []


def test_custom_tab_and_group_with_commands(base):
    arr = cz.standard(base)
    tab = cz.new_tab(arr, base, after=0, label="Mein Tab")
    assert tab.id == "eigener_tab_1" and arr.tabs[1] is tab
    group = cz.new_group(arr, base, tab, label="Häufig")
    cz.add_command(group, "loeschen", "medium")
    cz.add_command(group, "deckkraft", "large")
    cz.add_command(group, "werkzeuge", "large")
    eff = cz.apply(base, arr)
    mine = eff.tab("eigener_tab_1")
    assert [g.label for g in mine.groups] == ["Häufig"]
    elements = mine.groups[0].elements
    assert all(isinstance(e, CommandRef) for e in elements)
    assert [(e.command.id, e.size) for e in elements] == [("loeschen", "medium"), ("deckkraft", "large"),
                                                          ("werkzeuge", "large")]
    # Kontextlogik kennt die Bedingungen der Befehle im eigenen Tab
    logic = ContextLogic(eff)
    assert not logic.command_enabled("loeschen")
    again, warnings = cz.from_dict(json.loads(json.dumps(cz.to_dict(arr, base))), base)
    assert again == arr and not warnings


def test_custom_group_in_standard_and_context_tab(base):
    arr = cz.standard(base)
    g = cz.new_group(arr, base, arr.tab("karte"), after=0)
    cz.add_command(g, "drehen")
    cz.new_group(arr, base, arr.tab("vektor"))
    eff = cz.apply(base, arr)
    assert [x.id for x in eff.tab("karte").groups] == ["nav", "eigene_gruppe_1", "projekt"]
    assert eff.tab("vektor").contextual and len(eff.tab("vektor").groups) == 2


def test_group_from_other_tab_gets_unique_id(base):
    arr = cz.standard(base)
    karte = arr.tab("karte")
    assert cz.add_group_ref(karte, base, "bearbeiten/nav") is not None
    assert cz.add_group_ref(karte, base, "bearbeiten/nav") is None  # schon da
    eff = cz.apply(base, arr)
    ids = [g.id for g in eff.tab("karte").groups]
    assert ids == ["nav", "projekt", "bearbeiten_nav"]
    assert [c.id for c in iter_commands(eff.tab("karte").groups[2])] == ["verschieben"]


def test_standard_items_only_hidden_not_removed(base):
    arr = cz.standard(base)
    karte = arr.tab("karte")
    assert not cz.can_remove_tab(karte)
    assert not cz.can_remove_group(karte, karte.groups[0])
    with pytest.raises(ValueError):
        cz.remove_group(karte, karte.groups[0])
    with pytest.raises(ValueError):
        cz.remove_tab(arr, karte)
    copy_ = cz.add_group_ref(karte, base, "bearbeiten/werkzeuge")
    assert cz.can_remove_group(karte, copy_)
    cz.remove_group(karte, copy_)
    # Ausgeblendete Gruppe am eigenen Platz wird beim Hinzufügen wieder eingeblendet
    karte.groups[0].visible = False
    assert cz.add_group_ref(karte, base, "karte/nav") is karte.groups[0]
    assert karte.groups[0].visible
    with pytest.raises(ValueError):
        cz.add_command(karte.groups[0], "neu")


def test_problems_need_a_visible_main_tab(base):
    arr = cz.standard(base)
    for t in arr.tabs:
        t.visible = False
    assert cz.problems(arr) == ["Mindestens ein Haupt-Tab muss sichtbar bleiben."]
    assert cz.apply(base, arr) is base
    arr.tabs[0].visible = True
    tab = cz.new_tab(arr, base, label=" ")
    cz.new_group(arr, base, tab, label="")
    assert len(cz.problems(arr)) == 2


def test_customized_gallery(base):
    arr = cz.standard(base)
    assert set(cz.galleries(base)) == {"werkzeuge"}
    arr.galleries["werkzeuge"] = ["drehen", "zoomen"]
    eff = cz.apply(base, arr)
    menu = eff.tab("bearbeiten").groups[1].elements[0]
    assert isinstance(menu, Menu)
    assert [c.id for c in menu.gallery.gallery.items] == ["drehen", "zoomen"]
    assert eff.commands["werkzeuge"].gallery.items[0].id == "drehen"
    assert base.commands["werkzeuge"].gallery.items[0].id == "verschieben"  # Definition unverändert
    data = cz.to_dict(arr, base)
    assert data == {"galleries": {"werkzeuge": ["drehen", "zoomen"]}}
    # Standardinhalt wird nicht gespeichert
    arr.galleries["werkzeuge"] = ["verschieben", "drehen"]
    assert cz.to_dict(arr, base) is None


def test_gallery_rejects_controls_and_empty_ribbon_gallery(base):
    arr, warnings = cz.from_dict({"galleries": {"werkzeuge": ["deckkraft", "gibtsnicht"]}}, base)
    assert arr.galleries == {}
    assert len(warnings) == 3
    arr, warnings = cz.from_dict({"galleries": {"unbekannt": ["zoomen"]}}, base)
    assert arr.galleries == {} and warnings


def test_unknown_ids_are_skipped_with_warnings(base):
    data = {"tabs": [
        {"tab": "gibtsnicht"},
        {"tab": "bearbeiten", "groups": [{"group": "bearbeiten/weg"}, {"group": "bearbeiten/nav"}]},
        {"id": "eigener_tab_1", "label": "Mein Tab", "groups": [
            {"id": "eigene_gruppe_1", "label": "G", "items": [{"command": "weg"}, "zoomen"]}]},
        {"id": "Ungültig!", "label": "X"},
    ]}
    arr, warnings = cz.from_dict(data, base)
    assert len(warnings) == 4
    ids = [t.id for t in arr.tabs]
    # Fehlende Tabs der Definition kommen dazu: Karte hinter den letzten Haupt-Tab, Kontext ans Ende
    assert ids == ["bearbeiten", "eigener_tab_1", "karte", "vektor"]
    # Gruppe „werkzeuge“ fehlte in der Liste und wird hinten angefügt
    assert [g.ref for g in arr.tab("bearbeiten").groups] == ["bearbeiten/nav", "bearbeiten/werkzeuge"]
    assert [i.command for i in arr.tab("eigener_tab_1").groups[0].items] == ["zoomen"]


def test_new_definition_tabs_and_groups_appear(base):
    arr = cz.standard(base)
    arr.tab("karte").groups.reverse()
    data = cz.to_dict(arr, base)
    bigger = copy.deepcopy(DEFINITION)
    bigger["tabs"][0]["groups"].append({"id": "neu", "label": "Neu", "items": [{"command": "drehen"}]})
    bigger["tabs"].append({"id": "extra", "label": "Extra", "groups": [
        {"id": "x", "label": "X", "items": [{"command": "zoomen"}]}]})
    base2 = config_loader.parse(bigger)
    arr2, warnings = cz.from_dict(data, base2)
    assert not warnings
    assert [t.id for t in arr2.tabs] == ["karte", "bearbeiten", "extra", "vektor"]
    assert [g.id for g in arr2.tab("karte").groups] == ["projekt", "nav", "neu"]


def test_custom_ids_unique_and_not_colliding(base):
    arr = cz.standard(base)
    t1 = cz.new_tab(arr, base)
    t2 = cz.new_tab(arr, base)
    g1 = cz.new_group(arr, base, t1)
    g2 = cz.new_group(arr, base, t2)
    assert len({t1.id, t2.id, g1.id, g2.id}) == 4
    data = {"tabs": [{"tab": "karte"}, {"id": "karte", "label": "Doppelt"},
                     {"id": "eigener_tab_1", "label": "A"}, {"id": "eigener_tab_1", "label": "B"}]}
    arr, warnings = cz.from_dict(data, base)
    assert [t.label for t in arr.tabs if not t.standard] == ["A"]
    assert len(warnings) == 2


def test_custom_group_with_same_id_as_standard_group(base):
    data = {"tabs": [{"tab": "karte", "groups": [
        {"group": "karte/nav"}, {"id": "projekt_x", "label": "Eigen", "items": []},
        {"group": "karte/projekt"}]}]}
    arr, _ = cz.from_dict(data, base)
    arr.tab("karte").groups[1].id = "projekt"  # gleiche ID wie die Gruppe der Definition
    eff = cz.apply(base, arr)
    ids = [g.id for g in eff.tab("karte").groups]
    assert len(set(ids)) == 3


def test_bundle_roundtrip_and_errors(base):
    arr = cz.standard(base)
    arr.tab("karte").visible = False
    bundle = cz.make_bundle(cz.to_dict(arr, base), ["speichern"], {"tab:karte": "K"}, name="Test")
    text = json.dumps(bundle, ensure_ascii=False)
    read = cz.read_bundle(json.loads(text))
    assert read.name == "Test" and read.quick_access == ["speichern"]
    assert read.keytips == {"tab:karte": "K"}
    assert cz.from_dict(read.layout, base)[0] == arr
    empty = cz.read_bundle(cz.make_bundle(None))
    assert empty.layout is None and empty.quick_access is None and empty.keytips == {}
    with pytest.raises(cz.BundleError):
        cz.read_bundle({"format": "etwas anderes"})
    with pytest.raises(cz.BundleError):
        cz.read_bundle({"format": cz.FORMAT, "version": 99})
    with pytest.raises(cz.BundleError):
        cz.read_bundle([])


def test_shipped_definition_galleries_customizable():
    pytest.importorskip("yaml")
    base = config_loader.load()
    gals = cz.galleries(base)
    assert {"editor_galerie", "processing_galerie"} <= set(gals)
    arr = cz.standard(base)
    assert cz.apply(base, arr) is base
    tab = cz.new_tab(arr, base, label="Alles")
    group = cz.new_group(arr, base, tab)
    for cid in sorted(base.commands):
        cz.add_command(group, cid, "small")
    eff = cz.apply(base, arr)
    assert len(eff.tab(tab.id).groups[0].elements) == len(base.commands)


def test_default_size(base):
    assert cz.default_size(base.commands["deckkraft"]) == "medium"
    assert cz.default_size(base.commands["werkzeuge"]) == "large"
    assert cz.default_size(base.commands["zoomen"]) == "large"
