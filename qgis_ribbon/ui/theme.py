"""Design „Kontur“ in Qt: Maße, aktuelle Farben, Stylesheets.

Die Farben kommen aus den Tokens (``core.theme_tokens``, Datei
``config/themes/kontur.yaml``). ``ThemeManager`` wählt Modus und Akzent nach
den Einstellungen des Nutzers (automatisch wie QGIS, hell, dunkel), hält die
aktuellen Tokens (``current()``) und meldet Wechsel über ``changed``. Im
automatischen Modus folgt er der QGIS-Palette (Signal ``paletteChanged`` der
Anwendung, kein Polling). Im Hochkontrastmodus von Windows nimmt er die
Systemfarben statt der Tokens.

Stylesheets entstehen aus den Tokens und werden einmal am Wurzel-Widget
gesetzt (``ribbon_qss``), nicht je Button. Was QSS nicht kann (Schatten,
Tab-Unterstrich, Kontext-Kapseln, Gruppentrenner), zeichnen die Widgets
selbst mit ``color()``. Kleine Pfeile und Haken für das Stylesheet liegen als
SVG im Temp-Verzeichnis (``asset``), weil QSS-Bilder Dateien brauchen.
"""

import os
import sys

from qgis.PyQt.QtCore import QDir, QObject, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication

from ..core import theme_tokens

# Maße (Raster 4 px)
LARGE_ICON = 32
SMALL_ICON = 16
ROWS = 3                 # mittlere/kleine Buttons je Spalte
ROW_HEIGHT = 24          # Höhe eines mittleren Buttons
ROW_SPACING = 2
CONTENT_HEIGHT = ROWS * ROW_HEIGHT + (ROWS - 1) * ROW_SPACING   # 76
LARGE_MIN_WIDTH = 52
LARGE_PADDING = 12       # links + rechts neben der Beschriftung großer Buttons
MEDIUM_PADDING = 20      # Rand links/rechts + Abstand Icon–Text bei mittleren Buttons
SMALL_WIDTH = 26
GROUP_LABEL_HEIGHT = 20
GROUP_PADDING = 6        # links/rechts in einer Gruppe
GROUP_SPACING = 2        # zwischen Spalten einer Gruppe
GROUP_GAP = 1            # zwischen Gruppen (Trennlinie liegt darin)
PAGE_TOP = 6
PAGE_HEIGHT = PAGE_TOP + CONTENT_HEIGHT + GROUP_LABEL_HEIGHT + 2
HEADER_HEIGHT = 44
SURFACE_MARGIN = 8       # Abstand der Ribbon-Fläche zum Fensterrand
SHADOW = 6               # Platz für den Schatten unter der Fläche
RADIUS = 7
SURFACE_RADIUS = 10
WRAP_AT = 11             # große Buttons: Beschriftung ab dieser Länge zweizeilig
ANIMATION_MS = 120

_THEMES = None
_current = None
_settings = {"mode": "auto", "accent": "", "whole": False, "animations": True, "icons": True}
_generation = 0          # zählt Wechsel; Icon-Caches hängen daran


def themes():
    global _THEMES
    if _THEMES is None:
        _THEMES = theme_tokens.load()
    return _THEMES


def current():
    """Aktuelle Tokens (Modus „hell“ mit Standard-Akzent, solange kein Manager läuft)."""
    global _current
    if _current is None:
        _current = themes().tokens("hell")
    return _current


def generation():
    return _generation


def setting(key):
    return _settings.get(key)


def _set_current(tokens, settings):
    global _current, _generation
    _current = tokens
    _settings.update(settings)
    _generation += 1


def color(token, tokens=None):
    """QColor eines Tokens (``#RRGGBBAA`` mit Deckkraft)."""
    value = (tokens or current())[token]
    r, g, b = theme_tokens.rgb(value)
    return QColor(r, g, b, theme_tokens.alpha(value))


