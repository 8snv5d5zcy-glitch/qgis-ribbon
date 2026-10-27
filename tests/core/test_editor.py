"""Anpassbare Gruppen der Definition (Format 2), Editor-Operationen und Verlauf."""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core import config_loader, customization as cz  # noqa: E402
from qgis_ribbon.core import editor as ed  # noqa: E402
from qgis_ribbon.core.editor import EditError, Editor, Place  # noqa: E402
from qgis_ribbon.core.model import CommandRef, Menu, Row, Split  # noqa: E402


def qa(name):
    return {"type": "qgis_action", "object_name": name}


DEFINITION = {
    "version": 1,
    "quick_access": ["neu", "speichern"],
    "commands": {
        "neu": {"label": "Neu", "source": qa("mActionNewProject")},
        "speichern": {"label": "Speichern", "source": qa("mActionSaveProject")},
        "zoomen": {"label": "Zoomen", "source": qa("mActionZoomIn")},
        "verkleinern": {"label": "Herauszoomen", "source": qa("mActionZoomOut")},
        "verschieben": {"label": "Verschieben", "source": qa("mActionPan")},
        "rechteck": {"label": "Rechteck", "source": qa("mActionSelectRectangle")},
        "polygon": {"label": "Polygon", "source": qa("mActionSelectPolygon")},
        "puffer": {"label": "Puffer", "source": {"type": "processing", "algorithm": "native:buffer"}},
        "histogramm": {"label": "Histogramm", "source": qa("mActionHistogram"),
                       "enabled_when": ["active_layer_is_raster"]},
        "loeschen": {"label": "Löschen", "source": qa("mActionDeleteSelected"),
                     "enabled_when": ["active_layer_is_editable"]},
        "deckkraft": {"label": "Deckkraft", "kind": "control",
                      "source": {"type": "custom", "id": "ribbon.deckkraft"}},
    },
    "tabs": [
        {"id": "karte", "label": "Karte", "groups": [
            {"id": "nav", "label": "Navigieren", "items": [
                {"command": "verschieben"}, {"row": ["zoomen", "verkleinern"]}]},
            {"id": "auswahl", "label": "Auswahl", "items": [
                {"split": "rechteck", "items": ["polygon"]},
                {"menu": "Mehr", "items": ["loeschen"]}]}]},
        {"id": "analyse", "label": "Analyse", "groups": [
            {"id": "werkzeuge", "label": "Werkzeuge", "items": [{"command": "puffer"}]}]},
    ],
    "contextual_tabs": [
        {"id": "vektor", "label": "Darstellung", "context": "Vektorlayer",
         "visible_when": ["active_layer_is_vector"], "groups": [
             {"id": "effekte", "label": "Effekte", "items": [{"command": "deckkraft", "size": "medium"}]}]},
    ],
}


@pytest.fixture
def base():
    return config_loader.parse(copy.deepcopy(DEFINITION))


def roundtrip(arr, base):
    data = json.loads(json.dumps(cz.to_dict(arr, base)))
    again, warnings = cz.from_dict(data, base)
    assert not warnings
    return again, data


# -- Datenmodell (Format 2) ---------------------------------------------------

def test_element_keys_and_standard_items(base):
    index, by_group = cz.element_index(base)
    assert by_group["karte/nav"] == ["command:verschieben", "row:zoomen"]
    assert by_group["karte/auswahl"] == ["split:rechteck", "menu:karte/auswahl/Mehr"]
    assert isinstance(index["split:rechteck"], Split) and isinstance(index["row:zoomen"], Row)
    items = cz.standard_items(base, "karte/auswahl")
    assert [(i.element, i.size) for i in items] == [("split:rechteck", "large"),
                                                     ("menu:karte/auswahl/Mehr", "large")]
    assert cz.standard_items(base, "karte/nav")[1].size is None  # Zeile ohne Größe


