"""Georeferenzieren in der Karte: Sitzung, Verwaltung, Vorschaubild und Kartenwerkzeuge.

Eine Sitzung (``GeorefSession``) arbeitet auf einem Arbeitslayer: einer VRT des Bildes im
Temp-Ordner, geladen als „<Name> (georeferencing)“ über den übrigen Layern. Das Bild selbst
bleibt unberührt; ein geladener Originallayer wird für die Dauer ausgeblendet und danach
wieder so gezeigt wie vorher. Jede Lage steht im Verlauf der Sitzung (Rückgängig, Wiederholen).

Die Lage ist eine Geotransformation im Bezugssystem der Karte (``core.georef``). Ein Bild, das
schon eine Georeferenz im Bezugssystem der Karte hat, beginnt dort; sonst wird es in den
Ausschnitt gelegt.

``GeorefManager`` hält höchstens eine Sitzung. Er lebt über einen Neuaufbau des Ribbons hinweg
(``install``/``uninstall`` aus ``plugin.py``) und bricht die Sitzung ab, wenn das Projekt
geleert wird, der Arbeitslayer verschwindet, die klassische Oberfläche kommt oder das Plugin
entladen wird. Beim Speichern des Projekts lässt er den Arbeitslayer aus der Datei weg.

Während eines Zuges mit einem Kartenwerkzeug zeigt ``GeorefPreview`` ein Bild des Layers an
der neuen Stelle; die VRT wird erst beim Loslassen geschrieben (Zeichnen eines großen Bildes dauert zu lange).
"""

import os
import shutil
import tempfile
from collections import namedtuple

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMapRendererCustomPainterJob,
                       QgsMapSettings, QgsPointLocator, QgsPointXY, QgsProject, QgsRasterLayer, QgsRectangle)
from qgis.gui import QgsMapCanvasItem, QgsMapTool, QgsSnapIndicator
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPen, QTransform

from ..core import georef
from ..core.i18n import tr
from . import georef_ops
from .signals import SignalHub

LOG_TAG = "QGIS Ribbon"
PROPERTY = "qgis_ribbon/georef"     # Kennzeichen des Arbeitslayers
TEMP_PREFIX = "qgis_ribbon_georef_"
VRT_NAME = "work.vrt"
VRT_STEP = "work_%d.vrt"            # je Schritt eine neue Datei (georef_ops.show_geotransform)
GCP_STEP = "gcps_%d.vrt"            # höhere Ordnungen: VRT mit Passpunkten ...
WARP_STEP = "warped_%d.vrt"         # ... und entzerrte VRT
DROPPED_TAG = "qgis-ribbon-dropped"
ROTATE_STEP = 15.0                  # Grad, Drehen mit Strg

State = namedtuple("State", "gt points method")


def _same_crs(wkt, crs):
    if not wkt:
        return True     # Bild ohne Bezugssystem: Koordinaten gelten als die der Karte
    own = QgsCoordinateReferenceSystem.fromWkt(wkt)
    return not own.isValid() or own == crs


def canvas_extent(canvas):
    rect = canvas.extent()
    return rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()


def source_path(layer):
    """Datei eines Rasterlayers (Provider gdal), sonst None."""
    if not isinstance(layer, QgsRasterLayer) or layer.providerType() != "gdal":
        return None
    from qgis.core import QgsProviderRegistry
    path = QgsProviderRegistry.instance().decodeUri("gdal", layer.source()).get("path") or layer.source()
    return path if os.path.isfile(path) else None


def same_file(path, other):
    return bool(path and other) and os.path.normcase(os.path.abspath(path)) == os.path.normcase(
        os.path.abspath(other))


def release_file(path):
    """Lesezugriffe von QGIS auf eine Bilddatei schließen, bevor ihre Begleitdatei geschrieben wird.

    GDAL schreibt beim Schließen die Begleitdatei (``.aux.xml``) mit dem Stand beim Öffnen zurück
    (etwa nach Statistiken) und überschriebe so eine eben gespeicherte Georeferenz.
    """
    for layer in QgsProject.instance().mapLayers().values():
        if same_file(source_path(layer), path):
            layer.dataProvider().reloadData()


def is_work_layer(layer):
    return layer is not None and not sip.isdeleted(layer) and bool(layer.customProperty(PROPERTY, False))


