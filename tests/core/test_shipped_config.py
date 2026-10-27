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
    # Befehle ohne Ort stehen nur im Editor zur Auswahl: einfache Buttons mit Beschreibung
    used = {c.id for t in ribbon.tabs for c in iter_commands(t)} | {c.id for c in ribbon.quick_access}
    unplaced = [ribbon.commands[c] for c in set(ribbon.commands) - used]
    assert unplaced and len(used) > 150
    assert all(c.kind == "button" and c.description for c in unplaced), [c.id for c in unplaced]


# Wörter, in denen ae/oe/ue/ss richtig geschrieben sind (keine Ersatzschreibweise)
ALLOWED_ASCII = {"ausschneiden", "messen", "messwerkzeuge", "neue", "neues", "neuer", "aktueller",
                 "processing", "quelle", "anpassen", "ausschnitt", "klasse",
                 "beschriftungsklasse", "bildverbesserung", "virtueller", "aktuelles",
                 "kartenausschnitt", "neuen", "virtuellen", "zeitsteuerung", "zusammenfassung",
                 "ausschalten", "datenquellen", "hilfsspeicher", "oberflächenanpassung"}


def test_labels_use_real_umlauts():
    # Die YAML ist englisch; die deutschen Texte stehen im Katalog
    import json
    path = os.path.join(os.path.dirname(config_loader.DEFAULT_CONFIG), "..", "i18n", "de_ribbon.json")
    with io.open(path, encoding="utf-8") as fh:
        labels = [v for v in json.load(fh).values() if len(v) < 40]
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
