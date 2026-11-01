"""„Kontur für ganz QGIS“ (abschaltbar, Standard aus).

Legt ein Stylesheet über das QGIS-Hauptfenster: Menüleiste, Statusleiste,
Docks (Layerbaum, Browser, Verarbeitung …), verbleibende Werkzeugleisten
und Trenner im selben Stil wie der Ribbon. Die Kartenansicht bleibt
unberührt.

Dazu kommt eine Anwendungspalette aus den Tokens: Viele QGIS-Ansichten
(Layerbaum, Browser) zeichnen ihre Schrift über eigene Modelle mit der
Palettenfarbe ``Text``, die kein Stylesheet erreicht. Ohne eigene Palette
stünde im dunklen Modus schwarze Schrift auf dunklem Grund.

Vorheriges Stylesheet und vorherige Palette werden beim ersten Anwenden
gesichert und beim Abschalten und Entladen unverändert zurückgesetzt.
Setzt QGIS oder ein anderes Plugin inzwischen ein eigenes Stylesheet oder
eine eigene Palette, wird diese übernommen statt überschrieben.
"""

import re

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QLineEdit, QStatusBar

from . import theme

MARKER = "/* qgis_ribbon:kontur */"
# Meldungsfeld der QGIS-Statusleiste: QGIS schreibt die Schriftfarbe beim Start fest in
# dessen eigenes Stylesheet („* { … color: #000000; }“); kein äußeres Stylesheet und
# keine Palette erreicht sie danach.
_MESSAGE_SHEET = "background-color: rgba(0, 0, 0, 0)"
_MESSAGE_COLOR = re.compile(r"(\bcolor:\s*)#[0-9A-Fa-f]{6}")


def menu_button_qss(t, scope):
    """Menüpfeile von Werkzeugleisten-Buttons (Plugins, Docks).

    Sobald ein Stylesheet Rahmen oder Hintergrund eines QToolButton setzt,
    zeichnet Qt dessen Menüteil (``::menu-button``, ``::menu-indicator``)
    nicht mehr im Systemstil, sondern als schwarzes Feld. Darum bekommen
    beide Teile hier eigene Regeln mit Pfeilen in Tokenfarbe.
    """
    c = lambda k: theme.css(k, t)  # noqa: E731
    chev = theme.asset("chevron_down", "muted", t)
    chev_on = theme.asset("chevron_down", "accT", t)
    b = scope + " QToolButton"
    return "\n".join([
        '%s[popupMode="1"] { padding-right: 13px; }' % b,
        ("%s::menu-button { background: transparent; border: 0px; width: 12px; "
         "border-top-right-radius: 6px; border-bottom-right-radius: 6px; }") % b,
        "%s::menu-button:hover { background: %s; }" % (b, c("press")),
        "%s::menu-arrow { image: url(%s); width: 9px; height: 9px; }" % (b, chev),
        "%s::menu-arrow:open { image: url(%s); }" % (b, chev_on),
        ("%s::menu-indicator { image: url(%s); width: 8px; height: 8px; "
         "subcontrol-origin: padding; subcontrol-position: bottom right; }") % (b, chev),
        "%s::menu-indicator:open { image: url(%s); }" % (b, chev_on),
        "%s:open { background: %s; }" % (b, c("press")),
    ])


