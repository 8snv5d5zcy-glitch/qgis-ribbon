"""Unterschiede zwischen Qt5 und Qt6 sowie QGIS 3 und QGIS 4 für ``qgis_integration``.

``qgis_integration`` darf nicht auf ``ui`` zugreifen, daher hat es eine eigene Kopie
der wenigen Brücken (Gegenstück für die Oberfläche: ``ui/qt_compat.py``).
"""
from qgis.core import Qgis

try:
    from qgis.PyQt.QtGui import QUndoCommand      # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QUndoCommand  # Qt5

__all__ = ["QUndoCommand", "legend_auto_update", "set_legend_auto_update"]


def legend_auto_update(item):
    """Folgt die Legende dem Layerbaum? QGIS 4 kennt dafür ``syncMode``, ``autoUpdateModel`` ist dort veraltet."""
    if hasattr(item, "syncMode"):
        return item.syncMode() != Qgis.LegendSyncMode.Manual
    return item.autoUpdateModel()


def set_legend_auto_update(item, on):
    if hasattr(item, "setSyncMode"):
        item.setSyncMode(Qgis.LegendSyncMode.AllProjectLayers if on else Qgis.LegendSyncMode.Manual)
    else:
        item.setAutoUpdateModel(bool(on))
