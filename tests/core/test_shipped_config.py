"""Prüft die mitgelieferte Ribbon-Definition (qgis_ribbon/config/ribbon_arcgis.yaml)."""
import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core import config_loader  # noqa: E402
from qgis_ribbon.core.inventory import (INVALID, MISSING, InventoryIndex,  # noqa: E402
                                        check_source, merge_inventories)
from qgis_ribbon.core.model import iter_commands  # noqa: E402

pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def ribbon():
    return config_loader.load()


@pytest.fixture(scope="module")
def raw_text():
    with io.open(config_loader.DEFAULT_CONFIG, encoding="utf-8") as fh:
        return fh.read()


def test_shipped_definition_is_valid(ribbon):
    assert [t.id for t in ribbon.tabs if not t.contextual][:2] == ["karte", "einfuegen"]
    assert all(t.groups for t in ribbon.tabs if not t.dynamic)
    assert [t.id for t in ribbon.tabs if t.dynamic] == ["erweiterungen"]


def test_contextual_tabs_come_last(ribbon):
    flags = [t.contextual for t in ribbon.tabs]
    assert flags == sorted(flags)
    assert any(flags)


def test_no_esri_ids_or_esri_texts(raw_text):
    assert "esri" not in raw_text.lower()


def test_unplaced_commands_are_editor_offers(ribbon):
    # Befehle ohne Ort stehen nur im Editor zur Auswahl: einfache Buttons mit Beschreibung;
    # Ausnahmen: die Galerie „Abfragbare Layer“, standardmäßig aus dem Erkunden-Dropdown genommen,
    # und die übrigen Einrast-Einstellungen (Platz im Tab Bearbeiten ist knapp)
    used = {c.id for t in ribbon.tabs for c in iter_commands(t)} | {c.id for c in ribbon.quick_access}
    unplaced = [ribbon.commands[c] for c in set(ribbon.commands) - used]
    assert unplaced and len(used) > 150
    snapping = {"einrasten_einheit", "einrasten_massstab_modus", "einrasten_massstab_min", "einrasten_massstab_max",
                "spurverfolgung_versatz"}
    assert all((c.kind == "button" or c.id == "abfragbare_layer" or c.id in snapping) and c.description
               for c in unplaced), [c.id for c in unplaced]


def test_snapping_settings_one_by_one(ribbon):
    """Gruppe Einrasten: Split mit Einrastoptionen, Modus, Dropdown Einrasttyp, Toleranz, Zeile mit den Schaltern."""
    from qgis_ribbon.core.model import CommandRef, Menu, Row, Split
    tab = next(t for t in ribbon.tabs if t.id == "bearbeiten")
    group = next(g for g in tab.groups if g.id == "einrasten")
    kinds = [type(el) for el in group.elements]
    assert kinds == [Split, CommandRef, Menu, CommandRef, Row]
    split, mode, menu, tolerance, row = group.elements
    assert split.command.id == "einrasten" and [c.id for c in split.items] == ["einrastoptionen"]
    assert (mode.command.id, mode.size) == ("einrasten_modus", "medium")
    assert (tolerance.command.id, tolerance.size) == ("einrasten_toleranz", "medium")
    assert menu.key == "Einrasttyp" and menu.size == "medium"
    types = ["stuetzpunkt", "segment", "flaeche", "schwerpunkt", "mittelpunkt", "endpunkt"]
    assert [c.id for c in menu.items] == ["einrasten_" + t for t in types]
    for cmd in menu.items:
        assert cmd.source.type == "custom" and cmd.source.get("id") == "ribbon.einrasttyp" and cmd.kind == "button"
    assert [c.id for c in row.commands] == ["spurverfolgung", "selbsteinrasten", "schnittpunkte_einrasten"]
    for cid in ("einrasten_einheit", "einrasten_massstab_modus", "einrasten_massstab_min",
                "einrasten_massstab_max", "spurverfolgung_versatz"):
        assert ribbon.commands[cid].kind == "control", cid
    for cid in ("einrasten_ueberschneidungen", "einrasten_erweitert"):
        assert ribbon.commands[cid].kind == "button", cid


# Wörter, in denen ae/oe/ue/ss richtig geschrieben sind (keine Ersatzschreibweise)
ALLOWED_ASCII = {"aussehen", "webadresse", "ausschneiden", "messen", "messwerkzeuge", "neue", "neues", "neuer", "aktueller",
                 "processing", "quelle", "anpassen", "ausschnitt", "klasse",
                 "beschriftungsklasse", "beschriftungsklassen", "bildverbesserung", "virtueller", "aktuelles",
                 "kartenausschnitt", "neuen", "virtuellen", "zeitsteuerung", "zusammenfassung",
                 "ausschalten", "datenquellen", "hilfsspeicher", "oberflächenanpassung", "quer", "lässt",
                 "grundausstattung", "maßstabsstile"}
