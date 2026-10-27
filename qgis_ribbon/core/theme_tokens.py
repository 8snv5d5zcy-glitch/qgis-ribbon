"""Farbtokens des Designs „Kontur“ laden und prüfen (ohne qgis-Imports).

Die Tokens stehen in ``config/themes/kontur.yaml``: je Modus (hell, dunkel)
die Flächen- und Textfarben, je Akzent (moos, kobalt, bernstein) vier
Farben pro Modus. ``ThemeSet.tokens(mode, accent)`` liefert alle Farben eines
Modus samt abgeleiteter Werte (Icon-Akzentfläche, Auswahlfläche,
KeyTip-Schrift).

Prüfungen (``check``): Pflicht-Tokens vorhanden, Format ``#RRGGBB`` bzw.
``#RRGGBBAA``, Kontrast mindestens 4,5:1 für jedes Paar Text/Fläche aus
``CONTRAST_PAIRS`` in jedem Modus und mit jedem Akzent, mindestens 1,8:1 für
Trennlinien (``DIVIDER_PAIRS``). Fehler sammelt
``ThemeError`` vollständig, wie beim Config-Loader.

``resolve_mode`` übersetzt die Einstellung des Nutzers (automatisch, hell,
dunkel) in einen Modus; automatisch folgt der Helligkeit der QGIS-Palette.
"""

import io
import os
import re
from . import yaml_cache
from .i18n import tr

DEFAULT_THEME = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "themes",
                             "kontur.yaml")

MODES = ("hell", "dunkel")
MODE_SETTINGS = ("auto", "hell", "dunkel")
MODE_LABELS = {"auto": tr("Automatic (like QGIS)"), "hell": tr("Light"), "dunkel": tr("Dark")}
MODE_TOKENS = ("win", "surf", "bord", "div", "gdiv", "text", "muted", "faint", "hover", "press",
               "ctx", "ctxS", "ctxT", "shadow", "tip", "err")
ACCENT_TOKENS = ("acc", "accS", "accT", "accB")
ALPHA_TOKENS = ("shadow", "accB")       # mit Deckkraft (#RRGGBBAA erlaubt)
MIN_CONTRAST = 4.5
# (Vordergrund, Hintergrund): Text muss auf diesen Flächen lesbar sein
CONTRAST_PAIRS = (
    ("text", "win"), ("text", "surf"), ("text", "hover"), ("text", "press"),
    ("muted", "win"), ("muted", "surf"), ("muted", "hover"),
    ("accT", "accS"), ("ctxT", "ctxS"), ("ctxT", "win"), ("surf", "tip"),
    ("err", "win"), ("err", "surf"),
)
# Linien, die Bereiche trennen: deutlich, aber kein Text (Gruppentrenner im Ribbon)
DIVIDER_PAIRS = (("gdiv", "surf"),)
MIN_DIVIDER_CONTRAST = 1.8
ICON_FILL_ALPHA = "2E"   # Akzentfläche in Icons (18 %)
SELECTION_ALPHA = "38"   # Auswahlfläche (22 %)
DARK_BELOW = 128         # Helligkeit der Fensterfarbe (0–255), unter der QGIS als dunkel gilt

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_HEX_ALPHA = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


class ThemeError(ValueError):
    def __init__(self, errors):
        self.errors = list(errors)
        ValueError.__init__(self, tr("Design tokens have errors:\n- ") + "\n- ".join(self.errors))