class GeorefSession(QObject):
    """Eine laufende Georeferenzierung (Arbeitslayer, Temp-Dateien, Verlauf)."""

    changed = pyqtSignal()

    def __init__(self, iface, source, original=None):
        QObject.__init__(self)
        self.iface = iface
        self.source = source
        self.width, self.height, own_gt, wkt = georef_ops.image_size(source)
        self.source_gt = own_gt     # Quellkoordinaten der Punktdatei wie im QGIS-Georeferenzierer
        canvas = iface.mapCanvas()
        crs = canvas.mapSettings().destinationCrs()
        self.crs_wkt = crs.toWkt()
        if own_gt is not None and _same_crs(wkt, crs):
            start = tuple(own_gt)
        else:
            start = georef.fit_to_extent(self.width, self.height, canvas_extent(canvas))
        self.dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
        self.vrt = os.path.join(self.dir, VRT_NAME)
        self._serial = 0
        self.layer = None
        try:
            georef_ops.create_vrt(source, self.vrt, start, self.crs_wkt)
            name = os.path.splitext(os.path.basename(source))[0]
            layer = QgsRasterLayer(self.vrt, tr("%s (georeferencing)") % name, "gdal")
            if not layer.isValid():
                raise ValueError(tr("The image cannot be read: %s") % source)
        except Exception:
            shutil.rmtree(self.dir, ignore_errors=True)
            raise
        layer.setCustomProperty(PROPERTY, True)
        project = QgsProject.instance()
        project.addMapLayer(layer, False)
        project.layerTreeRoot().insertLayer(0, layer)
        self.layer = layer
        self.layer_id = layer.id()
        # Originallayer für die Dauer ausblenden (und sich merken, ob er zu sehen war)
        self.original_id = original.id() if original is not None else None
        self._original_visible = None
        node = self._node(self.original_id)
        if node is not None:
            self._original_visible = node.itemVisibilityChecked()
            node.setItemVisibilityChecked(False)
        self.history = georef.History(State(start, (), georef.AUTO))
        self.ending = False
        self.highlight = None       # Zeile des hervorgehobenen Passpunkts
        self.problem = None         # Grund, warum die letzte Rechnung nicht ging
        self._warped = []           # Dateien der angezeigten entzerrten VRT
        self._cache_state = self._res_state = None
        self._cache_transformer = self._res = None

    # Zustand
    @property
    def gt(self):
        return self.history.current.gt

    def center(self):
        return georef.center(self.gt, self.width, self.height)

    def _node(self, layer_id):
        if not layer_id:
            return None
        return QgsProject.instance().layerTreeRoot().findLayer(layer_id)

    def alive(self):
        return self.layer is not None and not sip.isdeleted(self.layer)

    # Lage ändern
    def apply(self, gt):
        """Neue Lage übernehmen (Verlauf) und anzeigen. False, wenn sie gleich bleibt."""
        state = self.history.current
        if not self.history.push(State(tuple(gt), state.points, state.method)):
            return False
        self.show()
        return True

    def undo(self):
        if self.history.can_undo():
            self.history.undo()
            self.show()

    def redo(self):
        if self.history.can_redo():
            self.history.redo()
            self.show()

    def show(self):
        """Aktuellen Zustand anzeigen: über die Geotransformation oder eine entzerrte VRT (höhere Ordnungen)."""
        if self.alive():
            self._serial += 1
            old = list(self._warped)
            used = self.used_method()
            if self.linear():
                new = os.path.join(self.dir, VRT_STEP % self._serial)
                self.vrt = georef_ops.show_geotransform(self.layer, self.vrt, self.gt, new)
                self._warped = []
            else:
                gcp = os.path.join(self.dir, GCP_STEP % self._serial)
                warped = os.path.join(self.dir, WARP_STEP % self._serial)
                georef_ops.create_warped_vrt(self.source, gcp, warped, self.points, used, self.crs_wkt,
                                             size=(self.width, self.height))
                georef_ops.reload_layer(self.layer, warped)
                self._warped = [gcp, warped]
            georef_ops.remove_files(old)
        self.changed.emit()

    # -- Passpunkte und Transformation ---------------------------------------------

    @property
    def points(self):
        return self.history.current.points

    @property
    def method(self):
        return self.history.current.method

    def active_count(self):
        return len(georef.active(self.points))

    def used_method(self):
        """Tatsächliche Transformation (``auto`` aufgelöst); ohne genug Punkte die Lage von Hand (``None``)."""
        count = self.active_count()
        if count == 0 or not georef.available(self.method, count)[0]:
            return None
        return georef.resolve(self.method, count)

    def linear(self):
        """Wird die Lage über eine Geotransformation gezeigt (von Hand, Verschiebung, Helmert, affin)?"""
        return self.used_method() in (None,) + georef.LINEAR

    def _transformer(self):
        """Transformation höherer Ordnung des aktuellen Zustands (zwischengespeichert)."""
        state = self.history.current
        if self._cache_state is not state:
            self._cache_state = state
            self._cache_transformer = None
            used = self.used_method()
            if used is not None and used not in georef.LINEAR:
                self._cache_transformer = georef_ops.Transformer(used, self.points)
        return self._cache_transformer

    def map_point(self, col, row):
        """Bildpunkt -> Kartenpunkt in der angezeigten Lage."""
        t = self._transformer() if not self.linear() else None
        if t is not None:
            return t.forward(col, row)
        return georef.apply(self.gt, col, row)

    def image_pixel(self, x, y):
        """Kartenpunkt -> Bildpunkt in der angezeigten Lage (``ValueError``, wenn nicht umkehrbar)."""
        t = self._transformer() if not self.linear() else None
        if t is not None:
            return t.inverse(x, y)
        return georef.to_pixel(self.gt, x, y)

    @property
    def residuals(self):
        """Restfehler je Passpunkt in der aktuellen Transformation, sonst None."""
        state = self.history.current
        if self._res_state is not state:
            self._res_state = state
            used = self.used_method()
            self._res = None
            if used is not None:
                try:
                    self._res = georef_ops.residuals(self.points, used, self.gt)[0]
                except ValueError:
                    self._res = None
        return self._res

    def mean_error(self):
        res = self.residuals
        return georef.mean_error(self.points, res, pixels=True) if res is not None else None

    def _set_points(self, points, method=None):
        """Neue Passpunkte (oder Transformation) übernehmen: neu rechnen, Verlauf, anzeigen."""
        method = self.method if method is None else method
        points = tuple(points)
        gt = self.gt
        count = len(georef.active(points))
        if count and georef.available(method, count)[0] and georef.resolve(method, count) in georef.LINEAR:
            try:
                gt = tuple(georef.fit(points, method, self.gt))
            except ValueError as exc:
                self.problem = str(exc)
        if not self.history.push(State(gt, points, method)):
            return False
        self.show()
        return True

    def add_point(self, col, row, x, y):
        return self._set_points(self.points + (georef.ControlPoint(col, row, x, y, True),))

    def remove_points(self, rows):
        rows = set(rows)
        return self._set_points(p for i, p in enumerate(self.points) if i not in rows)

    def set_point_active(self, row, on):
        points = [p.copy() for p in self.points]
        if 0 <= row < len(points):
            points[row].active = bool(on)
        return self._set_points(points)

    def set_method(self, method):
        return self._set_points(self.points, method)

    def replace_points(self, points):
        return self._set_points(points)

    def set_highlight(self, row):
        if row != self.highlight:
            self.highlight = row
            self.changed.emit()

    # Punktdatei (Format des QGIS-Georeferenzierers)
    def points_text(self):
        return georef.write_points(self.points, self.crs_wkt, self.source_gt, self.residuals)

    def save_points(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.points_text())

    def load_points(self, path):
        """Passpunkte aus einer Punktdatei (ersetzt die bisherigen; Ziele ins Bezugssystem der Karte)."""
        with open(path, encoding="utf-8") as fh:
            points, wkt = georef.read_points(fh.read(), self.source_gt)
        crs = QgsCoordinateReferenceSystem.fromWkt(wkt) if wkt else None
        target = QgsCoordinateReferenceSystem.fromWkt(self.crs_wkt)
        if crs is not None and crs.isValid() and crs != target:
            transform = QgsCoordinateTransform(crs, target, QgsProject.instance())
            for p in points:
                q = transform.transform(QgsPointXY(p.x, p.y))
                p.x, p.y = q.x(), q.y()
        return self.replace_points(points)

    # Anzeige
    def image_visible(self):
        node = self._node(self.layer_id)
        return node is not None and node.itemVisibilityChecked()

    def set_image_visible(self, on):
        node = self._node(self.layer_id)
        if node is not None:
            node.setItemVisibilityChecked(bool(on))
        self.changed.emit()

    # Ende
    def forget_original(self, layer_ids):
        if self.original_id in layer_ids:
            self.original_id = None

    def end(self):
        """Arbeitslayer und Temp-Dateien entfernen, Sichtbarkeit des Originals zurück.

        Gibt die Dateien zurück, die nicht entfernt werden konnten.
        """
        if self.ending:
            return []
        self.ending = True
        project = QgsProject.instance()
        if project.mapLayer(self.layer_id) is not None:
            project.removeMapLayer(self.layer_id)
        self.layer = None
        node = self._node(self.original_id)
        if node is not None and self._original_visible is not None:
            node.setItemVisibilityChecked(self._original_visible)
        shutil.rmtree(self.dir, ignore_errors=True)
        return [self.dir] if os.path.exists(self.dir) else []


