"""Meldungen ins QGIS-Protokoll.

Eine Meldung kostet im echten QGIS rund 7 ms (Protokollfenster). Messwerte
(Aufbau, Neuaufbau, Tab) gehen deshalb erst nach der Ereignisschleife hinaus,
nicht mitten im gemessenen Ablauf.
"""

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QTimer

LOG_TAG = "QGIS Ribbon"


def info_later(text):
    QTimer.singleShot(0, lambda: QgsMessageLog.logMessage(text, LOG_TAG, Qgis.Info))