def whole_qss(t):
    c = lambda k: theme.css(k, t)  # noqa: E731
    rules = [
        MARKER,
        "QMainWindow { background: %s; }" % c("win"),
        "QMainWindow::separator { background: %s; width: 1px; height: 1px; }" % c("div"),
        "QMainWindow::separator:hover { background: %s; }" % c("acc"),
        "QMenuBar { background: %s; color: %s; border: 0px; padding: 2px 6px; }" % (c("win"), c("text")),
        "QMenuBar::item { background: transparent; padding: 4px 9px; border-radius: 5px; }",
        "QMenuBar::item:selected, QMenuBar::item:pressed { background: %s; }" % c("hover"),
        ("QStatusBar { background: %s; color: %s; border-top: 1px solid %s; }"
         % (c("win"), c("muted"), c("div"))),
        "QStatusBar QLabel { color: %s; }" % c("muted"),
        # Knöpfe der Statusleiste (KBS, Meldungen): QGIS gibt ihnen eine eigene Palette,
        # die ein Palettenwechsel nicht erreicht; ohne Regel blieb die Schrift schwarz.
        ("QStatusBar QToolButton { background: transparent; color: %s; border: 1px solid transparent; "
         "border-radius: 5px; }") % c("text"),
        "QStatusBar QToolButton:hover { background: %s; }" % c("hover"),
        "QStatusBar::item { border: 0px; }",
        "QToolBar { background: %s; border: 0px; spacing: 2px; padding: 2px; }" % c("win"),
        ("QToolBar QToolButton { background: transparent; border: 1px solid transparent; "
         "border-radius: 6px; padding: 2px; color: %s; }") % c("text"),
        "QToolBar QToolButton:hover { background: %s; }" % c("hover"),
        "QToolBar QToolButton:checked { background: %s; border-color: %s; }" % (c("accS"), c("accB")),
        "QDockWidget { color: %s; }" % c("muted"),
        ("QDockWidget::title { background: %s; padding: 7px 10px 5px 10px; text-align: left; "
         "border-bottom: 1px solid %s; }") % (c("win"), c("div")),
        "QDockWidget > QWidget { background: %s; }" % c("surf"),
        # Rollbereiche in Docks (z. B. Layer-Styling): Viewport und Inhalt füllen ihren
        # Grund selbst mit einer eigenen Palette von QGIS, die ein Palettenwechsel nicht
        # erreicht; beim Einschalten zur Laufzeit stand sonst helle Schrift auf hellem Grund.
        ("QDockWidget QAbstractScrollArea > QWidget#qt_scrollarea_viewport, "
         "QDockWidget QWidget#scrollAreaWidgetContents { background: %s; }") % c("surf"),
        ("QDockWidget QAbstractItemView { background: %s; color: %s; border: 0px; "
         "selection-background-color: %s; selection-color: %s; outline: 0px; "
         "alternate-background-color: %s; }") % (c("surf"), c("text"), c("accS"), c("accT"), c("win")),
        "QDockWidget QAbstractItemView::item { padding: 1px 2px; }",
        "QDockWidget QAbstractItemView::item:hover { background: %s; }" % c("hover"),
        "QDockWidget QAbstractItemView::item:selected { background: %s; color: %s; }" % (c("accS"), c("accT")),
        ("QDockWidget QHeaderView::section { background: %s; color: %s; border: 0px; "
         "border-bottom: 1px solid %s; padding: 4px 6px; }") % (c("surf"), c("muted"), c("div")),
        ("QDockWidget QToolButton { background: transparent; color: %s; border: 1px solid transparent; "
         "border-radius: 6px; padding: 2px; }") % c("text"),
        "QDockWidget QToolButton:hover { background: %s; }" % c("hover"),
        "QDockWidget QToolButton:checked { background: %s; border-color: %s; }" % (c("accS"), c("accB")),
        "QDockWidget QToolBar { background: %s; border-bottom: 1px solid %s; }" % (c("surf"), c("div")),
        # Aufklappbare Gruppen von QGIS (z. B. „Layer Rendering“ im Layer-Styling): sonst
        # steht die helle Schrift auf einem hellen Titelbalken (Fusion u. a.; der
        # macOS-Stil zeichnet den Balken weiterhin selbst).
        ("QDockWidget QgsCollapsibleGroupBoxBasic, QDockWidget QgsCollapsibleGroupBox "
         "{ background: transparent; color: %s; }") % c("text"),
        ("QDockWidget QgsCollapsibleGroupBoxBasic::title, QDockWidget QgsCollapsibleGroupBox::title "
         "{ background: transparent; color: %s; }") % c("text"),
        ("QMainWindow > QTabBar::tab { background: %s; color: %s; padding: 5px 12px; border: 0px; "
         "border-top: 2px solid transparent; }") % (c("win"), c("muted")),
        "QMainWindow > QTabBar::tab:selected { background: %s; color: %s; border-top-color: %s; }"
        % (c("surf"), c("text"), c("acc")),
        menu_button_qss(t, "QToolBar"),
        menu_button_qss(t, "QDockWidget"),
        theme.widgets_qss(t, "QDockWidget"),
        theme.widgets_qss(t, "QStatusBar"),
    ]
    # Menüs der Menüleiste (eigene Fenster, erben das Stylesheet über die Menüleiste)
    rules += [rule for rule in theme.widgets_qss(t).splitlines() if rule.startswith(("QMenu", "QToolTip"))]
    return "\n".join(rules)


def whole_palette(t, base):
    """Anwendungspalette aus den Tokens (auf Grundlage der bisherigen Palette)."""
    c = lambda k: theme.color(k, t)  # noqa: E731
    pal = QPalette(base)
    roles = {
        QPalette.ColorRole.Window: "win", QPalette.ColorRole.WindowText: "text", QPalette.ColorRole.Base: "surf",
        QPalette.ColorRole.AlternateBase: "win", QPalette.ColorRole.Text: "text", QPalette.ColorRole.Button: "surf",
        QPalette.ColorRole.ButtonText: "text", QPalette.ColorRole.BrightText: "err",
        QPalette.ColorRole.Highlight: "accS", QPalette.ColorRole.HighlightedText: "accT",
        QPalette.ColorRole.ToolTipBase: "tip", QPalette.ColorRole.ToolTipText: "surf",
        QPalette.ColorRole.Link: "acc", QPalette.ColorRole.LinkVisited: "accT", QPalette.ColorRole.Light: "surf",
        QPalette.ColorRole.Midlight: "hover", QPalette.ColorRole.Mid: "bord", QPalette.ColorRole.Dark: "bord",
    }
    # Qt5: QPalette.PlaceholderText, Qt6/PyQt6: nur QPalette.ColorRole.PlaceholderText
    if hasattr(QPalette.ColorRole, "PlaceholderText"):
        roles[QPalette.ColorRole.PlaceholderText] = "muted"
    for role, token in roles.items():
        pal.setColor(role, c(token))
    pal.setColor(QPalette.ColorRole.Shadow, QColor(0, 0, 0))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, c("faint"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, c("press"))
    return pal


