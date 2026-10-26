"""Übersetzung: Sprachwahl, Kataloge und Vollständigkeit."""
import ast
import io
import json
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)

from qgis_ribbon.core import config_loader, i18n  # noqa: E402

PLUGIN = os.path.join(ROOT, "qgis_ribbon")
CATALOG_DIR = os.path.join(PLUGIN, "i18n")
GERMAN = re.compile(r"[äöüÄÖÜß„“]")
# Werte, die keine Oberflächentexte sind (Ergebnis-Schlüssel des Inventars)
NOT_UI = {"nicht prüfbar", "ungültig"}


def _catalog(name):
    with io.open(os.path.join(CATALOG_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def _literals():
    """(Datei, Zeile, Text, in tr()) aller Zeichenketten außer Docstrings."""
    out = []
    for folder, _dirs, files in os.walk(PLUGIN):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with io.open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            docs, in_tr = set(), set()
            for n in ast.walk(tree):
                body = getattr(n, "body", None)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and body \
                        and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docs.add(id(body[0].value))
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args:
                    in_tr.add(id(n.args[0]))
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                    out.append((os.path.relpath(path, PLUGIN), n.lineno, n.value, id(n) in in_tr))
    return out


def test_normalize():
    assert i18n.normalize("de_DE") == "de"
    assert i18n.normalize("de-AT") == "de"
    assert i18n.normalize("DE") == "de"
    assert i18n.normalize("") == "en"
    assert i18n.normalize(None) == "en"


def test_language_without_catalog_falls_back_to_english(english):
    assert i18n.set_language("xx_YY") == "en"
    assert i18n.tr("Customize Ribbon …") == "Customize Ribbon …"


def test_german_catalog():
    assert i18n.set_language("de_DE") == "de"
    assert i18n.tr("Customize Ribbon …") == "Ribbon anpassen …"
    assert i18n.tr("Unknown text") == "Unknown text"
    assert i18n.tr("") == ""
    assert "de" in i18n.available_languages() and "en" in i18n.available_languages()


def test_load_catalog_ignores_empty_entries(tmp_path):
    (tmp_path / "fr.json").write_text(json.dumps({"Save": "Enregistrer", "Cancel": ""}), encoding="utf-8")
    (tmp_path / "fr_ribbon.json").write_text(json.dumps({"Map": "Carte"}), encoding="utf-8")
    assert i18n.load_catalog("fr", str(tmp_path)) == {"Save": "Enregistrer", "Map": "Carte"}
    assert i18n.load_catalog("en", str(tmp_path)) == {}


def test_definition_follows_language(english):
    tab = config_loader.load().tabs[0]
    assert (tab.id, tab.label) == ("karte", "Map")
    i18n.set_language("de")
    tab = config_loader.load().tabs[0]
    assert (tab.id, tab.label) == ("karte", "Karte")


def test_menu_keys_do_not_depend_on_language(english):
    from qgis_ribbon.core import customization as cz
    keys_en = sorted(k for k in cz.element_index(config_loader.load())[0] if k.startswith("menu:"))
    i18n.set_language("de")
    keys_de = sorted(k for k in cz.element_index(config_loader.load())[0] if k.startswith("menu:"))
    assert keys_en == keys_de
    assert "menu:karte/navigieren/Lesezeichen" in keys_de


def test_catalogs_agree_and_keep_placeholders():
    code, ribbon = _catalog("de.json"), _catalog("de_ribbon.json")
    for key in set(code) & set(ribbon):
        assert code[key] == ribbon[key], key
    for catalog in (code, ribbon):
        for en, de in catalog.items():
            assert i18n.placeholders(en) == i18n.placeholders(de), en


def test_every_code_text_is_translated():
    code = _catalog("de.json")
    missing = sorted({text for _f, _l, text, in_tr in _literals() if in_tr and text not in code})
    assert not missing, missing


def test_no_unused_code_entries():
    used = {text for _f, _l, text, in_tr in _literals() if in_tr}
    used.add("Arrangement “%s” loaded")  # Beispiel im Docstring von core/i18n.py
    theme = os.path.join(PLUGIN, "config", "themes")
    for name in os.listdir(theme):
        with io.open(os.path.join(theme, name), encoding="utf-8") as fh:
            used.update(re.findall(r'label: "([^"]+)"', fh.read()))
    unused = sorted(set(_catalog("de.json")) - used)
    assert not unused, unused


def test_no_german_literals_outside_tr():
    found = ["%s:%d %r" % (f, line, text) for f, line, text, in_tr in _literals()
             if not in_tr and len(text) > 1 and GERMAN.search(text) and text not in NOT_UI]
    assert not found, found


def test_every_definition_text_is_translated():
    import yaml
    with io.open(config_loader.DEFAULT_CONFIG, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    ribbon = _catalog("de_ribbon.json")
    texts = set()

    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("label", "description", "context", "menu") and isinstance(v, str):
                    texts.add(v)
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(data)
    assert texts
    assert not sorted(t for t in texts if t not in ribbon)
    assert not sorted(t for t in texts if GERMAN.search(t))
