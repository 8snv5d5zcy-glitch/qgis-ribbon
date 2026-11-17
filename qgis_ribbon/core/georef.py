"""Rechenkern der Georeferenzierung in der Karte, ohne QGIS.

Ein Bild liegt über eine Geotransformation von GDAL in der Karte: sechs Werte
``(x0, a, b, y0, d, e)``, ein Bildpunkt (Spalte, Zeile) landet bei
``x = x0 + a*Spalte + b*Zeile``, ``y = y0 + d*Spalte + e*Zeile``. Spalte und Zeile
sind stetig, (0, 0) ist die obere linke Ecke des ersten Pixels (wie in GDAL).

Inhalt:
- Passpunkte (``ControlPoint``) und Transformationen daraus: Verschiebung (ab 1 Punkt),
  Helmert (ab 2, kleinste Quadrate), affin (ab 3, kleinste Quadrate), dazu ``fit``
  mit „automatisch“. Höhere Ordnungen rechnet ``qgis_integration/georef_ops.py``.
- Bedienschritte auf einer Geotransformation: verschieben, skalieren und drehen um
  einen Punkt, spiegeln, um 90° drehen, in ein Rechteck einpassen.
- Restfehler je Passpunkt und mittlerer Fehler.
- Punktdatei des QGIS-Georeferenzierers (``.points``) lesen und schreiben.
- Worldfile, Verlauf (Rückgängig/Wiederholen).
"""

import math
from collections import namedtuple

# Transformationen: Schlüssel, kleinste Zahl der Passpunkte
TRANSLATION = "translation"
HELMERT = "helmert"
AFFINE = "affine"
POLY2 = "poly2"
POLY3 = "poly3"
TPS = "tps"
PROJECTIVE = "projective"
AUTO = "auto"

MIN_POINTS = {TRANSLATION: 1, HELMERT: 2, AFFINE: 3, POLY2: 6, POLY3: 10, TPS: 1, PROJECTIVE: 4}
# Reihenfolge im Auswahlfeld
METHODS = (AUTO, HELMERT, AFFINE, POLY2, POLY3, TPS, PROJECTIVE)
# Diese drei bleiben eine Geotransformation (Bild wird nicht entzerrt)
LINEAR = (TRANSLATION, HELMERT, AFFINE)

POINTS_HEADER = "mapX,mapY,sourceX,sourceY,enable,dX,dY,residual"
CRS_PREFIX = "#CRS: "

IDENTITY = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)


class ControlPoint(object):
    """Passpunkt: Bildpunkt (Spalte, Zeile), Zielpunkt (x, y) in Karteneinheiten, aktiv."""

    __slots__ = ("col", "row", "x", "y", "active")

    def __init__(self, col, row, x, y, active=True):
        self.col = float(col)
        self.row = float(row)
        self.x = float(x)
        self.y = float(y)
        self.active = bool(active)

    def copy(self):
        return ControlPoint(self.col, self.row, self.x, self.y, self.active)

    def __eq__(self, other):
        return isinstance(other, ControlPoint) and self.astuple() == other.astuple()

    def __ne__(self, other):
        return not self == other

    def astuple(self):
        return (self.col, self.row, self.x, self.y, self.active)

    def __repr__(self):
        return "ControlPoint(%r, %r, %r, %r, %r)" % self.astuple()


Residual = namedtuple("Residual", "dx dy map pdx pdy pixels")


# -- Geotransformation ----------------------------------------------------

def apply(gt, col, row):
    """Bildpunkt -> Kartenpunkt."""
    return (gt[0] + gt[1] * col + gt[2] * row, gt[3] + gt[4] * col + gt[5] * row)


def determinant(gt):
    return gt[1] * gt[5] - gt[2] * gt[4]


