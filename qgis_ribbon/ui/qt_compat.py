"""Unterschiede zwischen Qt5 und Qt6 an einer Stelle.

Qt6 ersetzt ``pos()`` der Maus- und Zieh-Ereignisse durch ``position()``; Qt 5.15
kennt ``position()`` dort noch nicht. ``QFontDatabase`` hat unter Qt6 nur noch
statische Methoden und lässt sich nicht mehr instanziieren.
"""
from qgis.PyQt.QtGui import QFontDatabase


def event_pos(event):
    """Position eines Maus- oder Zieh-Ereignisses im Widget als ``QPoint``."""
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


def font_database():
    """``QFontDatabase`` zum Aufruf von ``styles()`` usw.: unter Qt6 die Klasse
    (statische Methoden), unter Qt5 eine Instanz."""
    try:
        return QFontDatabase()
    except TypeError:
        return QFontDatabase


def associated_widgets(action):
    """Objekte, in denen ``action`` steckt (Knöpfe, Menüs): Qt6 ``associatedObjects()``,
    Qt5 ``associatedWidgets()``."""
    getter = getattr(action, "associatedObjects", None) or action.associatedWidgets
    return getter()