class GeorefManager(QObject):
    """Höchstens eine Sitzung; Projekt-Signale über einen eigenen Hub (beim Entladen getrennt)."""

    changed = pyqtSignal()      # Sitzung begonnen, geändert oder beendet
    started = pyqtSignal()

    def __init__(self, iface):
        QObject.__init__(self)
        self.iface = iface
        self.session = None
        self.markers = None         # Passpunkte in der Karte (GcpMarkers), solange eine Sitzung läuft
        self.tasks = []             # laufende Entzerrungen (festhalten bis fertig)
        self.hub = SignalHub()
        project = QgsProject.instance()
        self.hub.connect(project, "aboutToBeCleared", self.cancel)
        self.hub.connect(project, "layersWillBeRemoved", self._on_removed)
        self.hub.connect(project, "layersRemoved", self._on_layers_gone)
        self.hub.connect(project, "writeMapLayer", self._drop_layer)
        self.hub.connect(project, "writeProject", self._drop_tree)

    def active(self):
        return self.session is not None

    def start(self, source, original=None):
        """Neue Sitzung für die Bilddatei ``source`` (eine laufende wird vorher abgebrochen)."""
        self.cancel()
        session = GeorefSession(self.iface, source, original)
        self.session = session
        session.changed.connect(self.changed)
        self.markers = GcpMarkers(self.iface.mapCanvas(), self)
        session.changed.connect(self.markers.update)
        if hasattr(self.iface, "setActiveLayer"):
            self.iface.setActiveLayer(session.layer)
        self.started.emit()
        self.changed.emit()
        return session

    def cancel(self):
        """Sitzung abbrechen: nichts bleibt zurück."""
        session, self.session = self.session, None
        if session is None:
            return
        left = session.end()
        session.changed.disconnect(self.changed)
        if self.markers is not None:
            session.changed.disconnect(self.markers.update)
            scene = self.markers.scene()
            if scene is not None:
                scene.removeItem(self.markers)
            self.markers = None
        session.deleteLater()
        if left:
            self.iface.messageBar().pushMessage(
                LOG_TAG, tr("Temporary files of the georeferencing could not be removed: %s") % ", ".join(left),
                level=Qgis.MessageLevel.Warning)
        self.changed.emit()

    def close(self):
        self.cancel()
        for task in list(self.tasks):
            task.done = lambda *_args: None     # Plugin weg: Ergebnis nicht mehr laden
            task.cancel()
        self.tasks = []
        self.hub.disconnect_all()

    def message(self, text, level=Qgis.MessageLevel.Info, duration=6):
        self.iface.messageBar().pushMessage(LOG_TAG, text, level=level, duration=duration)

    # Abschließen
    def finish(self, result_path, replace=False):
        """Sitzung beenden und das Ergebnis zeigen.

        Ist ``result_path`` das Bild eines geladenen Originals (Georeferenz gespeichert), liest dieses
        seine Datei neu. Sonst kommt das Ergebnis als neuer Layer dazu; mit ``replace`` an die Stelle
        des Originals, das dann entfällt. Gibt den Layer mit dem Ergebnis zurück.
        """
        session = self.session
        project = QgsProject.instance()
        original = project.mapLayer(session.original_id) if session is not None and session.original_id else None
        self.cancel()
        if original is not None and same_file(result_path, source_path(original)):
            georef_ops.reload_layer(original)
            original.triggerRepaint()
            return original
        layer = QgsRasterLayer(result_path, os.path.splitext(os.path.basename(result_path))[0], "gdal")
        if not layer.isValid():
            self.message(tr("The result cannot be loaded: %s") % result_path, Qgis.MessageLevel.Warning)
            return None
        root = project.layerTreeRoot()
        node = root.findLayer(original.id()) if original is not None and replace else None
        project.addMapLayer(layer, False)
        if node is not None:
            parent = node.parent()
            parent.insertLayer(parent.children().index(node), layer)
            project.removeMapLayer(original.id())
        else:
            root.insertLayer(0, layer)
        return layer

    def warp(self, out_path, resampling="near", compression="LZW", dst_wkt=None, replace=False,
             background=True, done=None):
        """Bild in der aktuellen Lage als GeoTIFF entzerren; danach endet die Sitzung, das Ergebnis wird geladen.

        Läuft als Hintergrundaufgabe von QGIS (``background``) oder sofort (Tests). ``done(Layer oder None)``.
        """
        session = self.session
        if session is None:
            return None
        work = tempfile.mkdtemp(prefix=TEMP_PREFIX + "warp_")
        arguments = {"source": session.source, "out_path": out_path, "work_dir": work,
                     "points": tuple(session.points), "method": session.used_method(), "gt": session.gt,
                     "crs_wkt": session.crs_wkt, "dst_wkt": dst_wkt, "resampling": resampling,
                     "compression": compression}

        def finished(ok, error, task=None):
            shutil.rmtree(work, ignore_errors=True)
            if task in self.tasks:
                self.tasks.remove(task)
            layer = None
            if ok:
                layer = self.finish(out_path, replace) if self.session is session else self._load(out_path)
                self.message(tr("Image warped: %s") % out_path, Qgis.MessageLevel.Success)
            else:
                self.message(tr("Warping failed: %s") % (error or tr("cancelled")), Qgis.MessageLevel.Warning)
            if done is not None:
                done(layer)
            return layer

        if not background:
            try:
                georef_ops.warp_to_file(**arguments)
            except (OSError, ValueError, RuntimeError) as exc:
                return finished(False, str(exc))
            return finished(True, None)
        from qgis.core import QgsApplication
        task = georef_ops.WarpTask(tr("Warp %s") % os.path.basename(session.source), arguments, None)
        task.done = lambda ok, error: finished(ok, error, task)
        self.tasks.append(task)
        QgsApplication.taskManager().addTask(task)
        return task

    def _load(self, path):
        layer = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0], "gdal")
        if not layer.isValid():
            return None
        QgsProject.instance().addMapLayer(layer)
        return layer

    # Projekt
    def _on_removed(self, layer_ids):
        session = self.session
        if session is None or session.ending:
            return
        if session.layer_id not in layer_ids:
            session.forget_original(layer_ids)

    def _on_layers_gone(self, layer_ids):
        """Arbeitslayer entfernt: Sitzung erst jetzt beenden, nicht schon in ``layersWillBeRemoved``.

        Dort sähe ``end()`` den Layer noch im Projekt und entfernte ihn ein zweites Mal,
        mitten in seiner Entfernung (unter Linux ein Absturz). Jetzt ist er gelöscht und
        seine Dateien sind frei.
        """
        session = self.session
        if session is not None and not session.ending and session.layer_id in layer_ids:
            self.cancel()

    def _drop_layer(self, layer, element, _doc):
        # Das Element hängt QGIS erst nach diesem Signal an: leeren und unkenntlich machen
        if self.session is None or layer is None or layer.id() != self.session.layer_id:
            return
        while not element.firstChild().isNull():
            element.removeChild(element.firstChild())
        attrs = element.attributes()
        for name in [attrs.item(i).nodeName() for i in range(attrs.count())]:
            element.removeAttribute(name)
        element.setTagName(DROPPED_TAG)

    def _drop_tree(self, doc):
        if self.session is None:
            return
        drop_layer_refs(doc, self.session.layer_id)
        self.iface.messageBar().pushMessage(
            LOG_TAG, tr("A georeferencing session is running. Its work layer is not saved with the project."),
            level=Qgis.MessageLevel.Info, duration=8)


