"""Domänen-Modell und Bearbeitungsstand (ohne QGIS)."""
import pytest

from qgis_ribbon.core import domains as dm


def coded(name="Arten", values=(("E", "Eiche"), ("B", "Buche")), ftype="string"):
    return dm.Domain(name, "coded", ftype, values=list(values))


def test_parse_value():
    assert dm.parse_value(" 5 ", "integer") == 5
    assert dm.parse_value("2,5", "real") == 2.5
    assert dm.parse_value("x", "string") == "x"
    with pytest.raises(ValueError, match="keine Ganzzahl"):
        dm.parse_value("2,5", "integer")
    with pytest.raises(ValueError, match="fehlt"):
        dm.parse_value("", "real")


def test_errors_of_coded_domain():
    assert dm.errors(coded()) == []
    assert "Name fehlt" in dm.errors(coded(name=" "))
    assert any("gibt es schon" in e for e in dm.errors(coded(), other_names=["arten"]))
    assert "Werteliste ist leer" in dm.errors(coded(values=()))
    errs = dm.errors(coded(values=(("1", "a"), ("1", "b"), ("x", "c"), ("2", "")), ftype="integer"))
    assert any("doppelt" in e for e in errs)
    assert any("keine Ganzzahl" in e for e in errs)
    assert any("Beschreibung fehlt" in e for e in errs)


def test_errors_of_range_domain():
    ok = dm.Domain("Höhe", "range", "integer", minimum="0", maximum="100")
    assert dm.errors(ok) == []
    assert dm.errors(dm.Domain("H", "range", "integer", maximum=10)) == []
    assert "Minimum ist größer als Maximum" in dm.errors(
        dm.Domain("H", "range", "real", minimum="5", maximum="1,5"))
    assert "Minimum oder Maximum angeben" in dm.errors(dm.Domain("H", "range", "integer"))
    assert "Bereich nur für Ganzzahl oder Dezimalzahl" in dm.errors(
        dm.Domain("H", "range", "string", minimum="a", maximum="b"))


def test_normalized_and_widget_configs():
    d = dm.normalized(coded(values=(("1", " Eins "),), ftype="integer"))
    assert d.values == [(1, "Eins")]
    assert dm.value_map_config(d) == {"map": [{"Eins": 1}]}
    r = dm.normalized(dm.Domain("H", "range", "real", minimum="0,5", maximum=None))
    assert r.minimum == 0.5 and r.maximum is None
    cfg = dm.range_config(r)
    assert cfg["Min"] == 0.5 and "Max" not in cfg and cfg["Precision"] == 2


def test_compatible():
    assert dm.compatible(coded(), "string")
    assert not dm.compatible(coded(), "integer")
    assert dm.compatible(coded(ftype="integer"), "real")
    assert not dm.compatible(coded(ftype="real"), "integer")
    assert not dm.compatible(coded(), None)


def session():
    return dm.DomainSession(
        [coded(), dm.Domain("Höhen", "range", "integer", minimum=0, maximum=100)],
        {"art": "string", "hoehe": "integer", "wert": "real", "datum": None},
        {"art": "Arten", "hoehe": ""})


def test_session_without_edits_has_no_changes():
    s = session()
    assert not s.dirty() and s.problems() == []
    assert s.assignments == {"art": "Arten"}
    assert s.choices("wert") == ["Höhen"] and s.choices("datum") == []


def test_session_add_update_remove_and_assign():
    s = session()
    s.add(dm.Domain(s.unique_name(), "coded", "string", values=[("a", "A")]))
    assert s.names()[-1] == "Neue Domäne" and s.unique_name() == "Neue Domäne 2"
    # Wert als Text, der dem gespeicherten Wert entspricht: keine Änderung
    h = s.get("Höhen").copy()
    h.minimum = "0"
    s.replace("Höhen", h)
    assert s.changes()["updated"] == []
    h = h.copy()
    h.maximum = "50"
    s.replace("Höhen", h)
    s.assign("hoehe", "Höhen")
    s.assign("art", "")
    s.remove("Arten")
    c = s.changes()
    assert [d.name for d in c["added"]] == ["Neue Domäne"]
    assert [(d.name, d.maximum) for d in c["updated"]] == [("Höhen", 50)]
    assert c["removed"] == ["Arten"]
    assert c["assign"] == {"hoehe": "Höhen"} and c["unassign"] == ["art"]
    assert s.problems() == []


def test_saved_domain_keeps_name_new_domain_renames_assignments():
    s = session()
    d = s.get("Arten").copy()
    d.name = "Umbenannt"
    s.replace("Arten", d)
    assert s.names()[0] == "Arten"
    s.add(dm.Domain("Neu", "coded", "string", values=[("x", "X")]))
    s.assign("art", "Neu")
    n = s.get("Neu").copy()
    n.name = "Neu2"
    s.replace("Neu", n)
    assert s.assignments["art"] == "Neu2"


def test_session_problems():
    s = session()
    s.remove("Arten")
    assert ("art", "Domäne „Arten“ gibt es nicht mehr") in s.problems()
    s = session()
    s.add(dm.Domain("arten", "coded", "string", values=[("x", "X")]))
    assert any("gibt es schon" in text for _w, text in s.problems())
    s = session()
    s.assign("wert", "Arten")
    assert ("wert", "Domäne „Arten“ passt nicht zum Feldtyp") in s.problems()
    s = session()
    bad = s.get("Höhen").copy()
    bad.minimum = "x"
    s.replace("Höhen", bad)
    assert s.dirty() and s.problems()
