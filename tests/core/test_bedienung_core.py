"""Bedienung (core): KeyTips, Befehlssuche, Schnellzugriffsleiste."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core import keytips, quick_access  # noqa: E402
from qgis_ribbon.core.model import Command, Gallery, Ribbon, Source, Tab  # noqa: E402
from qgis_ribbon.core.search import Entry, SearchIndex, fold  # noqa: E402


def no_prefix_conflicts(codes):
    for a in codes:
        for b in codes:
            if a != b and b.startswith(a):
                return False
    return True


# -- KeyTips ------------------------------------------------------------------

def test_keytips_prefer_word_initials():
    codes = keytips.assign(["Karte", "Einfügen", "Analyse", "Ansicht", "Bearbeiten"])
    assert codes == ["K", "E", "A", "N", "B"]


def test_keytips_umlauts_and_reserved():
    codes = keytips.assign(["Übersicht", "Quelle"], reserved=("Q",))
    assert codes[0] == "U" and codes[1] != "Q" and len(codes[1]) == 1


def test_keytips_unique_and_prefix_free_with_many_entries():
    labels = ["Befehl %d" % i for i in range(60)] + ["Alpha", "Beta", "Gamma"]
    codes = keytips.assign(labels)
    assert len(set(codes)) == len(codes) and all(codes)
    assert no_prefix_conflicts(codes)
    assert all(1 <= len(c) <= 2 for c in codes)


def test_keytips_are_deterministic():
    labels = ["Einfügen", "Ausschneiden", "Kopieren", "Erkunden", "Lesezeichen"]
    assert keytips.assign(labels) == keytips.assign(list(labels))


def test_keytips_matches():
    codes = ["A", "BE", "BL", None]
    assert keytips.matches(codes, "a") == (0, False)
    assert keytips.matches(codes, "B") == (None, True)
    assert keytips.matches(codes, "BL") == (2, False)
    assert keytips.matches(codes, "X") == (None, False)


def test_top_level_reserves_search_and_numbers_quick_access():
    tabs, qat = keytips.top_level(["Karte", "Quelle"], 3)
    assert "Q" not in tabs and tabs[0] == "K"
    assert qat == ["1", "2", "3"]
    assert keytips.top_level(["Karte"], 12)[1] == list("123456789")


# -- Suche --------------------------------------------------------------------

def test_fold():
    assert fold("Größter Maßstab") == "groesster massstab"
    assert fold("WFS / OGC-API") == "wfs ogc api"


def _index():
    return SearchIndex([
        Entry("Größter Maßstab", "max", path="Darstellung › Sichtbarkeitsbereich"),
        Entry("Puffer", "puffer", path="Analyse › Werkzeuge", description="Flächen um Objekte"),
        Entry("Auswahl aufheben", "aufheben", path="Karte › Auswahl"),
        Entry("Alle auswählen", "alle", path="Daten › Auswahl"),
        Entry("Puffer (QGIS)", "qgis_puffer", ribbon=False),
    ])


def test_search_ranking_and_umlauts():
    idx = _index()
    assert [e.ref for e in idx.search("groesster")] == ["max"]
    assert [e.ref for e in idx.search("Maßstab")] == ["max"]
    # Beginnt mit > Wortanfang; Ribbon vor QGIS-Aktion
    assert [e.ref for e in idx.search("puf")] == ["puffer", "qgis_puffer"]
    assert [e.ref for e in idx.search("auswahl")][:2] == ["aufheben", "alle"] or \
        [e.ref for e in idx.search("auswahl")][0] == "aufheben"
    # Alle Wörter müssen vorkommen, auch über Ort und Beschreibung
    assert [e.ref for e in idx.search("analyse puffer")] == ["puffer"]
    assert [e.ref for e in idx.search("flächen")] == ["puffer"]
    assert idx.search("") == [] and idx.search("gibtsnicht") == []


def test_search_budget():
    idx = SearchIndex(Entry("Befehl Nummer %d Auswahl" % i, i, path="Tab › Gruppe",
                            description="Beschreibung %d" % i) for i in range(1500))
    if sys.gettrace() is not None or "coverage" in sys.modules:
        pytest.skip("Zeitmessung unter Abdeckungsmessung nicht aussagekräftig")
    runs = []
    for _ in range(3):   # bester von drei Läufen: robust gegen Last auf dem Rechner
        start = time.perf_counter()
        for text in ("b", "be", "bef", "befehl", "befehl 14", "auswahl"):
            idx.search(text)
        runs.append((time.perf_counter() - start) / 6 * 1000)
    assert min(runs) < 10, runs


# -- Schnellzugriff -----------------------------------------------------------

def cmd(cid, kind="button", gallery=None):
    return Command(id=cid, label=cid, source=Source("qgis_action", {"object_name": cid}),
                   kind=kind, gallery=gallery)


@pytest.fixture
def ribbon():
    cmds = {c.id: c for c in (cmd("neu"), cmd("speichern"), cmd("zoomen"),
                              cmd("regler", kind="control"),
                              cmd("galerie", kind="control", gallery=Gallery()))}
    return Ribbon(tabs=(Tab("t", "T"),), commands=cmds,
                  quick_access=(cmds["neu"], cmds["speichern"]))


def test_quick_access_default_and_stored(ribbon):
    assert [c.id for c in quick_access.effective(ribbon, None)] == ["neu", "speichern"]
    assert quick_access.effective(ribbon, "") == ()
    stored = "zoomen, neu,gibtsnicht,regler,galerie,neu"
    assert [c.id for c in quick_access.effective(ribbon, stored)] == ["zoomen", "neu"]


def test_quick_access_add_remove_roundtrip(ribbon):
    cur = quick_access.effective(ribbon, None)
    cur = quick_access.added(cur, ribbon.commands["zoomen"])
    cur = quick_access.added(cur, ribbon.commands["zoomen"])          # doppelt: unverändert
    cur = quick_access.added(cur, ribbon.commands["regler"])          # nicht erlaubt
    assert quick_access.serialize(cur) == "neu,speichern,zoomen"
    cur = quick_access.removed(cur, ribbon.commands["neu"])
    assert [c.id for c in quick_access.effective(ribbon, quick_access.serialize(cur))] == \
        ["speichern", "zoomen"]


def test_ribbon_entries_have_paths():
    from qgis_ribbon.core import config_loader
    pytest.importorskip("yaml")
    ribbon = config_loader.load()
    entries = {e.ref[0].id: e for e in __import__("qgis_ribbon.core.search", fromlist=["x"]).ribbon_entries(ribbon)}
    assert set(entries) == set(ribbon.commands)
    assert entries["layer_deckkraft"].path == "Vektorlayer: Darstellung › Effekte"
    assert entries["neues_projekt"].path == "Schnellzugriff"
    idx = SearchIndex(entries.values())
    assert idx.search("deckkraft")[0].ref[0].id == "layer_deckkraft"
    assert idx.search("puffer")[0].ref[0].id == "puffer"


# -- Eigene Kürzel (Overrides) ----------------------------------------------------

def test_fixed_codes_take_precedence_and_others_adapt():
    labels = ["Karte", "Kopieren", "Einfügen"]
    assert keytips.assign(labels) == ["K", "O", "E"]
    codes = keytips.assign(labels, fixed={1: "k"})        # Kopieren bekommt K
    assert codes[1] == "K" and codes[0] != "K"
    assert len(set(codes)) == 3 and no_prefix_conflicts(codes)


def test_fixed_two_letter_blocks_its_first_letter():
    labels = ["Speichern", "Suchen", "Senden"]
    codes = keytips.assign(labels, fixed={2: "SE"})
    assert codes[2] == "SE" and "S" not in codes and no_prefix_conflicts(codes)


def test_invalid_or_conflicting_fixed_codes_are_ignored():
    labels = ["Alpha", "Beta", "Gamma"]
    codes = keytips.assign(labels, fixed={0: "B", 1: "B", 2: "1x"}, reserved=("Q",))
    assert codes[0] == "B" and codes[1] != "B" and codes[2] != "1X"
    assert keytips.assign(["A"], fixed={0: "Q"}, reserved=("Q",))[0] != "Q"
    assert keytips.assign(["Ä"], fixed={0: "ä"})[0] == "A"


def test_fixed_with_many_entries():
    labels = ["Befehl %d" % i for i in range(60)]
    fixed = {i: c for i, c in zip(range(0, 60, 7), "ABCDEFGHI")}
    codes = keytips.assign(labels, fixed=fixed)
    assert all(codes[i] == c for i, c in fixed.items())
    assert len(set(codes)) == 60 and no_prefix_conflicts(codes)


def test_code_validation_and_conflicts():
    assert keytips.code_error("AB") is None
    assert keytips.code_error("ABC") and keytips.code_error("1") and keytips.code_error("")
    assert keytips.conflicts(["A", "AB", "C", "C"]) == [(0, 1), (2, 3)]


def test_target_keys_are_stable():
    keys = keytips.target_keys([("zoom", "Zoom"), (None, "Lesezeichen"), ("zoom", "Zoom")])
    assert keys == ["zoom", "menu:Lesezeichen", "zoom#2"]
    assert keytips.element_key("karte", "zoom") == "karte/zoom"
    assert keytips.tab_key("karte") == "tab:karte"
    tabs, _ = keytips.top_level(["Karte", "Einfügen"], 0, fixed={0: "M"})
    assert tabs == ["M", "E"]
