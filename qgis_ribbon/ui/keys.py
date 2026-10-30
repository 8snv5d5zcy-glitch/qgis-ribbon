"""Tastenkürzel des Ribbons und ihre Schreibweise in Texten, je Plattform.

Qt bildet auf dem Mac ``Ctrl`` auf die Befehlstaste (⌘) ab und ``Meta`` auf
die Control-Taste (⌃). Einige Kürzel, die unter Windows üblich sind, belegt
macOS selbst: ⌘Q beendet das Programm, ⌘F1 spiegelt den Bildschirm, ⌃F1
schaltet die Tastaturbedienung um. Auf dem Mac gelten deshalb eigene Kürzel.

Texte nennen Kürzel über ``text``: auf dem Mac mit den Symbolen der Tasten
(⌘Z, ⌥), sonst mit übersetzten Namen (Strg+Z).
"""

import sys

from qgis.PyQt.QtCore import Qt

from ..core.i18n import tr

MAC = sys.platform == "darwin"

MINIMIZE = "Ctrl+Alt+T" if MAC else "Ctrl+F1"   # Mac: wie „Symbolleiste ein/aus“
REDO = "Ctrl+Shift+Z" if MAC else "Ctrl+Y"
QUICK_ACCESS = "Meta+Q" if MAC else "Ctrl+Q"     # ⌘Q beendet auf dem Mac QGIS
QUICK_ACCESS_MODIFIER = Qt.KeyboardModifier.MetaModifier if MAC else Qt.KeyboardModifier.ControlModifier

_MAC_SYMBOLS = {"Ctrl": "⌘", "Alt": "⌥", "Meta": "⌃", "Shift": "⇧", "Del": "⌫"}
_MAC_ORDER = ("Meta", "Alt", "Shift", "Ctrl")   # Reihenfolge auf dem Mac: ⌃⌥⇧⌘


def _names():
    return {"Ctrl": tr("Ctrl"), "Del": tr("Del"), "Arrow": tr("Arrow"), "Shift": tr("Shift")}


def text(portable):
    """Kürzel in portabler Form (``"Ctrl+Z"``) für einen Text der Oberfläche."""
    parts = portable.split("+")
    if MAC:
        mods = [p for p in _MAC_ORDER if p in parts[:-1]]
        last = parts[-1]
        key = _MAC_SYMBOLS.get(last) or _names().get(last, last)
        return "".join(_MAC_SYMBOLS[m] for m in mods) + key
    names = _names()
    return "+".join(names.get(p, p) for p in parts)