def invert(gt):
    """Umkehrung: Geotransformation von Karte nach Bild (``apply(invert(gt), x, y)`` -> Spalte, Zeile)."""
    det = determinant(gt)
    if abs(det) < 1e-300:
        raise ValueError("geotransform is not invertible")
    a, b, d, e = gt[1], gt[2], gt[4], gt[5]
    ia, ib, id_, ie = e / det, -b / det, -d / det, a / det
    return (-(ia * gt[0] + ib * gt[3]), ia, ib, -(id_ * gt[0] + ie * gt[3]), id_, ie)


def to_pixel(gt, x, y):
    """Kartenpunkt -> Bildpunkt (Spalte, Zeile)."""
    return apply(invert(gt), x, y)


def compose(outer, inner):
    """Hintereinander: erst ``inner``, dann ``outer`` (beide als Geotransformation geschrieben)."""
    o, i = outer, inner
    return (o[0] + o[1] * i[0] + o[2] * i[3], o[1] * i[1] + o[2] * i[4], o[1] * i[2] + o[2] * i[5],
            o[3] + o[4] * i[0] + o[5] * i[3], o[4] * i[1] + o[5] * i[4], o[4] * i[2] + o[5] * i[5])


def change(before, after):
    """Kartenseitige Abbildung, die das Bild von ``before`` nach ``after`` bringt (für Vorschaubilder)."""
    return compose(after, invert(before))


def corners(gt, width, height):
    """Die vier Ecken des Bildes in der Karte (oben links, oben rechts, unten rechts, unten links)."""
    return [apply(gt, c, r) for c, r in ((0, 0), (width, 0), (width, height), (0, height))]


def bounds(gt, width, height):
    """Umgebendes Rechteck (xmin, ymin, xmax, ymax) des Bildes in der Karte."""
    pts = corners(gt, width, height)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def center(gt, width, height):
    """Mittelpunkt des Bildes in der Karte."""
    return apply(gt, width / 2.0, height / 2.0)


def is_north_up(gt, eps=1e-12):
    """Ohne Drehung und Scherung (nur dann darf ein Raster ohne Entzerren angezeigt werden)."""
    return abs(gt[2]) <= eps * max(1.0, abs(gt[1])) and abs(gt[4]) <= eps * max(1.0, abs(gt[5]))


def pixel_size(gt):
    """Mittlere Kantenlänge eines Pixels in Karteneinheiten."""
    return math.sqrt(abs(determinant(gt)))


def rotation(gt):
    """Drehung der Bildzeilen gegen die x-Achse in Grad (gegen den Uhrzeigersinn)."""
    return math.degrees(math.atan2(gt[4], gt[1]))


# -- Bedienschritte -------------------------------------------------------

def _map_affine(gt, m):
    """Kartenseitige affine Abbildung ``m = (a, b, c, d, e, f)`` (x' = a*x + b*y + c, y' = d*x + e*y + f) anwenden."""
    a, b, c, d, e, f = m
    return (a * gt[0] + b * gt[3] + c, a * gt[1] + b * gt[4], a * gt[2] + b * gt[5],
            d * gt[0] + e * gt[3] + f, d * gt[1] + e * gt[4], d * gt[2] + e * gt[5])


def translate(gt, dx, dy):
    return (gt[0] + dx, gt[1], gt[2], gt[3] + dy, gt[4], gt[5])


def scale(gt, fx, fy, cx, cy):
    """Um den Kartenpunkt (cx, cy) skalieren, je Achse der Karte."""
    if fx == 0 or fy == 0:
        raise ValueError("scale factor must not be 0")
    return _map_affine(gt, (fx, 0.0, cx * (1 - fx), 0.0, fy, cy * (1 - fy)))