def test_every_shipped_group_rebuilds_from_its_items():
    pytest.importorskip("yaml")
    base = config_loader.load()
    for ref, (_tab, group) in cz.standard_groups(base).items():
        items = cz.standard_items(base, ref)
        assert cz._elements(base, items) == group.elements, ref
    # Persönliche Fassung aller Gruppen, die der Definition entspricht, ändert nichts
    arr = cz.standard(base)
    for t in arr.tabs:
        for g in t.groups:
            cz.make_personal(base, g)
    assert cz.apply(base, arr).tabs == base.tabs
    for t in arr.tabs:
        for g in t.groups:
            cz.normalize(base, g)
    assert cz.to_dict(arr, base) is None


def test_format1_layout_reads_unchanged(base):
    """Anordnungen im Format 1 laden unverändert und werden gleich geschrieben."""
    v1 = {"tabs": [
        {"tab": "analyse"},
        {"tab": "karte", "visible": False, "groups": [
            {"group": "karte/auswahl"},
            {"id": "eigene_gruppe_1", "label": "Häufig", "items": [
                {"command": "puffer", "size": "medium"}]},
            {"group": "karte/nav", "visible": False}]},
        {"id": "eigener_tab_1", "label": "Mein Tab", "groups": [{"group": "analyse/werkzeuge"}]},
        {"tab": "vektor"}],
        "galleries": {}}
    arr, warnings = cz.from_dict(v1, base)
    assert not warnings
    out = cz.to_dict(arr, base)
    v1.pop("galleries")
    assert out == v1
    assert all(g.items is None for t in arr.tabs for g in t.groups if g.ref)


def test_bundle_version_1_is_read_and_3_is_written(base):
    assert cz.make_bundle(None)["version"] == 3
    old = {"format": cz.FORMAT, "version": 1, "layout": {"tabs": [{"tab": "karte", "visible": False},
                                                                   {"tab": "analyse"}, {"tab": "vektor"}]},
           "quick_access": None, "keytips": {}}
    bundle = cz.read_bundle(old)
    arr, warnings = cz.from_dict(bundle.layout, base)
    assert not warnings and not arr.tab("karte").visible
    assert cz.same_bundle(old, cz.make_bundle(old["layout"], name="X"))
    assert cz.read_bundle(dict(old, version=2)).layout == old["layout"]
    with pytest.raises(cz.BundleError):
        cz.read_bundle(dict(old, version=4))


def test_personal_version_of_definition_group(base):
    arr = cz.standard(base)
    e = Editor(base, arr)
    e.insert_command("karte", 0, 1, "puffer")
    group = e.arr.tab("karte").groups[0]
    assert cz.is_modified(base, group)
    data = cz.to_dict(e.arr, base)
    assert data["tabs"][0] == {"tab": "karte", "groups": [
        {"group": "karte/nav", "items": [{"command": "verschieben", "size": "large"},
                                         {"command": "puffer", "size": "large"},
                                         {"element": "row:zoomen"}]},
        {"group": "karte/auswahl"}]}
    eff = cz.apply(base, e.arr)
    nav = eff.tab("karte").groups[0]
    assert nav.id == "nav" and nav.label == "Navigieren"
    assert [type(x).__name__ for x in nav.elements] == ["CommandRef", "CommandRef", "Row"]
    again, _ = roundtrip(e.arr, base)
    assert again == e.arr


def test_rename_and_reset_definition_group(base):
    e = Editor(base, cz.standard(base))
    e.rename_group("karte", 1, "Meine Auswahl")
    e.remove_item(Place("karte", 1, 1))
    eff = cz.apply(base, e.arr)
    assert eff.tab("karte").groups[1].label == "Meine Auswahl"
    assert len(eff.tab("karte").groups[1].elements) == 1
    again, data = roundtrip(e.arr, base)
    assert data["tabs"][0]["groups"][1]["label"] == "Meine Auswahl"
    e.reset_group("karte", 1)
    assert not cz.is_modified(base, e.arr.tab("karte").groups[1])
    assert cz.to_dict(e.arr, base) is None
    with pytest.raises(EditError):
        e.rename_group("karte", 1, "  ")


