"""Felder anlegen, löschen, umbenennen: Prüfung ohne QGIS."""
from qgis_ribbon.core import fields as fm
from qgis_ribbon.core.conditions import Snapshot, all_true, depending_on, evaluate


def test_name_checks():
    assert fm.name_errors("  ") == ["Einen Feldnamen eingeben."]
    assert fm.name_errors("Name", ["id", "name"]) == ["Ein Feld „Name“ gibt es schon."]
    assert fm.name_errors(" neu ", ["id"]) == []


def test_spec_checks_length_and_precision():
    assert fm.errors(fm.FieldSpec("a", "string", 80)) == []
    assert fm.errors(fm.FieldSpec("a", "string", fm.MAX_LENGTH + 1)) == ["Die Länge muss zwischen 0 und 65535 liegen."]
    assert fm.errors(fm.FieldSpec("a", "real", 10, 3)) == []
    assert fm.errors(fm.FieldSpec("a", "real", 10, 10)) == ["Die Genauigkeit muss kleiner als die Länge sein."]
    assert fm.errors(fm.FieldSpec("a", "real", 0, 4)) == []          # Länge 0: Anbieter wählt
    assert fm.errors(fm.FieldSpec("a", "real", 10, -1)) == ["Die Genauigkeit darf nicht negativ sein."]
    # Typen ohne Länge prüfen keine Länge
    assert fm.errors(fm.FieldSpec("a", "integer", -5, -5)) == []
    assert fm.errors(fm.FieldSpec("a", "kurios")) == ["Feldtyp unbekannt: kurios"]


def test_normalized_drops_what_the_type_has_not():
    spec = fm.normalized(fm.FieldSpec(" a ", "date", 80, 3, " Alias ", " Notiz "))
    assert (spec.name, spec.length, spec.precision, spec.alias, spec.comment) == ("a", 0, 0, "Alias", "Notiz")
    assert fm.normalized(fm.FieldSpec("b", "real", 12, 4)).length == 12
    assert fm.default_length("string") == 80 and fm.type_label("integer") == "Ganzzahl (integer)"


def test_rename_checks():
    names = ["id", "name", "Wert"]
    assert fm.rename_errors("name", "name", names) == ["Einen neuen Namen eingeben."]
    assert fm.rename_errors("name", "wert", names) == ["Ein Feld „wert“ gibt es schon."]
    assert fm.rename_errors("name", "Name", names) == []          # nur Schreibweise ändern
    assert fm.rename_errors("name", "bezeichnung", names) == []


def test_field_capability_conditions():
    snap = Snapshot("vector", field_caps=frozenset({"add", "rename"}))
    assert evaluate("active_layer_can_add_fields", snap)
    assert evaluate("active_layer_can_rename_fields", snap)
    assert not evaluate("active_layer_can_delete_fields", snap)
    assert not all_true(["active_layer_can_add_fields"], Snapshot("raster"))
    assert depending_on({"field_caps"}) == {"active_layer_can_add_fields", "active_layer_can_delete_fields",
                                            "active_layer_can_rename_fields"}
    try:
        Snapshot("vector", field_caps=frozenset({"drop"}))
    except ValueError as exc:
        assert "drop" in str(exc)
    else:
        raise AssertionError("ungültige Fähigkeit angenommen")