def drop_layer_refs(doc, layer_id):
    """Einträge des Layers (Layerbaum, Legende, Reihenfolge) aus dem Projekt-DOM entfernen."""
    doomed = []
    stack = [doc.documentElement()]
    while stack:
        node = stack.pop()
        el = node.toElement()
        if not el.isNull():
            if layer_id in (el.attribute("id"), el.attribute("layerid"), el.attribute("layer")) \
                    or el.tagName() == DROPPED_TAG:
                doomed.append(el)
                continue
            if el.tagName() == "item" and el.text() == layer_id:
                doomed.append(el)
                continue
        child = node.firstChild()
        while not child.isNull():
            stack.append(child)
            child = child.nextSibling()
    for el in doomed:
        el.parentNode().removeChild(el)
    return len(doomed)


# -- Vorschau und Kartenwerkzeuge --------------------------------------------

def screen_transform(m2p, change):
    """``QTransform`` in Bildschirmpunkten für die Änderung ``change`` (Geotransformation in der Karte).

    Über drei Punkte, damit auch eine gedrehte Karte stimmt.
    """
    size = 1000.0
    pts = []
    for sx, sy in ((0.0, 0.0), (size, 0.0), (0.0, size)):
        m = m2p.toMapCoordinates(int(sx), int(sy))
        x, y = georef.apply(change, m.x(), m.y())
        p = m2p.transform(QgsPointXY(x, y))
        pts.append((p.x(), p.y()))
    (x0, y0), (x1, y1), (x2, y2) = pts
    return QTransform((x1 - x0) / size, (y1 - y0) / size, (x2 - x0) / size, (y2 - y0) / size, x0, y0)


