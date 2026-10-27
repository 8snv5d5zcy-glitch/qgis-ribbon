import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core import conditions, config_loader  # noqa: E402
from qgis_ribbon.core.conditions import Snapshot  # noqa: E402
from qgis_ribbon.core.context import ContextLogic  # noqa: E402


def qa(name):
    return {"type": "qgis_action", "object_name": name}


def tab(tid, label, cmd, **extra):
    t = {"id": tid, "label": label, "groups": [{"id": "g", "label": "G", "items": [{"command": cmd}]}]}
    t.update(extra)
    return t


def ctx_tab(tid, label, context, cond):
    return tab(tid, label, "neu", context=context, visible_when=[cond])


DEFINITION = {
    "version": 1,
    "commands": {
        "neu": {"label": "Neu", "source": qa("mActionNewProject")},
        "felder": {"label": "Felder", "source": qa("mActionFelder"),
                   "enabled_when": ["active_layer_has_fields"]},
        "deckkraft": {"label": "Deckkraft", "source": qa("mActionDeckkraft"),
                      "enabled_when": ["active_layer"]},
        "beides": {"label": "Beides", "source": qa("mActionBeides"),
                   "enabled_when": ["active_layer_is_vector", "active_layer_has_selection"]},
    },
    "tabs": [
        tab("karte", "Karte", "neu"),
        tab("analyse", "Analyse", "deckkraft"),
        tab("bearbeiten", "Bearbeiten", "beides", activate_on=["editing_started"]),
    ],
    "contextual_tabs": [
        ctx_tab("vektor_darstellung", "Darstellung", "Vektorlayer", "active_layer_is_vector"),
        ctx_tab("vektor_daten", "Daten", "Vektorlayer", "active_layer_is_vector"),
        ctx_tab("tabelle_daten", "Daten", "Tabelle", "active_layer_is_table"),
        ctx_tab("raster_darstellung", "Darstellung", "Rasterlayer", "active_layer_is_raster"),
    ],
}


@pytest.fixture
def logic():
    import copy
    return ContextLogic(config_loader.parse(copy.deepcopy(DEFINITION)))


VECTOR = Snapshot(layer_kind="vector")
TABLE = Snapshot(layer_kind="table")
RASTER = Snapshot(layer_kind="raster")


def test_every_condition_declares_known_fields():
    for name, (deps, pred, text) in conditions.CONDITIONS.items():
        assert deps and set(deps) <= set(conditions.SNAPSHOT_FIELDS), name
        assert text
        pred(Snapshot())  # wertet ohne Fehler aus


@pytest.mark.parametrize("snap, true", [
    (Snapshot(), set()),
    (VECTOR, {"active_layer", "active_layer_or_group", "active_layer_is_vector", "active_layer_has_fields"}),
    (TABLE, {"active_layer", "active_layer_or_group", "active_layer_is_table", "active_layer_has_fields"}),
    (RASTER, {"active_layer", "active_layer_or_group", "active_layer_is_raster"}),
    (Snapshot(layer_kind="other"), {"active_layer", "active_layer_or_group"}),
    (Snapshot(layer_kind="mesh"), {"active_layer", "active_layer_or_group", "active_layer_is_mesh"}),
    (Snapshot(layer_kind="group"), {"active_layer_or_group", "active_node_is_group"}),
    (Snapshot("vector", editable=True, has_selection=True),
     {"active_layer", "active_layer_or_group", "active_layer_is_vector", "active_layer_has_fields",
      "active_layer_is_editable", "active_layer_has_selection"}),
])
def test_condition_values(snap, true):
    assert {n for n in conditions.CONDITIONS if conditions.evaluate(n, snap)} == true


def test_snapshot_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Snapshot(layer_kind="annotation")


def test_initial_state_without_layer(logic):
    assert not logic.tab_visible("vektor_daten") and not logic.tab_visible("raster_darstellung")
    assert logic.tab_visible("karte")
    assert not logic.command_enabled("felder")
    assert logic.command_enabled("neu")  # ohne Bedingung
    assert logic.current_tab == "karte"


def test_index_condition_to_targets(logic):
    assert logic.affected("active_layer_is_vector") == (
        {"beides"}, {"vektor_darstellung", "vektor_daten"})
    assert logic.affected("active_layer_has_fields") == ({"felder"}, set())
    assert "active_layer_is_editable" not in logic.conditions  # nicht verwendet


