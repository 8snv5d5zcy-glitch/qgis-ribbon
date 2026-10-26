"""Erzeugt das Icon-Set „Kontur“ (qgis_ribbon/config/icons/kontur.yaml).

Aufruf aus dem Projektordner:  python tools/kontur_icons.py

Die Motive sind hier aus Bausteinen zusammengesetzt (Grundformen, Marken
für Plus/Stern/Pfeil, Auswahl-Cursor), damit gleiche Ideen gleich aussehen.
Die YAML-Datei ist das Ergebnis und wird mit eingecheckt; Änderungen an
Motiven bitte hier vornehmen und die Datei neu erzeugen.

Rollen je Motiv (siehe core/icons.py): f = Akzentfläche, k = Kontur,
a = Akzentdetail. Raster 24 × 24, Inhalt zwischen 2 und 22.
"""

import io
import math
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "qgis_ribbon", "config", "icons", "kontur.yaml")


# Elemente
def P(d, extra=""):
    return '<path d="%s"%s/>' % (d, extra)


def R(x, y, w, h, rx=0, extra=""):
    r = ' rx="%s"' % rx if rx else ""
    return '<rect x="%s" y="%s" width="%s" height="%s"%s%s/>' % (x, y, w, h, r, extra)


def C(cx, cy, r, extra=""):
    return '<circle cx="%s" cy="%s" r="%s"%s/>' % (cx, cy, r, extra)


def E(cx, cy, rx, ry, extra=""):
    return '<ellipse cx="%s" cy="%s" rx="%s" ry="%s"%s/>' % (cx, cy, rx, ry, extra)


DASH = ' stroke-dasharray="2.4 2.2"'
EVENODD = ' fill-rule="evenodd"'


def M(k=(), a=(), f=()):
    return {"f": list(f), "k": list(k), "a": list(a)}


def add(*motifs):
    out = M()
    for m in motifs:
        for role in "fka":
            out[role] += m[role]
    return out


def shrink(m, s=0.78, dx=0.6, dy=0.6):
    """Motiv verkleinert nach oben links (Platz für eine Marke unten rechts)."""
    t = ' transform="translate(%s %s) scale(%s)"' % (dx, dy, s)
    return {role: [el.replace("/>", t + "/>") for el in m[role]] for role in m}


def badge(m, b):
    return add(shrink(m), b)


# Marken (unten rechts, Mitte 18,5/18,5)
PLUS = M(a=[P("M18.5 14.5v8M14.5 18.5h8")])
STAR = M(a=[P("M18.5 13.8l1.3 3.4 3.4 1.3-3.4 1.3-1.3 3.4-1.3-3.4-3.4-1.3 3.4-1.3z")])
CROSS = M(a=[P("M15.5 15.5l6 6M21.5 15.5l-6 6")])
CHECK = M(a=[P("M14.8 18.6l2.6 2.6 5-5.6")])
OUT_ARROW = M(a=[P("M15 22l7-7M16.5 15H22v5.5")])
IN_ARROW = M(a=[P("M22 15l-7 7M15 16.5V22h5.5")])
DOWN_ARROW = M(a=[P("M18.5 14v8M15 18.5l3.5 3.5 3.5-3.5")])
LINK = M(a=[P("M17.2 20.8l-.9.9a2.1 2.1 0 0 1-3-3l1.8-1.8a2.1 2.1 0 0 1 3 0"),
            P("M19.8 16.2l.9-.9a2.1 2.1 0 0 1 3 3l-1.8 1.8a2.1 2.1 0 0 1-3 0")])
DOTS = M(a=[P("M15 18.5h.1M18.5 18.5h.1M22 18.5h.1")])
PIN = M(a=[P("M18.5 22.5s-3.6-3.4-3.6-6a3.6 3.6 0 0 1 7.2 0c0 2.6-3.6 6-3.6 6z"), C(18.5, 16.5, 1.1)])
UP_SMALL = M(a=[P("M18.5 22v-7M15.5 18l3-3 3 3")])
DOWN_SMALL = M(a=[P("M18.5 15v7M15.5 19l3 3 3-3")])

# Auswahl-Cursor (Pfeil unten rechts, gefüllt)
CURSOR_D = "M13.5 12.5l8.5 3.4-3.6 1.3-1.3 3.6z"
CURSOR = M(a=[P(CURSOR_D)], f=[P(CURSOR_D)])


# Grundformen
def gear():
    pts = []
    for i in range(8):
        th = math.radians(i * 45)
        for dang, r in ((-15, 6.6), (-9, 9.2), (9, 9.2), (15, 6.6)):
            a = th + math.radians(dang)
            pts.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
    d = "M" + " L".join("%.2f %.2f" % p for p in pts) + "z"
    return M(k=[P(d)], a=[C(12, 12, 2.8)], f=[C(12, 12, 6.6)])


def star_path(cx=12, cy=12.4, ro=9.2, ri=4.2):
    pts = []
    for i in range(10):
        r = ro if i % 2 == 0 else ri
        a = math.radians(-90 + i * 36)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return "M" + " L".join("%.2f %.2f" % p for p in pts) + "z"


def sun():
    rays = []
    for i in range(8):
        a = math.radians(i * 45)
        rays.append("M%.2f %.2fL%.2f %.2f" % (12 + 6.6 * math.cos(a), 12 + 6.6 * math.sin(a),
                                              12 + 9.2 * math.cos(a), 12 + 9.2 * math.sin(a)))
    return M(k=[C(12, 12, 4)], a=["<path d=\"%s\"/>" % "".join(rays)], f=[C(12, 12, 4)])


LAYERS_TOP = "M12 3.5l9 4.5-9 4.5-9-4.5z"
LAYERS = M(k=[P(LAYERS_TOP), P("M3 12.5l9 4.5 9-4.5"), P("M3 16.8l9 4.5 9-4.5")], f=[P(LAYERS_TOP)])
MAGNIFIER = M(k=[C(10.5, 10.5, 6.5), P("M15.3 15.3l5.2 5.2")], f=[C(10.5, 10.5, 6.5)])
TABLE = M(k=[R(3, 4, 18, 16, 2), P("M3 9.5h18M3 14.8h18M9.5 9.5V20")], f=[P("M3 6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3.5H3z")])
DOC = M(k=[P("M6 2.8h8.2L19 7.6V19a2 2 0 0 1-2 2H6.5a2 2 0 0 1-2-2V4.8a2 2 0 0 1 1.5-2"), P("M14 3v4.8h5")])
FOLDER_D = "M3 7a2 2 0 0 1 2-2h4.2l2 2.2H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
FOLDER = M(k=[P(FOLDER_D)], f=[P(FOLDER_D)])
DISK_D = "M5 3h11.2L20 6.8V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 1-2z"
DISK = M(k=[P(DISK_D), P("M8 3.2v4.6h7V3.2")], a=[P("M7.5 20.8v-6.3h9v6.3")], f=[P(DISK_D)])
DB = M(k=[E(12, 6, 7.5, 3), P("M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"), P("M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3")],
       f=[E(12, 6, 7.5, 3)])
CUBE = M(k=[P("M12 2.8l8.2 4.6v9.2L12 21.2l-8.2-4.6V7.4z"), P("M3.8 7.4L12 12l8.2-4.6M12 12v9.2")],
         f=[P("M12 2.8l8.2 4.6L12 12 3.8 7.4z")])
