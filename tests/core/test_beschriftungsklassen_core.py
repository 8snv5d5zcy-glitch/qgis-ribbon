"""Beschriftungsklassen: Bedingung ``label_classes_on`` und ihre Verwendung in der Definition."""
from qgis_ribbon.core import config_loader
from qgis_ribbon.core.conditions import Snapshot, all_true, changed_fields, depending_on, evaluate
from qgis_ribbon.core.model import iter_commands

CLASS_COMMANDS = ("beschriftungsklasse", "beschriftungsklasse_filter", "beschriftungsklasse_aktiv",
                  "beschriftungsklasse_loeschen")
ALWAYS_COMMANDS = ("beschriftungsklasse_neu", "beschriftungsfeld", "beschriftung_schrift", "beschriftung_groesse",
                   "beschriftung_massstab_max", "beschriftung_massstab_min", "beschriftung_massstab_aus",
                   "beschriftung_farbe", "beschriftung_schriftschnitt", "beschriftung_groesser",
                   "beschriftung_kleiner", "textformat_galerie", "platzierung_galerie", "beschriftungsklassen")


def test_condition_follows_snapshot_field():
    on = Snapshot("vector", label_classes=True)
    off = Snapshot("vector")
    assert evaluate("label_classes_on", on) and not evaluate("label_classes_on", off)
    assert not all_true(["active_layer_is_vector", "label_classes_on"], off)
    assert depending_on(changed_fields(off, on)) == {"label_classes_on"}
    assert depending_on({"editable"}).isdisjoint({"label_classes_on"})


def test_class_commands_need_classes_and_the_rest_does_not():
    ribbon = config_loader.load()
    for cid in CLASS_COMMANDS:
        assert "label_classes_on" in ribbon.commands[cid].enabled_when, cid
    for cid in ALWAYS_COMMANDS:
        assert "label_classes_on" not in ribbon.commands[cid].enabled_when, cid


def test_switch_is_the_first_item_of_the_group():
    ribbon = config_loader.load()
    tab = next(t for t in ribbon.tabs if t.id == "vektor_beschriftung")
    group = next(g for g in tab.groups if g.id == "beschriftungsklasse")
    assert [c.id for c in iter_commands(group.elements[0])] == ["beschriftungsklassen"]
    switch = ribbon.commands["beschriftungsklassen"]
    assert switch.source.get("id") == "ribbon.beschriftung_klassen_schalten"
    assert switch.enabled_when == ("active_layer_is_vector",)
