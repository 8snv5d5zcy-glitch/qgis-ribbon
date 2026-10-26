import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core import config_loader  # noqa: E402
from qgis_ribbon.core.model import CommandRef, Menu, Row, Split, SubMenu  # noqa: E402

VALID = {
    "version": 1,
    "hide_toolbars": ["mFileToolBar"],
    "quick_access": ["speichern"],
    "commands": {
        "speichern": {"label": "Speichern",
                      "source": {"type": "qgis_action", "object_name": "mActionSaveProject"}},
        "verschieben": {"label": "Verschieben",
                        "source": {"type": "qgis_action", "object_name": "mActionPan"}},
        "zoomen": {"label": "Zoomen", "source": {"type": "iface_method", "method": "mapCanvas.zoomIn"},
                   "icon": "/mActionZoomIn.svg"},
        "felder": {"label": "Felder", "source": {
            "type": "iface_method", "method": "showLayerProperties",
            "args": ["@aktiver_layer", "mOptsPage_SourceFields"]}},
        "puffer": {"label": "Puffer", "source": {"type": "processing", "algorithm": "native:buffer"}},
        "layer_menue": {"label": "Layer hinzufügen",
                        "source": {"type": "qgis_menu", "object_name": "mAddLayerMenu"}},
        "galerie": {"label": "Galerie", "kind": "control",
                    "source": {"type": "custom", "id": "ribbon.galerie"}},
    },
    "tabs": [{
        "id": "karte", "label": "Karte",
        "groups": [{
            "id": "navigieren", "label": "Navigieren",
            "items": [
                {"split": "verschieben", "items": ["zoomen", {"menu": "Mehr", "items": ["felder"]}],
                 "size": "large", "label": "Erkunden"},
                {"command": "puffer", "size": "medium"},
                {"menu": "Lesezeichen", "gallery": "galerie", "items": ["layer_menue"]},
                {"row": ["zoomen", "speichern"]},
            ],
        }],
    }],
    "contextual_tabs": [{
        "id": "daten", "label": "Daten", "context": "Vektorlayer",
        "visible_when": ["active_layer_is_vector"],
        "groups": [{"id": "felder", "label": "Felder", "items": [{"command": "felder"}]}],
    }],
}


def broken(mutate):
    data = copy.deepcopy(VALID)
    mutate(data)
    with pytest.raises(config_loader.ConfigError) as exc:
        config_loader.parse(data)
    return exc.value.errors


def test_parse_valid_definition():
    r = config_loader.parse(copy.deepcopy(VALID))
    assert [t.id for t in r.tabs] == ["karte", "daten"]
    assert r.tab("daten").contextual and r.tab("daten").visible_when == ("active_layer_is_vector",)
    assert [c.id for c in r.quick_access] == ["speichern"]
    assert r.hide_toolbars == ("mFileToolBar",)
    split, ref, menu, row = r.tab("karte").groups[0].elements
    assert isinstance(split, Split) and split.display_label == "Erkunden"
    assert isinstance(split.items[1], SubMenu) and split.items[1].items[0].id == "felder"
    assert isinstance(ref, CommandRef) and ref.size == "medium"
    assert isinstance(menu, Menu) and menu.size == "large" and menu.gallery.id == "galerie"
    assert isinstance(row, Row) and [c.id for c in row.commands] == ["zoomen", "speichern"]
    assert r.commands["felder"].source.get("args") == ["@aktiver_layer", "mOptsPage_SourceFields"]
    # Derselbe Befehl ist überall dasselbe Objekt
    assert row.commands[0] is split.items[0]


