"""Unterschiede zwischen Qt5 und Qt6 an einer Stelle.

Qt6 ersetzt ``pos()`` der Maus- und Zieh-Ereignisse durch ``position()``; Qt 5.15
kennt ``position()`` dort noch nicht.
"""


def event_pos(event):
    """Position eines Maus- oder Zieh-Ereignisses im Widget als ``QPoint``."""
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()
