"""Georeferenzierung mit QGIS und GDAL: höhere Transformationen, Restfehler, virtuelle Dateien (VRT).

Die Rechnung für Verschiebung, Helmert und affin steht in ``core/georef.py``. Hier:

- Transformationen höherer Ordnung (Polynom 2 und 3, Thin Plate Spline, projektiv) über
  ``QgsGcpTransformerInterface``. Quellpunkte sind (Spalte, -Zeile) wie im QGIS-Georeferenzierer
  bei einem Bild ohne Georeferenz; ``invertYAxis`` bleibt aus (geprüft unter 3.44 und 4).
- VRT des Arbeitslayers: einmal aus dem Original mit ``gdal.Translate`` erzeugt; danach schreibt
  ``show_geotransform`` eine Kopie mit neuem Element ``GeoTransform`` (wenige Millisekunden).
- Entzerrte VRT mit Passpunkten (``gdal.Warp``) für Transformationen ohne Geotransformation.
- Abschließen: ``warp_to_file`` (GeoTIFF, auch als Hintergrundaufgabe) und ``save_georeference``
  (Worldfile und ``.aux.xml`` neben dem Bild, das Bild selbst bleibt unverändert).
"""

import os
import re

from qgis.analysis import QgsGcpTransformerInterface
from qgis.core import QgsDataProvider, QgsPointXY, QgsProject, QgsTask

from ..core import georef

_METHODS = {
    georef.HELMERT: "Helmert",
    georef.AFFINE: "PolynomialOrder1",
    georef.POLY2: "PolynomialOrder2",
    georef.POLY3: "PolynomialOrder3",
    georef.TPS: "ThinPlateSpline",
    georef.PROJECTIVE: "Projective",
}


def qgis_method(method):
    """``QgsGcpTransformerInterface.TransformMethod`` zu einem Schlüssel aus ``core.georef``."""
    return getattr(QgsGcpTransformerInterface.TransformMethod, _METHODS[method])


def minimum_points(method):
    """Kleinste Zahl der Passpunkte laut QGIS (für Verschiebung 1)."""
    if method == georef.TRANSLATION:
        return 1
    return QgsGcpTransformerInterface.create(qgis_method(method)).minimumGcpCount()


class Transformer(object):
    """Transformation aus Passpunkten über QGIS: ``forward``/``inverse`` wie in ``core.georef.residuals``."""

    def __init__(self, method, points):
        pts = georef.active(points)
        self.method = method
        self._t = QgsGcpTransformerInterface.create(qgis_method(method))
        if len(pts) < self._t.minimumGcpCount():
            raise ValueError("%s needs %d control points" % (method, self._t.minimumGcpCount()))
        src = [QgsPointXY(p.col, -p.row) for p in pts]
        dst = [QgsPointXY(p.x, p.y) for p in pts]
        if not self._t.updateParametersFromGcps(src, dst, False):
            raise ValueError("%s could not be computed from these control points" % method)

    def forward(self, col, row):
        ok, x, y = self._t.transform(col, -row, False)
        if not ok:
            raise ValueError("transformation failed")
        return x, y

    def inverse(self, x, y):
        ok, col, mrow = self._t.transform(x, y, True)
        if not ok:
            raise ValueError("inverse transformation failed")
        return col, -mrow


def residuals(points, method, base):
    """Restfehler aller Punkte für eine Transformation, ``(Restfehler, Geotransformation oder None)``.

    ``method`` ist schon aufgelöst (kein ``auto``). Verschiebung, Helmert und affin rechnet der Kern.
    """
    if method in georef.LINEAR:
        gt = georef.fit(points, method, base)
        return georef.gt_residuals(points, gt), gt
    t = Transformer(method, points)
    try:
        return georef.residuals(points, t.forward, t.inverse), None
    except ValueError:
        # Thin Plate Spline kennt keine Umkehrung jedes Punktes: dann nur in Karteneinheiten
        return georef.residuals(points, t.forward), None


# -- VRT ------------------------------------------------------------------

def _gdal():
    # Kein gdal.UseExceptions(): Die Einstellung gälte für ganz QGIS und alle Plugins.
    from osgeo import gdal
    return gdal


def image_size(path):
    """(Breite, Höhe, Geotransformation oder None, WKT) eines Bildes."""
    gdal = _gdal()
    ds = gdal.Open(path)
    if ds is None:
        raise ValueError("cannot open %s" % path)
    gt = ds.GetGeoTransform(can_return_null=True)
    out = (ds.RasterXSize, ds.RasterYSize, tuple(gt) if gt else None, ds.GetProjection() or "")
    ds = None
    return out


def create_vrt(source, vrt_path, gt, crs_wkt=""):
    """VRT des Originals mit eigener Geotransformation anlegen (Original bleibt unberührt)."""
    gdal = _gdal()
    options = gdal.TranslateOptions(format="VRT", outputSRS=crs_wkt or None)
    ds = gdal.Translate(vrt_path, source, options=options)
    if ds is None:
        raise ValueError("cannot create %s" % vrt_path)
    ds = None
    set_vrt_geotransform(vrt_path, gt)
    return vrt_path


