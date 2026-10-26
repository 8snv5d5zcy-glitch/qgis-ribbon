"""Eigene Kartenwerkzeuge.

``SelectByLineTool``: Linie zeichnen, Objekte des aktiven Vektorlayers, die sie
schneidet, werden ausgewählt. Bedienung wie die QGIS-Auswahlwerkzeuge:
Linksklick setzt Stützpunkte, Rechtsklick (oder Doppelklick) beendet die
Linie, Esc bricht ab, Rücktaste nimmt den letzten Stützpunkt zurück. Umschalt
fügt zur Auswahl hinzu, Strg entfernt aus ihr.
"""

from qgis.core import (Qgis, QgsCoordinateTransform, QgsFeatureRequest, QgsGeometry, QgsPointXY,
                       QgsProject, QgsWkbTypes)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from .layer_ops import is_vector

LINE_COLOR = QColor(255, 0, 0, 160)


def selection_behavior(modifiers):
    if modifiers & Qt.ShiftModifier:
        return Qgis.SelectBehavior.AddToSelection
    if modifiers & Qt.ControlModifier:
        return Qgis.SelectBehavior.RemoveFromSelection
    return Qgis.SelectBehavior.SetSelection


def select_by_line(layer, line, canvas_crs, behavior=Qgis.SelectBehavior.SetSelection):
    """Objekte von ``layer`` wählen, die die Linie (``QgsGeometry`` im Karten-KBS) schneiden.

    Gibt die Anzahl der getroffenen Objekte zurück.
    """
    geom = QgsGeometry(line)
    if canvas_crs != layer.crs():
        geom.transform(QgsCoordinateTransform(canvas_crs, layer.crs(), QgsProject.instance()))
    engine = QgsGeometry.createGeometryEngine(geom.constGet())
    engine.prepareGeometry()
    request = QgsFeatureRequest().setFilterRect(geom.boundingBox()).setNoAttributes()
    ids = [f.id() for f in layer.getFeatures(request)
           if f.hasGeometry() and engine.intersects(f.geometry().constGet())]
    layer.selectByIds(ids, behavior)
    return len(ids)


class SelectByLineTool(QgsMapTool):
    def __init__(self, canvas, layer_getter):
        QgsMapTool.__init__(self, canvas)
        self._layer = layer_getter
        self._points = []
        self._band = None
        self.setCursor(Qt.CrossCursor)

    def _rubber_band(self):
        if self._band is None:
            self._band = QgsRubberBand(self.canvas(), QgsWkbTypes.LineGeometry)
            self._band.setColor(LINE_COLOR)
            self._band.setWidth(2)
        return self._band

    def _redraw(self, moving=None):
        band = self._rubber_band()
        points = list(self._points) + ([moving] if moving is not None else [])
        band.setToGeometry(QgsGeometry.fromPolylineXY(points) if len(points) > 1 else QgsGeometry(),
                           None)

    def reset(self):
        self._points = []
        if self._band is not None:
            self._band.reset(QgsWkbTypes.LineGeometry)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._points.append(QgsPointXY(event.mapPoint()))
            self._redraw()
        elif event.button() == Qt.RightButton:
            self.finish(event.modifiers())

    def canvasDoubleClickEvent(self, event):
        self.finish(event.modifiers())

    def canvasMoveEvent(self, event):
        if self._points:
            self._redraw(QgsPointXY(event.mapPoint()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reset()
            event.accept()
        elif event.key() == Qt.Key_Backspace and self._points:
            self._points.pop()
            self._redraw()
            event.accept()
        else:
            event.ignore()

    def finish(self, modifiers=Qt.NoModifier):
        points = self._points
        self.reset()
        layer = self._layer()
        if len(points) < 2 or not is_vector(layer):
            return None
        line = QgsGeometry.fromPolylineXY(points)
        crs = self.canvas().mapSettings().destinationCrs()
        return select_by_line(layer, line, crs, selection_behavior(modifiers))

    def deactivate(self):
        self.reset()
        QgsMapTool.deactivate(self)

    def close(self):
        """Gummiband entfernen (vor dem Löschen des Werkzeugs)."""
        self.reset()
        if self._band is not None:
            self.canvas().scene().removeItem(self._band)
            self._band = None
