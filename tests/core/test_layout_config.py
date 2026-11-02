"""Definition des Layout-Fensters (ribbon_layout.yaml) und die neuen Quelltypen."""
import io
import json
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)

from qgis_ribbon.core import config_loader, icons  # noqa: E402
from qgis_ribbon.core.inventory import (INVALID, MISSING, OK, InventoryIndex, check_source)  # noqa: E402
from qgis_ribbon.core.model import Menu, iter_commands  # noqa: E402

pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def ribbon():
    return config_loader.load(config_loader.LAYOUT_CONFIG)


def _definition(source):
    return {"version": 1, "commands": {"x": {"label": "X", "source": source}},
            "tabs": [{"id": "t", "label": "T", "groups": [{"id": "g", "label": "G", "items": [{"command": "x"}]}]}]}


def test_main_tabs(ribbon):
    main = [t for t in ribbon.tabs if not t.contextual]
    assert [t.id for t in main] == ["layout", "einfuegen", "atlas", "bericht", "ansicht", "teilen", "erweiterungen"]
    assert all(t.groups or t.dynamic for t in ribbon.tabs)


def test_report_shows_its_tab_instead_of_atlas_and_share(ribbon):
    from qgis_ribbon.core.conditions import Snapshot
    from qgis_ribbon.core.context import ContextLogic
    logic = ContextLogic(ribbon)
    assert not logic.tab_visible("bericht") and logic.tab_visible("atlas") and logic.tab_visible("teilen")
    assert logic.command_enabled("panel_atlas")
    changes = logic.update(Snapshot(layout_report=True))
    assert changes.tabs == {"bericht": True, "atlas": False, "teilen": False}
    assert logic.tab_visible("layout") and logic.tab_visible("ansicht")
    assert not logic.command_enabled("panel_atlas")


def test_report_tab_offers_settings_and_output(ribbon):
    ids = {c.id for c in iter_commands(ribbon.tab("bericht"))}
    assert ids == {"bericht_einstellungen", "panel_bericht", "bericht_export_pdf", "bericht_export_bild",
                   "bericht_export_svg", "bericht_drucken"}


def test_page_sizes_and_template_are_offered(ribbon):
    assert ribbon.commands["seitengroesse"].source.get("id") == "ribbon.seite_groesse"
    assert "seitengroesse" in {c.id for c in iter_commands(ribbon.tab("layout"))}
    insert = {c.id for c in iter_commands(ribbon.tab("einfuegen"))}
    assert {"layout_neu", "neues_layout_a4_quer", "neues_layout_a3_hoch", "neu_aus_vorlage_layout"} <= insert
    main = config_loader.load()
    assert "neu_aus_vorlage_layout" in {c.id for c in iter_commands(main.tab("teilen"))}


def test_format_tab_shows_with_a_selection(ribbon):
    from qgis_ribbon.core.context import ContextLogic
    from qgis_ribbon.core.conditions import Snapshot
    tab = ribbon.tab("layout_format")
    assert tab.contextual and tab.visible_when == ("layout_items_selected",)
    logic = ContextLogic(ribbon)
    assert not logic.tab_visible("layout_format")
    changes = logic.update(Snapshot(selected_items=2))
    assert changes.tabs == {"layout_format": True} and changes.select is None
    assert logic.command_enabled("item_x")
    changes = logic.update(Snapshot(selected_items=0))
    assert changes.tabs == {"layout_format": False}
    assert not logic.command_enabled("item_x")


def test_format_controls_are_gated_by_the_selection(ribbon):
    controls = [c for t in ribbon.tabs if t.id == "layout_format" for c in iter_commands(t) if c.kind == "control"]
    assert len(controls) == 13
    assert all(c.enabled_when == ("layout_items_selected",) for c in controls)


KIND_TABS = {"map": "layout_karte", "label": "layout_text", "legend": "layout_legende", "scalebar": "layout_massstab",
             "picture": "layout_bild", "shape": "layout_form", "table": "layout_tabelle"}


def test_every_item_kind_has_its_tab_besides_format(ribbon):
    from qgis_ribbon.core.conditions import ITEM_KINDS, Snapshot
    from qgis_ribbon.core.context import ContextLogic
    assert set(KIND_TABS) | {"other"} == set(ITEM_KINDS)
    logic = ContextLogic(ribbon)
    for kind, tab in KIND_TABS.items():
        logic.update(Snapshot(selected_items=1, item_kind=kind))
        visible = {t.id for t in ribbon.tabs if t.contextual and logic.tab_visible(t.id)}
        assert visible == {"layout_format", tab}
    logic.update(Snapshot(selected_items=1, item_kind="other"))
    assert {t.id for t in ribbon.tabs if t.contextual and logic.tab_visible(t.id)} == {"layout_format"}


def test_several_items_show_only_format(ribbon):
    from qgis_ribbon.core.conditions import Snapshot
    from qgis_ribbon.core.context import ContextLogic
    logic = ContextLogic(ribbon)
    logic.update(Snapshot(selected_items=1, item_kind="map"))
    changes = logic.update(Snapshot(selected_items=3))
    assert changes.tabs == {"layout_karte": False} and changes.select is None
    assert not logic.command_enabled("item_karte_massstab")
    assert logic.command_enabled("item_x")