class WholeTheme(object):
    """Stylesheet am Hauptfenster und Anwendungspalette setzen und exakt zurücknehmen."""

    def __init__(self, main_window):
        self.mw = main_window
        self.app = QApplication.instance()
        self.active = False
        self._before = None
        self._applied = None
        self._palette_before = None
        self._palette_applied = None
        self._messages = {}   # Meldungsfeld -> (Stylesheet vorher, gesetztes Stylesheet)

    def _message_edits(self):
        # findChildren statt statusBar(): das legte eine fehlende Statusleiste erst an
        return [e for bar in self.mw.findChildren(QStatusBar) for e in bar.findChildren(QLineEdit)
                if _MESSAGE_SHEET in e.styleSheet() and _MESSAGE_COLOR.search(e.styleSheet())]

    def _color_messages(self, t):
        color = theme.color("muted", t).name()
        for edit in self._message_edits():
            before = self._messages[edit][0] if edit in self._messages else edit.styleSheet()
            if edit in self._messages and edit.styleSheet() != self._messages[edit][1]:
                before = edit.styleSheet()   # QGIS hat es inzwischen neu gesetzt
            sheet = _MESSAGE_COLOR.sub(lambda m: m.group(1) + color, before)
            edit.setStyleSheet(sheet)
            self._messages[edit] = (before, sheet)

    def _resync_later(self, sheet):
        """Stylesheet nach dem Zurücksetzen der Palette noch einmal setzen.

        QGIS gibt seinen Widgets eigene Paletten; ein Wechsel der Anwendungspalette
        erreicht sie nicht. Erst ein neu gesetztes Stylesheet poliert alle Widgets
        mit der dann gültigen Palette. Ohne das blieben unter macOS nach dem
        Abschalten Docks in der dunklen Palette (dunkle Schrift auf dunklem Grund).
        Beim Einschalten nicht: dort überdeckte das neu Polieren die Stylesheet-
        Hintergründe der Docks mit hellen Flächen.
        """
        def resync():
            try:
                if self.mw.styleSheet() == sheet:
                    self.mw.setStyleSheet(sheet + "\n")
                    self.mw.setStyleSheet(sheet)
            except RuntimeError:   # Hauptfenster inzwischen gelöscht
                pass
        QTimer.singleShot(0, resync)

    def _restore_messages(self):
        for edit, (before, applied) in self._messages.items():
            try:
                if edit.styleSheet() == applied:
                    edit.setStyleSheet(before)
            except RuntimeError:   # Widget inzwischen gelöscht
                pass
        self._messages = {}

    def apply(self, tokens=None):
        t = tokens or theme.current()
        if not self.active:
            self._before = self.mw.styleSheet()
            self._palette_before = QPalette(self.app.palette())
            self.active = True
        else:
            if self.mw.styleSheet() != self._applied:
                # Jemand anderes hat das Stylesheet inzwischen geändert: dessen Stand übernehmen
                current = self.mw.styleSheet()
                self._before = current.split(MARKER)[0][:-1] if MARKER in current else current
            if self._foreign_palette():
                self._palette_before = QPalette(self.app.palette())
        sheet = whole_qss(t)
        self._applied = (self._before + "\n" + sheet) if self._before else sheet
        self.mw.setStyleSheet(self._applied)
        pal = whole_palette(t, self._palette_before)
        self._palette_applied = pal
        if self.app.palette() != pal:
            self.app.setPalette(pal)
        self._color_messages(t)

    def _foreign_palette(self):
        return self._palette_applied is not None and self.app.palette() != self._palette_applied

    def base_lightness(self):
        """Helligkeit von QGIS ohne die eigene Palette (für den Modus „Automatisch“)."""
        if self.active and not self._foreign_palette():
            return self._palette_before.color(QPalette.ColorRole.Window).lightness()
        return self.app.palette().color(QPalette.ColorRole.Window).lightness()

    def restore(self):
        if not self.active:
            return
        self.active = False
        self._restore_messages()
        if self.mw.styleSheet() == self._applied:
            self.mw.setStyleSheet(self._before)
        if self.app.palette() == self._palette_applied:
            self.app.setPalette(self._palette_before)
            self._resync_later(self._before)
        self._before = None
        self._applied = None
        self._palette_before = None
        self._palette_applied = None

    def update(self, on, tokens=None):
        if on:
            self.apply(tokens)
        else:
            self.restore()