SERVER = M(k=[R(3.5, 3.5, 17, 7, 1.8), R(3.5, 13.5, 17, 7, 1.8)], a=[P("M7.5 7h.1M7.5 17h.1M11 7h6M11 17h6")],
           f=[R(3.5, 3.5, 17, 7, 1.8)])
MAP_D = "M3 6.2l6-2.2 6 2.2 6-2.2v13.8l-6 2.2-6-2.2-6 2.2z"
MAP = M(k=[P(MAP_D), P("M9 4v13.8M15 6.2V20")], f=[P("M9 4l6 2.2V20l-6-2.2z")])
PAGE = M(k=[R(4, 2.8, 16, 18.4, 2)], a=[P("M7.5 16.5h5M7.5 19h3")], f=[R(7, 6, 10, 7.5, 1)])
PAGE_K = M(k=[R(4, 2.8, 16, 18.4, 2), R(7, 6, 10, 7.5, 1)], a=[P("M7.5 16.8h6")], f=[R(7, 6, 10, 7.5, 1)])
WINDOW = M(k=[R(2.8, 4, 18.4, 16, 2), P("M2.8 8.5h18.4")], a=[P("M5.5 6.3h.1M8 6.3h.1")], f=[P("M2.8 6a2 2 0 0 1 2-2h14.4a2 2 0 0 1 2 2v2.5H2.8z")])
TOOLBOX_D = "M3 10a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
TOOLBOX = M(k=[P(TOOLBOX_D), P("M9 8V5.5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5.5V8"), P("M3 13.5h18")],
            a=[P("M10.5 12v3h3v-3")], f=[P(TOOLBOX_D)])
SLIDERS = M(k=[P("M4 7h8.5M17.5 7H20M4 17h2.5M11.5 17H20")], a=[C(15, 7, 2.4), C(9, 17, 2.4)])
FUNNEL_D = "M3.5 4.5h17l-6.6 7.8v6.2L10 20.5v-8.2z"
FUNNEL = M(k=[P(FUNNEL_D)], f=[P(FUNNEL_D)])
PENCIL_D = "M15.6 4.4l4 4L9 19H5v-4z"
PENCIL = M(k=[P(PENCIL_D), P("M13.4 6.6l4 4")], a=[P("M5 15l4 4")], f=[P(PENCIL_D)])
CLIP_D = "M7 4.5H5.8A1.8 1.8 0 0 0 4 6.3v13a1.8 1.8 0 0 0 1.8 1.8h12.4a1.8 1.8 0 0 0 1.8-1.8v-13a1.8 1.8 0 0 0-1.8-1.8H17"
CLIPBOARD = M(k=[P(CLIP_D), R(8, 2.8, 8, 3.6, 1)], a=[P("M8 11.5h8M8 15.5h5")], f=[P(CLIP_D + "z")])
SCISSORS = M(k=[C(6.5, 17.5, 3), C(17.5, 17.5, 3), P("M8.6 15.3L17.5 3M15.4 15.3L6.5 3")], f=[C(6.5, 17.5, 3), C(17.5, 17.5, 3)])
COPY = M(k=[R(8.5, 8.5, 12.5, 12.5, 2), P("M15.5 8.5V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8.5a2 2 0 0 0 2 2h3.5")],
         a=[P("M11.8 12.8h6M11.8 16.5h4")], f=[R(8.5, 8.5, 12.5, 12.5, 2)])
TRASH = M(k=[P("M4 6.5h16M9.5 3.5h5"), P("M6 6.5l1 13a1.5 1.5 0 0 0 1.5 1.4h7a1.5 1.5 0 0 0 1.5-1.4l1-13")],
          a=[P("M10 10.5v6.5M14 10.5v6.5")], f=[P("M6 6.5h12l-1 13a1.5 1.5 0 0 1-1.5 1.4h-7A1.5 1.5 0 0 1 7 19.5z")])
EYE_D = "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"
EYE = M(k=[P(EYE_D)], a=[C(12, 12, 3)], f=[P(EYE_D)])
STAR_M = M(k=[P(star_path())], f=[P(star_path())])
BOOKMARK_D = "M6.5 3h11v18l-5.5-4.2L6.5 21z"
BOOKMARK = M(k=[P(BOOKMARK_D)], a=[P("M9.5 8h5")], f=[P(BOOKMARK_D)])
TERMINAL = M(k=[R(2.8, 4, 18.4, 16, 2)], a=[P("M7 9.5l3 2.5-3 2.5M12 15h5")], f=[R(2.8, 4, 18.4, 16, 2)])
CODE = M(k=[R(2.8, 4, 18.4, 16, 2)], a=[P("M9 9l-3 3 3 3M15 9l3 3-3 3M13 8.5l-2 7")])
CLOCK = M(k=[P("M4.2 12a7.8 7.8 0 1 0 2.3-5.5"), P("M4 4.5V8h3.5")], a=[P("M12 8v4.2l2.8 1.8")], f=[C(12, 12, 7.8)])
PLUG = M(k=[P("M9 3v4.5M15 3v4.5"), P("M6 7.5h12V11a6 6 0 0 1-12 0z"), P("M12 17v4")], f=[P("M6 7.5h12V11a6 6 0 0 1-12 0z")])
GRID = M(k=[R(3, 3, 18, 18, 2), P("M3 9h18M3 15h18M9 3v18M15 3v18")], f=[R(9, 9, 6, 6)])
HISTO = M(k=[P("M3.5 20.5h17")], a=[P("M6.5 20.5v-5M10 20.5V8M13.5 20.5V5M17 20.5v-7")])
PALETTE_D = ("M12 3a9 9 0 1 0 0 18c1.4 0 2-.9 2-1.9 0-1.2-1-1.6-1-2.6 0-1 .8-1.6 1.9-1.6H17"
             "a4 4 0 0 0 4-4C21 6.6 17 3 12 3z")
PALETTE = M(k=[P(PALETTE_D)], a=[C(7.6, 11.5, 1.3), C(9.8, 7.2, 1.3), C(14.6, 7, 1.3)], f=[P(PALETTE_D)])
CATEGORIES = M(k=[R(3, 3, 8, 8, 1.8), R(13, 3, 8, 8, 1.8), R(3, 13, 8, 8, 1.8)], a=[C(17, 17, 4)], f=[R(3, 3, 8, 8, 1.8)])
LETTER_A = P("M4 19.5L9.5 5h1L16 19.5M6.2 14h7.6")
BUBBLE_D = "M4 4.5h16a1 1 0 0 1 1 1V15a1 1 0 0 1-1 1h-9l-4.5 4v-4H4a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1z"
BUBBLE = M(k=[P(BUBBLE_D)], a=[P("M7.5 8.8h9M7.5 12h5.5")], f=[P(BUBBLE_D)])
FRAME = P("M3.5 8.5v-5h5M15.5 3.5h5v5M20.5 15.5v5h-5M8.5 20.5h-5v-5")
POLY_D = "M4 17.5L7.8 5.5l9.6 3 2.6 9.5-9 3z"
POLY = M(k=[P(POLY_D)], f=[P(POLY_D)])
RULER = M(k=[R(2.5, 7.5, 19, 9, 1.8)], a=[P("M6.5 7.5v3.5M10.2 7.5v5M14 7.5v3.5M17.8 7.5v5")], f=[R(2.5, 7.5, 19, 9, 1.8)])
INFO = M(k=[C(12, 12, 9)], a=[P("M12 11v6M12 7.6v.1")], f=[C(12, 12, 9)])
LIST_BULLETS = M(k=[P("M9 6.5h11M9 12h11M9 17.5h11")], a=[C(5, 6.5, 1.3), C(5, 12, 1.3), C(5, 17.5, 1.3)])


