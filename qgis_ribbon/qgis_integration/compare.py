"""Layer vergleichen: Wischen und Flimmern (Kontext-Tabs, Gruppe Vergleichen).

Beide blenden den verglichenen Layer (bei gewählter Gruppe: deren Layer)
aus, ohne Layerliste oder Projekt zu ändern. ``CompareOverlay`` legt dazu ein
Bild der Karte ohne diese Layer über die Karte:

- Wischen (``SwipeTool``): Bei gedrückter Maustaste deckt das Bild die Seite
  hinter der Wischkante ab; die Zugrichtung bestimmt, ob die Kante senkrecht
  oder waagerecht liegt. Beim Loslassen ist der Layer wieder ganz zu sehen.
- Flimmern: Das Bild wird im eingestellten Takt gezeigt und verborgen.

Das Bild wird nur gerendert, solange ein Vergleich läuft: beim Start, nach
jedem Neuzeichnen der Karte (Ausschnitt, Layer, Stil) und wenn ein anderer
Layer gewählt wird. Laufende Renderaufträge werden beim Entladen abgebrochen.
"""

from qgis.core import (QgsGroupLayer, QgsMapRendererParallelJob, QgsMapSettings, QgsPointXY, QgsRectangle,
                       QgsSettings)
from qgis.gui import QgsMapCanvasItem, QgsMapTool
from qgis.PyQt.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal

from .signals import SignalHub

FLICKER_KEY = "qgis_ribbon/flimmer_intervall"
FLICKER_DEFAULT = 500
FLICKER_RANGE = (100, 5000)    # Millisekunden
DRAG_THRESHOLD = 3             # Bildpunkte, ab denen die Zugrichtung feststeht


def layers_without(layers, hidden):
    """Layer der Karte ohne die IDs in ``hidden``.

    Steckt ein verglichener Layer in einer Gruppe, die als Gruppe dargestellt
    wird, kennt die Karte nur die Gruppenebene. Sie wird dann durch ihre
    übrigen Layer ersetzt (für das Vergleichsbild ohne Deckkraft und
    Mischmodus der Gruppe).
    """
    out = []
    for layer in layers:
        if layer.id() in hidden:
            continue
        if isinstance(layer, QgsGroupLayer):
            children = layer.childLayers()
            if any(child.id() in hidden for child in children):
                out.extend(layers_without(children, hidden))
                continue
        out.append(layer)
    return out


def clip_rect(width, height, orientation, position, hide_before):
    """Abgedeckter Bereich des Bildes (Bildpunkte) für eine Wischkante.

    ``orientation``: ``v`` (senkrechte Kante, Lage ``position`` = x) oder
    ``h`` (waagerechte Kante, ``position`` = y). ``hide_before``: Bereich vor
    der Kante (links bzw. oben) abdecken, sonst den danach.
    """
    if orientation == "v":
        x = max(0.0, min(float(width), position))
        return QRectF(0, 0, x, height) if hide_before else QRectF(x, 0, width - x, height)
    y = max(0.0, min(float(height), position))
    return QRectF(0, 0, width, y) if hide_before else QRectF(0, y, width, height - y)


class CompareOverlay(QgsMapCanvasItem):
    """Bild der Karte ohne die verglichenen Layer, ganz oder bis zur Wischkante."""

    Z_VALUE = -9    # über dem Kartenbild (-10), unter Gummibändern und Markierungen

    def __init__(self, canvas):
        QgsMapCanvasItem.__init__(self, canvas)
        self.setZValue(self.Z_VALUE)
        self.image = None
        self.edge = None        # (orientation, QgsPointXY auf der Kante, hide_before) oder None
        self.full = False       # ganzes Bild zeigen (Flimmern)

    def set_image(self, image, settings):
        """Gerendertes Bild an die Stelle legen, für die es gerendert wurde (wie die QGIS-Karte)."""
        m2p = settings.mapToPixel()
        top_left = m2p.toMapCoordinates(0, 0)
        res = m2p.mapUnitsPerPixel()
        size = settings.outputSize()
        self.image = image
        self.setRect(QgsRectangle(top_left.x(), top_left.y(), top_left.x() + size.width() * res,
                                  top_left.y() - size.height() * res), False)
        self.update()

    def _size(self):
        rect = self.boundingRect()
        return rect.width() - 2, rect.height() - 2

    def paint(self, painter, _option=None, _widget=None):
        # Python überschreibt beide C++-Varianten; Qt ruft die mit drei Argumenten auf.
        if self.image is None or not (self.full or self.edge):
            return
        width, height = self._size()
        painter.save()
        if not self.full:
            orientation, point, hide_before = self.edge
            local = self.mapFromScene(self.toCanvasCoordinates(point))
            position = local.x() if orientation == "v" else local.y()
            painter.setClipRect(clip_rect(width, height, orientation, position, hide_before))
        painter.drawImage(QRectF(0, 0, width, height), self.image)
        painter.restore()