def test_moving_back_restores_standard(base):
    e = Editor(base, cz.standard(base))
    e.move_item(Place("karte", 0, 0), "karte", 0, 2)   # Verschieben hinter die Zeile
    assert cz.to_dict(e.arr, base) is not None
    e.move_item(Place("karte", 0, 1), "karte", 0, 0)
    assert cz.to_dict(e.arr, base) is None and e.arr.tab("karte").groups[0].items is None


def test_units_of_definition_move_as_a_whole(base):
    e = Editor(base, cz.standard(base))
    place = e.new_group("analyse", label="Mix")
    e.move_item(Place("karte", 1, 0), "analyse", place.group, 0)     # Split
    e.move_item(Place("karte", 0, 1), "analyse", place.group, 1)     # Zeile
    e.set_size(Place("analyse", place.group, 0), "medium")
    with pytest.raises(EditError):
        e.set_size(Place("analyse", place.group, 1), "small")       # Zeile ohne Größe
    eff = cz.apply(base, e.arr)
    mix = eff.tab("analyse").groups[1]
    assert isinstance(mix.elements[0], Split) and mix.elements[0].size == "medium"
    assert [c.id for c in mix.elements[0].items] == ["polygon"]
    assert isinstance(mix.elements[1], Row)
    assert [type(x) for x in eff.tab("karte").groups[1].elements] == [Menu]
    again, data = roundtrip(e.arr, base)
    assert again == e.arr
    assert {"element": "split:rechteck", "size": "medium"} in data["tabs"][1]["groups"][1]["items"]


def test_missing_element_is_skipped_with_warning(base):
    data = {"tabs": [{"tab": "karte", "groups": [
        {"group": "karte/nav", "items": [{"element": "split:gibtsnicht"}, {"command": "weg"},
                                         {"command": "zoomen", "size": "small"}]}]}]}
    arr, warnings = cz.from_dict(data, base)
    assert len(warnings) == 2
    assert [i.command for i in arr.tab("karte").groups[0].items] == ["zoomen"]


def test_emptied_definition_group_disappears(base):
    e = Editor(base, cz.standard(base))
    e.remove_item(Place("analyse", 0, 0))
    eff = cz.apply(base, e.arr)
    assert eff.tab("analyse").groups == ()
    again, _ = roundtrip(e.arr, base)
    assert again.tab("analyse").groups[0].items == []


# -- Regeln ---------------------------------------------------------------------

def test_no_duplicate_in_same_group_but_in_same_tab(base):
    e = Editor(base, cz.standard(base))
    with pytest.raises(EditError, match="schon in dieser Gruppe"):
        e.insert_command("karte", 0, 0, "verschieben")
    with pytest.raises(EditError, match="schon in dieser Gruppe"):
        e.insert_command("karte", 0, 0, "zoomen")       # steckt in der Zeile
    with pytest.raises(EditError, match="schon in dieser Gruppe"):
        e.insert_command("karte", 1, 0, "rechteck")     # Hauptbefehl des Splits
    e.insert_command("karte", 1, 0, "verschieben")      # andere Gruppe im selben Tab: erlaubt
    assert not e.can_undo or e.undo_label() == "„Verschieben“ einfügen"
    assert ed.can_insert(e.arr, base, "karte", 1, cz.ItemEntry("verschieben")) is not None


def test_context_tab_takes_only_fitting_commands(base):
    e = Editor(base, cz.standard(base))
    with pytest.raises(EditError, match="passt nicht"):
        e.insert_command("vektor", 0, 0, "histogramm")
    e.insert_command("vektor", 0, 0, "puffer")
    e.insert_command("vektor", 0, 0, "loeschen")         # bearbeitbarer Vektorlayer möglich
    with pytest.raises(EditError):
        e.new_group("vektor", item=cz.ItemEntry("histogramm"))
    e.insert_command("analyse", 0, 0, "histogramm")
    with pytest.raises(EditError, match="passt nicht"):
        e.move_group("analyse", 0, "vektor", 0)