def scale_image(gt, f1, f2, cx, cy):
    """Um den Kartenpunkt (cx, cy) skalieren, je Achse des Bildes (Spalten mit ``f1``, Zeilen mit ``f2``).

    Anders als ``scale`` bleibt ein gedrehtes Bild dabei rechtwinklig.
    """
    if f1 == 0 or f2 == 0:
        raise ValueError("scale factor must not be 0")
    out = (gt[0], gt[1] * f1, gt[2] * f2, gt[3], gt[4] * f1, gt[5] * f2)
    # der Bildpunkt unter (cx, cy) bleibt dort stehen
    col, row = to_pixel(gt, cx, cy)
    px, py = apply(out, col, row)
    return translate(out, cx - px, cy - py)


def rotate(gt, angle, cx, cy):
    """Um den Kartenpunkt (cx, cy) drehen, ``angle`` in Grad gegen den Uhrzeigersinn."""
    rad = math.radians(angle)
    cos, sin = math.cos(rad), math.sin(rad)
    # bei Vielfachen von 90° exakt rechnen, damit 4 × 90° wieder genau den Ausgang ergibt
    if abs(angle % 90) < 1e-12:
        quarter = int(round(angle / 90.0)) % 4
        cos, sin = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[quarter]
    return _map_affine(gt, (cos, -sin, cx - cos * cx + sin * cy, sin, cos, cy - sin * cx - cos * cy))


def flip_horizontal(gt, width, height):
    """Bild waagerecht spiegeln (links und rechts tauschen), Lage und Umriss bleiben."""
    return (gt[0] + width * gt[1], -gt[1], gt[2], gt[3] + width * gt[4], -gt[4], gt[5])


def flip_vertical(gt, width, height):
    """Bild senkrecht spiegeln (oben und unten tauschen), Lage und Umriss bleiben."""
    return (gt[0] + height * gt[2], gt[1], -gt[2], gt[3] + height * gt[5], gt[4], -gt[5])


def rotate90(gt, width, height, clockwise=False):
    """Um 90° um den Bildmittelpunkt drehen."""
    cx, cy = center(gt, width, height)
    return rotate(gt, -90.0 if clockwise else 90.0, cx, cy)


def fit_to_extent(width, height, extent, fill=0.9):
    """Nordausgerichtete Geotransformation, die das Bild mittig in ``extent`` legt (Seitenverhältnis bleibt).

    ``extent`` = (xmin, ymin, xmax, ymax); ``fill`` = Anteil des Ausschnitts, den das Bild höchstens einnimmt.
    """
    if width <= 0 or height <= 0:
        raise ValueError("image has no size")
    xmin, ymin, xmax, ymax = extent
    ew, eh = float(xmax - xmin), float(ymax - ymin)
    if ew <= 0 or eh <= 0:
        raise ValueError("extent is empty")
    size = min(ew / width, eh / height) * fill
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    return (cx - size * width / 2.0, size, 0.0, cy + size * height / 2.0, 0.0, -size)


def drag_scale(center_xy, start, current, keep_aspect=True, minimum=1e-6):
    """Skalierfaktoren (fx, fy) aus einem Zug vom Mittelpunkt weg (``start`` -> ``current``).

    Mit festem Seitenverhältnis zählt der Abstand zum Mittelpunkt, sonst je Achse der Abstand.
    """
    cx, cy = center_xy
    if keep_aspect:
        d0 = math.hypot(start[0] - cx, start[1] - cy)
        d1 = math.hypot(current[0] - cx, current[1] - cy)
        f = d1 / d0 if d0 > 0 else 1.0
        f = max(f, minimum)
        return f, f

    def axis(s, c, m):
        if abs(s - m) <= 0:
            return 1.0
        return max(abs(c - m) / abs(s - m), minimum)

    return axis(start[0], current[0], cx), axis(start[1], current[1], cy)


def drag_angle(center_xy, start, current, step=None):
    """Drehwinkel in Grad (gegen den Uhrzeigersinn) aus einem Zug um den Mittelpunkt, optional gerastert."""
    cx, cy = center_xy
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(current[1] - cy, current[0] - cx)
    angle = math.degrees(a1 - a0)
    angle = (angle + 180.0) % 360.0 - 180.0
    if step:
        angle = round(angle / step) * step
    return angle


