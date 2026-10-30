"""Ribbon: Kopfzeile (Schnellzugriff, Tabs, Suche, Minimieren) und Seiten.

Seiten werden erst beim ersten Öffnen aufgebaut. Mit Kontextlogik
(``core.context.ContextLogic``) sind Kontext-Tabs nur sichtbar, wenn ihre
Bedingungen gelten; ``apply_context`` übernimmt die Änderungen nach einem
neuen Snapshot.

Bedienung:

- Schnellzugriffsleiste links neben den Tabs; Rechtsklick auf einen Befehl
  im Ribbon fügt ihn hinzu oder entfernt ihn.
- Minimieren: Doppelklick auf einen Tab, Strg+F1 oder der Pfeil rechts.
  Minimiert bleiben nur die Tabs sichtbar; ein Klick auf einen Tab klappt
  die Seite darüber auf, nach einem Befehl klappt sie wieder zu (wie in Pro).
- Befehlssuche rechts neben den Tabs.
- Eigene KeyTips über den Dialog „Kürzel anpassen“ (Menü ▾ oder Rechtsklick).
- Anleitung: Button „?“ rechts in der Kopfzeile, „Ribbon-Anleitung …“
  im Menü ▾ und im Rechtsklick-Menü (``ui/guide.py``).

Anpassen (Menü ▾ oder Rechtsklick): grafischer Editor „Ribbon anpassen“
(``ui/ribbon_editor.py``), gespeicherte Anordnungen
(Untermenü „Anordnungen“) und der Wechsel zur klassischen QGIS-Oberfläche
(``classicRequested``, nur mit Plugin). Nach einer Änderung baut das Plugin
den Ribbon neu auf (``Arrangements.changed``).

Design „Kontur“: Farben aus ``theme.ThemeManager``, ein
Stylesheet am Wurzel-Widget, Tableiste und Ribbon-Fläche selbst gezeichnet.
Untermenü „Darstellung“ (Menü ▾ und Rechtsklick): Modus (automatisch, hell,
dunkel), Akzent, eigene Icons, Animationen und – mit Plugin – „Kontur für
ganz QGIS“. Ein Wechsel stellt nur das Stylesheet um; nichts wird neu gebaut.

Anpassungen speichert ``UserSettings`` (Schnellzugriff, minimiert, Anordnung, Design).
"""

import time

from qgis.PyQt.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QPoint, QRectF, QSize, Qt,
                              QTimer, QVariantAnimation, pyqtSignal)
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from qgis.PyQt.QtWidgets import (QActionGroup, QFrame, QHBoxLayout, QMenu, QShortcut,
                                 QStackedWidget, QTabBar, QToolBar, QToolButton, QVBoxLayout,
                                 QWidget)

from ..core import customization as cz
from ..core import quick_access, theme_tokens
from ..qgis_integration import log, menu_bar
from ..qgis_integration.arrangements import Arrangements
from ..qgis_integration.user_settings import MemoryStore, UserSettings
from . import guide, icons, keys, theme
from .controls.buttons import BuildContext
from .quick_access import QuickAccessBar
from .qt_compat import event_pos
from .search_box import SearchBox
from .tab_page import TabPage
from ..core.i18n import tr

TEXT_DESIGN = tr("Appearance")
TEXT_ICONS = tr("Own Icons")
TEXT_ANIMATIONS = tr("Animations")
TEXT_WHOLE = tr("Kontur for All of QGIS")
MINIMIZE_SHORTCUT = keys.MINIMIZE
TEXT_MINIMIZE = tr("Minimize the Ribbon")
TEXT_PIN = tr("Pin the Ribbon")
TEXT_ADD = tr("Add to Quick Access Toolbar")
TEXT_REMOVE = tr("Remove from Quick Access Toolbar")
TEXT_KEYTIPS = tr("Customize KeyTips …")
TEXT_CUSTOMIZE = tr("Customize Ribbon …")
TEXT_GALLERY = tr("Customize Gallery “%s” …")
TEXT_CLASSIC = tr("Classic QGIS Interface")
TEXT_HIDE_MENUBAR = tr("Hide QGIS Menu Bar")
TEXT_QGIS_MENUS = tr("QGIS Menus")


