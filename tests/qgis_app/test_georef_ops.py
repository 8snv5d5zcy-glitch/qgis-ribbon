"""Georeferenzierung mit QGIS und GDAL: Kern gegen QgsGcpTransformerInterface, VRT-Dateien."""
import math
import os

import pytest
from osgeo import gdal
from qgis.analysis import QgsGcpTransformerInterface
from qgis.core import QgsPointXY, QgsRasterLayer

from qgis_ribbon.core import georef as g
from qgis_ribbon.core.georef import ControlPoint as CP
from qgis_ribbon.qgis_integration import georef_ops

AFF = (1000.0, 2.0, 0.5, 5000.0, 0.3, -1.5)
ANGLE = math.radians(-20)
SIM = (1000.0, 3 * math.cos(ANGLE), 3 * math.sin(ANGLE), 5000.0, 3 * math.sin(ANGLE), -3 * math.cos(ANGLE))
PIX = [(10, 20), (300, 40), (120, 250), (400, 380), (50, 330), (220, 160), (380, 90), (260, 300),
       (30, 120), (330, 200), (150, 60), (200, 390)]


def noisy(gt, pixels):
    """Punkte aus ``gt`` mit kleiner, fester Störung (kein Punkt trifft genau)."""
    out = []
    for i, (c, r) in enumerate(pixels):
        x, y = g.apply(gt, c, r)
        out.append(CP(c, r, x + ((i * 7) % 5 - 2) * 0.7, y + ((i * 3) % 5 - 2) * 0.9))
    return out


def qgis_transformer(method, points):
    t = QgsGcpTransformerInterface.create(getattr(QgsGcpTransformerInterface.TransformMethod, method))
    assert t.updateParametersFromGcps([QgsPointXY(p.col, -p.row) for p in points],
                                      [QgsPointXY(p.x, p.y) for p in points], False)
    return t


def assert_same(gt, t, pixels, tol=1e-6):
    for c, r in pixels:
        ok, x, y = t.transform(c, -r, False)
        assert ok
        ex, ey = g.apply(gt, c, r)
        assert abs(x - ex) < tol and abs(y - ey) < tol, (c, r, (x, y), (ex, ey))


def test_helmert_matches_qgis_least_squares():
    pts = noisy(SIM, PIX)
    assert_same(g.fit_helmert(pts), qgis_transformer("Helmert", pts), PIX)
    # auch bei Punkten, die gar keine Ähnlichkeitstransformation erlauben
    pts = noisy(AFF, PIX[:5])
    assert_same(g.fit_helmert(pts), qgis_transformer("Helmert", pts), PIX)
    assert_same(g.fit_helmert(pts[:2]), qgis_transformer("Helmert", pts[:2]), PIX)


def test_affine_matches_qgis_polynomial_order_1():
    pts = noisy(AFF, PIX)
    assert_same(g.fit_affine(pts), qgis_transformer("PolynomialOrder1", pts), PIX, tol=1e-5)
    pts = noisy(SIM, PIX[:3])
    assert_same(g.fit_affine(pts), qgis_transformer("PolynomialOrder1", pts), PIX, tol=1e-5)


def test_residuals_match_qgis_for_every_method():
    pts = noisy(AFF, PIX)
    for method, name in ((g.HELMERT, "Helmert"), (g.AFFINE, "PolynomialOrder1"), (g.POLY2, "PolynomialOrder2"),
                         (g.POLY3, "PolynomialOrder3"), (g.PROJECTIVE, "Projective")):
        res, gt = georef_ops.residuals(pts, method, AFF)
        assert (gt is not None) == (method in g.LINEAR)
        t = qgis_transformer(name, pts)
        for p, r in zip(pts, res):
            ok, x, y = t.transform(p.col, -p.row, False)
            assert abs(r.dx - (x - p.x)) < 1e-5 and abs(r.dy - (y - p.y)) < 1e-5, method
        assert g.mean_error(pts, res) > 0
    # Thin Plate Spline trifft jeden Punkt
    res, _ = georef_ops.residuals(pts, g.TPS, AFF)
    assert max(r.map for r in res) < 1e-6


def test_minimum_points_and_transformer_errors():
    assert [georef_ops.minimum_points(m) for m in (g.TRANSLATION, g.HELMERT, g.AFFINE, g.POLY2, g.POLY3,
                                                   g.PROJECTIVE)] == [1, 2, 3, 6, 10, 4]
    for method in g.MIN_POINTS:
        if method != g.TRANSLATION:
            assert georef_ops.minimum_points(method) == g.MIN_POINTS[method], method
    with pytest.raises(ValueError):
        georef_ops.Transformer(g.POLY2, noisy(AFF, PIX[:5]))
    t = georef_ops.Transformer(g.POLY2, noisy(AFF, PIX))
    x, y = t.forward(100, 100)
    col, row = t.inverse(x, y)
    # Polynome rechnen die Umkehrung als eigenes Polynom: nicht exakt
    assert abs(col - 100) < 0.01 and abs(row - 100) < 0.01