_GT = re.compile(r"<GeoTransform>[^<]*</GeoTransform>")
_GCP = re.compile(r"\s*<GCPList[^>]*>.*?</GCPList>|\s*<GCPList[^>]*/>", re.S)
_SRS = re.compile(r"(<VRTDataset[^>]*>)")


def _gt_element(gt):
    return "<GeoTransform>%s</GeoTransform>" % ", ".join("%.17g" % v for v in gt)


def set_vrt_geotransform(vrt_path, gt):
    """Geotransformation im Text der VRT ersetzen (oder einfügen); Passpunkte darin entfallen."""
    with open(vrt_path, encoding="utf-8") as fh:
        text = fh.read()
    text = _GCP.sub("", text)
    if _GT.search(text):
        text = _GT.sub(_gt_element(gt), text, count=1)
    else:
        text = _SRS.sub(lambda m: m.group(1) + "\n  " + _gt_element(gt), text, count=1)
    with open(vrt_path, "w", encoding="utf-8") as fh:
        fh.write(text)


def reload_layer(layer, path=None):
    """Rasterlayer neu aus seiner (geänderten) Datei lesen; ID, Stil und Platz in der Layerliste bleiben.

    Nur ``setDataSource`` übernimmt eine neue Lage zuverlässig: ``reloadData()`` und ``reload()`` behalten
    unter 3.44 die alte Ausdehnung, unter QGIS 4 bei einer Drehung (gemessen in 3.44 und 4.2).
    """
    options = QgsDataProvider.ProviderOptions()
    options.transformContext = QgsProject.instance().transformContext()
    layer.setDataSource(path or layer.source(), layer.name(), layer.providerType(), options, False)