def selection(shape):
    """Auswahlform gestrichelt plus Cursor."""
    return add(M(k=[shape.replace("/>", DASH + "/>")]), CURSOR)


def text_a(*extra):
    return add(M(k=[LETTER_A]), *extra)


# Motive
MOTIFS = {
    # Oberfläche
    "ui_launcher": M(k=[P("M8.5 8.5l8 8")], a=[P("M17 10.5v6.5h-6.5")]),
    "ui_chevron_up": M(k=[P("M6.5 14.5l5.5-5.5 5.5 5.5")]),
    "ui_chevron_down": M(k=[P("M6.5 9.5l5.5 5.5 5.5-5.5")]),
    "ui_pin": M(k=[P("M9 3.5h6l-.8 6 3.3 3.3H6.5l3.3-3.3z"), P("M12 12.8v7.7")]),
    # Ribbon-Editor
    "ui_auge": M(k=[P("M2.8 12s3.4-6.2 9.2-6.2 9.2 6.2 9.2 6.2-3.4 6.2-9.2 6.2S2.8 12 2.8 12z")],
                 a=[C(12, 12, 2.8)], f=[C(12, 12, 2.8)]),
    "ui_auge_aus": M(k=[P("M2.8 12s3.4-6.2 9.2-6.2 9.2 6.2 9.2 6.2-3.4 6.2-9.2 6.2S2.8 12 2.8 12z"),
                        P("M4.5 19.5l15-15")]),
    "ui_plus": M(k=[P("M12 5v14M5 12h14")]),
    "ui_griff": M(f=[C(9, 7, 1.4), C(15, 7, 1.4), C(9, 12, 1.4), C(15, 12, 1.4), C(9, 17, 1.4),
                     C(15, 17, 1.4)], a=[C(9, 7, 1.4), C(15, 7, 1.4), C(9, 12, 1.4), C(15, 12, 1.4),
                                         C(9, 17, 1.4), C(15, 17, 1.4)]),
    "ui_mehr": M(k=[C(6, 12, 1.2), C(12, 12, 1.2), C(18, 12, 1.2)]),
    # Anleitung: Fragezeichen im Kreis
    "ui_hilfe": M(k=[C(12, 12, 8.5), P("M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.6")], a=[C(12, 16.9, .9)]),
    "suchen": MAGNIFIER,

    # Navigation
    "erkunden": M(k=[P("M12 3v18M3 12h18"), P("M9 5.8L12 3l3 2.8M9 18.2l3 2.8 3-2.8M5.8 9L3 12l2.8 3M18.2 9L21 12l-2.8 3")],
                  a=[C(12, 12, 2.6)], f=[C(12, 12, 2.6)]),
    "zoom_in": add(MAGNIFIER, M(a=[P("M10.5 7.8v5.4M7.8 10.5h5.4")])),
    "zoom_out": add(MAGNIFIER, M(a=[P("M7.8 10.5h5.4")])),
    "volle_ausdehnung": M(k=[FRAME], a=[C(12, 12, 4.4), P("M7.6 12h8.8M12 7.6c-1.6 2.6-1.6 6.2 0 8.8M12 7.6c1.6 2.6 1.6 6.2 0 8.8")],
                          f=[C(12, 12, 4.4)]),
    "vorherige_ausdehnung": M(k=[FRAME], a=[P("M13.5 8l-4 4 4 4")], f=[R(7, 7, 10, 10, 1.5)]),
    "naechste_ausdehnung": M(k=[FRAME], a=[P("M10.5 8l4 4-4 4")], f=[R(7, 7, 10, 10, 1.5)]),
    "zur_auswahl": M(k=[FRAME], a=[R(8, 8, 8, 8, 1, DASH)], f=[R(8, 8, 8, 8, 1)]),
    "gehe_zu_xy": M(k=[C(12, 12, 7), P("M12 2.5V6M12 18v3.5M2.5 12H6M18 12h3.5")], a=[C(12, 12, 2.2)], f=[C(12, 12, 7)]),
    "lesezeichen": add(M(k=[P(BOOKMARK_D)], f=[P(BOOKMARK_D)]),
                       M(a=[P(star_path(12, 10.3, 3.6, 1.6))])),
    "lesezeichen_neu": badge(BOOKMARK, PLUS),
    "lesezeichen_verwalten": badge(BOOKMARK, DOTS),
    "drehung": M(k=[P("M19.8 12a7.8 7.8 0 1 1-2.3-5.5"), P("M20 4.5V8h-3.5")],
                 a=[P("M12 7.8l2.6 7.4-2.6-1.6-2.6 1.6z")], f=[P("M12 7.8l2.6 7.4-2.6-1.6-2.6 1.6z")]),
    "lupe": add(MAGNIFIER, M(a=[P("M7.2 12l2-2.2 2 1.6 2.2-2.6")])),
    "abfrage": INFO,
    "abfragbare_layer": badge(LAYERS, M(a=[C(18.5, 18.5, 4), P("M18.5 18v2.6M18.5 16.4v.1")])),
    "messen": RULER,
    "messwerkzeuge": add(M(k=[P("M4 20L20 4"), P("M4 20h16")]), M(a=[P("M14 20a10 10 0 0 0-2.9-7.1")])),
    "einstellungen": gear(),
    "optionen": SLIDERS,

    # Auswahl
    "auswahl_rechteck": add(selection(R(3, 3.5, 14, 11, 1.2)), M(f=[R(3, 3.5, 14, 11, 1.2)])),
    "auswahl_polygon": add(selection(P("M3.5 9l6-5.5 8.5 3.5-1 6.5-9 2.5z")), M(f=[P("M3.5 9l6-5.5 8.5 3.5-1 6.5-9 2.5z")])),
    "auswahl_freihand": add(selection(P("M5 14.5C2 11 3.5 4.5 9.5 4c5.5-.5 9.5 2.5 7.5 7")), M()),
    "auswahl_kreis": add(selection(C(10, 9.5, 6.5)), M(f=[C(10, 9.5, 6.5)])),
    "auswahl_linie": add(selection(P("M3 15l4.5-8 4.5 4 5.5-7")), M()),
    "nach_attributen": M(k=TABLE["k"], a=[R(9.5, 9.5, 11.5, 5.3)], f=[R(9.5, 9.5, 11.5, 5.3)]),
    "nach_lage": M(k=[R(3, 3, 11, 11, 1.8)], a=[C(15.5, 15.5, 5.5)], f=[C(15.5, 15.5, 5.5)]),
    "attribute": M(k=[R(4, 3, 16, 18, 2), P("M8 8h2.5M8 12h2.5M8 16h2.5")], a=[P("M13 8h3M13 12h3M13 16h3")], f=[R(4, 3, 16, 18, 2)]),
    "auswahl_aufheben": M(k=[R(3.5, 3.5, 17, 17, 2, DASH)], a=[P("M9 9l6 6M15 9l-6 6")]),
    "alle_auswaehlen": M(k=[R(3.5, 3.5, 17, 17, 2, DASH)], a=[P("M8 12.2l2.8 2.8 5.2-6")], f=[R(3.5, 3.5, 17, 17, 2)]),
    "auswahl_umkehren": M(k=[R(3.5, 3.5, 17, 17, 2, DASH)], a=[P("M8 9.5h8.5L14 7M16 14.5H7.5L10 17")], f=[P("M3.5 12V5.5a2 2 0 0 1 2-2H12v8.5z")]),
    "layer_aus_auswahl": badge(LAYERS, PLUS),
    "tabelle_auswahl": M(k=TABLE["k"], a=[P("M3 12.2h18")], f=TABLE["f"] + [R(3, 9.5, 18, 5.3)]),

    # Zwischenablage
    "einfuegen": CLIPBOARD,
    "einfuegen_als": badge(CLIPBOARD, DOTS),
    "stil_einfuegen": badge(CLIPBOARD, M(a=[P("M18.5 13.5s3.5 3.6 3.5 5.6a3.5 3.5 0 0 1-7 0c0-2 3.5-5.6 3.5-5.6z")])),
    "ausschneiden": SCISSORS,
    "kopieren": COPY,
    "pfad_kopieren": M(k=[P(FOLDER_D)], a=[P("M9 15.5l2.6-5M13 15.5l2.6-5")], f=[P(FOLDER_D)]),

    # Bearbeiten
    "bearbeiten": PENCIL,
    "speichern": DISK,
    "speichern_als": add(M(k=DISK["k"], f=DISK["f"]), M(a=[P("M8.5 17.5h.1M12 17.5h.1M15.5 17.5h.1")])),
    "verwerfen": add(DOC, M(a=[P("M9.5 11.5l5 5M14.5 11.5l-5 5")])),
    "rueckgaengig": M(k=[P("M4.5 9.5h10a5.5 5.5 0 0 1 0 11h-4")], a=[P("M8.5 5.5l-4 4 4 4")]),
    "wiederholen": M(k=[P("M19.5 9.5h-10a5.5 5.5 0 0 0 0 11h4")], a=[P("M15.5 5.5l4 4-4 4")]),
    "erstellen": badge(POLY, PLUS),
    "aendern": add(M(k=[P("M5 18.5L8 6l10.5 4.5-2.5 8z")], f=[P("M5 18.5L8 6l10.5 4.5-2.5 8z")]),
                   M(a=[R(6.4, 4.4, 3.2, 3.2, .6), R(16.9, 8.9, 3.2, 3.2, .6), R(14.4, 16.9, 3.2, 3.2, .6), R(3.4, 16.9, 3.2, 3.2, .6)])),
    "loeschen": TRASH,
    "einrasten": M(k=[P("M5 4h4.5v8.5a2.5 2.5 0 0 0 5 0V4H19v8.5a7 7 0 0 1-14 0z")], a=[P("M5 8.5h4.5M14.5 8.5H19")],
                   f=[P("M5 4h4.5v8.5a2.5 2.5 0 0 0 5 0V4H19v8.5a7 7 0 0 1-14 0z")]),
    "topologie": M(k=[P("M3 18.5L9 4.5l5.5 8z"), P("M9 4.5l11.5 2.5-6 5.5")], a=[P("M9 4.5l5.5 8"), C(9, 4.5, 1.6), C(14.5, 12.5, 1.6)],
                   f=[P("M3 18.5L9 4.5l5.5 8z")]),
    "z_wert": M(k=[P("M12 20.5V4.5M9 7.5l3-3 3 3"), P("M12 20.5l-8-3.8M12 20.5l8-3.8")], a=[C(12, 11.5, 2)], f=[C(12, 11.5, 2)]),
    "stuetzpunkte": add(M(k=[P("M3.5 17l5.5-9 9 3.5")]), M(a=[R(2, 15.5, 3, 3, .6), R(7.5, 6.5, 3, 3, .6), R(17, 10, 3, 3, .6)]),
                        M(k=[P("M14.5 14.5l6 2.3-2.5 1-1 2.5z")])),
    "abschneiden": M(k=[P("M17 3v18"), P("M3 12h8.5")], a=[P("M11.5 12H17", DASH), P("M14 9.5l3 2.5-3 2.5")]),
    "attribute_zusammen": M(k=[R(3, 3.5, 7, 7, 1.2), R(3, 13.5, 7, 7, 1.2)], a=[P("M10 7h3.5v10H10M13.5 12H20.5M18 9.5l2.5 2.5-2.5 2.5")],
                            f=[R(3, 3.5, 7, 7, 1.2), R(3, 13.5, 7, 7, 1.2)]),
    "drehen": M(k=[R(3.5, 9.5, 11, 11, 1.5)], a=[P("M9 4.5a10 10 0 0 1 11 10"), P("M17.5 12.5l2.5 2.5 2.5-2.5")], f=[R(3.5, 9.5, 11, 11, 1.5)]),
    "kopieren_verschieben": M(k=[R(3, 3, 8.5, 8.5, 1.5), R(12.5, 12.5, 8.5, 8.5, 1.5)], a=[P("M9.5 14.5l4-4M10 10.5h3.5V14")],
                              f=[R(12.5, 12.5, 8.5, 8.5, 1.5)]),
    "verschieben": M(k=[R(3, 3, 8.5, 8.5, 1.5, DASH), R(12.5, 12.5, 8.5, 8.5, 1.5)], a=[P("M9.5 14.5l4-4M10 10.5h3.5V14")],
                     f=[R(12.5, 12.5, 8.5, 8.5, 1.5)]),
    "linie_umkehren": M(k=[P("M5 17c4.5 0 4-10 8-10s3.5 10 7 10")], a=[P("M8 14l-3 3 3 3")]),
    "linie_versetzen": M(k=[P("M3.5 13.5c4-6.5 13-6.5 17 0")], a=[P("M3.5 19.5c4-6.5 13-6.5 17 0", DASH)]),
    "ring_fuellen": M(k=[P("M3 12l4.5-8h9L21 12l-4.5 8h-9z"), C(12, 12, 3.6)], a=[C(12, 12, 3.6)], f=[C(12, 12, 3.6)]),
    "ring_hinzufuegen": M(k=[P("M3 12l4.5-8h9L21 12l-4.5 8h-9z")], a=[C(12, 12, 3.6, DASH)],
                          f=[P("M3 12l4.5-8h9L21 12l-4.5 8h-9zM15.6 12a3.6 3.6 0 1 0-7.2 0 3.6 3.6 0 1 0 7.2 0z", EVENODD)]),
    "ring_loeschen": M(k=[P("M3 12l4.5-8h9L21 12l-4.5 8h-9z")], a=[P("M10 10l4 4M14 10l-4 4")], f=[P("M3 12l4.5-8h9L21 12l-4.5 8h-9z")]),
    "skalieren": M(k=[R(3, 12, 9, 9, 1.5), P("M3 8.5V4.5A1.5 1.5 0 0 1 4.5 3h15A1.5 1.5 0 0 1 21 4.5v15a1.5 1.5 0 0 1-1.5 1.5h-4", DASH)],
                   a=[P("M12 12l6-6M13 6h5v5")], f=[R(3, 12, 9, 9, 1.5)]),
    "teil_hinzufuegen": add(M(k=[R(3, 3, 9, 9, 1.5)], f=[R(3, 3, 9, 9, 1.5)]), PLUS),
    "teil_loeschen": add(M(k=[R(3, 3, 9, 9, 1.5)], f=[R(3, 3, 9, 9, 1.5)]), CROSS),
    "teile_zerlegen": M(k=[R(3, 3, 7.5, 7.5, 1.4), R(13.5, 13.5, 7.5, 7.5, 1.4)], a=[P("M13.5 3.5h7v7M3.5 13.5v7h7", DASH)],
                        f=[R(3, 3, 7.5, 7.5, 1.4), R(13.5, 13.5, 7.5, 7.5, 1.4)]),
    "teilen": add(POLY, M(a=[P("M5 21L20 3")])),
    "umformen": M(k=[P("M4 17.5L7.8 5.5l9.6 3 2.6 9.5")], a=[P("M20 18c-3 4-9 4-10 3S6 19 4 17.5")], f=[P(POLY_D)]),
    "vereinfachen": M(k=[P("M3 16c1.5-3 2.5 1 4-2s2-5 3.5-3 2 4 3.5 1 3-6 4.5-4 3 3 3 3", DASH)], a=[P("M3 16l7-8.5 11 3.5")]),
    "zusammenfuehren": M(k=[P("M4 4h9v6h7v10h-9v-6H4z")], a=[P("M11 10h2v4h-2", DASH)], f=[P("M4 4h9v6h7v10h-9v-6H4z")]),

    # Analyse
    "puffer": M(k=[P("M8.5 15.5l7-7")], a=[P("M5.4 12.6l7.2-7.2a4.1 4.1 0 0 1 5.8 5.8l-7.2 7.2a4.1 4.1 0 0 1-5.8-5.8z")],
                f=[P("M5.4 12.6l7.2-7.2a4.1 4.1 0 0 1 5.8 5.8l-7.2 7.2a4.1 4.1 0 0 1-5.8-5.8z")]),
    "zuschneiden": M(k=[P("M3.5 15l5-11.5 12 5-4 12z", DASH)], a=[R(7, 7, 10, 10, 1.5)], f=[R(7, 7, 10, 10, 1.5)]),
    "verschneiden": M(k=[C(9, 12, 6), C(15, 12, 6)], a=[P("M12 6.8a6 6 0 0 1 0 10.4 6 6 0 0 1 0-10.4z")],
                      f=[P("M12 6.8a6 6 0 0 1 0 10.4 6 6 0 0 1 0-10.4z")]),
    "vereinigen": M(k=[P("M12 6.8a6 6 0 1 0 0 10.4 6 6 0 1 0 0-10.4z")], a=[P("M12 6.8a6 6 0 0 1 0 10.4 6 6 0 0 1 0-10.4z", DASH)],
                    f=[P("M12 6.8a6 6 0 1 0 0 10.4 6 6 0 1 0 0-10.4z")]),
    "differenz": M(k=[P("M12 6.8a6 6 0 1 0 0 10.4 6 6 0 0 1 0-10.4z")], a=[P("M12 6.8a6 6 0 1 1 0 10.4", DASH)],
                   f=[P("M12 6.8a6 6 0 1 0 0 10.4 6 6 0 0 1 0-10.4z")]),
    "aufloesen": M(k=[P("M3.5 4h17v16h-17z")], a=[P("M12 4v16M3.5 12H12", DASH)], f=[P("M3.5 4h17v16h-17z")]),
    "zentroide": add(POLY, M(a=[C(12, 12.8, 2.2)])),
    "punkte_zaehlen": add(POLY, M(a=[C(9.5, 10, 1.3), C(14.5, 11.5, 1.3), C(11, 15.5, 1.3)])),
    "layer_zusammen": M(k=[P("M8 3.5l5 2.5-5 2.5-5-2.5z"), P("M16 3.5l5 2.5-5 2.5-5-2.5z"), P("M12 13l8 4-8 4-8-4z")],
                        a=[P("M8 10.5l3 3M16 10.5l-3 3")], f=[P("M12 13l8 4-8 4-8-4z")]),
    "raeumlich_verknuepfen": M(k=[C(7.5, 8, 4.5), R(12.5, 12, 8.5, 8.5, 1.4), P("M12.5 16.2H21")], a=[P("M10.5 11.5l3 3")],
                               f=[C(7.5, 8, 4.5)]),
    "werkzeugkasten": TOOLBOX,
    "galerie_anpassen": add(shrink(M(k=[R(3, 3, 7.5, 7.5, 1.4), R(13.5, 3, 7.5, 7.5, 1.4), R(3, 13.5, 7.5, 7.5, 1.4), R(13.5, 13.5, 7.5, 7.5, 1.4)],
                                     f=[R(3, 3, 7.5, 7.5, 1.4)])),
                            M(a=[P("M19.8 13.2l2.4 2.4-5.6 5.6h-2.4v-2.4z")])),
    "galerie_groesse": M(k=[R(3, 3, 7.5, 7.5, 1.4), R(13.5, 3, 7.5, 7.5, 1.4), R(3, 13.5, 7.5, 7.5, 1.4)],
                         a=[P("M14 20.5l6.5-6.5M16 14h4.5v4.5")], f=[R(3, 3, 7.5, 7.5, 1.4)]),
    "modell": M(k=[R(3, 3, 8, 5.5, 1.2), R(13, 15.5, 8, 5.5, 1.2)], a=[P("M7 8.5v5h10v2")], f=[R(3, 3, 8, 5.5, 1.2), R(13, 15.5, 8, 5.5, 1.2)]),
    "python": CODE,
    "konsole": TERMINAL,
    "verlauf": CLOCK,

    # Layer und Daten
    "daten_hinzufuegen": badge(LAYERS, PLUS),
    "vektorlayer": badge(M(k=[P(POLY_D)], a=[C(7.8, 5.5, 1.4), C(20, 18, 1.4)], f=[P(POLY_D)]), PLUS),
    "grundkarte": add(MAP, M(a=[P("M4.5 13c2-1.5 3-.5 4.5-1.5")])),
    "annotation": BUBBLE,
    "neuer_layer": badge(LAYERS, STAR),
    "geopackage": CUBE,
    "geopackage_layer": badge(CUBE, STAR),
    "datenbank": DB,
    "datenbank_neu": badge(DB, STAR),
    "datenbank_verbinden": badge(DB, LINK),
    "virtueller_layer": M(k=[P(LAYERS_TOP, DASH), P("M3 12.5l9 4.5 9-4.5", DASH), P("M3 16.8l9 4.5 9-4.5", DASH)],
                          a=[P("M9.5 7.5l2.5 1.2 2.5-1.2")]),
    "scratch_layer": badge(M(k=[P(LAYERS_TOP), P("M3 12.5l9 4.5 9-4.5")], f=[P(LAYERS_TOP)]), M(a=[P("M15 22l2-5 4.5-4.5 2 2-4.5 4.5z")])),
    "server": SERVER,
    "server_karte": badge(SERVER, M(a=[C(18.5, 18.5, 4), P("M14.5 18.5h8M18.5 14.5c-1.4 2.4-1.4 5.6 0 8M18.5 14.5c1.4 2.4 1.4 5.6 0 8")])),
    "server_objekte": badge(SERVER, M(a=[P("M14.8 21.5l1.6-6 5.4 1.5-1.4 4.5z")])),
    "server_katalog": badge(SERVER, STAR),
    "ordner": badge(FOLDER, LINK),
    "katalog": add(FOLDER, M(a=[P("M7.5 12h9M7.5 15.5h6")])),
    "favoriten": STAR_M,
    "inhalt": M(k=[P("M9.5 6.5h11M9.5 12h11M9.5 17.5h11")], a=[R(3.5, 5, 3, 3, .7), R(3.5, 10.5, 3, 3, .7), R(3.5, 16, 3, 3, .7)]),
    "layerdefinition": badge(LAYERS, DOWN_ARROW),
    "punkte_aus_tabelle": add(shrink(TABLE), PIN),
    "verbindungen": PLUG,
    "objekte_exportieren": add(shrink(TABLE), OUT_ARROW),
    "karte_exportieren": add(shrink(MAP), OUT_ARROW),
    "layout_exportieren": add(shrink(PAGE_K), OUT_ARROW),
    "pdf": add(DOC, M(a=[P("M8.5 12.5h7M8.5 16h4.5")], f=[P("M5 4.5h9v4h5v3H5z")])),
    "atlas": add(M(k=[R(7, 2.8, 13, 15.5, 2), P("M4.5 7v12a2.2 2.2 0 0 0 2.2 2.2H16")]), M(a=[P("M10 8h7M10 11.5h4.5")], f=[R(7, 2.8, 13, 15.5, 2)])),
    "bild": M(k=[R(3, 4, 18, 16, 2)], a=[P("M3.5 17.5l5-5.5 4 4 2.5-2.5 5.5 5"), C(15.5, 8.5, 1.6)], f=[R(3, 4, 18, 16, 2)]),
    "dxf": add(DOC, M(a=[P("M8 17l2.5-5 3 3 2.5-5"), C(8, 17, 1), C(16, 10, 1)])),
    "drucken": M(k=[P("M6.5 9V3.5h11V9"), R(3, 9, 18, 8, 2), P("M7 14h10v7H7z")], a=[P("M16.5 11.8h.1")], f=[R(3, 9, 18, 8, 2)]),
    "layout_neu": badge(PAGE_K, PLUS),
    "layoutverwaltung": M(k=[R(7, 2.8, 13, 15.5, 2), P("M4.5 7v12a2.2 2.2 0 0 0 2.2 2.2H16")], a=[R(9.5, 5.5, 8, 6, .8)], f=[R(9.5, 5.5, 8, 6, .8)]),
    "bericht": badge(add(DOC, M(a=[P("M8.5 11h7M8.5 14.5h7M8.5 18h4")])), PLUS),
    "kartenansicht_neu": badge(add(WINDOW, M(f=[P("M5 11l4-1.5 4 1.5 4-1.5v6l-4 1.5-4-1.5-4 1.5z")])), PLUS),
    "projekt_neu": badge(DOC, PLUS),
    "projekt_oeffnen": M(k=[P("M3 18.5V6.5a2 2 0 0 1 2-2h4l2 2.2h6a2 2 0 0 1 2 2V10")],
                         a=[P("M3 18.5L6 11h16l-3 7.5z")], f=[P("M3 18.5L6 11h16l-3 7.5z")]),

    # Tabelle
    "tabelle": TABLE,
    "felder": M(k=TABLE["k"], a=[P("M15.2 4v16")], f=[R(9.5, 4, 5.7, 16)]),
    "domaenen": LIST_BULLETS,
    "filter": FUNNEL,
    "quelle_filter": add(shrink(FUNNEL), M(a=[P("M14.5 18h8M14.5 21.5h5")])),
    "beziehungen": M(k=[R(3, 3, 8, 7, 1.4), R(13, 14, 8, 7, 1.4)], a=[P("M7 10v4.5h6.5M17 14V9.5h-6", DASH)], f=[R(3, 3, 8, 7, 1.4)]),
    "verknuepfung": M(k=[R(3, 4, 8, 16, 1.6), R(13, 4, 8, 16, 1.6)], a=[P("M7 9.5h10M7 14.5h10")], f=[R(3, 4, 8, 16, 1.6)]),

    # Darstellung
    "symbolisierung": PALETTE,
    "darstellungsart": CATEGORIES,
    "stil_importieren": badge(PALETTE, IN_ARROW),
    "stilverwaltung": M(k=[R(3, 3, 7, 18, 1.5), P("M10 8.5l5.8-3.4 3.5 6.2-9.3 5.4"), P("M10 15.5l9.2-.2v5.7H10")],
                        a=[C(6.5, 17, 1.4)], f=[R(3, 3, 7, 18, 1.5)]),
    "masken": M(k=[R(3, 3, 18, 18, 2)], a=[C(12, 12, 5)], f=[P("M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM17 12a5 5 0 1 0-10 0 5 5 0 1 0 10 0z", EVENODD)]),
    "deckkraft": M(k=[R(3, 3, 18, 18, 2)], a=[P("M3 12h18M12 3v18")], f=[R(3, 3, 9, 9), R(12, 12, 9, 9)]),
    "mischmodus": M(k=[C(12, 8.5, 5.2), C(8.5, 14.5, 5.2), C(15.5, 14.5, 5.2)], f=[C(12, 8.5, 5.2)]),
    "massstabsbereich": M(k=[P("M3 15.5h18M3 12.5v6M21 12.5v6")], a=[P("M7 15.5V9.5M12 15.5v-9M17 15.5V9.5")]),
    "massstab_entfernen": M(k=[P("M3 9.5h18M3 6.5v6M21 6.5v6")], a=[P("M9.5 15.5l5 5M14.5 15.5l-5 5")]),

    # Beschriftung
    "beschriften": text_a(M(a=[P("M17.5 9h4M17.5 13h4M17.5 17h4")])),
    "beschriftungsklasse": text_a(M(a=[C(19, 7, 1.2), C(19, 12, 1.2), C(19, 17, 1.2)])),
    "beschriftungsklasse_aktiv": add(shrink(M(k=[LETTER_A])), CHECK),
    "ausdruck": M(k=[P("M8 3.5c-3.5 3.5-3.5 13.5 0 17M16 3.5c3.5 3.5 3.5 13.5 0 17")], a=[P("M9.5 9l5 6M14.5 9l-5 6")]),
    "schriftfarbe": M(k=[P("M5 16.5L10.5 3.5h1L17 16.5M7 12h8")], a=[R(4, 19, 16, 2.5, .8)], f=[R(4, 19, 16, 2.5, .8)]),
    "schriftgroesse": M(k=[P("M3 19.5L8.5 5h1L15 19.5M5.2 14h7.6")], a=[P("M19 5v14M16.5 7.5L19 5l2.5 2.5M16.5 16.5L19 19l2.5-2.5")]),
    "schrift_groesser": add(shrink(M(k=[LETTER_A])), UP_SMALL),
    "schrift_kleiner": add(shrink(M(k=[LETTER_A])), DOWN_SMALL),
    "schriftart": M(k=[P("M3.5 5.5h11M9 5.5v14")], a=[P("M14 11.5h7M17.5 9v10.5")]),
    "schriftschnitt": M(k=[P("M7 4.5h6a3.8 3.8 0 0 1 0 7.5H7zM7 12h7a4 4 0 0 1 0 8H7z")], f=[P("M7 4.5h6a3.8 3.8 0 0 1 0 7.5H7zM7 12h7a4 4 0 0 1 0 8H7z")]),
    "beschriftungen_extrahieren": add(shrink(M(k=[LETTER_A])), OUT_ARROW),
    "nicht_platziert": add(M(k=[P("M4 19.5L9.5 5h1L16 19.5M6.2 14h7.6", DASH)]), M(a=[P("M16.5 4.5l5 5M21.5 4.5l-5 5")])),
    "platzierung": M(k=[C(12, 12, 2.4)], a=[R(3, 3, 6, 4, 1), R(15, 3, 6, 4, 1), R(3, 17, 6, 4, 1), R(15, 17, 6, 4, 1)],
                     f=[C(12, 12, 2.4), R(15, 3, 6, 4, 1)]),
    "textformat": M(k=[LETTER_A], a=[P("M15.5 14.5l5-5 1.6 1.6-5 5-2.3.7z")], f=[R(2.5, 3, 15.5, 18, 2)]),

    # Raster
    "georeferenzieren": add(shrink(GRID), PIN),
    "raster_anpassen": add(shrink(GRID), CHECK),
    "raster_transformieren": add(shrink(GRID), M(a=[P("M15 19.5a4 4 0 0 1 7-3.2"), P("M22.5 13.5v3h-3")])),
    "rasterrechner": M(k=[R(5, 2.8, 14, 18.4, 2), R(8, 5.8, 8, 4, .8)], a=[P("M8.8 13.5h.1M12 13.5h.1M15.2 13.5h.1M8.8 17.2h.1M12 17.2h.1M15.2 17.2h.1")],
                       f=[R(8, 5.8, 8, 4, .8)]),
    "resampling": M(k=[R(3, 3, 18, 18, 2), P("M3 12h18M12 3v18")], a=[P("M7.5 3v18M16.5 3v18M3 7.5h18M3 16.5h18", ' stroke-opacity="0.55"')],
                    f=[R(12, 3, 9, 9)]),
    "histogramm": HISTO,
    "streckung_ausschnitt": add(shrink(HISTO), M(k=[P("M14 15v-1.5h1.5M21 15v-1.5h-1.5M14 21v1.5h1.5M21 21v1.5h-1.5")])),
    "kanaele": M(k=[R(3, 3, 13, 10, 1.6), R(5.5, 6.5, 13, 10, 1.6), R(8, 10, 13, 10, 1.6)], f=[R(8, 10, 13, 10, 1.6)]),
    "gamma": M(k=[P("M4 3.5V20h16.5")], a=[P("M4 20C10.5 19.5 12 6 20.5 4.5")]),
    "helligkeit": sun(),
    "kontrast": M(k=[C(12, 12, 8.5)], f=[P("M12 3.5a8.5 8.5 0 0 1 0 17z")], a=[P("M12 3.5v17")]),

    # Ansicht
    "farbsehen": EYE,
    "deuteranopie": add(EYE, M(k=[P("M4 20L20 4")])),
}