class Comparison(QObject):
    """Gemeinsamer Zustand von Wischen und Flimmern (ein Bild für beide).

    ``targets()`` liefert die Layer, die verglichen (ausgeblendet) werden.
    ``changed`` meldet Start und Ende des Flimmerns an die Buttons.
    """

    changed = pyqtSignal()

    def __init__(self, canvas, targets, settings=None, layers=None):
        QObject.__init__(self)
        self.canvas = canvas
        self._targets = targets
        self._settings = settings
        self._layers = layers
        self.overlay = None
        self.swiping = False
        self.flickering = False
        self._jobs = []         # [(Auftrag, Karteneinstellungen)], festhalten bis fertig
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(self.interval())
        self._hub = SignalHub()
        self._hub.connect(canvas, "mapCanvasRefreshed", self._render)
        if layers is not None:
            layers.subscribe(self._on_target)

    # Einstellung
    def _store(self):
        return self._settings if self._settings is not None else QgsSettings()

    def interval(self):
        try:
            value = int(self._store().value(FLICKER_KEY, FLICKER_DEFAULT))
        except (TypeError, ValueError):
            value = FLICKER_DEFAULT
        return max(FLICKER_RANGE[0], min(FLICKER_RANGE[1], value))

    def set_interval(self, value):
        value = max(FLICKER_RANGE[0], min(FLICKER_RANGE[1], int(value)))
        self._store().setValue(FLICKER_KEY, value)
        self._timer.setInterval(value)

    # Ablauf
    def active(self):
        return self.swiping or self.flickering

    def _overlay(self):
        if self.overlay is None:
            self.overlay = CompareOverlay(self.canvas)
        return self.overlay

    def set_swipe(self, on):
        self.swiping = bool(on)
        if self.swiping:
            self.stop_flicker()
            self._render()
        else:
            self.set_edge(None)
            self._idle()

    def set_edge(self, edge):
        if self.overlay is not None:
            self.overlay.edge = edge
            self.overlay.update()

    def start_flicker(self):
        if not self._targets():
            return False
        self.flickering = True
        self._render()
        self._timer.start()
        self.changed.emit()
        return True

    def stop_flicker(self):
        if not self.flickering:
            return
        self.flickering = False
        self._timer.stop()
        if self.overlay is not None:
            self.overlay.full = False
            self.overlay.update()
        self._idle()
        self.changed.emit()

    def _tick(self):
        overlay = self._overlay()
        overlay.full = not overlay.full
        overlay.update()

    def _on_target(self, *_args):
        if not self.active():
            return
        if self.flickering and not self._targets():
            self.stop_flicker()
            return
        self._render()

    def _idle(self):
        """Kein Vergleich mehr: Bild freigeben, laufende Aufträge abbrechen."""
        if self.active():
            return
        for job, _settings in self._jobs:
            job.cancelWithoutBlocking()
        if self.overlay is not None:
            self.overlay.image = None
            self.overlay.update()

    # Rendern
    def _render(self, *_args):
        if not self.active():
            return
        hidden = {layer.id() for layer in self._targets()}
        settings = QgsMapSettings(self.canvas.mapSettings())
        settings.setLayers(layers_without(settings.layers(), hidden))
        for job, _settings in self._jobs:
            job.cancelWithoutBlocking()
        job = QgsMapRendererParallelJob(settings)
        job.finished.connect(self._rendered)
        self._jobs.append((job, settings))
        job.start()

    def _rendered(self):
        job = self.sender()
        index = next((i for i, (j, _s) in enumerate(self._jobs) if j is job), None)
        if index is None:
            return
        latest = index == len(self._jobs) - 1
        _job, settings = self._jobs.pop(index)
        if latest and self.active():
            self._overlay().set_image(job.renderedImage(), settings)

    def close_binding(self):
        self.swiping = False
        self.flickering = False
        self._timer.stop()
        if self._layers is not None:
            self._layers.unsubscribe(self._on_target)
        self._hub.disconnect_all()
        while self._jobs:
            job, _settings = self._jobs.pop()
            job.finished.disconnect(self._rendered)
            job.cancel()
        if self.overlay is not None:
            scene = self.overlay.scene()
            if scene is not None:
                scene.removeItem(self.overlay)
            self.overlay = None


class SwipeTool(QgsMapTool):
    """Kartenwerkzeug Wischen: Ziehen mit gedrückter linker Maustaste."""

    def __init__(self, canvas, comparison):
        QgsMapTool.__init__(self, canvas)
        self.comparison = comparison
        self._start = None
        self._orientation = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def activate(self):
        QgsMapTool.activate(self)
        self.comparison.set_swipe(True)

    def deactivate(self):
        self._start = None
        self.comparison.set_swipe(False)
        QgsMapTool.deactivate(self)

    def canvasPressEvent(self, event):  # noqa: N802 (Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.pixelPoint()
            self._orientation = None

    def canvasMoveEvent(self, event):  # noqa: N802 (Qt)
        if self._start is None:
            return
        pos = event.pixelPoint()
        dx, dy = pos.x() - self._start.x(), pos.y() - self._start.y()
        if self._orientation is None:
            if max(abs(dx), abs(dy)) < DRAG_THRESHOLD:
                return
            self._orientation = "v" if abs(dx) >= abs(dy) else "h"
        hide_before = dx > 0 if self._orientation == "v" else dy > 0
        self.comparison.set_edge((self._orientation, QgsPointXY(event.mapPoint()), hide_before))

    def canvasReleaseEvent(self, event):  # noqa: N802 (Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = None
            self.comparison.set_edge(None)

    def keyPressEvent(self, event):  # noqa: N802 (Qt)
        if event.key() == Qt.Key.Key_Escape:
            self._start = None
            self.comparison.set_edge(None)

    def close(self):
        self.comparison = _Inert()


class _Inert(object):
    """Ersatz nach dem Entladen: Aufrufe des Werkzeugs bewirken nichts mehr."""

    def __getattr__(self, _name):
        return lambda *_args: None
