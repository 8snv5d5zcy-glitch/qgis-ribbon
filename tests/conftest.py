"""Gemeinsame Einstellung aller Tests: Oberfläche auf Deutsch.

Die Grundsprache des Plugins ist Englisch; die Tests prüfen die Texte mit dem
deutschen Katalog. Die Sprache wird hier gesetzt, bevor ein Test ein Modul
importiert, damit auch Texte auf Modulebene deutsch sind. Englisch und die
Kataloge selbst prüft ``tests/core/test_i18n.py``.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qgis_ribbon.core import i18n  # noqa: E402

i18n.set_language("de")
