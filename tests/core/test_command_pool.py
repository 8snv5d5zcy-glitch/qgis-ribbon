"""Suche im Befehlsvorrat: Befehle ohne Platz im Ribbon."""
import pytest

from qgis_ribbon.core import config_loader, search


@pytest.fixture(scope="module")
def ribbon():
    return config_loader.load()


def test_search_finds_the_command_pool(ribbon):
    placed = {e.ref[0].id for e in search.ribbon_entries(ribbon)}
    pool = {e.ref[0].id: e for e in search.pool_entries(ribbon, placed)}
    assert "eigenschaften_metadaten" in pool and "zuletzt_verwendet" in pool
    assert pool["eigenschaften_metadaten"].path == "Befehlsvorrat"
    assert "feld_hinzufuegen" in placed and "feld_hinzufuegen" not in pool
    # QGIS-Aktionen findet die Suche als QGIS-Aktion, Steuerelemente brauchen ihren Platz
    assert "projekt_schliessen" not in pool
    assert all(ribbon.commands[c].kind == "button" for c in pool)
    index = search.SearchIndex(search.ribbon_entries(ribbon) + list(pool.values()))
    assert index.search("metadaten")[0].ref[0].id in ("eigenschaften_metadaten", "projekt_metadaten")
