"""Rechenkern der Georeferenzierung: Transformationen, Bedienschritte, Restfehler, Punktdatei."""
import math
import os

import pytest

from qgis_ribbon.core import georef as g
from qgis_ribbon.core.georef import ControlPoint as CP

DATA = os.path.join(os.path.dirname(__file__), "data")


def close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


# Lage zum Prüfen: gedreht um 30°, 2 Einheiten je Pixel, verschoben
ANGLE = math.radians(30)
SIM = (1000.0, 2 * math.cos(ANGLE), 2 * math.sin(ANGLE), 5000.0, 2 * math.sin(ANGLE), -2 * math.cos(ANGLE))
AFF = (1000.0, 2.0, 0.5, 5000.0, 0.3, -1.5)


def points_from(gt, pixels):
    return [CP(c, r, *g.apply(gt, c, r)) for c, r in pixels]


PIX = [(10, 20), (300, 40), (120, 250), (400, 380), (50, 330)]


def test_apply_and_invert_by_hand():
    gt = (100.0, 2.0, 0.0, 200.0, 0.0, -2.0)
    assert g.apply(gt, 10, 5) == (120.0, 190.0)
    assert close(g.to_pixel(gt, 120, 190), (10, 5))
    inv = g.invert(gt)
    assert close(inv, (-50.0, 0.5, 0.0, 100.0, 0.0, -0.5))
    assert close(g.invert(inv), gt)
    with pytest.raises(ValueError):
        g.invert((0, 1, 1, 0, 1, 1))


def test_compose_and_change():
    gt = (100.0, 2.0, 0.0, 200.0, 0.0, -2.0)
    assert close(g.compose(gt, g.invert(gt)), (0, 1, 0, 0, 0, 1))
    assert close(g.compose(g.invert(AFF), AFF), (0, 1, 0, 0, 0, 1))
    moved = g.rotate(g.translate(AFF, 10, 5), 33, 1200, 4800)
    m = g.change(AFF, moved)
    for c, r in PIX:
        assert close(g.apply(m, *g.apply(AFF, c, r)), g.apply(moved, c, r))


def test_corners_bounds_center():
    gt = (0.0, 1.0, 0.0, 10.0, 0.0, -1.0)
    assert g.corners(gt, 4, 2) == [(0, 10), (4, 10), (4, 8), (0, 8)]
    assert g.bounds(gt, 4, 2) == (0, 8, 4, 10)
    assert g.center(gt, 4, 2) == (2, 9)
    assert g.is_north_up(gt) and not g.is_north_up(SIM)
    assert g.pixel_size(SIM) == pytest.approx(2.0)
    assert g.rotation(SIM) == pytest.approx(30.0)


def test_translation_by_hand():
    base = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
    pts = [CP(0, 0, 10, 20), CP(2, 2, 14, 16)]    # erwartet (10, 20) und (12, 18): Mittel +1/-1
    assert g.fit_translation(pts, base) == (11.0, 1.0, 0.0, 19.0, 0.0, -1.0)
    assert g.fit(pts[:1], g.AUTO, base) == (10.0, 1.0, 0.0, 20.0, 0.0, -1.0)
    with pytest.raises(ValueError):
        g.fit_translation([], base)


def test_helmert_by_hand():
    # zwei Punkte, 90° gegen den Uhrzeigersinn, Maßstab 2: Spalte nach +y, Zeile nach +x
    pts = [CP(0, 0, 100, 100), CP(10, 0, 100, 120)]
    gt = g.fit_helmert(pts)
    assert close(gt, (100, 0, 2, 100, 2, 0))
    assert close(g.apply(gt, 0, 5), (110, 100))
    assert g.fit(pts, g.AUTO, g.IDENTITY) == gt


def test_helmert_recovers_similarity_and_keeps_orientation():
    gt = g.fit_helmert(points_from(SIM, PIX))
    assert close(gt, SIM)
    assert g.determinant(gt) < 0        # Zeile nach unten wie bei jedem Bild: nicht gespiegelt