def test_reports_all_errors_at_once():
    def mutate(d):
        d["commands"]["speichern"]["source"] = {"type": "qgis_action"}
        d["commands"]["puffer"]["source"]["type"] = "esri"
        d["tabs"][0]["groups"][0]["items"].append({"command": "gibt_es_nicht"})
    errors = broken(mutate)
    assert any("object_name" in e for e in errors)
    assert any("Quelltyp 'esri' unbekannt" in e for e in errors)
    assert any("'gibt_es_nicht' nicht definiert" in e for e in errors)
    # Fehlerhafte Befehle werden nicht zusätzlich als "nicht definiert" gemeldet
    assert not any("'speichern' nicht definiert" in e for e in errors)


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.update(version=2), "version"),
    (lambda d: d.update(extra=1), "unbekannter Schlüssel 'extra'"),
    (lambda d: d["commands"]["zoomen"].update(lable="x"), "unbekannter Schlüssel 'lable'"),
    (lambda d: d["commands"]["zoomen"]["source"].update(foo=1), "unbekannter Schlüssel 'foo'"),
    (lambda d: d["commands"]["zoomen"]["source"].update(args="x"), "args muss eine Liste sein"),
    (lambda d: d["commands"]["zoomen"].update(kind="regler"), "kind 'regler' unbekannt"),
    (lambda d: d["commands"]["zoomen"]["source"].update(modus="zeigen"), "unbekannter Schlüssel 'modus'"),
    (lambda d: d["commands"].update(dock={"label": "D", "source": {
        "type": "dock", "object_name": "Layers", "modus": "an"}}), "modus 'an' unbekannt"),
    (lambda d: d["commands"].update({"Gross": d["commands"]["zoomen"]}), "ungültige ID"),
    (lambda d: d["tabs"][0]["groups"][0]["items"][1].update(size="riesig"), "size 'riesig'"),
    (lambda d: d["tabs"][0]["groups"][0]["items"][1].update(split="zoomen"), "genau einer"),
    (lambda d: d["tabs"][0]["groups"][0].update(items=[]), "items darf nicht leer"),
    (lambda d: d["tabs"][0]["groups"].append(copy.deepcopy(d["tabs"][0]["groups"][0])), "Gruppen-ID 'navigieren' doppelt"),
    (lambda d: d["contextual_tabs"][0].update(id="karte"), "Tab-ID 'karte' doppelt"),
    (lambda d: d["contextual_tabs"][0].pop("context"), "context fehlt"),
    (lambda d: d["contextual_tabs"][0].update(visible_when=[]), "visible_when darf nicht leer"),
    (lambda d: d["tabs"][0].update(context="X"), "unbekannter Schlüssel 'context'"),
    (lambda d: d["tabs"][0]["groups"][0]["items"][2].update(gallery="zoomen"), "muss ein Steuerelement sein"),
    (lambda d: d["tabs"][0]["groups"][0]["items"].append({"row": []}), "row darf nicht leer"),
    (lambda d: d["quick_access"].append("fehlt"), "'fehlt' nicht definiert"),
    (lambda d: d.update(tabs=[]), "tabs"),
    (lambda d: d["contextual_tabs"][0].update(visible_when=["aktiver_layer"]), "Bedingung 'aktiver_layer' unbekannt"),
    (lambda d: d["commands"]["felder"].update(enabled_when=["vektor"]), "Bedingung 'vektor' unbekannt"),
    (lambda d: d["commands"]["felder"].update(enabled_when="active_layer"), "enabled_when muss eine Liste sein"),
    (lambda d: d["tabs"][0].update(activate_on=["start"]), "Ereignis 'start' unbekannt"),
])
def test_rejects_invalid(mutate, expected):
    errors = broken(mutate)
    assert any(expected in e for e in errors), errors


def test_menu_depth_is_limited():
    def mutate(d):
        sub = {"menu": "Ebene", "items": ["zoomen"]}
        for _ in range(4):
            sub = {"menu": "Ebene", "items": [sub]}
        d["tabs"][0]["groups"][0]["items"][0]["items"] = [sub]
    assert any("Ebenen tief" in e for e in broken(mutate))


def test_load_reads_yaml(tmp_path):
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "ribbon.yaml"
    path.write_text(yaml.safe_dump(VALID, allow_unicode=True), encoding="utf-8")
    assert config_loader.load(str(path)).tab("karte").label == "Karte"