def test_failed_operation_leaves_state_and_history(base):
    e = Editor(base, cz.standard(base))
    before = copy.deepcopy(e.arr)
    with pytest.raises(EditError):
        e.insert_command("karte", 0, 0, "verschieben")
    assert e.arr == before and not e.can_undo and not e.dirty


# -- Gruppen und Tabs -------------------------------------------------------------

def test_groups_move_within_and_between_tabs(base):
    e = Editor(base, cz.standard(base))
    assert e.move_group("karte", 0, "karte", 2) == Place("karte", 1)
    assert [g.id for g in e.arr.tab("karte").groups] == ["auswahl", "nav"]
    # Gruppe der Definition in einen anderen Tab: Kopie, das Original bleibt
    assert e.move_group("karte", 1, "analyse", 0) == Place("analyse", 0)
    assert [g.ref for g in e.arr.tab("analyse").groups] == ["karte/nav", "analyse/werkzeuge"]
    assert len(e.arr.tab("karte").groups) == 2
    with pytest.raises(EditError, match="schon in"):
        e.move_group("karte", 1, "analyse", 0)
    # Eigene Gruppe wandert ganz
    p = e.new_group("karte", 0, label="Eigen", item=cz.ItemEntry("puffer"))
    e.move_group("karte", p.group, "analyse", 3)
    assert [g.label for g in e.arr.tab("analyse").groups][-1] == "Eigen"
    assert "Eigen" not in [g.label for g in e.arr.tab("karte").groups]


def test_remove_group_deletes_home_groups_and_palette_restores(base):
    e = Editor(base, cz.standard(base))
    e.set_group_visible("karte", 0, False)
    e.copy_group_ref("karte/nav", "karte")        # ausgeblendete wieder einblenden
    assert e.arr.tab("karte").groups[0].visible
    assert e.remove_group("karte", 0) is True
    assert [g.ref for g in e.arr.tab("karte").groups] == ["karte/auswahl"]
    assert e.arr.removed == {"karte/nav"}
    p = e.copy_group_ref("karte/nav", "analyse", 0)  # Kopie anderswo: bleibt gelöscht am eigenen Platz
    assert e.arr.removed == {"karte/nav"}
    assert e.remove_group("analyse", p.group) is True
    p = e.copy_group_ref("karte/nav", "karte", 0)     # zurück in den eigenen Tab
    assert e.arr.removed == set() and e.arr.tab("karte").groups[0].ref == "karte/nav"
    with pytest.raises(EditError):
        e.copy_group_ref("karte/nav", "karte")
    e.undo()
    e.undo()
    e.undo()
    assert e.arr.removed == {"karte/nav"}
    e.undo()
    assert e.arr.removed == set()


def test_moving_home_group_to_other_tab_copies_it(base):
    e = Editor(base, cz.standard(base))
    e.move_group("karte", 0, "analyse", 0)
    assert e.arr.tab("karte").groups[0].ref == "karte/nav"
    assert e.arr.tab("analyse").groups[0].ref == "karte/nav"
    assert e.arr.removed == set()


def test_tabs_move_hide_rename(base):
    e = Editor(base, cz.standard(base))
    p = e.new_tab(label="Mein Tab")
    assert [t.id for t in e.arr.tabs] == ["karte", "analyse", p.tab, "vektor"]
    e.move_tab(p.tab, 0)
    assert e.arr.tabs[0].id == p.tab
    e.move_tab(p.tab, 99)                              # nicht hinter Kontext-Tabs
    assert [t.id for t in e.arr.tabs] == ["karte", "analyse", p.tab, "vektor"]
    assert e.move_tab_by("vektor", -1) is None
    assert e.move_tab_by("karte", 1) == Place("karte")
    assert [t.id for t in e.arr.tabs][:2] == ["analyse", "karte"]
    e.rename_tab(p.tab, "Häufig")
    with pytest.raises(EditError):
        e.rename_tab("karte", "Anders")
    e.set_tab_visible("karte", False)
    e.set_tab_visible("analyse", False)
    assert e.problems() == []                          # der eigene Tab ist noch sichtbar
    assert e.remove_tab(p.tab) is True
    assert e.problems() == ["Mindestens ein Haupt-Tab muss sichtbar bleiben."]