def layer_image(canvas, layer):
    """Bild des Layers im aktuellen Ausschnitt: aus dem Zwischenspeicher der Karte oder neu gezeichnet."""
    cache = canvas.cache() if hasattr(canvas, "cache") else None
    if cache is not None and cache.hasCacheImage(layer.id()):
        image = cache.cacheImage(layer.id())
        if not image.isNull():
            return image
    settings = QgsMapSettings(canvas.mapSettings())
    settings.setLayers([layer])
    size = settings.deviceOutputSize() if hasattr(settings, "deviceOutputSize") else settings.outputSize()
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(settings.devicePixelRatio())
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    job = QgsMapRendererCustomPainterJob(settings, painter)
    job.start()
    job.waitForFinished()
    painter.end()
    return image


class GeorefPreview(QgsMapCanvasItem):
    """Bild des Arbeitslayers an der Lage während eines Zuges (der Layer selbst ist so lange unsichtbar)."""

    Z_VALUE = -9

    def __init__(self, canvas):
        QgsMapCanvasItem.__init__(self, canvas)
        self.setZValue(self.Z_VALUE)
        self.canvas = canvas
        self.image = None
        self.opacity = 1.0
        self.transform = QTransform()

    def begin(self, image, opacity):
        settings = self.canvas.mapSettings()
        m2p = settings.mapToPixel()
        top_left = m2p.toMapCoordinates(0, 0)
        res = m2p.mapUnitsPerPixel()
        size = settings.outputSize()
        self.image = image
        self.opacity = opacity
        self.transform = QTransform()
        self.setRect(QgsRectangle(top_left.x(), top_left.y(), top_left.x() + size.width() * res,
                                  top_left.y() - size.height() * res), False)
        self.show()
        self.update()

    def set_transform(self, transform):
        self.transform = transform
        self.update()

    def end(self):
        self.image = None
        self.hide()
        self.update()

    def paint(self, painter, _option=None, _widget=None):
        if self.image is None:
            return
        rect = self.boundingRect()
        painter.save()
        painter.setOpacity(self.opacity)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setTransform(self.transform, True)
        painter.drawImage(QRectF(0, 0, rect.width() - 2, rect.height() - 2), self.image)
        painter.restore()


