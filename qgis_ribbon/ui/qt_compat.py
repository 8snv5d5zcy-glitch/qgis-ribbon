"""Unterschiede zwischen Qt5 und Qt6 an einer Stelle.

Qt6 ersetzt ``pos()`` der Maus- und Zieh-Ereignisse durch ``position()``; Qt 5.15
kennt ``position()`` dort noch nicht. Ebenso sind ``QFontDatabase``-Methoden unter Qt6
statisch, ``QAction.associatedWidgets`` heißt dort ``associatedObjects`` und
``QApplication.paletteChanged`` gibt es nicht mehr.
"""
import sys

from qgis.PyQt.QtCore import QT_VERSION, QEvent
from qgis.PyQt.QtGui import QFontDatabase


def event_pos(event):
    """Position eines Maus- oder Zieh-Ereignisses im Widget als ``QPoint``."""
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


def font_styles(family):
    """Schriftschnitte einer Familie."""
    try:
        return QFontDatabase.styles(family)       # Qt6: statisch
    except TypeError:
        return QFontDatabase().styles(family)     # Qt5


def font_style_string(font):
    """Name des Schriftschnitts einer ``QFont``."""
    try:
        return QFontDatabase.styleString(font)
    except TypeError:
        return QFontDatabase().styleString(font)


def action_widgets(action):
    """Widgets, in denen ``action`` steht (Knöpfe, Menüs)."""
    if hasattr(action, "associatedObjects"):
        return [o for o in action.associatedObjects() if o.isWidgetType()]
    return action.associatedWidgets()


PALETTE_CHANGE = QEvent.Type.ApplicationPaletteChange

# macOS mit PyQt5 (QGIS 3): Ein app-weiter Ereignisfilter in Python bringt QGIS in sip zum Absturz, sobald Qt
# ihm ein Objekt übergibt, dessen Typ sip nicht bestimmen kann (Zeitgeber-Ereignis, Objekt im Abbau). Dort
# keine app-weiten Filter: ohne KeyTips und ohne Ausrichten fremder Menüs.
APP_FILTER = not (sys.platform == "darwin" and QT_VERSION < 0x060000)