def test_commands_of_kind_tabs_are_gated_by_their_kind(ribbon):
    shared = {"item_optionen", "inhalt_verschieben", "knoten_bearbeiten"}       # liegen auch auf anderen Tabs
    for tab_id in KIND_TABS.values():
        tab = ribbon.tab(tab_id)
        assert tab.contextual and len(tab.visible_when) == 1
        for command in iter_commands(tab):
            if command.id not in shared:
                assert command.enabled_when == tab.visible_when, command.id


def test_atlas_feature_control_sits_between_previous_and_next(ribbon):
    group = next(g for g in ribbon.tab("atlas").groups if g.id == "blaettern")
    ids = [c.id for c in iter_commands(group)]
    assert ids == ["atlas_erstes", "atlas_zurueck", "atlas_objekt", "atlas_weiter", "atlas_letztes"]


def test_invalid_item_kind_is_refused():
    from qgis_ribbon.core.conditions import Snapshot
    with pytest.raises(ValueError):
        Snapshot(item_kind="kreis")


def test_replaces_the_toolbars_of_qgis(ribbon):
    assert set(ribbon.hide_toolbars) == {"mLayoutToolbar", "mToolsToolbar", "mNavigationToolbar", "mActionsToolbar",
                                         "mAtlasToolbar", "mReportToolbar"}


def test_quick_access(ribbon):
    assert [c.id for c in ribbon.quick_access] == ["projekt_speichern", "rueckgaengig", "wiederholen"]


def test_every_command_is_placed_and_described(ribbon):
    used = {c.id for t in ribbon.tabs if not t.dynamic for c in iter_commands(t)}
    used |= {c.id for c in ribbon.quick_access}
    assert used == set(ribbon.commands)
    assert all(c.description for c in ribbon.commands.values())


def test_no_esri_texts():
    with io.open(config_loader.LAYOUT_CONFIG, encoding="utf-8") as fh:
        assert "esri" not in fh.read().lower()


def test_every_text_is_translated():
    import yaml
    with io.open(config_loader.LAYOUT_CONFIG, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    with io.open(os.path.join(ROOT, "qgis_ribbon", "i18n", "de_ribbon_layout.json"), encoding="utf-8") as fh:
        catalog = json.load(fh)
    texts = set()

    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("label", "description", "menu") and isinstance(v, str):
                    texts.add(v)
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(data)
    assert texts
    assert sorted(t for t in texts if t not in catalog) == []


def test_every_command_and_menu_has_a_motif(ribbon):
    main = config_loader.load()
    shipped = icons.load(command_ids=set(ribbon.commands) | set(main.commands))
    assert set(ribbon.commands) - set(shipped.commands) == set()
    menus = [e.key for t in ribbon.tabs for g in t.groups for e in g.elements if isinstance(e, Menu)]
    assert menus and set(menus) - set(shipped.menus) == set()


def test_all_sources_exist_in_the_real_designer(ribbon):
    path = os.path.join(ROOT, "docs", "qgis_layout_inventory.json")
    if not os.path.isfile(path):
        pytest.skip("Inventar liegt nur im Entwicklungsrepository")
    with io.open(path, encoding="utf-8") as fh:
        index = InventoryIndex(json.load(fh))
    problems = []
    for cmd in ribbon.commands.values():
        result, msg = check_source(dict(cmd.source.params, type=cmd.source.type), index)
        if result in (MISSING, INVALID):
            problems.append("%s: %s" % (cmd.id, msg))
    assert problems == []
    assert "mLayoutToolbar" in {t["object_name"] for t in json.load(io.open(path, encoding="utf-8"))["toolbars"]}


def test_new_source_types_are_accepted():
    for source in ({"type": "designer_action", "object_name": "mActionPan"},
                   {"type": "designer_edit", "role": "undo"},
                   {"type": "designer_item", "item": "LayoutMap"},
                   {"type": "designer_item", "item": "LayoutShape", "group": "shapes", "index": 2},
                   {"type": "designer_item", "item": "LayoutLabel", "submenu": True}):
        assert config_loader.parse(_definition(source)).commands["x"].source.type == source["type"]


@pytest.mark.parametrize("source, word", [
    ({"type": "designer_action"}, "object_name"),
    ({"type": "designer_edit", "role": "drucken"}, "drucken"),
    ({"type": "designer_item"}, "item"),
    ({"type": "designer_item", "item": "LayoutMap", "index": -1}, "index"),
    ({"type": "designer_item", "item": "LayoutMap", "index": True}, "index"),
    ({"type": "designer_item", "item": "LayoutMap", "anders": 1}, "anders"),
])
def test_invalid_sources_are_reported(source, word):
    with pytest.raises(config_loader.ConfigError) as exc:
        config_loader.parse(_definition(source))
    assert word in str(exc.value)


def test_check_source_of_designer_types():
    index = InventoryIndex({"actions": [{"object_name": "mActionPan"}],
                            "items": [{"item": "LayoutShape", "group": "shapes", "index": 1}]})
    assert check_source({"type": "designer_action", "object_name": "mActionPan"}, index)[0] == OK
    assert check_source({"type": "designer_action", "object_name": "mActionNein"}, index)[0] == MISSING
    assert check_source({"type": "designer_item", "item": "LayoutShape", "group": "shapes", "index": 1}, index)[0] == OK
    assert check_source({"type": "designer_item", "item": "LayoutShape", "group": "shapes"}, index)[0] == MISSING
    assert check_source({"type": "designer_edit", "role": "copy"}, index)[0] == OK
    assert check_source({"type": "designer_edit", "role": "nein"}, index)[0] == INVALID