# -- Transformationen aus Passpunkten -------------------------------------

def active(points):
    return [p for p in points if p.active]


def fit_translation(points, base):
    """Nur verschieben: ``base`` so versetzen, dass die Passpunkte im Mittel treffen (ab 1 Punkt)."""
    pts = active(points)
    if not pts:
        raise ValueError("translation needs 1 control point")
    dx = sum(p.x - apply(base, p.col, p.row)[0] for p in pts) / len(pts)
    dy = sum(p.y - apply(base, p.col, p.row)[1] for p in pts) / len(pts)
    return translate(base, dx, dy)


def fit_helmert(points):
    """Helmert (verschieben, drehen, einheitlich skalieren), kleinste Quadrate, ab 2 Punkten.

    Gerechnet mit (Spalte, -Zeile), damit das Bild nicht gespiegelt wird.
    """
    pts = active(points)
    if len(pts) < 2:
        raise ValueError("Helmert needs 2 control points")
    n = float(len(pts))
    mu = sum(p.col for p in pts) / n
    mv = sum(-p.row for p in pts) / n
    mx = sum(p.x for p in pts) / n
    my = sum(p.y for p in pts) / n
    num_a = num_b = den = 0.0
    for p in pts:
        u, v, x, y = p.col - mu, -p.row - mv, p.x - mx, p.y - my
        num_a += u * x + v * y
        num_b += u * y - v * x
        den += u * u + v * v
    if den <= 0:
        raise ValueError("control points coincide in the image")
    a, b = num_a / den, num_b / den
    if a == 0 and b == 0:
        raise ValueError("control points coincide in the map")
    tx = mx - a * mu + b * mv
    ty = my - b * mu - a * mv
    # x = tx + a*u - b*v, y = ty + b*u + a*v mit u = Spalte, v = -Zeile
    return (tx, a, b, ty, b, -a)


