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


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def slot_errors():
    """Python-Fehler in Qt-Slots machen den Test rot.

    Unter PyQt6 beendet ein Fehler in einem Slot ohne ``sys.excepthook`` den ganzen
    Prozess ohne Meldung (Rückgabewert 127); unter PyQt5 steht er nur im Protokoll.
    """
    seen = []
    old = sys.excepthook

    def hook(kind, value, tb):
        seen.append((kind, value, tb))

    sys.excepthook = hook
    try:
        yield seen
    finally:
        sys.excepthook = old
    if seen:
        import traceback
        text = "".join(traceback.format_exception(*seen[0]))
        pytest.fail("Fehler in einem Qt-Slot (%d):\n%s" % (len(seen), text), pytrace=False)