ALLOWED_ASCII |= {"passpunkt", "passpunkte", "passpunkttabelle"}


def test_labels_use_real_umlauts():
    # Die YAML ist englisch; die deutschen Texte stehen im Katalog
    import json
    labels = []
    for name in ("de_ribbon.json", "de_ribbon_layout.json"):
        path = os.path.join(os.path.dirname(config_loader.DEFAULT_CONFIG), "..", "i18n", name)
        with io.open(path, encoding="utf-8") as fh:
            labels += [v for v in json.load(fh).values() if len(v) < 40]
    assert labels
    words = {w.lower() for text in labels for w in re.findall(r"\w+", text)}
    suspicious = {w for w in words if re.search(r"ae|oe|ue|ss", w)} - ALLOWED_ASCII
    assert not suspicious, "Ersatzschreibweise statt Umlaut? %s" % sorted(suspicious)


def _inventory(name):
    import json
    path = os.path.join(os.path.dirname(config_loader.DEFAULT_CONFIG), "..", "..", "docs", name)
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_all_sources_exist_in_inventory(ribbon):
    """Jede Quelle gegen das Inventar (Live vor statisch."""
    static = _inventory("qgis_inventory_static.json")
    live = _inventory("qgis_inventory_live.json")  # nur lokal vorhanden
    if static is None and live is None:
        pytest.skip("QGIS-Inventar liegt nur im Entwicklungsrepository")
    merged = merge_inventories(live, static) if live else static
    index = InventoryIndex(merged)
    problems = []
    for cmd in ribbon.commands.values():
        if cmd.qgis_min:
            continue  # Inventare stammen aus 3.44; geprüft im echten QGIS 4 vom Klicklauf
        src = dict(cmd.source.params, type=cmd.source.type)
        result, msg = check_source(src, index)
        if result in (MISSING, INVALID):
            problems.append("%s: %s" % (cmd.id, msg))
    assert not problems, problems


def test_hidden_toolbars_keep_plugin_toolbars(ribbon):
    for name in ("mPluginToolBar", "mRasterToolBar", "mVectorToolBar", "mDatabaseToolBar",
                 "mWebToolBar"):
        assert name not in ribbon.hide_toolbars
    assert "mMapNavToolBar" in ribbon.hide_toolbars


def test_context_conditions(ribbon):
    """Kontext-Tabs mit Bedingungen, Bearbeiten-Tab beim Start der Bearbeitung."""
    assert ribbon.tab("bearbeiten").activate_on == ("editing_started",)
    assert not ribbon.tab("bearbeiten").contextual
    assert all(t.visible_when for t in ribbon.tabs if t.contextual)
    assert ribbon.commands["felder"].enabled_when == ("active_layer_has_fields",)
    assert ribbon.commands["beschriftung_schalten"].enabled_when == ("active_layer_is_vector",)


def test_accessibility_and_construction_without_duplicates(ribbon):
    """Farbsehschwäche ohne doppelten Eintrag, Konstruktion als ein Split."""
    from qgis_ribbon.core.model import CommandRef, Split

    def group(tab_id, group_id):
        tab = next(t for t in ribbon.tabs if t.id == tab_id)
        return next(g for g in tab.groups if g.id == group_id)

    (el,) = group("ansicht", "barrierefreiheit").elements
    assert isinstance(el, CommandRef) and el.command.id == "farbsehschwaeche_simulieren"
    assert "vorschau_deuteranopie" in ribbon.commands   # bleibt im Befehlsvorrat
    (el,) = group("bearbeiten", "konstruktion").elements
    assert isinstance(el, Split) and el.command.id == "erweiterte_digitalisierung"
    assert [c.id for c in el.items] == ["konstruktionspanel"]


@pytest.mark.parametrize("kind,tab", [("group", "gruppe_darstellung"), ("point_cloud", "punktwolke_darstellung"),
                                      ("vector_tile", "vektorkacheln_darstellung"),
                                      ("raster", "raster_darstellung")])
def test_switch_to_vector_shows_all_vector_tabs(ribbon, kind, tab):
    """Von einem anderen „Darstellung“-Tab auf einen Vektorlayer: alle drei Vektor-Tabs, Darstellung gewählt."""
    from qgis_ribbon.core.conditions import Snapshot
    from qgis_ribbon.core.context import ContextLogic
    logic = ContextLogic(ribbon, Snapshot(layer_kind=kind))
    logic.tab_selected(tab)
    ch = logic.update(Snapshot(layer_kind="vector"))
    assert ch.select == "vektor_darstellung"
    shown = {tid for tid, on in ch.tabs.items() if on}
    assert shown == {"vektor_darstellung", "vektor_beschriftung", "vektor_daten"}
    assert ch.tabs[tab] is False