def css(token, tokens=None):
    """Farbe für Stylesheets: ``#RRGGBB`` oder ``rgba(…)`` (QSS kennt kein #RRGGBBAA)."""
    value = (tokens or current())[token]
    a = theme_tokens.alpha(value)
    if a == 255:
        return value[:7]
    r, g, b = theme_tokens.rgb(value)
    return "rgba(%d, %d, %d, %d)" % (r, g, b, a)


def is_dark(tokens=None):
    return (tokens or current())["mode"] == "dunkel"


# Ältere Schnittstelle (Farben aus der Palette)
def context_color(_palette=None):
    return color("ctxT")


def muted_text(_palette=None):
    return color("muted")


def wrap_label(text):
    """Beschriftung großer Buttons auf zwei Zeilen verteilen (am Leerzeichen nahe der Mitte)."""
    if len(text) < WRAP_AT or " " not in text:
        return text
    mid = len(text) // 2
    spaces = [i for i, c in enumerate(text) if c == " "]
    pos = min(spaces, key=lambda i: abs(i - mid))
    return text[:pos] + "\n" + text[pos + 1:]


# Hochkontrast (Windows)
def high_contrast():
    """Hochkontrastmodus von Windows aktiv? (sonst immer False)"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD),
                        ("lpszDefaultScheme", wintypes.LPWSTR)]

        hc = HIGHCONTRAST()
        hc.cbSize = ctypes.sizeof(HIGHCONTRAST)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x0042, hc.cbSize, ctypes.byref(hc), 0)
        return bool(ok and hc.dwFlags & 0x1)
    except Exception:  # noqa: BLE001 - nie wegen der Abfrage scheitern
        return False


def _hex(qcolor):
    return "#%02X%02X%02X" % (qcolor.red(), qcolor.green(), qcolor.blue())


def palette_tokens(palette):
    """Tokens aus der Systempalette (Hochkontrast): keine eigenen Farben, keine Schatten."""
    win = _hex(palette.color(QPalette.Window))
    base = _hex(palette.color(QPalette.Base))
    text = _hex(palette.color(QPalette.WindowText))
    hi = _hex(palette.color(QPalette.Highlight))
    hi_text = _hex(palette.color(QPalette.HighlightedText))
    dis = _hex(palette.color(QPalette.Disabled, QPalette.WindowText))
    dark = palette.color(QPalette.Window).lightness() < theme_tokens.DARK_BELOW
    return {
        "win": win, "surf": base, "bord": text, "div": text, "text": text, "muted": text,
        "faint": dis, "hover": hi, "press": hi, "ctx": hi, "ctxS": base, "ctxT": text,
        "shadow": "#00000000", "tip": text, "tipText": base, "err": text,
        "acc": hi, "accS": hi, "accT": hi_text, "accB": hi_text, "icf": hi + "00",
        "selF": hi + "38", "mode": "dunkel" if dark else "hell", "accent": "system",
    }


class ThemeManager(QObject):
    """Aktueller Modus und Akzent; ``changed`` nach jedem Wechsel."""

    changed = pyqtSignal()

    def __init__(self, user, parent=None):
        QObject.__init__(self, parent)
        self.user = user
        self.tokens = None
        self._last_settings = None
        self.lightness_override = None   # Gesamtbild: Helligkeit von QGIS vor der eigenen Palette
        self.high_contrast = high_contrast()
        self._connected = False
        app = QApplication.instance()
        if app is not None and hasattr(app, "paletteChanged"):
            app.paletteChanged.connect(self._on_palette)
            self._connected = True
        self.refresh(emit=False)

    def settings(self):
        return self.user.design()

    def qgis_lightness(self):
        app = QApplication.instance()
        return app.palette().color(QPalette.Window).lightness() if app is not None else 255

    def refresh(self, emit=True):
        s = self.settings()
        if self.high_contrast:
            tokens = palette_tokens(QApplication.instance().palette())
        else:
            mode = theme_tokens.resolve_mode(s["mode"], self.base_lightness())
            tokens = themes().tokens(mode, s["accent"] or None)
        old = self.tokens
        self.tokens = tokens
        _set_current(tokens, s)
        if emit and (old != tokens or self._last_settings != s):
            self.changed.emit()
        self._last_settings = dict(s)

    def base_lightness(self):
        """Helligkeit von QGIS ohne eigene Palette (Gesamtbild setzt ggf. eine eigene)."""
        if self.lightness_override is not None:
            return self.lightness_override()
        return self.qgis_lightness()

    def set(self, key, value):
        self.user.set_design(key, value)
        self.refresh()

    def _on_palette(self, _palette=None):
        if self.settings()["mode"] == "auto" or self.high_contrast:
            self.refresh()

    def stop(self):
        if self._connected:
            try:
                QApplication.instance().paletteChanged.disconnect(self._on_palette)
            except (TypeError, RuntimeError):
                pass
            self._connected = False


# Bilder für Stylesheets
_ASSETS = {
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "chevron_up": '<path d="M6 15l6-6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
}


_ASSET_PATHS = {}


def asset(name, token, tokens=None):
    """Pfad einer kleinen SVG (Pfeil, Haken) in Tokenfarbe; für ``url()`` im Stylesheet."""
    value = (tokens or current())[token][:7]
    path = _ASSET_PATHS.get((name, value))
    if path is not None and os.path.exists(path):
        return path.replace("\\", "/")
    # QDir statt tempfile: tempfile zieht shutil, random, bz2 … nach (bis 50 ms Import)
    folder = os.path.join(QDir.tempPath(), "qgis_ribbon_kontur")
    path = os.path.join(folder, "%s_%s.svg" % (name, value.lstrip("#")))
    _ASSET_PATHS[(name, value)] = path
    if not os.path.exists(path):
        os.makedirs(folder, exist_ok=True)
        body = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
                '<g fill="none" stroke="%s" stroke-width="2.4" stroke-linecap="round" '
                'stroke-linejoin="round">%s</g></svg>' % (value, _ASSETS[name]))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    return path.replace("\\", "/")


# Stylesheets
def widgets_qss(t, scope=""):
    """Eingabefelder, Listen, Kontrollkästchen, Regler, Bildlaufleisten, Menüs, Tooltips.

    ``scope`` (z. B. ``QDockWidget``) begrenzt die Regeln auf Nachfahren davon.
    """
    s = (scope + " ") if scope else ""
    c = lambda k: css(k, t)  # noqa: E731
    down = asset("chevron_down", "muted", t)
    up = asset("chevron_up", "muted", t)
    check = asset("check", "surf", t)
    rules = [
        "%sQLabel { color: %s; background: transparent; }" % (s, c("text")),
        "%sQLabel:disabled { color: %s; }" % (s, c("faint")),
        ("{s}QLineEdit, {s}QComboBox, {s}QAbstractSpinBox {{ background: {surf}; color: {text}; "
         "border: 1px solid {bord}; border-radius: 5px; padding: 1px 6px; "
         "selection-background-color: {acc}; selection-color: {surf}; }}").format(
            s=s, surf=c("surf"), text=c("text"), bord=c("bord"), acc=c("acc")),
        "{s}QLineEdit:hover, {s}QComboBox:hover, {s}QAbstractSpinBox:hover {{ border-color: {m}; }}".format(
            s=s, m=c("muted")),
        "{s}QLineEdit:focus, {s}QComboBox:focus, {s}QAbstractSpinBox:focus {{ border-color: {a}; }}".format(
            s=s, a=c("acc")),
        "{s}QLineEdit:disabled, {s}QComboBox:disabled, {s}QAbstractSpinBox:disabled {{ color: {f}; }}".format(
            s=s, f=c("faint")),
        "%sQComboBox::drop-down { border: 0px; width: 18px; }" % s,
        "%sQComboBox::down-arrow { image: url(%s); width: 10px; height: 10px; }" % (s, down),
        ("%sQComboBox QAbstractItemView { background: %s; color: %s; border: 1px solid %s; "
         "selection-background-color: %s; selection-color: %s; outline: 0px; }")
        % (s, c("surf"), c("text"), c("bord"), c("hover"), c("text")),
        "%sQAbstractSpinBox::up-button, %sQAbstractSpinBox::down-button { border: 0px; width: 14px; }" % (s, s),
        "%sQAbstractSpinBox::up-arrow { image: url(%s); width: 9px; height: 9px; }" % (s, up),
        "%sQAbstractSpinBox::down-arrow { image: url(%s); width: 9px; height: 9px; }" % (s, down),
        "%sQCheckBox, %sQRadioButton { color: %s; spacing: 6px; background: transparent; }" % (s, s, c("text")),
        "%sQCheckBox:disabled, %sQRadioButton:disabled { color: %s; }" % (s, s, c("faint")),
        ("%sQCheckBox::indicator { width: 14px; height: 14px; border: 1px solid %s; "
         "border-radius: 4px; background: %s; }") % (s, c("muted"), c("surf")),
        "%sQCheckBox::indicator:checked { background: %s; border-color: %s; image: url(%s); }"
        % (s, c("acc"), c("acc"), check),
        ("%sQRadioButton::indicator { width: 14px; height: 14px; border: 1px solid %s; "
         "border-radius: 7px; background: %s; }") % (s, c("muted"), c("surf")),
        "%sQRadioButton::indicator:checked { border: 4px solid %s; background: %s; }"
        % (s, c("acc"), c("surf")),
        "%sQSlider::groove:horizontal { height: 4px; background: %s; border-radius: 2px; }" % (s, c("div")),
        "%sQSlider::sub-page:horizontal { background: %s; border-radius: 2px; }" % (s, c("acc")),
        ("%sQSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0px; "
         "border-radius: 7px; background: %s; border: 2px solid %s; }") % (s, c("surf"), c("acc")),
        ("{s}QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 0px; }} "
         "{s}QScrollBar:vertical {{ width: 8px; background: transparent; margin: 0px; }} "
         "{s}QScrollBar::handle {{ background: {d}; border-radius: 4px; min-width: 24px; min-height: 24px; }} "
         "{s}QScrollBar::handle:hover {{ background: {m}; }} "
         "{s}QScrollBar::add-line, {s}QScrollBar::sub-line {{ width: 0px; height: 0px; }} "
         "{s}QScrollBar::add-page, {s}QScrollBar::sub-page {{ background: transparent; }}").format(
            s=s, d=c("bord"), m=c("muted")),
        ("%sQMenu { background: %s; color: %s; border: 1px solid %s; padding: 4px; }"
         % (s, c("surf"), c("text"), c("bord"))),
        "%sQMenu::item { padding: 5px 22px 5px 8px; border-radius: 5px; background: transparent; }" % s,
        "%sQMenu::item:selected { background: %s; color: %s; }" % (s, c("hover"), c("text")),
        "%sQMenu::item:disabled { color: %s; }" % (s, c("faint")),
        "%sQMenu::separator { height: 1px; background: %s; margin: 4px 6px; }" % (s, c("div")),
        "%sQMenu::icon { padding-left: 6px; }" % s,
        ("%sQMenu::indicator { width: 14px; height: 14px; border: 1px solid %s; border-radius: 4px; "
         "margin-left: 4px; }") % (s, c("muted")),
        "%sQMenu::indicator:checked { background: %s; border-color: %s; image: url(%s); }"
        % (s, c("acc"), c("acc"), check),
        "%sQMenu::right-arrow { image: url(%s); width: 10px; height: 10px; }"
        % (s, asset("chevron_right", "muted", t)),
        ("QToolTip { background: %s; color: %s; border: 1px solid %s; padding: 6px 8px; "
         "border-radius: 6px; }") % (c("surf"), c("text"), c("bord")),
    ]
    return "\n".join(rules)


def ribbon_qss(t):
    """Stylesheet des Ribbons (am Wurzel-Widget gesetzt, gilt für alle Kinder)."""
    c = lambda k: css(k, t)  # noqa: E731
    chev = asset("chevron_down", "muted", t)
    chev_on = asset("chevron_down", "accT", t)
    rules = [
        "#QgisRibbonWidget, #ribbon_header, #ribbon_surface_host { background: %s; }" % c("win"),
        "#QgisRibbonWidget { color: %s; }" % c("text"),
        ("QToolButton { background: transparent; color: %s; border: 1px solid transparent; "
         "border-radius: %dpx; padding: 1px; }") % (c("text"), RADIUS),
        "QToolButton:hover { background: %s; }" % c("hover"),
        "QToolButton:pressed, QToolButton:open { background: %s; }" % c("press"),
        "QToolButton:checked { background: %s; color: %s; border-color: %s; }"
        % (c("accS"), c("accT"), c("accB")),
        "QToolButton:disabled { color: %s; }" % c("faint"),
        "QToolButton:focus { border-color: %s; }" % c("acc"),
        "QToolButton::menu-indicator { image: none; width: 0px; }",
        'QToolButton[ribbon_size="large"] { padding: 3px 3px 2px 3px; }',
        'QToolButton[ribbon_size="medium"] { padding: 0px 6px 0px 3px; text-align: left; }',
        'QToolButton[ribbon_size="small"] { padding: 0px; }',
        ('QToolButton[ribbon_size="medium"][popupMode="2"] { padding-right: 16px; }'),
        ('QToolButton[ribbon_size="medium"][popupMode="2"]::menu-indicator, '
         'QToolButton[ribbon_size="small"][popupMode="2"]::menu-indicator '
         '{ image: url(%s); width: 9px; height: 9px; subcontrol-origin: padding; '
         'subcontrol-position: right center; right: 4px; }') % chev,
        'QToolButton[ribbon_size="small"][popupMode="2"] { padding-right: 10px; }',
        'QToolButton[popupMode="1"] { padding-right: 14px; }',
        ("QToolButton::menu-button { border: 0px; width: 14px; border-top-right-radius: %dpx; "
         "border-bottom-right-radius: %dpx; }") % (RADIUS, RADIUS),
        "QToolButton::menu-button:hover { background: %s; }" % c("press"),
        "QToolButton::menu-arrow { image: url(%s); width: 9px; height: 9px; }" % chev,
        "QToolButton::menu-arrow:open { image: url(%s); }" % chev_on,
        ("#ribbon_split_top { border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; "
         "padding: 4px 2px 0px 2px; }"),
        "#ribbon_split_bottom { border-top-left-radius: 0px; border-top-right-radius: 0px; padding: 0px 2px 2px 2px; }",
        'QToolButton[ribbon_tile="true"] { padding: 3px; }',
        "#ribbon_group_label { color: %s; background: transparent; }" % c("muted"),
        ("QLineEdit#ribbon_search { background: %s; color: %s; border: 1px solid %s; "
         "border-radius: 15px; padding: 0px 10px 0px 4px; min-height: 28px; max-height: 28px; }")
        % (c("surf"), c("text"), c("bord")),
        "QLineEdit#ribbon_search:focus { border: 2px solid %s; padding: 0px 9px 0px 3px; }" % c("acc"),
        "QFrame#ribbon_popup, QFrame#ribbon_group_popup { background: %s; border: 1px solid %s; }"
        % (c("surf"), c("bord")),
        "QFrame#ribbon_header_sep { background: %s; border: 0px; }" % c("div"),
        "QLabel#ribbon_keytip { background: %s; color: %s; border-radius: 5px; padding: 0px 4px; "
        "font-weight: 600; }" % (c("tip"), c("tipText")),
        "QLabel#ribbon_keytip:disabled { background: %s; color: %s; }" % (c("faint"), c("surf")),
        "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0px; }",
        widgets_qss(t),
    ]
    return "\n".join(rules)


def toolbar_qss(t):
    return ("QToolBar#QgisRibbonToolbar { background: %s; border: 0px; padding: 0px; margin: 0px; "
            "spacing: 0px; }" % css("win", t))


def style_dialog(dialog):
    """Eigenen Dialog im Kontur-Stil zeigen (aktueller Modus und Akzent)."""
    dialog.setStyleSheet(dialog_qss(current()))


def dialog_qss(t):
    """Eigene Dialoge (Anpassen, Kürzel, Galerie, Domänen) im Kontur-Stil."""
    c = lambda k: css(k, t)  # noqa: E731
    rules = [
        "QDialog { background: %s; color: %s; }" % (c("win"), c("text")),
        ("QPushButton { background: %s; color: %s; border: 1px solid %s; border-radius: 6px; "
         "padding: 4px 14px; min-height: 18px; }") % (c("surf"), c("text"), c("bord")),
        "QPushButton:hover { background: %s; }" % c("hover"),
        "QPushButton:pressed { background: %s; }" % c("press"),
        "QPushButton:default { background: %s; color: %s; border-color: %s; }"
        % (c("acc"), c("surf") if not is_dark(t) else c("win"), c("acc")),
        "QPushButton:disabled { color: %s; border-color: %s; }" % (c("faint"), c("div")),
        "QPushButton:focus { border-color: %s; }" % c("acc"),
        ("QToolButton { background: transparent; color: %s; border: 1px solid transparent; "
         "border-radius: 6px; padding: 3px; }") % c("text"),
        "QToolButton:hover { background: %s; }" % c("hover"),
        "QToolButton:checked { background: %s; color: %s; border-color: %s; }"
        % (c("accS"), c("accT"), c("accB")),
        "QToolButton:disabled { color: %s; }" % c("faint"),
        ("QAbstractItemView { background: %s; color: %s; border: 1px solid %s; border-radius: 6px; "
         "alternate-background-color: %s; selection-background-color: %s; selection-color: %s; "
         "outline: 0px; }") % (c("surf"), c("text"), c("bord"), c("win"), c("accS"), c("accT")),
        "QAbstractItemView::item { padding: 2px 4px; border-radius: 4px; }",
        "QAbstractItemView::item:hover { background: %s; }" % c("hover"),
        "QAbstractItemView::item:selected { background: %s; color: %s; }" % (c("accS"), c("accT")),
        ("QHeaderView::section { background: %s; color: %s; border: 0px; "
         "border-bottom: 1px solid %s; padding: 4px 6px; }") % (c("win"), c("muted"), c("div")),
        ("QGroupBox { color: %s; border: 1px solid %s; border-radius: 8px; margin-top: 14px; "
         "padding: 8px; }") % (c("text"), c("bord")),
        "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0px 4px; color: %s; }"
        % c("muted"),
        "QTabWidget::pane { border: 1px solid %s; border-radius: 8px; background: %s; top: -1px; }"
        % (c("bord"), c("surf")),
        ("QTabBar::tab { background: transparent; color: %s; padding: 6px 12px; border: 0px; "
         "border-bottom: 3px solid transparent; }") % c("muted"),
        "QTabBar::tab:selected { color: %s; border-bottom-color: %s; }" % (c("text"), c("acc")),
        "QTabBar::tab:hover { color: %s; }" % c("text"),
        "QSplitter::handle { background: %s; }" % c("div"),
        "QTextEdit, QPlainTextEdit { background: %s; color: %s; border: 1px solid %s; border-radius: 6px; }"
        % (c("surf"), c("text"), c("bord")),
        widgets_qss(t),
    ]
    return "\n".join(rules)