def test_remove_and_restore_tabs_of_the_definition(base):
    e = Editor(base, cz.standard(base))
    assert e.removed_tabs() == []
    assert e.remove_tab("karte") is True
    assert [t.id for t in e.arr.tabs] == ["analyse", "vektor"] and e.arr.removed == {"karte"}
    assert [t.id for t in e.removed_tabs()] == ["karte"]
    with pytest.raises(EditError):
        e.remove_tab("analyse")                        # letzter Haupt-Tab bleibt
    assert e.remove_tab("vektor") is False and not e.arr.tab("vektor").visible   # Kontext-Tab: ausblenden
    assert e.restore_tab("karte") == Place("karte")
    assert [t.id for t in e.arr.tabs] == ["karte", "analyse", "vektor"]
    assert [g.ref for g in e.arr.tab("karte").groups] == ["karte/nav", "karte/auswahl"]
    assert e.arr.removed == set()
    with pytest.raises(EditError):
        e.restore_tab("karte")
    # Gelöschte Gruppen des Tabs kommen beim Wiederherstellen mit
    e.remove_group("karte", 1)
    e.remove_tab("karte")
    assert e.arr.removed == {"karte", "karte/auswahl"}
    e.restore_tab("karte")
    assert len(e.arr.tab("karte").groups) == 2 and e.arr.removed == set()
    # Auf Standard zurücksetzen leert die Liste
    e.remove_tab("karte")
    e.reset_all()
    assert e.arr.removed == set() and [t.id for t in e.arr.tabs] == ["karte", "analyse", "vektor"]


def test_keyboard_moves(base):
    e = Editor(base, cz.standard(base))
    assert e.move_item_by(Place("karte", 0, 0), 1) == Place("karte", 0, 1)
    assert e.move_item_by(Place("karte", 0, 1), 1) is None
    assert e.move_group_by("karte", 0, 1) == Place("karte", 1)
    assert e.move_group_by("karte", 1, 1) is None


# -- Schnellzugriff, Verlauf, Ergebnis ---------------------------------------------

def test_quick_access(base):
    e = Editor(base, cz.standard(base))
    assert e.quick_ids() == ["neu", "speichern"]
    e.quick_insert(0, "puffer")
    assert e.qat == ["puffer", "neu", "speichern"]
    e.quick_insert(3, "puffer")                        # verschieben statt doppelt
    assert e.qat == ["neu", "speichern", "puffer"]
    with pytest.raises(EditError):
        e.quick_insert(0, "deckkraft")
    e.quick_remove(2)
    assert e.qat is None                               # wieder Standard


def test_undo_redo(base):
    e = Editor(base, cz.standard(base))
    e.insert_command("karte", 0, 0, "puffer")
    e.set_tab_visible("analyse", False)
    assert e.undo_label() == "Tab ausblenden"
    assert e.undo() == "Tab ausblenden" and e.arr.tab("analyse").visible
    assert e.redo() == "Tab ausblenden" and not e.arr.tab("analyse").visible
    e.undo()
    e.undo()
    assert not e.dirty and not e.can_undo and e.can_redo
    e.quick_insert(0, "zoomen")
    assert not e.can_redo                              # neue Änderung verwirft Wiederholen
    e.reset_all()
    assert e.qat is None and cz.to_dict(e.arr, base) is None
    assert e.undo() == "Standard wiederherstellen" and e.qat == ["zoomen", "neu", "speichern"]