def test_affine_recovers_affine_exactly():
    gt = g.fit_affine(points_from(AFF, PIX))
    assert close(gt, AFF)
    assert g.fit(points_from(AFF, PIX[:3]), g.AUTO, g.IDENTITY) == pytest.approx(AFF)


def test_affine_least_squares_by_hand():
    # vier Punkte, Ziel abwechselnd um ±1 in x gestört: die Störungen heben sich auf,
    # der Ausgleich ergibt die ungestörte Lage, jeder Punkt behält 1 Einheit Restfehler
    pts = [CP(0, 0, 1, 0), CP(10, 0, 9, 0), CP(0, 10, -1, -10), CP(10, 10, 11, -10)]
    gt = g.fit_affine(pts)
    assert close(gt, (0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
    res = g.gt_residuals(pts, gt)
    assert [round(r.dx, 9) for r in res] == [-1, 1, 1, -1]
    assert g.mean_error(pts, res) == pytest.approx(1.0)
    # mit Verschiebung aller Ziele um +2 in y: nur y0 ändert sich
    moved = [CP(p.col, p.row, p.x, p.y + 2) for p in pts]
    assert close(g.fit_affine(moved), (0.0, 1.0, 0.0, 2.0, 0.0, -1.0))


def test_degenerate_points_are_errors():
    with pytest.raises(ValueError):
        g.fit_affine([CP(0, 0, 0, 0), CP(1, 1, 1, 1), CP(2, 2, 2, 2)])
    with pytest.raises(ValueError):
        g.fit_helmert([CP(5, 5, 0, 0), CP(5, 5, 1, 1)])
    with pytest.raises(ValueError):
        g.fit_helmert([CP(0, 0, 3, 3), CP(5, 5, 3, 3)])
    with pytest.raises(ValueError):
        g.fit_affine([CP(0, 0, 0, 0), CP(1, 0, 1, 0)])
    with pytest.raises(ValueError):
        g.fit(points_from(AFF, PIX), g.POLY2, AFF)


def test_inactive_points_are_ignored_but_get_residuals():
    pts = points_from(AFF, PIX[:3]) + [CP(5, 5, 9999, 9999, active=False)]
    gt = g.fit(pts, g.AUTO, g.IDENTITY)
    assert close(gt, AFF)
    res = g.gt_residuals(pts, gt)
    assert res[3].map > 1000 and all(r.map < 1e-6 for r in res[:3])
    assert g.mean_error(pts, res) == pytest.approx(0, abs=1e-6)


def test_residuals_are_zero_for_exactly_determined_points():
    for gt, pts, method in ((SIM, points_from(SIM, PIX[:2]), g.HELMERT),
                            (AFF, points_from(AFF, PIX[:3]), g.AFFINE),
                            (AFF, points_from(AFF, PIX[:1]), g.TRANSLATION)):
        fitted = g.fit(pts, method, AFF)
        res = g.gt_residuals(pts, fitted)
        assert max(r.map for r in res) < 1e-6
        assert max(r.pixels for r in res) < 1e-6


def test_residuals_in_pixels_by_hand():
    gt = (0.0, 2.0, 0.0, 0.0, 0.0, -2.0)            # 2 Einheiten je Pixel
    pts = [CP(1, 1, 2, -2), CP(3, 3, 8, -6)]        # zweiter liegt 2 Einheiten in x daneben
    res = g.gt_residuals(pts, gt)
    assert res[1].dx == -2 and res[1].dy == 0 and res[1].map == 2
    assert res[1].pdx == pytest.approx(-1) and res[1].pixels == pytest.approx(1)
    assert g.mean_error(pts, res) == pytest.approx(math.sqrt(2))
    assert g.mean_error(pts, res, pixels=True) == pytest.approx(math.sqrt(0.5))
    assert g.mean_error([], []) is None
    without = g.residuals(pts, lambda c, r: g.apply(gt, c, r))
    assert without[1].pixels is None and g.mean_error(pts, without, pixels=True) is None


def test_resolve_and_available():
    assert [g.resolve(g.AUTO, n) for n in (0, 1, 2, 3, 7)] == [g.TRANSLATION, g.TRANSLATION, g.HELMERT,
                                                               g.AFFINE, g.AFFINE]
    assert g.resolve(g.POLY2, 1) == g.POLY2
    assert g.available(g.POLY2, 4) == (False, 2)
    assert g.available(g.POLY3, 10) == (True, 0)
    assert g.available(g.AUTO, 0) == (False, 1)
    assert g.available(g.TPS, 1) == (True, 0)
    assert set(g.METHODS) - {g.AUTO} <= set(g.MIN_POINTS)


# -- Bedienschritte -------------------------------------------------------

def test_translate_scale_rotate_by_hand():
    gt = (0.0, 1.0, 0.0, 10.0, 0.0, -1.0)
    assert g.translate(gt, 5, -2) == (5.0, 1.0, 0.0, 8.0, 0.0, -1.0)
    # um (2, 9) verdoppeln: Ecke (0, 10) wandert nach (-2, 11)
    assert close(g.scale(gt, 2, 2, 2, 9), (-2.0, 2.0, 0.0, 11.0, 0.0, -2.0))
    # 90° gegen den Uhrzeigersinn um (0, 10): Spalte zeigt nach +y
    rot = g.rotate(gt, 90, 0, 10)
    assert close(rot, (0.0, 0.0, 1.0, 10.0, 1.0, 0.0))
    assert close(g.apply(rot, 1, 0), (0, 11))
    with pytest.raises(ValueError):
        g.scale(gt, 0, 1, 0, 0)


def test_steps_are_reversible():
    w, h = 400, 300
    cx, cy = g.center(AFF, w, h)
    assert close(g.translate(g.translate(AFF, 7.5, -3), -7.5, 3), AFF)
    assert close(g.scale(g.scale(AFF, 2.5, 0.5, cx, cy), 0.4, 2, cx, cy), AFF)
    assert close(g.rotate(g.rotate(AFF, 37, cx, cy), -37, cx, cy), AFF)
    assert close(g.scale_image(g.scale_image(SIM, 2, 3, cx, cy), 0.5, 1 / 3.0, cx, cy), SIM)
    assert g.flip_horizontal(g.flip_horizontal(AFF, w, h), w, h) == AFF
    assert g.flip_vertical(g.flip_vertical(AFF, w, h), w, h) == AFF
    gt = AFF
    for _ in range(4):
        gt = g.rotate90(gt, w, h)
    assert close(gt, AFF)
    assert close(g.rotate90(g.rotate90(AFF, w, h), w, h, clockwise=True), AFF)


def test_flip_keeps_outline_and_mirrors():
    gt = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
    flipped = g.flip_horizontal(gt, 4, 2)
    assert g.bounds(flipped, 4, 2) == g.bounds(gt, 4, 2)
    assert g.apply(flipped, 0, 0) == (4, 0)            # linke obere Ecke liegt jetzt rechts
    assert g.determinant(flipped) > 0                  # gespiegelt
    flipped = g.flip_vertical(gt, 4, 2)
    assert g.bounds(flipped, 4, 2) == g.bounds(gt, 4, 2) and g.apply(flipped, 0, 0) == (0, -2)


def test_rotate90_turns_about_the_center():
    gt = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
    left = g.rotate90(gt, 4, 2)
    assert close(g.center(left, 4, 2), g.center(gt, 4, 2))
    assert close(g.bounds(left, 4, 2), (1, -3, 3, 1))
    # obere linke Ecke landet nach links unten bei Drehung gegen den Uhrzeigersinn
    assert close(g.apply(left, 0, 0), (3 - 2, -3))
    right = g.rotate90(gt, 4, 2, clockwise=True)
    assert close(g.apply(right, 0, 0), (3, 1))


def test_scale_image_keeps_a_rotated_image_rectangular():
    cx, cy = g.center(SIM, 100, 50)
    out = g.scale_image(SIM, 2, 1, cx, cy)
    assert g.rotation(out) == pytest.approx(30)
    c = g.corners(out, 100, 50)
    v1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    v2 = (c[3][0] - c[0][0], c[3][1] - c[0][1])
    assert v1[0] * v2[0] + v1[1] * v2[1] == pytest.approx(0, abs=1e-6)
    assert close(g.apply(out, *g.to_pixel(SIM, cx, cy)), (cx, cy))


def test_fit_to_extent_keeps_aspect_and_centers():
    gt = g.fit_to_extent(200, 100, (0, 0, 1000, 1000), fill=1.0)
    assert close(gt, (0.0, 5.0, 0.0, 750.0, 0.0, -5.0))      # 200 Pixel füllen die 1000 Einheiten Breite
    assert close(g.bounds(gt, 200, 100), (0, 250, 1000, 750))
    gt = g.fit_to_extent(100, 400, (0, 0, 1000, 1000), fill=0.8)
    assert g.center(gt, 100, 400) == pytest.approx((500, 500))
    b = g.bounds(gt, 100, 400)
    assert b[3] - b[1] == pytest.approx(800) and b[2] - b[0] == pytest.approx(200)
    for bad in ((0, 10, (0, 0, 1, 1)), (10, 10, (0, 0, 0, 1))):
        with pytest.raises(ValueError):
            g.fit_to_extent(*bad)


def test_drag_scale_and_angle():
    assert g.drag_scale((0, 0), (10, 0), (0, 20)) == (2.0, 2.0)
    assert g.drag_scale((0, 0), (10, 5), (20, 15), keep_aspect=False) == (2.0, 3.0)
    assert g.drag_scale((0, 0), (0, 5), (7, 10), keep_aspect=False) == (1.0, 2.0)
    assert g.drag_scale((0, 0), (0, 0), (5, 5)) == (1.0, 1.0)
    assert g.drag_scale((0, 0), (10, 0), (0, 0))[0] > 0
    assert g.drag_angle((0, 0), (10, 0), (0, 10)) == pytest.approx(90)
    assert g.drag_angle((0, 0), (10, 0), (0, -10)) == pytest.approx(-90)
    assert g.drag_angle((0, 0), (-10, 1), (-10, -1)) == pytest.approx(11.42, abs=0.01)
    assert g.drag_angle((0, 0), (10, 0), (10, 4), step=15) == 15
    assert g.drag_angle((0, 0), (10, 0), (10, 1), step=15) == 0


# -- Punktdatei -----------------------------------------------------------

def test_points_round_trip_without_source_georeference():
    pts = [CP(10, 20, 1000.5, 5000.25), CP(300, 40.5, 1600, 4900, active=False)]
    text = g.write_points(pts, 'PROJCRS["ETRS89 / UTM 32N",\n  ID["EPSG",25832]]')
    lines = text.splitlines()
    assert lines[0] == '#CRS: PROJCRS["ETRS89 / UTM 32N", ID["EPSG",25832]]'
    assert lines[1] == g.POINTS_HEADER
    assert lines[2] == "1000.5,5000.25,10,-20,1,0,0,0"      # Zeile mit negativem Vorzeichen wie in QGIS
    assert lines[3].split(",")[4] == "0"
    back, crs = g.read_points(text)
    assert back == pts and crs.endswith('ID["EPSG",25832]]')


def test_points_with_source_georeference_and_residuals():
    src = (500.0, 0.5, 0.0, 800.0, 0.0, -0.5)
    pts = points_from(AFF, PIX[:3])
    res = g.gt_residuals(pts, AFF)
    text = g.write_points(pts, "", source_gt=src, res=res)
    assert text.splitlines()[0] == g.POINTS_HEADER
    first = text.splitlines()[1].split(",")
    assert (float(first[2]), float(first[3])) == g.apply(src, 10, 20)
    back, crs = g.read_points(text, source_gt=src)
    assert crs == "" and all(close(a.astuple()[:4], b.astuple()[:4]) for a, b in zip(back, pts))


def test_read_old_formats_and_errors():
    old = "1000\t5000\t10\t-20\n\n# Kommentar\n1600 4900 300 -40 0\n"
    pts, crs = g.read_points(old)
    assert crs == "" and pts == [CP(10, 20, 1000, 5000), CP(300, 40, 1600, 4900, False)]
    with pytest.raises(ValueError, match="line 2"):
        g.read_points("mapX,mapY,sourceX,sourceY\n1,2,3\n")
    with pytest.raises(ValueError, match="line 1"):
        g.read_points("a,b,c,d\n")


@pytest.mark.parametrize("name", ["qgis3.points", "qgis4.points"])
def test_points_saved_by_qgis_can_be_read(name):
    """Dateien, die der Georeferenzierer von QGIS 3.44 und 4 gespeichert hat (vier Klicks, Bild ohne Georeferenz)."""
    path = os.path.join(DATA, name)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    pts, crs = g.read_points(text)
    assert "EPSG" in crs and len(pts) >= 3
    # Die Sonde setzt die Punkte auf ein Raster ohne Georeferenz: Bildpunkte positiv, Zeile über -sourceY
    assert all(p.col >= 0 and p.row >= 0 for p in pts)
    with open(os.path.join(DATA, "sonde_points.txt"), encoding="utf-8") as fh:
        expected = [tuple(float(v) for v in line.split()) for line in fh if line.strip()]
    assert len(pts) == len(expected)
    for p, (col, row, x, y) in zip(pts, expected):
        # Die Sonde klickt auf Bildschirmpixel: Bildpunkte auf weniger als einen halben Pixel
        assert abs(p.col - col) < 0.5 and abs(p.row - row) < 0.5
        assert (p.x, p.y) == (x, y)
    assert text.splitlines()[1] == g.POINTS_HEADER and text.startswith(g.CRS_PREFIX)
    # was der Kern schreibt, liest er gleich zurück
    again, crs2 = g.read_points(g.write_points(pts, crs))
    assert again == pts and crs2 == crs


# -- Worldfile und Verlauf ------------------------------------------------

def test_world_file_by_hand_and_round_trip():
    gt = (100.0, 2.0, 0.0, 200.0, 0.0, -2.0)
    assert g.world_file_text(gt).split() == ["2.0", "0.0", "0.0", "-2.0", "101.0", "199.0"]
    assert close(g.read_world_file(g.world_file_text(AFF)), AFF)
    with pytest.raises(ValueError):
        g.read_world_file("1 2 3")
    assert g.world_file_suffix("C:/x/karte.tif") == ".tfw"
    assert g.world_file_suffix("blatt.jpeg") == ".jgw"
    assert g.world_file_suffix("scan.png") == ".pgw"
    assert g.world_file_suffix("ordner.v2/ohne") == ".wld"


def test_history():
    h = g.History("a")
    assert not h.can_undo() and not h.can_redo()
    assert h.push("b") and h.push("c") and not h.push("c")
    assert h.undo() == "b" and h.undo() == "a" and h.undo() == "a"
    assert h.redo() == "b" and h.can_redo()
    h.push("d")
    assert not h.can_redo() and h.current == "d"
    small = g.History(0, limit=3)
    for i in range(1, 6):
        small.push(i)
    assert small.undo() == 4 and small.undo() == 3 and not small.can_undo()


def test_control_point_basics():
    p = CP(1, 2, 3, 4)
    q = p.copy()
    assert p == q and not (p != q) and p is not q
    q.active = False
    assert p != q and "False" in repr(q)