def test_load_reports_yaml_syntax_error(tmp_path):
    pytest.importorskip("yaml")
    path = tmp_path / "kaputt.yaml"
    path.write_text("tabs: [\n", encoding="utf-8")
    with pytest.raises(config_loader.ConfigError) as exc:
        config_loader.load(str(path))
    assert "YAML nicht lesbar" in exc.value.errors[0]


def test_conditions_and_events():
    data = copy.deepcopy(VALID)
    data["commands"]["felder"]["enabled_when"] = ["active_layer_has_fields"]
    data["tabs"][0]["activate_on"] = ["editing_started"]
    r = config_loader.parse(data)
    assert r.commands["felder"].enabled_when == ("active_layer_has_fields",)
    assert r.commands["zoomen"].enabled_when == ()
    assert r.tab("karte").activate_on == ("editing_started",)


def _ap5(data):
    """Galerie mit festen Einträgen, Launcher, Beschreibung, Parameter eigener Befehle."""
    data["commands"]["galerie"]["gallery"] = {"display": "ribbon", "items": ["puffer", "zoomen"],
                                              "columns": 3}
    data["commands"]["optionen"] = {
        "label": "Optionen", "description": "Öffnet die Optionen.",
        "source": {"type": "iface_method", "method": "showOptionsDialog",
                   "args": [None, "mOptionsPageMapTools"]}}
    data["commands"]["modus"] = {"label": "Modus", "source": {
        "type": "custom", "id": "ribbon.abfragemodus", "args": ["TopDownAll"]}}
    data["tabs"][0]["groups"][0]["launcher"] = "optionen"
    data["tabs"][0]["groups"][0]["items"].append({"command": "modus"})
    return data


def test_gallery_launcher_description_and_custom_args():
    r = config_loader.parse(_ap5(copy.deepcopy(VALID)))
    group = r.tab("karte").groups[0]
    assert group.launcher.id == "optionen"
    assert r.commands["optionen"].description == "Öffnet die Optionen."
    assert r.commands["modus"].source.get("args") == ["TopDownAll"]
    gallery = r.commands["galerie"].gallery
    assert gallery.display == "ribbon" and gallery.columns == 3
    assert [c.id for c in gallery.items] == ["puffer", "zoomen"]
    # Das Menü verweist auf das Steuerelement samt Galerie
    assert group.elements[2].gallery is r.commands["galerie"]
    assert gallery.items[1] is r.commands["zoomen"]


def test_gallery_without_items_defaults_to_dropdown():
    data = copy.deepcopy(VALID)
    data["commands"]["galerie"]["gallery"] = {}
    gallery = config_loader.parse(data).commands["galerie"].gallery
    assert gallery.display == "dropdown" and gallery.items == ()


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d["commands"]["galerie"]["gallery"].update(display="band"), "display 'band' unbekannt"),
    (lambda d: d["commands"]["galerie"]["gallery"].update(columns=0), "columns"),
    (lambda d: d["commands"]["galerie"]["gallery"].update(items=["galerie"]), "darf kein Steuerelement"),
    (lambda d: d["commands"]["galerie"]["gallery"].update(items=["nix"]), "'nix' nicht definiert"),
    (lambda d: d["commands"]["galerie"]["gallery"].update(items=[]), "display ribbon braucht"),
    (lambda d: d["commands"]["galerie"]["gallery"].update(farbe="rot"), "unbekannter Schlüssel 'farbe'"),
    (lambda d: d["commands"]["puffer"].update(gallery={}), "gallery nur an Steuerelementen"),
    (lambda d: d["tabs"][0]["groups"][0].update(launcher="galerie"), "muss ein Button sein"),
    (lambda d: d["tabs"][0]["groups"][0].update(launcher="nix"), "'nix' nicht definiert"),
    (lambda d: d["commands"]["modus"]["source"].update(args="x"), "args muss eine Liste sein"),
    (lambda d: d["commands"]["optionen"].update(description=""), "description muss"),
])
def test_rejects_invalid_ap5(mutate, expected):
    errors = broken(lambda d: (_ap5(d), mutate(d)))
    assert any(expected in e for e in errors), errors