# Befehls-ID -> Motiv
COMMANDS = {
    "abfragbare_layer": "abfragbare_layer", "abfrage_aktueller_layer": "abfrage", "abfrage_oberster_layer": "abfrage",
    "abfrage_sichtbare_layer": "abfrage", "abschneiden_ausdehnen": "abschneiden", "aendern": "aendern",
    "aenderungen_speichern": "speichern", "aenderungen_verwerfen": "verwerfen", "alle_auswaehlen": "alle_auswaehlen",
    "alle_werkzeuge": "stuetzpunkte", "analyse_galerie_anpassen": "galerie_anpassen", "arcgis_rest_server": "server_objekte",
    "atlas_als_pdf": "atlas", "attribute": "attribute", "attribute_zusammenfuehren": "attribute_zusammen",
    "attributtabelle": "tabelle", "aufloesen": "aufloesen", "ausschneiden": "ausschneiden",
    "auswahl_aufheben": "auswahl_aufheben", "auswahl_im_layer_aufheben": "auswahl_aufheben", "auswahl_linie": "auswahl_linie",
    "auswahl_umkehren": "auswahl_umkehren", "auswahloptionen": "optionen", "bearbeiten": "bearbeiten",
    "beschriftung_farbe": "schriftfarbe", "beschriftung_groesse": "schriftgroesse", "beschriftung_groesser": "schrift_groesser",
    "beschriftung_kleiner": "schrift_kleiner", "beschriftung_massstab_aus": "massstab_entfernen",
    "beschriftung_massstab_max": "zoom_in", "beschriftung_massstab_min": "zoom_out", "beschriftung_schalten": "beschriften",
    "beschriftung_schrift": "schriftart", "beschriftung_schriftschnitt": "schriftschnitt",
    "beschriftungen_extrahieren": "beschriftungen_extrahieren", "beschriftungsausdruck": "ausdruck",
    "beschriftungseigenschaften": "optionen", "beschriftungsfeld": "felder", "beschriftungsklasse": "beschriftungsklasse",
    "beschriftungsklasse_aktiv": "beschriftungsklasse_aktiv", "beschriftungsklasse_filter": "filter",
    "beziehungen_verwalten": "beziehungen", "daten_hinzufuegen": "daten_hinzufuegen", 
    "differenz": "differenz", "digitalisieroptionen": "optionen", "domaenen": "domaenen", "drehen": "drehen",
    "drucken": "drucken", "editor_galerie": "stuetzpunkte", "editor_galerie_anpassen": "galerie_anpassen",
    "einfuegen": "einfuegen", "einfuegen_als": "einfuegen_als", "einrasten": "einrasten", "einrastoptionen": "optionen",
    "einstellungen": "einstellungen", "erkunden": "erkunden", "erstellen": "erstellen",
    "farbsehschwaeche_simulieren": "farbsehen", "favoriten": "favoriten", "felder": "felder", "filter": "filter",
    "freihand": "auswahl_freihand", "galerie_groesse": "galerie_groesse", "galerie_raeumlich_verknuepfen": "raeumlich_verknuepfen",
    "gehe_zu_xy": "gehe_zu_xy", "georeferenzieren": "georeferenzieren", "geoverarbeitung": "werkzeugkasten",
    "grundkarte_basemap_de_farbig": "grundkarte", "grundkarte_basemap_de_grau": "grundkarte",
    "grundkarte_opentopomap": "grundkarte", "grundkarten_galerie": "grundkarte", "hineinzoomen": "zoom_in",
    "histogramm": "histogramm", "inhalt": "inhalt", "karte_als_pdf": "pdf", "karte_exportieren": "karte_exportieren",
    "kartendrehung": "drehung", "katalog": "katalog", "kopieren": "kopieren", "kopieren_und_verschieben": "kopieren_verschieben",
    "kreis": "auswahl_kreis", "layer_aus_auswahl": "layer_aus_auswahl", "layer_deckkraft": "deckkraft",
    "layer_hinzufuegen": "daten_hinzufuegen", "layer_massstab_max": "zoom_in", "layer_massstab_min": "zoom_out",
    "layer_massstab_schalten": "massstabsbereich", "layer_mischmodus": "mischmodus", "layer_verpacken": "geopackage",
    "layer_zusammenfuehren": "layer_zusammen", "layerdatei_speichern": "speichern_als", "layerdefinition_laden": "layerdefinition",
    "layout_als_bild": "bild", "layout_exportieren": "layout_exportieren", "layoutverwaltung": "layoutverwaltung",
    "lesezeichen_galerie": "lesezeichen", "lesezeichen_verwalten": "lesezeichen_verwalten", "linie_umkehren": "linie_umkehren",
    "linie_versetzen": "linie_versetzen", "loeschen": "loeschen", "lupe": "lupe", "masken": "masken", "messen": "messen",
    "messwerkzeuge": "messwerkzeuge", "modell_designer": "modell", "nach_attributen": "nach_attributen", "nach_lage": "nach_lage",
    "naechste_ausdehnung": "naechste_ausdehnung", "neue_kartenansicht": "kartenansicht_neu",
    "neuer_annotationslayer": "annotation", "neuer_bericht": "bericht", "neuer_geopackage_layer": "geopackage_layer",
    "neuer_shapefile_layer": "neuer_layer", "neuer_scratch_layer": "scratch_layer", "neuer_spatialite_layer": "datenbank_neu",
    "neuer_virtueller_layer": "virtueller_layer", "neues_layout": "layout_neu",
    "neues_lesezeichen": "lesezeichen_neu", "neues_projekt": "projekt_neu",
    "nicht_platzierte_beschriftungen": "nicht_platziert", "objekte_exportieren": "objekte_exportieren",
    "optionen_kartenwerkzeuge": "optionen", "ordner_verbinden": "ordner", "pfad_kopieren": "pfad_kopieren",
    "platzierung_galerie": "platzierung", "polygon": "auswahl_polygon", "postgresql_verbindung": "datenbank_verbinden",
    "processing_galerie": "werkzeugkasten", "processing_optionen": "optionen", "projekt_als_dxf": "dxf",
    "projekt_oeffnen": "projekt_oeffnen", "projekt_speichern": "speichern", "projekt_speichern_als": "speichern_als",
    "puffer": "puffer", "punkte_in_polygon_zaehlen": "punkte_zaehlen", "python": "python", "python_konsole": "konsole",
    "quelle_und_filter": "quelle_filter", "raeumliche_verknuepfung": "raeumlich_verknuepfen",
    "raster_anpassen": "raster_anpassen", "raster_darstellungsart": "darstellungsart", "raster_gamma": "gamma",
    "raster_helligkeit": "helligkeit", "raster_kanaele": "kanaele", 
    "raster_kontrast": "kontrast", "raster_resampling": "resampling", 
    "raster_symbolisierung": "symbolisierung", "raster_transformieren": "raster_transformieren",
    "rasterrechner": "rasterrechner", "rechteck": "auswahl_rechteck", "renderer_galerie": "darstellungsart",
    "ring_fuellen": "ring_fuellen", "ring_hinzufuegen": "ring_hinzufuegen", "ring_loeschen": "ring_loeschen",
    "rueckgaengig": "rueckgaengig", "schrittweise_herauszoomen": "zoom_out", "schrittweise_hineinzoomen": "zoom_in",
    "skalieren": "skalieren", "stac_verbindung": "server_katalog", "stil_einfuegen": "stil_einfuegen",
    "stil_importieren": "stil_importieren", "stilverwaltung": "stilverwaltung",
    "streckung_auf_ausschnitt": "streckung_ausschnitt", "sucheinstellungen": "optionen", "suchen": "suchen",
    "symbolisierung": "symbolisierung", "tabelle_der_auswahl": "tabelle_auswahl", "teil_hinzufuegen": "teil_hinzufuegen",
    "teil_loeschen": "teil_loeschen", "teile_zerlegen": "teile_zerlegen", "teilen": "teilen",
    "textdatei_mit_koordinaten": "punkte_aus_tabelle", "textformat_galerie": "textformat",
    "topologisch_bearbeiten": "topologie", "umformen": "umformen", "umgebungen": "optionen",
    "vektorlayer_hinzufuegen": "vektorlayer", "vereinfachen": "vereinfachen", "vereinigen": "vereinigen",
    "verknuepfung_hinzufuegen": "verknuepfung", "verlauf": "verlauf", "verschieben": "verschieben",
    "verschneiden": "verschneiden", "volle_ausdehnung": "volle_ausdehnung", "vorherige_ausdehnung": "vorherige_ausdehnung",
    "vorschau_deuteranopie": "deuteranopie", "wcs_server": "server_karte", 
    "werkzeuge": "werkzeugkasten", "wfs_ogc_api": "server_objekte", "wiederholen": "wiederholen",
    "wms_wmts_server": "server_karte", "xy_tabelle_zu_punkten": "punkte_aus_tabelle", "z_wert": "z_wert",
    "zentroide": "zentroide", "zur_auswahl_zoomen": "zur_auswahl", "zusammenfuehren": "zusammenfuehren",
    "zuschneiden": "zuschneiden",
}