class RibbonTabBar(QTabBar):
    """Tableiste im Kontur-Stil, vollständig selbst gezeichnet.

    Kontext-Tabs stehen in einer Kapsel (Fläche ``ctxS``) mit dem Namen des
    Kontexts davor; der gewählte Tab hat einen Unterstrich in Akzentfarbe
    (bei Kontext-Tabs ``ctx``), der beim Wechsel gleitet. Klicks, Tastatur und
    Scrollpfeile bleiben bei ``QTabBar``; nur Größe und Zeichnen sind eigen.
    """

    PAD = 11            # links/rechts neben dem Tabtext
    HEIGHT = 34
    LABEL_GAP = 8       # Kontextname – erster Tabtext
    UNDERLINE = 3

    def __init__(self, ribbon, parent=None):
        QTabBar.__init__(self, parent)
        # Zustand vor jedem Setter: unter macOS lösen setDocumentMode & Co.
        # sofort ein Layout aus, das tabSizeHint (also _fm) aufruft.
        self.ribbon = ribbon
        self.contextual = set()
        self._hover = -1
        self._metrics = {}  # Schriftmaße (Tab, Kontextname); geleert bei Schrift-/Stilwechsel
        self._from = None   # Unterstrich vor dem Wechsel (QRectF)
        self._progress = 1.0
        self._last = -1
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setUsesScrollButtons(True)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.currentChanged.connect(self._start_animation)

    # Schriften
    def _font(self, bold=False):
        f = QFont(self.font())
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() * 1.08)
        f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        return f

    def _label_font(self):
        f = QFont(self.font())
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() * 0.8)
        f.setWeight(QFont.Weight.DemiBold)
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)
        return f

    def _fm(self, kind):
        """Schriftmaße für ``"tab"`` (fett) oder ``"label"`` (Kontextname), gecacht.

        Qt fragt ``tabSizeHint`` bei jedem Layout-Durchlauf für alle Tabs ab, also
        bei jedem Ein- und Ausblenden eines Kontext-Tabs.
        """
        fm = self._metrics.get(kind)
        if fm is None:
            fm = QFontMetrics(self._font(True) if kind == "tab" else self._label_font())
            self._metrics[kind] = fm
        return fm

    def changeEvent(self, event):  # noqa: N802 (Qt)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._metrics = {}
        QTabBar.changeEvent(self, event)

    def context_of(self, index):
        tab = self.ribbon.tabs[index] if 0 <= index < len(self.ribbon.tabs) else None
        return tab.context if tab is not None and tab.contextual else None

    def context_label(self, index):
        """Kontextname, wenn ``index`` der erste sichtbare Tab seines Kontexts ist."""
        ctx = self.context_of(index)
        if ctx is None:
            return None
        for i in range(index - 1, -1, -1):
            if self.context_of(i) != ctx:
                break
            if self.isTabVisible(i):
                return None
        return ctx

    # Größe
    def _label_width(self, index):
        label = self.context_label(index)
        if label is None:
            return 0
        return self._fm("label").horizontalAdvance(label) + self.LABEL_GAP

    def tabSizeHint(self, index):  # noqa: N802 (Qt)
        w = self._fm("tab").horizontalAdvance(self.tabText(index)) + 2 * self.PAD + self._label_width(index)
        if index in self.contextual and self.context_label(index) is not None:
            w += 4
        return QSize(w, self.HEIGHT)

    def minimumTabSizeHint(self, index):  # noqa: N802 (Qt)
        return self.tabSizeHint(index)

    def text_rect(self, index):
        r = self.tabRect(index)
        left = r.x() + self.PAD + self._label_width(index)
        if index in self.contextual and self.context_label(index) is not None:
            left += 4
        width = self._fm("tab").horizontalAdvance(self.tabText(index))
        return QRectF(left, r.y(), width, r.height())

    def _underline(self, index):
        rect = self.text_rect(index)
        return QRectF(rect.x(), self.height() - self.UNDERLINE, rect.width(), self.UNDERLINE)

    # Animation
    def _start_animation(self, index):
        old, self._last = self._last, index
        animate = theme.setting("animations") is not False and old >= 0 and self.isVisible()
        if animate and 0 <= old < self.count() and self.isTabVisible(old):
            self._from = self._underline(old)
            self._anim.stop()
            self._anim.setDuration(theme.ANIMATION_MS)
            self._anim.start()
        else:
            self._from = None
            self._progress = 1.0
        self.update()

    def _on_anim(self, value):
        self._progress = float(value)
        if self._anim.state() == QAbstractAnimation.State.Stopped or self._progress >= 1.0:
            self._from = None
        self.update()

    # Hover
    def mouseMoveEvent(self, event):  # noqa: N802 (Qt)
        i = self.tabAt(event_pos(event))
        if i != self._hover:
            self._hover = i
            self.update()
        QTabBar.mouseMoveEvent(self, event)

    def leaveEvent(self, event):  # noqa: N802 (Qt)
        self._hover = -1
        self.update()
        QTabBar.leaveEvent(self, event)

    # Zeichnen
    def _capsules(self):
        """(Kontextname, QRectF) je Gruppe sichtbarer Kontext-Tabs."""
        groups = []
        for i in range(self.count()):
            ctx = self.context_of(i)
            if ctx is None or not self.isTabVisible(i):
                continue
            r = QRectF(self.tabRect(i))
            if groups and groups[-1][0] == ctx and groups[-1][2] == i - 1:
                groups[-1] = (ctx, groups[-1][1].united(r), i)
            elif groups and groups[-1][0] == ctx and all(
                    not self.isTabVisible(j) for j in range(groups[-1][2] + 1, i)):
                groups[-1] = (ctx, groups[-1][1].united(r), i)
            else:
                groups.append((ctx, r, i))
        return [(ctx, r) for ctx, r, _last in groups]

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        current = self.currentIndex()

        # Kontext-Kapseln mit Namen
        for ctx, r in self._capsules():
            cap = r.adjusted(1, 5, -1, -7)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("ctxS"))
            p.drawRoundedRect(cap, 8, 8)
        p.setFont(self._label_font())
        for i in range(self.count()):
            label = self.context_label(i) if self.isTabVisible(i) else None
            if label is None:
                continue
            r = self.tabRect(i)
            lr = QRectF(r.x() + self.PAD, r.y(), self._label_width(i), r.height() - 2)
            p.setPen(theme.color("ctxT"))
            p.drawText(lr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        # Tabtexte und Hover
        for i in range(self.count()):
            if not self.isTabVisible(i):
                continue
            tr = self.text_rect(i)
            contextual = i in self.contextual
            enabled = self.isTabEnabled(i)
            if i == self._hover and i != current and enabled:
                hr = tr.adjusted(-6, 7, 6, -9)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("hover") if not contextual else theme.color("surf"))
                p.drawRoundedRect(hr, 6, 6)
            if not enabled:
                col = theme.color("faint")
            elif i == current:
                col = theme.color("ctxT") if contextual else theme.color("text")
            elif contextual:
                col = theme.color("ctxT")
            elif i == self._hover:
                col = theme.color("text")
            else:
                col = theme.color("muted")
            p.setPen(col)
            p.setFont(self._font(i == current))
            p.drawText(tr.adjusted(0, 0, 0, -2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       self.tabText(i))

        # Unterstrich
        if 0 <= current < self.count() and self.isTabVisible(current):
            target = self._underline(current)
            if self._from is not None and self._progress < 1.0:
                t = self._progress
                f = self._from
                target = QRectF(f.x() + (target.x() - f.x()) * t, target.y(),
                                f.width() + (target.width() - f.width()) * t, target.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("ctx") if current in self.contextual else theme.color("acc"))
            p.drawRoundedRect(target, 1.5, 1.5)

        # Fokusring (Tastatur)
        if self.hasFocus() and 0 <= current < self.count():
            fr = self.text_rect(current).adjusted(-6, 6, 6, -8)
            pen = QPen(theme.color("acc"))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(fr, 6, 6)
        p.end()


class SurfaceFrame(QFrame):
    """Ribbon-Fläche: abgerundet, mit weichem Schatten (Tokens ``surf``, ``shadow``)."""

    def __init__(self, parent=None):
        QFrame.__init__(self, parent)
        self.setObjectName("ribbon_surface")
        lay = QVBoxLayout(self)
        m = theme.SURFACE_MARGIN
        lay.setContentsMargins(m + 4, 1, m + 4, theme.SHADOW + 2)
        lay.setSpacing(0)

    def surface_rect(self):
        m = theme.SURFACE_MARGIN
        return QRectF(m + 0.5, 0.5, self.width() - 2 * m - 1, self.height() - theme.SHADOW - 1)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.surface_rect()
        radius = theme.SURFACE_RADIUS
        shadow = theme.color("shadow")
        if shadow.alpha() > 0:
            p.setPen(Qt.PenStyle.NoPen)
            steps = 5
            for k in range(steps, 0, -1):
                c = QColor(shadow)
                c.setAlpha(max(1, int(shadow.alpha() * (steps + 1 - k) / (steps * 2.2))))
                p.setBrush(c)
                grow = k * 0.9
                p.drawRoundedRect(r.adjusted(-grow, -grow + 1.5 + k * 0.5, grow, grow + k * 0.5),
                                  radius + grow, radius + grow)
        p.setBrush(theme.color("surf"))
        pen = QPen(theme.color("div") if theme.is_dark() else theme.color("bord"))
        pen.setWidthF(1.0)
        if not theme.is_dark():
            col = pen.color()
            col.setAlpha(150)
            pen.setColor(col)
        p.setPen(pen)
        p.drawRoundedRect(r, radius, radius)
        p.end()


class RibbonPopup(QFrame):
    """Aufgeklappte Seite bei minimiertem Ribbon (schließt bei Klick daneben)."""

    def __init__(self, ribbon_widget):
        QFrame.__init__(self, ribbon_widget, Qt.WindowType.Popup)
        self.setObjectName("ribbon_popup")
        self._ribbon = ribbon_widget
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)

    def contextMenuEvent(self, event):  # noqa: N802 (Qt)
        self._ribbon.show_context_menu(event.globalPos(), self.childAt(event.pos()))