MOVE, SCALE, ROTATE = "move", "scale", "rotate"
_CURSORS = {MOVE: Qt.CursorShape.SizeAllCursor, SCALE: Qt.CursorShape.SizeFDiagCursor,
            ROTATE: Qt.CursorShape.CrossCursor}


def dragged(mode, gt, size, start, current, modifiers):
    """Lage nach einem Zug von ``start`` nach ``current`` (Kartenkoordinaten).

    Skalieren: vom Mittelpunkt weg, Seitenverhältnis fest, mit Umschalt je Bildachse frei.
    Drehen: um den Mittelpunkt, mit Strg in Schritten von 15°.
    """
    width, height = size
    if mode == MOVE:
        return georef.translate(gt, current[0] - start[0], current[1] - start[1])
    cx, cy = georef.center(gt, width, height)
    if mode == SCALE:
        free = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        f1, f2 = georef.drag_scale((width / 2.0, height / 2.0), georef.to_pixel(gt, *start),
                                   georef.to_pixel(gt, *current), keep_aspect=not free)
        return georef.scale_image(gt, f1, f2, cx, cy)
    step = ROTATE_STEP if modifiers & Qt.KeyboardModifier.ControlModifier else None
    return georef.rotate(gt, georef.drag_angle((cx, cy), start, current, step), cx, cy)