# Menü-Elemente ohne eigenen Befehl (nach Beschriftung)
MENUS = {
    "Lesezeichen": "lesezeichen", "Verbindungen": "verbindungen", "Datenbank": "datenbank", "Server": "server",
    "Analysewerkzeuge": "werkzeugkasten", "Editorwerkzeuge": "stuetzpunkte", "Textformat": "textformat",
    "Aus Tabelle": "punkte_aus_tabelle", "Kanalkombination": "kanaele",
}

UI = {
    "launcher": "ui_launcher", "suchen": "suchen", "minimieren": "ui_chevron_up", "anheften": "ui_chevron_down",
    "chevron_down": "ui_chevron_down", "chevron_up": "ui_chevron_up", "pin": "ui_pin",
    "auge": "ui_auge", "auge_aus": "ui_auge_aus", "plus": "ui_plus", "griff": "ui_griff", "mehr": "ui_mehr",
    "rueckgaengig": "rueckgaengig", "wiederholen": "wiederholen", "entfernen": "loeschen", "hilfe": "ui_hilfe",
}


def q(s):
    return "'" + s.replace("'", "''") + "'"


def write(path=OUT):
    used = set(COMMANDS.values()) | set(MENUS.values()) | set(UI.values())
    unused = sorted(set(MOTIFS) - used)
    lines = ["# Icon-Set „Kontur“ – erzeugt von tools/kontur_icons.py, nicht von Hand ändern.",
             "# Rollen: f = Akzentfläche, k = Kontur, a = Akzentdetail (Raster 24 × 24).",
             "version: 1", "motive:"]
    for name in sorted(MOTIFS):
        m = MOTIFS[name]
        lines.append("  %s:" % name)
        for role in "fka":
            if m[role]:
                lines.append("    %s:" % role)
                lines.extend("      - %s" % q(el) for el in m[role])
    for title, mapping in (("befehle", COMMANDS), ("menues", MENUS), ("oberflaeche", UI)):
        lines.append("%s:" % title)
        for key in sorted(mapping):
            lines.append("  %s: %s" % (q(key) if not key.isidentifier() or not key.isascii() else key, mapping[key]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return unused


if __name__ == "__main__":
    rest = write()
    print("%d Motive, %d Befehle -> %s" % (len(MOTIFS), len(COMMANDS), OUT))
    if rest:
        print("nicht zugeordnet:", ", ".join(rest))
