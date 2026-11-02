"""Befehle aus QGIS 4: im Befehlsvorrat, nur wo QGIS sie kennt; Standardanordnung überall gleich."""
import io
import json
import os

import pytest

from qgis_ribbon.core import config_loader, customization as cz
from qgis_ribbon.core.search import ribbon_entries

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QGIS3, QGIS4 = 34415, 40203
NEW = {"digitalisieren_bezier", "digitalisieren_nurbs", "fasen_runden", "objekte_als_array",
       "hoehenprofile_verwalten", "annotationen_waehlen", "netz_digitalisieren", "netz_erzwingen",
       "netz_reindizieren", "netz_alle_stuetzpunkte", "netz_isolierte_stuetzpunkte", "netz_transformieren"}
# Bringen QGIS 4.2.3 beim Auslösen außerhalb des Kontextmenüs zum Absturz, auch ohne Projekt
CRASH = {"mActionRemoveVerticesFillingHole", "mActionRemoveVerticesWithoutFillingHole"}


def minimal(**command):
    cmd = {"label": "A", "source": {"type": "qgis_action", "object_name": "mActionA"}}
    tab = {"id": "t", "label": "T", "groups": [{"id": "g", "label": "G", "items": [{"command": "basis"}]}]}
    return {"version": config_loader.SCHEMA_VERSION, "tabs": [tab],
            "commands": {"basis": dict(cmd), "neu": dict(cmd, **command)}}


def test_new_commands_only_where_qgis_knows_them():
    assert {c.id for c in config_loader.load().commands.values() if c.qgis_min} == NEW
    assert not NEW & set(config_loader.load(qgis_version=QGIS3).commands)
    assert NEW <= set(config_loader.load(qgis_version=QGIS4).commands)
    # Ohne ihn käme man von Bezier und NURBS bei ausgeblendeter Leiste nicht zurück
    assert "digitalisieren_segment" in config_loader.load(qgis_version=QGIS3).commands


def test_default_arrangement_is_the_same_in_both_versions():
    old, new = config_loader.load(qgis_version=QGIS3), config_loader.load(qgis_version=QGIS4)
    assert old.tabs == new.tabs
    assert old.quick_access == new.quick_access
    assert not NEW & {e.ref[0].id for e in ribbon_entries(new)}


def test_all_commands_of_qgis3_are_kept():
    all_ids = set(config_loader.load().commands)
    assert set(config_loader.load(qgis_version=QGIS3).commands) == all_ids - NEW
    assert set(config_loader.load(qgis_version=QGIS4).commands) == all_ids


def test_layout_definition_has_no_version_limits():
    assert not any(c.qgis_min for c in config_loader.load(config_loader.LAYOUT_CONFIG).commands.values())


def test_qgis_min_compares_the_whole_version():
    data = minimal(qgis_min=40200)
    assert "neu" not in config_loader.parse(data, 40199).commands
    assert "neu" in config_loader.parse(data, 40200).commands
    assert "neu" in config_loader.parse(data).commands


@pytest.mark.parametrize("value", ["4.0", 0, -1, True, 4.0])
def test_invalid_qgis_min_is_an_error(value):
    with pytest.raises(config_loader.ConfigError) as err:
        config_loader.parse(minimal(qgis_min=value))
    assert "qgis_min" in str(err.value)


@pytest.mark.parametrize("part", ["tab", "quick_access"])
def test_command_with_qgis_min_cannot_be_placed(part):
    data = minimal(qgis_min=40000)
    if part == "tab":
        data["tabs"][0]["groups"][0]["items"].append({"command": "neu"})
    else:
        data["quick_access"] = ["neu"]
    with pytest.raises(config_loader.ConfigError) as err:
        config_loader.parse(data)
    assert "qgis_min" in str(err.value)


def test_arrangement_from_qgis4_loads_in_qgis3_without_the_new_command():
    """Datei aus QGIS 4 in QGIS 3.44: Der Befehl entfällt mit Hinweis, der Rest bleibt."""
    reader = cz._Reader(config_loader.load(qgis_version=QGIS3))
    entries = reader.items([{"command": "digitalisieren_bezier"}, {"command": "neues_projekt"}], "Gruppe")
    assert [e.command for e in entries] == ["neues_projekt"]
    assert len(reader.warnings) == 1 and "digitalisieren_bezier" in reader.warnings[0]


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "tools", "befehlsluecken.json")),
                    reason="Lückenliste gibt es nur im Entwicklungsrepository")
def test_every_new_qgis4_action_is_answered_and_crashing_ones_stay_out():
    with io.open(os.path.join(ROOT, "tools", "befehlsluecken.json"), encoding="utf-8") as fh:
        gaps = json.load(fh)
    place = next(p for p in gaps["stellen"] if "QGIS 4" in p["ort"])
    answered = {e["qgis"]: e for e in place["eintraege"]}
    assert len([e for e in answered.values() if "befehl" in e]) == 13
    assert len([e for e in answered.values() if "grund" in e]) == 6
    assert CRASH <= set(answered) and all("Absturz" in answered[n]["grund"] for n in CRASH)
    sources = {c.source.get("object_name") for c in config_loader.load().commands.values()}
    assert not {n for n, e in answered.items() if "grund" in e} & sources