def show_geotransform(layer, vrt_path, gt, new_path):
    """Neue Geotransformation anzeigen: VRT ``vrt_path`` mit ``gt`` nach ``new_path``, Layer darauf umstellen.

    Immer in eine neue Datei: GDAL schreibt eine geöffnete VRT beim Schließen zurück; beim Neuladen
    derselben Datei überschriebe die alte Lage die neue (gemessen in 3.44). Die alte Datei wird danach
    entfernt. Gibt ``new_path`` zurück.
    """
    with open(vrt_path, encoding="utf-8") as fh:
        text = fh.read()
    with open(new_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    set_vrt_geotransform(new_path, gt)
    reload_layer(layer, new_path)
    if os.path.normcase(os.path.abspath(new_path)) != os.path.normcase(os.path.abspath(vrt_path)):
        remove_files([vrt_path])
    return new_path


def read_vrt_geotransform(vrt_path):
    with open(vrt_path, encoding="utf-8") as fh:
        found = _GT.search(fh.read())
    if not found:
        return None
    inner = found.group(0)[len("<GeoTransform>"):-len("</GeoTransform>")]
    return tuple(float(v) for v in inner.split(","))


def gcps(points):
    gdal = _gdal()
    return [gdal.GCP(p.x, p.y, 0.0, p.col, p.row) for p in georef.active(points)]


_WARP = {georef.POLY2: {"polynomialOrder": 2}, georef.POLY3: {"polynomialOrder": 3}, georef.TPS: {"tps": True},
         georef.AFFINE: {"polynomialOrder": 1}, georef.HELMERT: {"polynomialOrder": 1}}


def warp_options(method):
    """Schlüsselwörter für ``gdal.WarpOptions`` je Transformation (projektiv: Polynom 1 als Näherung entfällt)."""
    if method not in _WARP:
        raise ValueError("%s cannot be warped with GDAL" % method)
    return dict(_WARP[method])


def create_warped_vrt(source, gcp_path, warped_path, points, method, crs_wkt, resampling="near", size=None):
    """Entzerrte VRT: erst VRT mit Passpunkten, dann ``gdal.Warp`` als VRT (rechnet erst beim Anzeigen).

    Projektiv kennt GDAL nicht: dann ein Gitter projektiv gerechneter Punkte mit Thin Plate Spline.
    """
    gdal = _gdal()
    if method == georef.PROJECTIVE:
        width, height = size if size is not None else image_size(source)[:2]
        points, method = projective_grid(points, width, height), georef.TPS
    ds = gdal.Translate(gcp_path, source, options=gdal.TranslateOptions(
        format="VRT", GCPs=gcps(points), outputSRS=crs_wkt))
    ds = None
    ds = gdal.Warp(warped_path, gcp_path, options=gdal.WarpOptions(
        format="VRT", dstSRS=crs_wkt, resampleAlg=resampling, **warp_options(method)))
    if ds is None:
        raise ValueError("cannot warp %s" % source)
    ds = None
    return warped_path


def remove_files(paths):
    """Temp-Dateien entfernen; was fehlt oder gesperrt ist, bleibt still liegen und wird gemeldet."""
    left = []
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            left.append(path)
    return left


def projective_grid(points, width, height, steps=9):
    """Projektiv hat in GDAL kein Gegenstück: Gitter aus Punkten, die QGIS projektiv rechnet (für Thin Plate Spline)."""
    t = Transformer(georef.PROJECTIVE, points)
    grid = []
    for i in range(steps):
        for k in range(steps):
            col, row = width * i / (steps - 1.0), height * k / (steps - 1.0)
            x, y = t.forward(col, row)
            grid.append(georef.ControlPoint(col, row, x, y, True))
    return grid


def _warp_input(source, work_dir, points, method, gt, crs_wkt, size=None):
    """Quelle für ``gdal.Warp``: VRT mit Geotransformation (linear) oder mit Passpunkten.

    Gibt (Pfad, Schlüsselwörter für ``gdal.WarpOptions``) zurück.
    """
    gdal = _gdal()
    if method is None or method in georef.LINEAR:
        path = os.path.join(work_dir, "warp_input.vrt")
        create_vrt(source, path, gt, crs_wkt)
        return path, {}
    if method == georef.PROJECTIVE:
        width, height = size if size is not None else image_size(source)[:2]
        points, method = projective_grid(points, width, height), georef.TPS
    path = os.path.join(work_dir, "warp_gcps.vrt")
    options = gdal.TranslateOptions(format="VRT", GCPs=gcps(points), outputSRS=crs_wkt or None)
    ds = gdal.Translate(path, source, options=options)
    if ds is None:
        raise ValueError("cannot read %s" % source)
    ds = None
    return path, warp_options(method)


RESAMPLING = ("near", "bilinear", "cubic")
COMPRESSION = ("NONE", "LZW", "DEFLATE")


def warp_to_file(source, out_path, work_dir, points, method, gt, crs_wkt, dst_wkt=None,
                 resampling="near", compression="LZW", progress=None):
    """Bild entzerren und als GeoTIFF ``out_path`` schreiben.

    ``method``: tatsächliche Transformation (None = Lage von Hand über ``gt``). ``progress(Anteil)``
    gibt False zurück, um abzubrechen. Außerhalb des Bildes transparent (Alphakanal).
    """
    gdal = _gdal()
    path, extra = _warp_input(source, work_dir, points, method, gt, crs_wkt)
    options = ["COMPRESS=%s" % compression] if compression and compression != "NONE" else []
    options.append("TILED=YES")

    def callback(complete, _message, _data):
        if progress is None:
            return 1
        return 1 if progress(complete) is not False else 0

    ds = gdal.Warp(out_path, path, options=gdal.WarpOptions(
        format="GTiff", dstSRS=dst_wkt or crs_wkt or None, resampleAlg=resampling, dstAlpha=True,
        creationOptions=options, callback=callback, **extra))
    if ds is None:
        raise ValueError("cannot write %s" % out_path)
    ds = None
    return out_path


def save_georeference(path, gt, crs_wkt):
    """Georeferenz neben das Bild schreiben, nie in das Bild: Worldfile und GDAL-Begleitdatei (``.aux.xml``).

    Das Worldfile lesen auch andere Programme, das Bezugssystem steht nur in der Begleitdatei. Die
    Begleitdatei gilt bei GDAL vor einer Georeferenz im Bild selbst. Gibt die geschriebenen Dateien zurück.
    """
    gdal = _gdal()
    world = os.path.splitext(path)[0] + georef.world_file_suffix(path)
    with open(world, "w", encoding="ascii") as fh:
        fh.write(georef.world_file_text(gt))
    ds = gdal.Open(path)       # nur lesen: GDAL legt Georeferenz und Bezugssystem in der Begleitdatei ab
    if ds is None:
        raise ValueError("cannot open %s" % path)
    ds.SetGeoTransform(list(gt))
    if crs_wkt:
        ds.SetProjection(crs_wkt)
    ds = None
    return [world, path + ".aux.xml"]


class WarpTask(QgsTask):
    """Entzerren als Hintergrundaufgabe von QGIS (Fortschritt, Abbrechen).

    ``done(ok, Fehlertext)`` läuft danach im Hauptthread. ``run`` fasst keine Layer an.
    """

    def __init__(self, description, arguments, done):
        QgsTask.__init__(self, description, QgsTask.Flag.CanCancel)
        self.arguments = arguments
        self.done = done
        self.error = None

    def _progress(self, complete):
        self.setProgress(complete * 100.0)
        return not self.isCanceled()

    def run(self):
        try:
            warp_to_file(progress=self._progress, **self.arguments)
        except (OSError, ValueError, RuntimeError) as exc:
            self.error = str(exc)
            return False
        return not self.isCanceled()

    def finished(self, result):
        self.done(bool(result), self.error)