def test_result_drops_empty_custom_groups(base):
    e = Editor(base, cz.standard(base))
    e.new_group("karte", label="Leer")
    p = e.new_group("analyse", label="Voll", item=cz.ItemEntry("zoomen"))
    arr, dropped, qat = e.result()
    assert dropped == ["Leer"] and qat is None
    assert [g.label for g in arr.tab("analyse").groups] == ["Werkzeuge", "Voll"]
    assert "Leer" in [g.label for g in e.arr.tab("karte").groups]   # Editor selbst unverändert
    assert p == Place("analyse", 1)


def test_palette_helpers(base):
    arr = cz.standard(base)
    assert ed.tab_commands(base, arr, "karte") >= {"verschieben", "zoomen", "rechteck", "polygon", "loeschen"}
    arr.tab("analyse").visible = False
    assert "puffer" not in ed.ribbon_commands(base, arr)
    item = cz.standard_items(base, "karte/auswahl")[0]
    assert ed.describe(base, item, "Gruppe Auswahl") == "Rechteck, Split-Button, groß, Gruppe Auswahl"


def test_move_item_to_new_group_is_one_step(base):
    e = Editor(base, cz.standard(base))
    p = e.move_item_to_new_group(Place("karte", 0, 0), "karte", 0, label="Neu")
    assert p == Place("karte", 0)
    assert [g.label for g in e.arr.tab("karte").groups] == ["Neu", "Navigieren", "Auswahl"]
    assert [i.command for i in e.arr.tab("karte").groups[0].items] == ["verschieben"]
    assert e.undo() and cz.to_dict(e.arr, base) is None
    e.insert_command("analyse", 0, 0, "histogramm")
    before = copy.deepcopy(e.arr)
    with pytest.raises(EditError, match="passt nicht"):
        e.move_item_to_new_group(Place("analyse", 0, 0), "vektor")
    assert e.arr == before                                            # Entfernen zurückgenommen


def test_drop_checks_match_operations(base):
    """Die Prüfungen für die Einfügemarke sagen dasselbe wie die Operationen."""
    arr = cz.standard(base)
    # Gruppen verschieben
    assert ed.can_move_group(arr, base, "karte", 0, "karte") is None
    assert ed.can_move_group(arr, base, "karte", 0, "analyse") is None
    ed.new_group(arr, base, "analyse", None, "Raster", ed.command_item(base, "histogramm"))
    assert "passt nicht" in ed.can_move_group(arr, base, "analyse", 1, "vektor")
    ed.move_group(arr, base, "karte", 0, "analyse", 0)
    assert "steht schon" in ed.can_move_group(arr, base, "karte", 0, "analyse")
    with pytest.raises(EditError):
        ed.move_group(arr, base, "karte", 0, "analyse", 0)
    # Gruppen der Definition übernehmen (ausgeblendet: wieder einblenden)
    ref = cz.group_ref("karte", "auswahl")
    assert "steht schon" in ed.can_copy_group_ref(arr, base, ref, "karte")
    ed.set_group_visible(arr, "karte", 1, False)
    assert ed.can_copy_group_ref(arr, base, ref, "karte") is None
    assert ed.copy_group_ref(arr, base, ref, "karte") == Place("karte", 1)
    assert arr.tab("karte").groups[1].visible
    assert ed.can_copy_group_ref(arr, base, ref, "vektor") is None
    ed.copy_group_ref(arr, base, ref, "vektor")
    assert "steht schon" in ed.can_copy_group_ref(arr, base, ref, "vektor")
    # Tabs: Haupt-Tabs vor Kontext-Tabs
    assert list(ed.tab_gaps(arr, "karte")) == [0, 1, 2]
    assert list(ed.tab_gaps(arr, "vektor")) == [2, 3]
    # Schnellzugriff aus einer Gruppe: nur einzelne Buttons
    assert ed.quick_command(base, cz.ItemEntry("verschieben")) == "verschieben"
    assert ed.quick_command(base, cz.ItemEntry("deckkraft", "medium")) is None
    assert ed.quick_command(base, cz.ItemEntry(size=None, element="row:zoomen")) is None