def small_image(path, width=40, height=30):
    ds = gdal.GetDriverByName("GTiff").Create(path, width, height, 1, gdal.GDT_Byte)
    ds.GetRasterBand(1).Fill(77)
    ds = None
    return path


def test_vrt_geotransform_is_written_and_read(tmp_path):
    src = small_image(str(tmp_path / "bild.tif"))
    assert georef_ops.image_size(src)[:3] == (40, 30, None)
    vrt = georef_ops.create_vrt(src, str(tmp_path / "arbeit.vrt"), AFF)
    assert georef_ops.read_vrt_geotransform(vrt) == AFF
    ds = gdal.Open(vrt)
    assert tuple(ds.GetGeoTransform()) == pytest.approx(AFF)
    ds = None
    georef_ops.set_vrt_geotransform(vrt, SIM)
    assert georef_ops.read_vrt_geotransform(vrt) == SIM
    # QGIS zeigt die neue Lage; Layer-ID und Stil bleiben
    layer = QgsRasterLayer(vrt, "arbeit", "gdal")
    assert layer.isValid()
    layer.renderer().setOpacity(0.4)
    lid = layer.id()
    vrt2 = vrt.replace(".vrt", "_2.vrt")
    assert georef_ops.show_geotransform(layer, vrt, (0.0, 2.0, 0.0, 100.0, 0.0, -2.0), vrt2) == vrt2
    # GDAL schreibt die alte VRT beim Schließen zurück: die neue Datei behält die neue Lage
    assert georef_ops.read_vrt_geotransform(vrt2) == (0.0, 2.0, 0.0, 100.0, 0.0, -2.0)
    assert not os.path.exists(vrt) and layer.source() == vrt2
    e = layer.extent()
    assert (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()) == pytest.approx((0, 40, 80, 100))
    assert layer.id() == lid and layer.renderer().opacity() == pytest.approx(0.4)
    # gedreht: Ausdehnung umschließt die gedrehten Ecken
    georef_ops.show_geotransform(layer, vrt2, SIM, vrt)
    assert georef_ops.read_vrt_geotransform(vrt) == pytest.approx(SIM)
    e = layer.extent()
    # GDAL rundet die Ausdehnung gedrehter Raster auf ganze Ausgabepixel (3 Einheiten)
    assert (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()) == pytest.approx(g.bounds(SIM, 40, 30), abs=3)
    # Original unberührt
    assert georef_ops.image_size(src)[2] is None


def test_vrt_without_geotransform_element_gets_one(tmp_path):
    vrt = tmp_path / "ohne.vrt"
    vrt.write_text('<VRTDataset rasterXSize="2" rasterYSize="2">\n  <GCPList Projection="">'
                   '<GCP Id="1" Pixel="0" Line="0" X="1" Y="1"/></GCPList>\n</VRTDataset>\n', encoding="utf-8")
    georef_ops.set_vrt_geotransform(str(vrt), AFF)
    text = vrt.read_text(encoding="utf-8")
    assert "GCPList" not in text and georef_ops.read_vrt_geotransform(str(vrt)) == AFF


def test_warped_vrt_hits_the_control_points(tmp_path):
    src = small_image(str(tmp_path / "bild.tif"), 200, 150)
    gt = (500000.0, 1.0, 0.0, 5700000.0, 0.0, -1.0)
    pixels = ((10, 10), (190, 15), (100, 75), (20, 140), (180, 140), (60, 40), (150, 100))
    pts = [CP(c, r, *g.apply(gt, c, r)) for c, r in pixels]
    from qgis.core import QgsCoordinateReferenceSystem
    wkt = QgsCoordinateReferenceSystem("EPSG:25832").toWkt()
    for method in (g.POLY2, g.TPS):
        warped = georef_ops.create_warped_vrt(src, str(tmp_path / ("gcp_%s.vrt" % method)),
                                              str(tmp_path / ("w_%s.vrt" % method)), pts, method, wkt)
        ds = gdal.Open(warped)
        wgt = ds.GetGeoTransform()
        assert ds.RasterXSize == pytest.approx(200, abs=2) and wgt[1] == pytest.approx(1.0, rel=0.02)
        assert wgt[0] == pytest.approx(500000, abs=2) and wgt[3] == pytest.approx(5700000, abs=2)
        ds = None
    with pytest.raises(ValueError):
        georef_ops.warp_options(g.PROJECTIVE)


def test_remove_files(tmp_path):
    a = tmp_path / "a.vrt"
    a.write_text("x")
    assert georef_ops.remove_files([str(a), str(tmp_path / "fehlt.vrt")]) == []
    assert not os.path.exists(str(a))