class RibbonWidget(QWidget):
    classicRequested = pyqtSignal()
    menuBarToggled = pyqtSignal(bool)

    def __init__(self, ribbon, resolver, hub, parent=None, logic=None, user=None, arrangements=None,
                 theme_manager=None):
        QWidget.__init__(self, parent)
        self.setObjectName("QgisRibbonWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.ribbon = ribbon
        self.logic = logic
        self.user = user if user is not None else UserSettings(MemoryStore())
        # Design: Stylesheet vor dem Aufbau setzen, damit jedes Kind nur einmal poliert wird
        self.themes = theme_manager if theme_manager is not None else theme.ThemeManager(self.user, self)
        self._own_themes = theme_manager is None
        self.whole_available = False   # „Kontur für ganz QGIS“ (nur mit Plugin)
        self.menubar_available = False  # QGIS-Menüleiste ausblenden (nur mit Plugin)
        self.menubar_hidden = False
        self.themes.changed.connect(self.apply_theme)
        self.setStyleSheet(theme.ribbon_qss(theme.current()))
        # Ohne Plugin: Anordnung auf Grundlage des gezeigten Ribbons (gespeichert, nicht neu aufgebaut)
        self.arrangements = arrangements if arrangements is not None else Arrangements(ribbon, self.user, self)
        self.classic_available = arrangements is not None
        self.ctx = BuildContext(resolver, hub, logic)
        self.ctx.trigger_hooks.append(self._after_trigger)
        self.build_times = {}  # Tab-ID -> ms (Messpunkt)
        self.last_apply_ms = None  # Messpunkt: Übernahme eines neuen Kontexts
        self._index = {t.id: i for i, t in enumerate(ribbon.tabs)}
        self.minimized = False
        self.popup = None

        self.header = QWidget(self)
        self.header.setObjectName("ribbon_header")
        self.header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header.setFixedHeight(theme.HEADER_HEIGHT)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(8, 0, 10, 0)
        head.setSpacing(4)
        self.quick = QuickAccessBar(self.ctx, self.header)
        self.quick.removeRequested.connect(self.remove_from_quick_access)
        self.quick.resetRequested.connect(self.reset_quick_access)
        self.quick.minimizeToggled.connect(self.toggle_minimized)
        self.quick.keytipsRequested.connect(self.open_keytip_dialog)
        self.quick.extend_menu = self.add_customize_actions
        self.tabbar = RibbonTabBar(ribbon, self.header)
        self.tabbar.setObjectName("ribbon_tabbar")
        self.search = SearchBox(ribbon, self.ctx, self.run_entry, self.can_run_entry, self.header)
        self.pin = QToolButton(self.header)
        self.pin.setAutoRaise(True)
        self.pin.setObjectName("ribbon_minimize")
        self.pin.setFixedSize(28, 28)
        self.pin.clicked.connect(self.toggle_minimized)
        self.guide_button = QToolButton(self.header)
        self.guide_button.setAutoRaise(True)
        self.guide_button.setObjectName("ribbon_help_button")
        self.guide_button.setFixedSize(28, 28)
        self.guide_button.clicked.connect(lambda: self.open_help("index"))
        # Menüs der QGIS-Menüleiste, nur sichtbar, wenn die Menüleiste ausgeblendet ist
        self.menus_button = QToolButton(self.header)
        self.menus_button.setAutoRaise(True)
        self.menus_button.setObjectName("ribbon_qgis_menus")
        self.menus_button.setFixedSize(28, 28)
        self.menus_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menus_menu = QMenu(self.menus_button)
        self.menus_menu.aboutToShow.connect(lambda: menu_bar.fill_menu(self.menus_menu, self.window()))
        self.menus_button.setMenu(self.menus_menu)
        self.menus_button.hide()
        sep = QFrame(self.header)
        sep.setObjectName("ribbon_header_sep")
        sep.setFixedSize(1, 20)
        head.addWidget(self.menus_button, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.quick)
        head.addSpacing(4)
        head.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(6)
        # Die Tableiste bekommt den freien Platz (Tabs bleiben links, setExpanding(False)).
        # Mit einem Platzhalter daneben fiel sie auf ihre Mindestbreite zurück, sobald
        # Kontext-Tabs dazukamen, und zeigte Scrollpfeile trotz freiem Platz.
        head.addWidget(self.tabbar, 1, Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self.search, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.pin, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.guide_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.surface = SurfaceFrame(self)
        self.stack = QStackedWidget(self.surface)
        self.stack.setFixedHeight(theme.PAGE_HEIGHT)
        self.surface.layout().addWidget(self.stack)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.surface)

        self._pages = {}
        for i, tab in enumerate(ribbon.tabs):
            self.tabbar.addTab(tab.label)
            self.stack.addWidget(QWidget(self.stack))  # Platzhalter bis zum ersten Öffnen
            if tab.contextual:
                self.tabbar.contextual.add(i)
                self.tabbar.setTabToolTip(i, "%s: %s" % (tab.context, tab.label))
                if logic is not None and not logic.tab_visible(tab.id):
                    self.tabbar.setTabVisible(i, False)
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabBarClicked.connect(self._on_tab_clicked)
        self.tabbar.tabBarDoubleClicked.connect(lambda _i: self.toggle_minimized())
        self.shortcut = QShortcut(QKeySequence(MINIMIZE_SHORTCUT), self)
        self.shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.shortcut.activated.connect(self.toggle_minimized)
        if ribbon.tabs:
            self._on_tab_changed(0)
        self.load_quick_access()
        self._update_pin()
        if self.user.minimized():
            self.set_minimized(True, save=False)

    # Design
    def apply_theme(self):
        """Stylesheet und Farben nach einem Wechsel von Modus, Akzent oder Einstellung."""
        t = theme.current()
        icons.clear_cache()
        self.setStyleSheet(theme.ribbon_qss(t))
        parent = self.parentWidget()
        if isinstance(parent, QToolBar):
            parent.setStyleSheet(theme.toolbar_qss(t))
        self._update_pin()
        for w in [self] + self.findChildren(QWidget):
            w.update()

    def add_design_menu(self, menu):
        """Untermenü „Darstellung“: Modus, Akzent, eigene Icons, Animationen, Gesamtbild."""
        sub = menu.addMenu(TEXT_DESIGN)
        sub.setObjectName("ribbon_design_menu")
        s = self.themes.settings()
        modes = QActionGroup(sub)
        for key in theme_tokens.MODE_SETTINGS:
            act = sub.addAction(theme_tokens.MODE_LABELS[key])
            act.setCheckable(True)
            act.setChecked(s["mode"] == key)
            act.setActionGroup(modes)
            act.triggered.connect(lambda _c=False, k=key: self.themes.set("mode", k))
        sub.addSeparator()
        accents = QActionGroup(sub)
        current = theme.themes().valid_accent(s["accent"] or None)
        for key in theme.themes().accent_ids():
            act = sub.addAction(tr("Accent ") + theme.themes().accent_label(key))
            act.setCheckable(True)
            act.setChecked(current == key)
            act.setActionGroup(accents)
            act.triggered.connect(lambda _c=False, k=key: self.themes.set("accent", k))
        if self.themes.high_contrast:
            for act in sub.actions():
                act.setEnabled(False)
        sub.addSeparator()
        for key, text in (("icons", TEXT_ICONS), ("animations", TEXT_ANIMATIONS)):
            act = sub.addAction(text)
            act.setCheckable(True)
            act.setChecked(bool(s[key]))
            act.triggered.connect(lambda on, k=key: self.themes.set(k, bool(on)))
        if self.whole_available:
            act = sub.addAction(TEXT_WHOLE)
            act.setCheckable(True)
            act.setChecked(bool(s["whole"]))
            act.setToolTip(tr("Docks, layer tree, menu bar and status bar in the same style as the ribbon"))
            act.triggered.connect(lambda on: self.themes.set("whole", bool(on)))
        return sub

    def collapsed_groups(self, tab_id):
        """Eingeklappte Gruppen eines (gebauten) Tabs."""
        page = self._pages.get(tab_id)
        return [g for g in page.groups if g.collapsed] if page is not None else []

    # Tabs und Seiten
    def _on_tab_changed(self, index):
        if index < 0:
            return
        page = self.ensure_built(index)
        self.stack.setCurrentIndex(index)
        page.refresh_stale()
        if self.logic is not None:
            self.logic.tab_selected(self.ribbon.tabs[index].id)

    def _on_tab_clicked(self, index):
        if self.minimized and index >= 0:
            # Erst wählen (baut die Seite), dann aufklappen
            self.tabbar.setCurrentIndex(index)
            self.show_popup()

    def apply_context(self, changes):
        """Änderungen der Kontextlogik übernehmen (``core.context.Changes``)."""
        start = time.perf_counter()
        for cid in changes.commands:
            self.ctx.refresh(cid)
        if changes.select is not None:
            # Erst wählen, dann ausblenden: sonst springt Qt selbst auf einen Nachbar-Tab.
            self.tabbar.setTabVisible(self._index[changes.select], True)
            self.tabbar.setCurrentIndex(self._index[changes.select])
        for tid, visible in changes.tabs.items():
            self.tabbar.setTabVisible(self._index[tid], visible)
        self.last_apply_ms = (time.perf_counter() - start) * 1000.0

    def is_tab_visible(self, tab_id):
        return self.tabbar.isTabVisible(self._index[tab_id])

    def current_tab(self):
        return self.ribbon.tabs[self.tabbar.currentIndex()].id

    def tab_ids(self):
        return list(self._index)

    def ensure_built(self, index):
        tab = self.ribbon.tabs[index]
        if tab.id in self._pages:
            return self._pages[tab.id]
        start = time.perf_counter()
        self.ctx.resolver.refresh()
        page = TabPage(tab, self.ctx, self.stack)
        old = self.stack.widget(index)
        self.stack.insertWidget(index, page)
        self.stack.removeWidget(old)
        old.deleteLater()
        self._pages[tab.id] = page
        ms = (time.perf_counter() - start) * 1000.0
        self.build_times[tab.id] = ms
        log.info_later(tr("Tab “%s” built in %.1f ms") % (tab.label, ms))
        return page

    def is_built(self, tab_id):
        return tab_id in self._pages

    def page(self, tab_id):
        return self._pages.get(tab_id)

    def select_tab(self, tab_id):
        for i, tab in enumerate(self.ribbon.tabs):
            if tab.id == tab_id:
                self.tabbar.setCurrentIndex(i)
                return
        raise KeyError(tab_id)

    def targets(self, tab_id):
        """KeyTip-Ziele eines Tabs (baut den Tab bei Bedarf)."""
        self.ensure_built(self._index[tab_id])
        return list(self.ctx.targets.get(tab_id, ()))

    # Minimieren
    def toggle_minimized(self):
        self.set_minimized(not self.minimized)

    def set_minimized(self, on, save=True):
        on = bool(on)
        if on != self.minimized:
            self.minimized = on
            if on:
                self.surface.layout().removeWidget(self.stack)
                self.surface.hide()
                self.popup = RibbonPopup(self)
                self.popup.layout().addWidget(self.stack)
            else:
                popup, self.popup = self.popup, None
                popup.hide()
                popup.layout().removeWidget(self.stack)
                self.stack.setParent(self.surface)
                self.surface.layout().addWidget(self.stack)
                self.surface.show()
                popup.deleteLater()
            self.stack.show()
            self._update_pin()
            self.updateGeometry()
        if save:
            self.user.set_minimized(on)

    def _update_pin(self):
        text = TEXT_PIN if self.minimized else TEXT_MINIMIZE
        icon = icons.ui_icon("anheften" if self.minimized else "minimieren")
        if icon.isNull():
            self.pin.setText("▾" if self.minimized else "▴")  # ▾ / ▴
        else:
            self.pin.setIcon(icon)
        self.pin.setToolTip(tr("<b>%s</b><br>Shortcut: %s, double-click a tab")
                            % (text, keys.text(MINIMIZE_SHORTCUT)))
        icon = icons.ui_icon("hilfe")
        if icon.isNull():
            self.guide_button.setText("?")
        else:
            self.guide_button.setIcon(icon)
        self.guide_button.setToolTip("<b>%s</b><br>%s" % (guide.TITLE, guide.TIP))
        icon = icons.ui_icon("menue")
        if icon.isNull():
            self.menus_button.setText("☰")
        else:
            self.menus_button.setIcon(icon)
        self.menus_button.setToolTip(tr("<b>%s</b><br>The menus of the hidden QGIS menu bar") % TEXT_QGIS_MENUS)
        self.quick.minimized = self.minimized

    def show_popup(self):
        if not self.minimized or self.popup is None:
            return
        pos = self.header.mapToGlobal(QPoint(0, self.header.height()))
        self.popup.setGeometry(pos.x(), pos.y(), self.width(), self.stack.height() + 2)
        self.popup.show()
        self.popup.raise_()

    def hide_popup(self):
        if self.popup is not None:
            self.popup.hide()

    def _after_trigger(self):
        if self.minimized:
            self.hide_popup()

    # Schnellzugriffsleiste
    def load_quick_access(self):
        self.quick.set_commands(quick_access.effective(self.ribbon, self.user.quick_access()))

    def _store_quick_access(self, commands):
        self.user.set_quick_access(quick_access.serialize(commands))
        self.quick.set_commands(commands)

    def add_to_quick_access(self, command):
        self._store_quick_access(quick_access.added(self.quick.commands, command))

    def remove_from_quick_access(self, command):
        self._store_quick_access(quick_access.removed(self.quick.commands, command))

    def reset_quick_access(self):
        self.user.reset_quick_access()
        self.load_quick_access()

    # Kontextmenü
    def contextMenuEvent(self, event):
        self.show_context_menu(event.globalPos(), self.childAt(event.pos()))

    def command_at(self, widget):
        while widget is not None and widget is not self:
            cmd = self.ctx.widget_commands.get(widget)
            if cmd is not None:
                return cmd
            widget = widget.parentWidget()
        return None

    def gallery_at(self, widget):
        """Anpassbare Galerie unter dem Widget (Galerie-Button, Galerie im Ribbon, ihre Kacheln) oder None."""
        known = cz.galleries(self.arrangements.base)
        while widget is not None and widget is not self:
            cmd = self.ctx.widget_commands.get(widget) or getattr(widget, "command", None)
            if cmd is not None and getattr(cmd, "id", None) in known:
                return cmd
            widget = widget.parentWidget()
        return None

    def context_menu(self, widget):
        """Kontextmenü für das Widget (ohne es anzuzeigen; für Tests getrennt)."""
        menu = QMenu(self)
        cmd = self.command_at(widget)
        if cmd is not None and quick_access.allowed(cmd):
            if cmd in self.quick.commands:
                menu.addAction(TEXT_REMOVE, lambda: self.remove_from_quick_access(cmd))
            else:
                menu.addAction(TEXT_ADD, lambda: self.add_to_quick_access(cmd))
            menu.addSeparator()
        gallery = self.gallery_at(widget)
        if gallery is not None:
            act = menu.addAction(TEXT_GALLERY % gallery.label, lambda: self.open_gallery_dialog(gallery.id))
            act.setObjectName("ribbon_customize_gallery")
            menu.addSeparator()
        menu.addAction(TEXT_KEYTIPS, self.open_keytip_dialog)
        menu.addAction(TEXT_PIN if self.minimized else TEXT_MINIMIZE, self.toggle_minimized)
        menu.addSeparator()
        self.add_customize_actions(menu)
        return menu

    def add_customize_actions(self, menu):
        """Anpassen, Anordnungen und klassische Oberfläche (Kontextmenü und Menü ▾)."""
        from . import arrangement_menu
        menu.addAction(TEXT_CUSTOMIZE, self.open_customize_dialog)
        arrangement_menu.add_submenu(menu, self)
        self.add_design_menu(menu)
        if self.menubar_available:
            act = menu.addAction(TEXT_HIDE_MENUBAR)
            act.setObjectName("ribbon_hide_menubar")
            act.setCheckable(True)
            act.setChecked(self.menubar_hidden)
            act.setToolTip(tr("More room for the map. The QGIS menus stay available via the button "
                              "at the left of the Quick Access Toolbar and Alt+letter."))
            act.triggered.connect(lambda on: self.request_menubar_hidden(bool(on)))
        if self.classic_available:
            act = menu.addAction(TEXT_CLASSIC, self.request_classic)
            act.setToolTip(tr("Hide the ribbon and show the QGIS toolbars. Back via View › Ribbon Interface."))
        menu.addSeparator()
        act = menu.addAction(icons.ui_icon("hilfe"), guide.MENU_TEXT, lambda: self.open_help("index"))
        act.setToolTip(guide.TIP)

    def request_classic(self):
        self.hide_popup()
        self.classicRequested.emit()

    # QGIS-Menüleiste
    def set_menubar_hidden(self, on):
        """Zustand der Menüleiste übernehmen: Knopf „QGIS-Menüs“ zeigen oder verbergen."""
        self.menubar_hidden = bool(on)
        self.menus_button.setVisible(self.menubar_hidden)

    def request_menubar_hidden(self, on):
        self.set_menubar_hidden(on)
        self.menuBarToggled.emit(bool(on))

    def show_context_menu(self, global_pos, widget):
        menu = self.context_menu(widget)
        menu.exec(global_pos)
        menu.deleteLater()

    # Anleitung
    def open_help(self, topic):
        self.hide_popup()
        return guide.show_help(topic, self.window())

    # Kürzel
    def keytip_dialog(self):
        from .keytip_dialog import KeyTipDialog
        return KeyTipDialog(self)

    def open_keytip_dialog(self):
        self.hide_popup()
        dlg = self.keytip_dialog()
        dlg.exec()
        dlg.deleteLater()

    # Anpassen (grafischer Editor)
    def customize_dialog(self):
        from .ribbon_editor import RibbonEditor
        return RibbonEditor(self.arrangements, self.window())

    def open_customize_dialog(self):
        self.hide_popup()
        dlg = self.customize_dialog()
        dlg.exec()
        dlg.deleteLater()

    def gallery_dialog(self, gallery_id):
        from .customize_dialog import GalleryDialog
        return GalleryDialog(self.arrangements, gallery_id, self.window())

    def open_gallery_dialog(self, gallery_id):
        self.hide_popup()
        dlg = self.gallery_dialog(gallery_id)
        dlg.exec()
        dlg.deleteLater()

    # Befehlssuche
    def _navigates(self, command):
        """Befehle, die nicht direkt auslösbar sind, sondern über ihr Element bedient werden."""
        return not quick_access.allowed(command) or command.source.type == "qgis_menu"

    def can_run_entry(self, entry):
        cmd, tab_id = entry.ref
        res = self.ctx.resolver.resolve(cmd)
        if not res.available or not self.ctx.allowed(cmd):
            return False
        if self._pool_menu(cmd, tab_id):
            return res.menu is not None
        if self._navigates(cmd):
            return tab_id is not None and self.is_tab_visible(tab_id)
        return res.action is None or res.action.isEnabled()

    def _pool_menu(self, cmd, tab_id):
        """QGIS-Menü ohne Ort im Ribbon (Befehlsvorrat): öffnet unter dem Suchfeld."""
        return cmd.source.type == "qgis_menu" and tab_id is None

    def run_entry(self, entry):
        cmd, tab_id = entry.ref
        if self._pool_menu(cmd, tab_id):
            menu = self.ctx.resolver.resolve(cmd).menu
            if menu is None:
                return False
            menu.popup(self.search.mapToGlobal(QPoint(0, self.search.height())))
            return True
        if not self._navigates(cmd):
            self.ctx.resolver.trigger(cmd)
            self.ctx.after_trigger()
            return True
        if tab_id is None or not self.is_tab_visible(tab_id):
            return False
        self.select_tab(tab_id)
        target = next((t for t in self.targets(tab_id) if t.command is not None
                       and t.command.id == cmd.id), None)
        if target is None:
            return False
        if self.minimized:
            self.show_popup()
        QTimer.singleShot(0, target.activate)  # nach dem Layout des Tabs
        return True