def test_layer_change_reports_only_differences(logic):
    ch = logic.update(VECTOR)
    assert ch.tabs == {"vektor_darstellung": True, "vektor_daten": True}
    assert ch.commands == {"felder": True, "deckkraft": True}
    assert ch.select is None
    # Zweiter Vektorlayer: nichts ändert sich
    assert not logic.update(Snapshot(layer_kind="vector"))
    ch = logic.update(TABLE)
    assert ch.tabs == {"vektor_darstellung": False, "vektor_daten": False, "tabelle_daten": True}
    assert ch.commands == {}  # felder bleibt aktiv, deckkraft auch


def test_only_dependent_conditions_are_evaluated(logic, monkeypatch):
    logic.update(VECTOR)
    calls = []
    real = conditions.evaluate
    monkeypatch.setattr(conditions, "evaluate", lambda n, s: calls.append(n) or real(n, s))
    logic.update(Snapshot("vector", has_selection=True))
    assert calls == ["active_layer_has_selection"]


def test_all_conditions_must_hold(logic):
    logic.update(VECTOR)
    assert not logic.command_enabled("beides")
    assert logic.update(Snapshot("vector", has_selection=True)).commands == {"beides": True}
    assert logic.update(Snapshot("table", has_selection=True)).commands == {"beides": False}


def test_hidden_context_tab_falls_back_to_last_main_tab(logic):
    logic.tab_selected("analyse")
    logic.update(RASTER)
    logic.tab_selected("raster_darstellung")
    ch = logic.update(Snapshot())
    assert ch.select == "analyse"
    assert logic.current_tab == "analyse"


def test_hidden_context_tab_prefers_same_label(logic):
    logic.update(VECTOR)
    logic.tab_selected("vektor_daten")
    assert logic.update(TABLE).select == "tabelle_daten"
    logic.update(RASTER)  # Daten gibt es für Raster nicht
    assert logic.current_tab == "karte"


def test_same_type_keeps_context_tab(logic):
    logic.update(VECTOR)
    logic.tab_selected("vektor_darstellung")
    assert logic.update(Snapshot("vector", has_selection=True)).select is None
    assert logic.update(RASTER).select == "raster_darstellung"


def test_event_activates_tab(logic):
    logic.update(VECTOR)
    logic.tab_selected("vektor_daten")
    ch = logic.update(Snapshot("vector", editable=True), events=("editing_started",))
    assert ch.select == "bearbeiten"
    # Schon gewählt: keine erneute Auswahl
    assert logic.update(Snapshot("vector", editable=True), events=("editing_started",)).select is None


def test_event_does_not_leave_tabs_to_stay_on():
    import copy
    ribbon = config_loader.parse(copy.deepcopy(DEFINITION))
    logic = ContextLogic(ribbon, stay_on={"analyse"})
    logic.tab_selected("analyse")
    ch = logic.update(Snapshot("vector", editable=True), events=("editing_started",))
    assert ch.select is None and logic.current_tab == "analyse"
    # Aus anderen Tabs wird weiter gewechselt
    logic.tab_selected("karte")
    logic.update(Snapshot("vector"))
    assert logic.update(Snapshot("vector", editable=True), events=("editing_started",)).select == "bearbeiten"


def test_own_tabs_are_kept_on_event():
    import copy
    from qgis_ribbon.core import customization as cz
    base = config_loader.parse(copy.deepcopy(DEFINITION))
    arr = cz.standard(base)
    mine = cz.new_tab(arr, base, after=0, label="Mein Ablauf")
    cz.add_command(cz.new_group(arr, base, mine, label="G"), "neu")
    eff = cz.apply(base, arr)
    logic = ContextLogic(eff)
    assert logic.stay_on == {mine.id}
    logic.tab_selected(mine.id)
    assert logic.update(Snapshot("vector", editable=True), events=("editing_started",)).select is None
    assert logic.current_tab == mine.id
    # Aus einem Standard-Tab wird weiter gewechselt
    logic.tab_selected("karte")
    assert logic.update(Snapshot("vector"), events=("editing_started",)).select == "bearbeiten"


def test_main_tab_is_unaffected_by_layer_change(logic):
    logic.tab_selected("analyse")
    for snap in (VECTOR, TABLE, RASTER, Snapshot()):
        assert logic.update(snap).select is None
    assert logic.current_tab == "analyse"