class GeorefTool(QgsMapTool):
    """Verschieben, Skalieren oder Drehen des Arbeitslayers durch Ziehen; Esc bricht den Zug ab."""

    def __init__(self, canvas, manager, mode):
        QgsMapTool.__init__(self, canvas)
        self.manager = manager
        self.mode = mode
        self.preview = None
        self._drag = None       # (Sitzung, Lage vorher, Start, Deckkraft vorher)
        self.setCursor(_CURSORS[mode])

    def _session(self):
        session = self.manager.session
        return session if session is not None and session.alive() else None

    def canvasPressEvent(self, event):
        session = self._session()
        if event.button() != Qt.MouseButton.LeftButton or session is None:
            return
        layer = session.layer
        canvas = self.canvas()
        image = layer_image(canvas, layer)
        renderer = layer.renderer()
        opacity = renderer.opacity() if renderer is not None else 1.0
        if self.preview is None:
            self.preview = GeorefPreview(canvas)
        self.preview.begin(image, opacity)
        if renderer is not None:
            renderer.setOpacity(0.0)
            layer.triggerRepaint()
        start = event.mapPoint()
        self._drag = (session, session.gt, (start.x(), start.y()), opacity)
        # Bei gedrückter Maustaste gibt die Karte Tasten nur über ihr Signal weiter (nicht an das Werkzeug)
        canvas.keyPressed.connect(self._on_key)

    def _current(self, event):
        session, gt, start, _opacity = self._drag
        point = event.mapPoint()
        return dragged(self.mode, gt, (session.width, session.height), start, (point.x(), point.y()),
                       event.modifiers())

    def canvasMoveEvent(self, event):
        if self._drag is None:
            return
        try:
            new = self._current(event)
        except ValueError:
            return
        change = georef.change(self._drag[1], new)
        self.preview.set_transform(screen_transform(self.canvas().mapSettings().mapToPixel(), change))

    def canvasReleaseEvent(self, event):
        if self._drag is None or event.button() != Qt.MouseButton.LeftButton:
            return
        try:
            new = self._current(event)
        except ValueError:
            new = None
        session = self._drag[0]
        self._finish()
        if new is not None and session is self.manager.session:
            session.apply(new)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self._finish()
            event.accept()
        else:
            event.ignore()

    def _on_key(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._finish()

    def _finish(self):
        """Zug beenden: Vorschau weg, Deckkraft des Layers zurück."""
        if self._drag is None:
            return
        session, _gt, _start, opacity = self._drag
        self._drag = None
        self.canvas().keyPressed.disconnect(self._on_key)
        if self.preview is not None:
            self.preview.end()
        if session.alive() and session.layer.renderer() is not None:
            session.layer.renderer().setOpacity(opacity)
            session.layer.triggerRepaint()

    def dragging(self):
        return self._drag is not None

    def deactivate(self):
        self._finish()
        QgsMapTool.deactivate(self)

    def close(self):
        """Vorschau entfernen (vor dem Löschen des Werkzeugs)."""
        self._finish()
        if self.preview is not None:
            self.canvas().scene().removeItem(self.preview)
            self.preview = None


# -- Passpunkte in der Karte ----------------------------------------------------------

IMAGE_COLOR = QColor(30, 110, 230)
TARGET_COLOR = QColor(220, 40, 40)
LINE_COLOR = QColor(255, 140, 0)


class GcpMarkers(QgsMapCanvasItem):
    """Passpunkte der Sitzung: Bildpunkt (Kreuz), Ziel (Kreis), Linie dazwischen, Nummer.

    Deckt den ganzen Kartenausschnitt ab und zeichnet bei jeder Änderung neu.
    """

    Z_VALUE = 50

    def __init__(self, canvas, manager):
        QgsMapCanvasItem.__init__(self, canvas)
        self.setZValue(self.Z_VALUE)
        self.canvas = canvas
        self.manager = manager
        self.pending = None         # Bildpunkt (Spalte, Zeile) eines halben Passpunkts
        self.cursor = None          # Kartenpunkt unter der Maus beim halben Passpunkt
        self.updatePosition()

    def updatePosition(self):  # noqa: N802 (QGIS ruft sie bei jeder Änderung des Ausschnitts)
        self.setRect(self.canvas.extent(), False)

    def _local(self, x, y):
        return self.mapFromScene(self.toCanvasCoordinates(QgsPointXY(x, y)))

    def paint(self, painter, _option=None, _widget=None):
        session = self.manager.session
        if session is None or not session.alive():
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        for i, p in enumerate(session.points):
            try:
                ix, iy = session.map_point(p.col, p.row)
            except ValueError:
                continue
            image, target = self._local(ix, iy), self._local(p.x, p.y)
            strong = i == session.highlight
            alpha = 255 if p.active else 120
            pen = QPen(QColor(LINE_COLOR.red(), LINE_COLOR.green(), LINE_COLOR.blue(), alpha), 2 if strong else 1)
            painter.setPen(pen)
            painter.drawLine(image, target)
            size = 7 if strong else 5
            painter.setPen(QPen(QColor(IMAGE_COLOR.red(), IMAGE_COLOR.green(), IMAGE_COLOR.blue(), alpha), 2))
            painter.drawLine(QPointF(image.x() - size, image.y()), QPointF(image.x() + size, image.y()))
            painter.drawLine(QPointF(image.x(), image.y() - size), QPointF(image.x(), image.y() + size))
            painter.setPen(QPen(QColor(TARGET_COLOR.red(), TARGET_COLOR.green(), TARGET_COLOR.blue(), alpha), 2))
            painter.drawEllipse(target, size, size)
            painter.drawText(QPointF(target.x() + size + 2, target.y() - size - 2), str(i + 1))
        if self.pending is not None:
            try:
                ix, iy = session.map_point(*self.pending)
            except ValueError:
                ix = iy = None
            if ix is not None:
                image = self._local(ix, iy)
                painter.setPen(QPen(IMAGE_COLOR, 2))
                painter.drawLine(QPointF(image.x() - 7, image.y()), QPointF(image.x() + 7, image.y()))
                painter.drawLine(QPointF(image.x(), image.y() - 7), QPointF(image.x(), image.y() + 7))
                if self.cursor is not None:
                    painter.setPen(QPen(LINE_COLOR, 1, Qt.PenStyle.DashLine))
                    painter.drawLine(image, self._local(*self.cursor))
        painter.restore()


class GcpTool(QgsMapTool):
    """Passpunkt hinzufügen: erster Klick auf das Bild, zweiter auf das Ziel (mit Einrasten).

    Rechtsklick oder Esc bricht einen halben Punkt ab.
    """

    def __init__(self, canvas, manager):
        QgsMapTool.__init__(self, canvas)
        self.manager = manager
        self.markers = None
        self.indicator = QgsSnapIndicator(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _session(self):
        session = self.manager.session
        return session if session is not None and session.alive() else None

    def _markers(self):
        return self.manager.markers

    def pending(self):
        markers = self._markers()
        return markers.pending if markers is not None else None

    def canvasMoveEvent(self, event):
        markers = self._markers()
        if markers is None or markers.pending is None:
            self.indicator.setMatch(QgsPointLocator.Match())
            return
        point = event.snapPoint()
        self.indicator.setMatch(event.mapPointMatch())
        markers.cursor = (point.x(), point.y())
        markers.update()

    def canvasPressEvent(self, event):
        session = self._session()
        markers = self._markers()
        if session is None or markers is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if markers.pending is None:
            point = event.mapPoint()
            try:
                col, row = session.image_pixel(point.x(), point.y())
            except ValueError:
                return
            if not (0 <= col <= session.width and 0 <= row <= session.height):
                self.manager.message(tr("Click on the image first, then on the target in the map."))
                return
            markers.pending = (col, row)
            markers.cursor = (point.x(), point.y())
            markers.update()
            return
        target = event.snapPoint()
        col, row = markers.pending
        markers.pending = markers.cursor = None
        self.indicator.setMatch(QgsPointLocator.Match())
        session.add_point(col, row, target.x(), target.y())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.pending() is not None:
            self.cancel()
            event.accept()
        else:
            event.ignore()

    def cancel(self):
        markers = self._markers()
        if markers is not None:
            markers.pending = markers.cursor = None
            markers.update()
        self.indicator.setMatch(QgsPointLocator.Match())

    def deactivate(self):
        self.cancel()
        QgsMapTool.deactivate(self)

    def close(self):
        self.cancel()


# -- Verwaltung über den Neuaufbau des Ribbons hinweg ------------------------

_MANAGER = None


def install(iface):
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = GeorefManager(iface)
    return _MANAGER


def uninstall():
    """Sitzung abbrechen und Projekt-Signale trennen (klassische Oberfläche, Entladen)."""
    global _MANAGER
    if _MANAGER is not None:
        _MANAGER.close()
        _MANAGER.deleteLater()
        _MANAGER = None


def manager():
    return _MANAGER


def active():
    return _MANAGER is not None and _MANAGER.active()
