"""Übersetzung der Oberfläche, ohne qgis-Imports.

Grundsprache ist Englisch: Texte stehen englisch im Code (``tr("Zoom In")``)
und in der Ribbon-Definition. Übersetzungen liegen als JSON-Kataloge
(englischer Text -> übersetzter Text) in ``qgis_ribbon/i18n/``:

- ``<sprache>.json``: Texte aus dem Code, von Hand gepflegt,
- ``<sprache>_ribbon.json``: Beschriftungen und Beschreibungen der
  Ribbon-Definition.

Die Sprache setzt ``classFactory`` vor dem ersten Import der übrigen Module
(``set_language`` mit der Sprache von QGIS). Texte auf Modulebene werden beim
Import übersetzt, ein Sprachwechsel wirkt daher wie in QGIS erst nach einem
Neustart. Fehlt ein Eintrag, bleibt der englische Text. Platzhalter (``%s``,
``%d`` …) bleiben in der Übersetzung erhalten; ``tr`` übersetzt vor dem
Einsetzen: ``tr("Arrangement “%s” loaded") % name``.
"""

import io
import json
import os
import re

SOURCE_LANGUAGE = "en"
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")
CATALOG_PARTS = ("", "_ribbon")
PLACEHOLDER = re.compile(r"%(?:\([a-z_]+\))?[-+ #0]*\d*(?:\.\d+)?[sdirf%]")

_state = {"language": SOURCE_LANGUAGE, "catalog": {}}


def normalize(locale):
    """``"de_DE"``, ``"de-AT"``, ``"DE"`` -> ``"de"``; leer -> Grundsprache."""
    text = (locale or "").strip()
    if not text:
        return SOURCE_LANGUAGE
    return re.split(r"[_\-.@]", text, maxsplit=1)[0].lower() or SOURCE_LANGUAGE


def catalog_files(language, folder=DIR):
    """Vorhandene Katalogdateien einer Sprache (Code, dann Ribbon-Definition)."""
    out = []
    for part in CATALOG_PARTS:
        path = os.path.join(folder, "%s%s.json" % (language, part))
        if os.path.isfile(path):
            out.append(path)
    return out


def load_catalog(language, folder=DIR):
    """Alle Einträge einer Sprache; leer für die Grundsprache oder ohne Katalog."""
    catalog = {}
    if language == SOURCE_LANGUAGE:
        return catalog
    for path in catalog_files(language, folder):
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        catalog.update((k, v) for k, v in data.items() if isinstance(v, str) and v and k != "")
    return catalog


def available_languages(folder=DIR):
    """Sprachen mit Katalog, dazu die Grundsprache."""
    found = {SOURCE_LANGUAGE}
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            m = re.match(r"^([a-z]{2,3})(?:_ribbon)?\.json$", name)
            if m:
                found.add(m.group(1))
    return sorted(found)


def set_language(locale, folder=DIR):
    """Sprache wählen (QGIS-Locale wie ``"de_DE"``); ohne Katalog gilt Englisch."""
    language = normalize(locale)
    catalog = load_catalog(language, folder)
    if not catalog:
        language = SOURCE_LANGUAGE
    _state["language"] = language
    _state["catalog"] = catalog
    return language


def language():
    return _state["language"]


def tr(text):
    """Übersetzung von ``text`` in der gewählten Sprache (sonst ``text`` selbst)."""
    if not text:
        return text
    return _state["catalog"].get(text, text)


def placeholders(text):
    """Platzhalter eines Texts in Reihenfolge (zum Prüfen der Kataloge)."""
    return PLACEHOLDER.findall(text)