def _solve3(m, rhs):
    """3×3-Gleichungssystem (Gauß mit Pivotsuche)."""
    a = [list(m[i]) + [rhs[i]] for i in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12 * max(1.0, max(abs(v) for row in m for v in row)):
            raise ValueError("control points are collinear")
        a[col], a[piv] = a[piv], a[col]
        for r in range(3):
            if r != col:
                f = a[r][col] / a[col][col]
                for k in range(col, 4):
                    a[r][k] -= f * a[col][k]
    return [a[i][3] / a[i][i] for i in range(3)]


def fit_affine(points):
    """Affin (sechs Parameter), kleinste Quadrate, ab 3 Punkten, die nicht auf einer Linie liegen."""
    pts = active(points)
    if len(pts) < 3:
        raise ValueError("affine needs 3 control points")
    # Schwerpunkt abziehen: besser konditioniert
    n = float(len(pts))
    mc = sum(p.col for p in pts) / n
    mr = sum(p.row for p in pts) / n
    m = [[0.0] * 3 for _ in range(3)]
    bx = [0.0] * 3
    by = [0.0] * 3
    for p in pts:
        row = (1.0, p.col - mc, p.row - mr)
        for i in range(3):
            for k in range(3):
                m[i][k] += row[i] * row[k]
            bx[i] += row[i] * p.x
            by[i] += row[i] * p.y
    x0, a, b = _solve3(m, bx)
    y0, d, e = _solve3(m, by)
    if abs(a * e - b * d) < 1e-300:
        raise ValueError("control points coincide in the map")
    return (x0 - a * mc - b * mr, a, b, y0 - d * mc - e * mr, d, e)


def resolve(method, count):
    """Tatsächliche Transformation zu ``method`` bei ``count`` aktiven Punkten (``auto``: 1, 2, ab 3)."""
    if method == AUTO:
        if count >= 3:
            return AFFINE
        if count == 2:
            return HELMERT
        return TRANSLATION
    return method


def available(method, count):
    """``(wählbar, fehlende Punkte)``: Ist ``method`` mit ``count`` aktiven Punkten rechenbar?"""
    need = 1 if method == AUTO else MIN_POINTS[method]
    return count >= need, max(0, need - count)


def fit(points, method, base):
    """Geotransformation aus den Passpunkten für Verschiebung, Helmert und affin (auch ``auto``).

    ``base``: aktuelle Lage, Grundlage der Verschiebung und Ergebnis ohne aktive Punkte.
    Höhere Ordnungen haben keine Geotransformation: ``ValueError``.
    """
    pts = active(points)
    kind = resolve(method, len(pts))
    if not pts and method == AUTO:
        return base
    if kind == TRANSLATION:
        return fit_translation(pts, base)
    if kind == HELMERT:
        return fit_helmert(pts)
    if kind == AFFINE:
        return fit_affine(pts)
    raise ValueError("%s has no geotransform" % kind)


# -- Restfehler -----------------------------------------------------------

def residuals(points, forward, inverse=None):
    """Restfehler je Punkt (auch inaktive) als ``Residual``.

    ``forward(col, row) -> (x, y)``; ``inverse(x, y) -> (col, row)`` für die Restfehler in Bildpunkten
    (ohne ``inverse`` sind diese ``None``). Restfehler = gerechnet minus Ziel.
    """
    out = []
    for p in points:
        fx, fy = forward(p.col, p.row)
        dx, dy = fx - p.x, fy - p.y
        pdx = pdy = pix = None
        if inverse is not None:
            ic, ir = inverse(p.x, p.y)
            pdx, pdy = p.col - ic, p.row - ir
            pix = math.hypot(pdx, pdy)
        out.append(Residual(dx, dy, math.hypot(dx, dy), pdx, pdy, pix))
    return out


def gt_residuals(points, gt):
    inv = invert(gt)
    return residuals(points, lambda c, r: apply(gt, c, r), lambda x, y: apply(inv, x, y))


def mean_error(points, res, pixels=False):
    """Mittlerer Fehler (Wurzel aus dem Mittel der Quadrate) der aktiven Punkte; ``None`` ohne Punkte."""
    vals = [(r.pixels if pixels else r.map) for p, r in zip(points, res) if p.active]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return math.sqrt(sum(v * v for v in vals) / len(vals))


# -- Punktdatei (.points) -------------------------------------------------

def _num(value):
    """Zahl wie ``qgsDoubleToString``: ohne überflüssige Nullen."""
    value = float(value)
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def source_coords(col, row, source_gt=None):
    """Bildpunkt -> Quellkoordinate der Punktdatei.

    Wie der QGIS-Georeferenzierer: ohne Georeferenz am Original (Spalte, -Zeile), sonst die Koordinaten
    der bisherigen Georeferenz des Originals.
    """
    if source_gt is None:
        return col, -row
    return apply(source_gt, col, row)


def pixel_coords(sx, sy, source_gt=None):
    """Quellkoordinate der Punktdatei -> Bildpunkt (Umkehrung von ``source_coords``)."""
    if source_gt is None:
        return sx, -sy
    return to_pixel(source_gt, sx, sy)


def write_points(points, crs_wkt="", source_gt=None, res=None):
    """Text einer Punktdatei im Format des QGIS-Georeferenzierers.

    Kopfzeile ``#CRS: <WKT>`` (nur mit Bezugssystem), Spaltenzeile, je Passpunkt
    ``mapX,mapY,sourceX,sourceY,enable,dX,dY,residual``. ``res``: Restfehler (``Residual``) je Punkt,
    geschrieben in Bildpunkten wie in der Grundeinstellung von QGIS, sonst 0.
    """
    lines = []
    if crs_wkt:
        lines.append(CRS_PREFIX + " ".join(crs_wkt.split()))
    lines.append(POINTS_HEADER)
    for i, p in enumerate(points):
        sx, sy = source_coords(p.col, p.row, source_gt)
        dx = dy = dist = 0.0
        if res is not None and res[i].pixels is not None:
            dx, dy, dist = res[i].pdx, res[i].pdy, res[i].pixels
        lines.append(",".join([_num(p.x), _num(p.y), _num(sx), _num(sy), "1" if p.active else "0",
                               _num(dx), _num(dy), _num(dist)]))
    return "\n".join(lines) + "\n"


def read_points(text, source_gt=None):
    """Punktdatei lesen: ``(Passpunkte, WKT des Bezugssystems oder "")``.

    Liest auch das ältere Format ohne Kopfzeilen und mit Tabulatoren oder Leerzeichen.
    Fehlerhafte Zeilen sind ein ``ValueError`` mit Zeilennummer.
    """
    points = []
    crs = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(CRS_PREFIX.strip()):
            crs = line[len(CRS_PREFIX.strip()):].strip()
            continue
        if line.startswith("#") or line.lower().startswith("mapx"):
            continue
        if "," in line:
            parts = [s.strip() for s in line.split(",")]
        else:
            parts = line.split()
        if len(parts) < 4:
            raise ValueError("line %d: expected at least 4 values" % number)
        try:
            x, y, sx, sy = (float(v) for v in parts[:4])
        except ValueError:
            raise ValueError("line %d: not a number" % number)
        enabled = len(parts) < 5 or parts[4].strip() not in ("0", "false", "False")
        col, row = pixel_coords(sx, sy, source_gt)
        points.append(ControlPoint(col, row, x, y, enabled))
    return points, crs


# -- Worldfile ------------------------------------------------------------

def world_file_text(gt):
    """Worldfile zu einer Geotransformation (bezogen auf die Pixelmitte, sechs Zeilen A, D, B, E, C, F)."""
    x0, a, b, y0, d, e = gt
    c = x0 + a / 2.0 + b / 2.0
    f = y0 + d / 2.0 + e / 2.0
    return "\n".join(repr(float(v)) for v in (a, d, b, e, c, f)) + "\n"


def read_world_file(text):
    """Geotransformation aus einem Worldfile."""
    vals = [float(v) for v in text.split()]
    if len(vals) != 6:
        raise ValueError("a world file has 6 values")
    a, d, b, e, c, f = vals
    return (c - a / 2.0 - b / 2.0, a, b, f - d / 2.0 - e / 2.0, d, e)


def world_file_suffix(path):
    """Endung des Worldfiles nach Konvention (``bild.tif`` -> ``.tfw``, ``bild.jpeg`` -> ``.jgw``), sonst ``.wld``."""
    dot = path.rfind(".")
    slash = max(path.rfind("/"), path.rfind("\\"))
    ext = path[dot + 1:] if dot > slash else ""
    if len(ext) < 2:
        return ".wld"
    return "." + ext[0] + ext[-1] + "w"


# -- Verlauf --------------------------------------------------------------

class History(object):
    """Verlauf einer Sitzung: Zustände (beliebige unveränderliche Werte) mit Rückgängig und Wiederholen."""

    def __init__(self, initial, limit=200):
        self._done = [initial]
        self._undone = []
        self._limit = limit

    @property
    def current(self):
        return self._done[-1]

    def push(self, state):
        if state == self._done[-1]:
            return False
        self._done.append(state)
        if len(self._done) > self._limit:
            del self._done[0]
        self._undone = []
        return True

    def can_undo(self):
        return len(self._done) > 1

    def can_redo(self):
        return bool(self._undone)

    def undo(self):
        if self.can_undo():
            self._undone.append(self._done.pop())
        return self.current

    def redo(self):
        if self._undone:
            self._done.append(self._undone.pop())
        return self.current