def rgb(hex_color):
    """``#RRGGBB[AA]`` -> (r, g, b) als 0–255."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def alpha(hex_color):
    """Deckkraft 0–255 (255 ohne Angabe)."""
    h = hex_color.lstrip("#")
    return int(h[6:8], 16) if len(h) == 8 else 255


def luminance(hex_color):
    """Relative Leuchtdichte nach WCAG 2.x."""
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    """Kontrastverhältnis zweier Farben (1–21)."""
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def resolve_mode(setting, window_lightness):
    """Einstellung (auto/hell/dunkel) -> Modus; ``window_lightness`` 0–255 aus der QGIS-Palette."""
    if setting in MODES:
        return setting
    return "dunkel" if window_lightness < DARK_BELOW else "hell"


class ThemeSet(object):
    """Alle Modi und Akzente eines Designs."""

    def __init__(self, name, modes, accents, default_accent):
        self.name = name
        self.modes = modes            # Modus -> {Token: Farbe}
        self.accents = accents        # Akzent -> {"label": …, "hell": {…}, "dunkel": {…}}
        self.default_accent = default_accent

    def accent_ids(self):
        return list(self.accents)

    def accent_label(self, accent):
        return tr(self.accents[accent].get("label", accent))

    def valid_accent(self, accent):
        return accent if accent in self.accents else self.default_accent

    def tokens(self, mode, accent=None):
        """Farben eines Modus mit Akzent und abgeleiteten Werten."""
        if mode not in self.modes:
            raise KeyError(mode)
        accent = self.valid_accent(accent)
        t = dict(self.modes[mode])
        t.update(self.accents[accent][mode])
        t["icf"] = t["acc"] + ICON_FILL_ALPHA
        t["selF"] = t["acc"] + SELECTION_ALPHA
        t["tipText"] = t["surf"]
        t["mode"] = mode
        t["accent"] = accent
        return t


def parse(data):
    """Geladenes YAML -> ``ThemeSet``; sammelt alle Fehler in ``ThemeError``."""
    errors = []
    if not isinstance(data, dict):
        raise ThemeError([tr("File contains no object")])
    modes = data.get("modes") or {}
    accents = data.get("accents") or {}
    for mode in MODES:
        values = modes.get(mode)
        if not isinstance(values, dict):
            errors.append(tr("Mode missing: %s") % mode)
            continue
        for key in MODE_TOKENS:
            _check_color(errors, "%s.%s" % (mode, key), values.get(key), key in ALPHA_TOKENS)
        for key in sorted(set(values) - set(MODE_TOKENS)):
            errors.append(tr("Unknown token: %s.%s") % (mode, key))
    if not accents:
        errors.append(tr("No accents defined"))
    for name, acc in accents.items():
        if not isinstance(acc, dict):
            errors.append(tr("Accent %s: not an object") % name)
            continue
        for mode in MODES:
            values = acc.get(mode)
            if not isinstance(values, dict):
                errors.append(tr("Accent %s: mode %s missing") % (name, mode))
                continue
            for key in ACCENT_TOKENS:
                _check_color(errors, "%s.%s.%s" % (name, mode, key), values.get(key),
                             key in ALPHA_TOKENS)
    default = data.get("default_accent")
    if default not in accents:
        errors.append(tr("Unknown default accent: %r") % (default,))
    if errors:
        raise ThemeError(errors)
    themes = ThemeSet(str(data.get("name") or "Kontur"),
                      {m: dict(modes[m]) for m in MODES},
                      {k: dict(v) for k, v in accents.items()}, default)
    errors = check(themes)
    if errors:
        raise ThemeError(errors)
    return themes


def _check_color(errors, where, value, with_alpha):
    pattern = _HEX_ALPHA if with_alpha else _HEX
    if not isinstance(value, str) or not pattern.match(value):
        errors.append(tr("%s: color missing or invalid (%r)") % (where, value))


def check(themes):
    """Kontrastprüfung aller Modi und Akzente; Liste der Verstöße."""
    errors = []
    for mode in MODES:
        for accent in themes.accent_ids():
            t = themes.tokens(mode, accent)
            for fg, bg in CONTRAST_PAIRS:
                ratio = contrast(t[fg], t[bg])
                if ratio < MIN_CONTRAST:
                    errors.append(tr("Contrast %s on %s (%s, %s): %.2f < %.1f")
                                  % (fg, bg, mode, accent, ratio, MIN_CONTRAST))
            for fg, bg in DIVIDER_PAIRS:
                ratio = contrast(t[fg], t[bg])
                if ratio < MIN_DIVIDER_CONTRAST:
                    errors.append(tr("Contrast %s on %s (%s, %s): %.2f < %.1f")
                                  % (fg, bg, mode, accent, ratio, MIN_DIVIDER_CONTRAST))
    return errors


def load(path=DEFAULT_THEME):
    import yaml

    with io.open(path, encoding="utf-8") as fh:
        try:
            data = yaml_cache.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ThemeError([tr("YAML not readable: %s") % exc])
    return parse(data)
