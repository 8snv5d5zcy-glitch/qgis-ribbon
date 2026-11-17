"""Befehlssuche im Ribbon: Suchfeld rechts neben den Tabs.

Findet die Befehle des Ribbons (deutsche Beschriftung, Beschreibung, Ort),
alle übrigen QGIS-Aktionen aus Menüs und Werkzeugleisten (auch aus deren
Dropdowns und eingebetteten Buttons), die Funktionen des Ribbons selbst (Ort
„Ribbon“) und im Hauptfenster alle Werkzeuge des Werkzeugkastens (``tools``,
``core.search``). Der Index entsteht beim ersten Gebrauch, nicht beim Start;
die Werkzeuge kommen nach dem Fokus in Schritten zu je ``TOOL_CHUNK`` in den
folgenden Durchläufen der Ereignisschleife dazu (je Schritt unter 30 ms),
spätestens bei der ersten Suche. Ergebnisse zeigen den Ort („Karte › Auswahl“
bzw. „QGIS: Vektor › Geoverarbeitung“) getrennt von der Beschriftung; graue
Befehle stehen grau in der Liste und lassen sich nicht auslösen.

Auslösen: Buttons direkt; Steuerelemente, Galerien und Menüs über ihren Tab
(der Tab wird gewählt und das Element wie per KeyTip bedient).

Aktuell halten: Meldet der Katalog der Erweiterungen eine Änderung oder neue
bzw. gelöschte Werkzeuge, wird der Index verworfen (``invalidate``) und beim
nächsten Gebrauch neu gebaut. QGIS-Aktionen
können auch sonst verschwinden (neu aufgebaute Menüs); trifft die Suche auf eine
gelöschte Aktion, baut sie den Index neu, und tote Treffer fallen still weg.
Die Funktionen des Ribbons (Häkchen von Darstellung, Menüleiste …) werden bei
jedem Fokus neu gelesen.
"""

import time

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QModelIndex, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPalette, QPen, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (QApplication, QCompleter, QLineEdit, QStyle, QStyledItemDelegate,
                                 QStyleOptionViewItem, QToolBar, QToolButton, QWidgetAction)

from ..core import extensions as ext
from ..core.search import (PATH_SEP, TIER_ACTION, Entry, SearchIndex, algorithm_entries, placed_tools,
                           pool_entries, ribbon_entries)
from ..core.text import plain_text
from ..qgis_integration.action_resolver import clean_text
from ..qgis_integration.signals import alive as qt_alive
from . import icons, keys, theme
from ..core.i18n import tr

PLACEHOLDER = tr("Search commands")
HINT = keys.text("Alt") + " Q"   # KeyTip-Hinweis rechts im leeren Feld
WIDTH = 220
NARROW = 140        # Suchfeld bei wenig Platz (Tabs zuerst)
POPUP_WIDTH = 460   # Mindestbreite der Trefferliste
LIMIT = 15
TOOL_CHUNK = 400    # Werkzeuge je Schritt der Ereignisschleife
ROLE_ENTRY = Qt.ItemDataRole.UserRole + 1
ROLE_PATH = Qt.ItemDataRole.UserRole + 2
RIBBON_PLACE = "Ribbon"
# Menüeinträge und Buttons der Verarbeitung: stehen als Werkzeug im Index
TOOL_ACTIONS = ("mProcessingUserMenu_", "mProcessingAlg_")


def qgis_action_entries(main_window, skip_names, skip_prefixes=(), seen=None):
    """QGIS-Aktionen aus Menüleiste und Werkzeugleisten mit ihrem Ort.

    Dropdowns von Leistenaktionen und eingebettete Buttons (Hauptaktion und
    Menü) zählen mit; unsichtbare Aktionen nicht. ``seen`` (Menge von ``id``)
    sammelt die aufgenommenen Aktionen.
    """
    out = []
    seen = set() if seen is None else seen
    # Abgelaufene Menüs: die Hüllen festhalten, sonst vergibt Python ihre id() neu
    # und ein anderes Menü gälte als schon abgelaufen
    menus = {}

    def add(act, path):
        if act.isSeparator() or act.menu() is not None or id(act) in seen or not act.isVisible():
            return
        name = act.objectName()
        text = clean_text(act.text())
        if not text or name in skip_names or name.startswith(("ribbon_",) + tuple(skip_prefixes)):
            return
        seen.add(id(act))
        tip = plain_text(act.toolTip())
        out.append(Entry(text, act, path="QGIS: " + path,
                         description=tip if tip != text else "", ribbon=False))

    def walk(menu, path):
        if id(menu) in menus:
            return
        menus[id(menu)] = menu
        for act in menu.actions():
            if not act.isVisible():
                continue
            sub = act.menu()
            if sub is not None:
                walk(sub, path + PATH_SEP + clean_text(sub.title() or act.text()))
            else:
                add(act, path)

    for act in main_window.menuBar().actions():
        if act.menu() is not None:
            walk(act.menu(), clean_text(act.menu().title()))
    for tb in main_window.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly):
        if tb.objectName().startswith("QgisRibbon"):
            continue
        where = tr("Toolbar ") + clean_text(tb.windowTitle())
        for act in tb.actions():
            if not act.isVisible():
                continue
            if isinstance(act, QWidgetAction):
                btn = tb.widgetForAction(act)
                if not isinstance(btn, QToolButton):
                    if act.menu() is not None:
                        walk(act.menu(), where + PATH_SEP + clean_text(act.text() or act.menu().title()))
                    continue
                main = btn.defaultAction()
                menu = btn.menu() or act.menu()
                if main is not None:
                    menu = menu or main.menu()
                    add(main, where)
                if menu is not None:
                    title = clean_text(main.text()) if main is not None else clean_text(menu.title())
                    walk(menu, where + PATH_SEP + title if title else where)
            elif act.menu() is not None:
                walk(act.menu(), where + PATH_SEP + clean_text(act.text() or act.menu().title()))
            else:
                add(act, where)
    return out


def function_entries(menu, path=RIBBON_PLACE):
    """Einträge für die Funktionen des Ribbons (Aktionen eines Menüs, rekursiv), Ort „Ribbon › …“."""
    out = []
    for act in menu.actions():
        if act.isSeparator() or not act.isVisible():
            continue
        sub = act.menu()
        if sub is not None:
            out += function_entries(sub, path + PATH_SEP + clean_text(sub.title()))
            continue
        text = clean_text(act.text())
        if text:
            out.append(Entry(text, act, path=path, description=plain_text(act.toolTip()), ribbon=False,
                             tier=TIER_ACTION))
    return out


def alive(entry):
    """False, wenn die QAction einer QGIS-Aktion inzwischen gelöscht ist."""
    return entry.ribbon or qt_alive(entry.ref)


def columns(label_width, path_width, available, gap):
    """Breiten von Beschriftung und Ort in einer Zeile: der Ort wird zuerst gekürzt, nie die Beschriftung.

    Reicht der Platz nicht einmal für die Beschriftung, bekommt sie alles und der Ort entfällt.
    """
    if label_width >= available or path_width <= 0:
        return min(label_width, available), 0
    rest = available - label_width - gap
    return label_width, max(0, min(path_width, rest))


def _copy(option):
    """Kopie der Stiloption (Felder wie ``text`` und ``state`` gibt es nur am Objekt, nicht an der Klasse)."""
    return QStyleOptionViewItem(option)


class ResultDelegate(QStyledItemDelegate):
    """Treffer: Beschriftung, daneben der Ort gedämpft und bei Platzmangel gekürzt."""

    def paint(self, painter, option, index):
        opt = _copy(option)
        self.initStyleOption(opt, index)
        label = opt.text
        path = index.data(ROLE_PATH) or ""
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        gap = fm.horizontalAdvance("    ")
        label_w, path_w = columns(fm.horizontalAdvance(label), fm.horizontalAdvance(path) if path else 0,
                                  rect.width() - 4, gap)
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        group = QPalette.ColorGroup.Normal if enabled else QPalette.ColorGroup.Disabled
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        color = opt.palette.color(group, role)
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(color)
        x = rect.x() + 2
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(QRect(x, rect.y(), label_w, rect.height()), align,
                         fm.elidedText(label, Qt.TextElideMode.ElideRight, label_w))
        if path_w > fm.horizontalAdvance("…") * 2:
            muted = QColor(color)
            muted.setAlpha(150)
            painter.setPen(muted)
            painter.drawText(QRect(x + label_w + gap, rect.y(), path_w, rect.height()), align,
                             fm.elidedText(path, Qt.TextElideMode.ElideMiddle, path_w))
        painter.restore()


class SearchBox(QLineEdit):
    """Suchfeld mit Ergebnisliste.

    ``run(entry)`` löst einen Ribbon-Befehl aus, ``can_run(entry)`` sagt, ob er
    gerade bedienbar ist (beides vom ``RibbonWidget``, das Tabs und Elemente kennt).
    ``functions``: liefert ein Menü mit den Funktionen des Ribbons (oder None).
    """

    executed = pyqtSignal()
    focusLost = pyqtSignal()

    def __init__(self, ribbon, ctx, run, can_run, parent=None, functions=None):
        QLineEdit.__init__(self, parent)
        self.setObjectName("ribbon_search")
        self.setPlaceholderText(PLACEHOLDER)
        self.setClearButtonEnabled(True)
        self.setFixedWidth(WIDTH)
        self.addAction(icons.ui_icon("suchen", QgsApplication.getThemeIcon("/search.svg")),
                       QLineEdit.ActionPosition.LeadingPosition)
        self._ribbon = ribbon
        self._ctx = ctx
        self._run = run
        self._can_run = can_run
        self._functions = functions
        self._function_menu = None
        self._function_entries = []
        self.index = None
        self.tools = None     # -> Werkzeuge (core.extensions.Algorithm); nur im Hauptfenster
        self._with_tools = False
        self._pending = None  # Werkzeuge, die noch in den Index müssen
        self._known = {}      # Werkzeuge, die schon als Ribbon-Befehl im Index stehen
        self._tool_timer = QTimer(self)
        self._tool_timer.setSingleShot(True)
        self._tool_timer.setInterval(0)
        self._tool_timer.timeout.connect(self._add_tools)
        self.last_ms = None   # Messpunkt: Suche je Tastendruck
        self.build_ms = None  # Messpunkt: Aufbau des Index ohne Werkzeuge
        self.tools_ms = None  # Messpunkt: längster Schritt der Werkzeuge
        self._placed = set()
        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self)
        self.completer.setModel(self.model)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setMaxVisibleItems(LIMIT)
        self.completer.setWidget(self)
        self.completer.popup().setItemDelegate(ResultDelegate(self.completer.popup()))
        # setWidget statt setCompleter: das Feld übernimmt den Treffertext nicht
        self.completer.activated[QModelIndex].connect(self._activated)
        self.textEdited.connect(self.update_results)
        self.returnPressed.connect(self._run_first)

    def build_index(self, tools=True):
        """Index (bei Bedarf neu); ``tools=False``: Werkzeuge noch nicht (folgen mit ``_add_tools``)."""
        if self.index is None:
            start = time.perf_counter()
            entries = ribbon_entries(self._ribbon)
            # Befehle mit Ort im Ribbon, dann der Befehlsvorrat ohne Ort; was
            # eine QGIS-Aktion spiegelt, findet die Suche als QGIS-Aktion
            mirrored = {e.ref[0].source.get("object_name") for e in entries
                        if e.ref[0].source.type in ("qgis_action", "plugin_action", "designer_action")}
            self._placed = {e.ref[0].id for e in entries}
            self._known = placed_tools(entries)
            entries += pool_entries(self._ribbon, self._placed)
            # Plugin-Befehle mit Ort: ihre Aktion nicht noch einmal als QGIS-Aktion
            seen = set()
            for e in entries:
                if e.ref[0].source.type == "extension":
                    act = self._ctx.resolver.resolve(e.ref[0]).action
                    if act is not None:
                        seen.add(id(act))
            entries += qgis_action_entries(self._ctx.resolver.window, mirrored,
                                           TOOL_ACTIONS if self.tools is not None else (), seen)
            entries += self._runtime_entries(seen)
            self._function_entries = self._read_functions()
            entries += self._function_entries
            self.index = SearchIndex(entries)
            self._with_tools = self.tools is None
            self._pending = None
            self.tools_ms = None
            self.build_ms = (time.perf_counter() - start) * 1000.0
        if tools:
            while not self._with_tools:
                self._tool_step()
        return self.index

    def _runtime_entries(self, seen):
        """Befehle der Plugins ohne Ort im Ribbon, deren Aktion die Suche sonst nirgends findet."""
        out = []
        resolver = self._ctx.resolver
        for cid, cmd in self._ribbon.commands.items():
            if cid in self._placed or not ext.is_plugin(cid) or cmd.kind != "button":
                continue
            res = resolver.resolve(cmd)
            if not res.available or res.action is None or id(res.action) in seen:
                continue
            seen.add(id(res.action))
            out.append(Entry(cmd.label, (cmd, None), path=tr("Command pool"), description=cmd.description or ""))
        return out

    def _read_functions(self):
        """Funktionen des Ribbons neu lesen (Häkchen und Namen der Anordnungen ändern sich)."""
        if self._functions is None:
            return []
        old = self._function_menu
        self._function_menu = self._functions()
        if old is not None and qt_alive(old):
            old.deleteLater()
        return function_entries(self._function_menu) if self._function_menu is not None else []

    def _refresh_functions(self):
        if self.index is None or self._functions is None:
            return
        old = set(id(e) for e in self._function_entries)
        self.index.entries = [e for e in self.index.entries if id(e) not in old]
        self._function_entries = self._read_functions()
        self.index.entries += self._function_entries

    def _tool_step(self):
        """Ein Schritt Werkzeuge in den Index (im ersten die Liste holen)."""
        start = time.perf_counter()
        if self._pending is None:
            self._pending = list(self.tools())
        else:
            chunk, self._pending = self._pending[:TOOL_CHUNK], self._pending[TOOL_CHUNK:]
            self.index.entries += algorithm_entries(chunk, self._placed, known=self._known)
        if not self._pending:
            self._with_tools = True
            self._pending = None
        ms = (time.perf_counter() - start) * 1000.0
        self.tools_ms = ms if self.tools_ms is None else max(self.tools_ms, ms)

    def _add_tools(self):
        if self.index is not None and not self._with_tools:
            self._tool_step()
            if not self._with_tools:
                self._tool_timer.start()

    def paintEvent(self, event):  # noqa: N802 (Qt)
        QLineEdit.paintEvent(self, event)
        if self.text() or self.hasFocus():
            return
        # KeyTip-Hinweis als kleine Marke rechts im leeren Feld
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 0.85)
        painter.setFont(font)
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(HINT) + 10
        h = fm.height() + 2
        rect = QRectF(self.width() - w - 10, (self.height() - h) / 2.0, w, h)
        pen = QPen(theme.color("bord"))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(theme.color("muted"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, HINT)
        painter.end()

    def focusInEvent(self, event):
        QLineEdit.focusInEvent(self, event)
        if self.index is not None:
            self._refresh_functions()
        self.build_index(tools=False)
        if not self._with_tools:
            self._tool_timer.start()

    def focusOutEvent(self, event):  # noqa: N802 (Qt)
        QLineEdit.focusOutEvent(self, event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.focusLost.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self.completer.popup().hide()
            canvas = self._ctx.env.iface.mapCanvas()
            if canvas is not None:
                canvas.setFocus()
            return
        QLineEdit.keyPressEvent(self, event)

    def invalidate(self):
        """Index verwerfen (neue oder entladene Plugins, neue Werkzeuge); neu gebaut beim nächsten Gebrauch."""
        self.index = None
        self._pending = None
        self._tool_timer.stop()

    def results(self, text):
        start = time.perf_counter()
        hits = self.build_index().search(text, LIMIT)
        if not all(alive(e) for e in hits):
            # QGIS hat Aktionen gelöscht: Index einmal neu aufbauen
            self.index = None
            hits = [e for e in self.build_index().search(text, LIMIT) if alive(e)]
        self.last_ms = (time.perf_counter() - start) * 1000.0
        return hits

    def update_results(self, text):
        self.model.clear()
        hits = self.results(text)
        for e in hits:
            item = QStandardItem(e.label)
            item.setData(e.path, ROLE_PATH)
            item.setData("%s  —  %s" % (e.label, e.path) if e.path else e.label,
                         Qt.ItemDataRole.AccessibleTextRole)
            item.setData(e, ROLE_ENTRY)
            item.setToolTip(e.description or e.label)
            icon = self._icon(e)
            if icon is not None:
                item.setIcon(icon)
            item.setEnabled(self._enabled(e))
            item.setEditable(False)
            self.model.appendRow(item)
        if hits:
            self.completer.complete(self.popup_rect())
        else:
            self.completer.popup().hide()

    def popup_rect(self):
        """Lage der Trefferliste (im Feld): mindestens ``POPUP_WIDTH`` breit, rechtsbündig, im Fenster."""
        width = max(POPUP_WIDTH, self.width())
        window = self.window()
        if window is not None and window is not self:
            width = min(width, window.width())
        x = self.width() - width
        if window is not None and window is not self:
            left = window.mapToGlobal(QPoint(0, 0)).x()
            shift = left - self.mapToGlobal(QPoint(x, 0)).x()
            if shift > 0:
                x += shift
        return QRect(x, 0, width, self.height())

    def _icon(self, entry):
        if entry.ribbon:
            cmd = entry.ref[0]
            res = self._ctx.resolver.resolve(cmd)
            fallback = res.icon
            if fallback.isNull() and cmd.icon:
                fallback = self._ctx.resolver.theme_icon(cmd.icon)
            icon = icons.command_icon(cmd, fallback)
            return None if icon is None or icon.isNull() else icon
        return entry.ref.icon() if alive(entry) else None

    def _enabled(self, entry):
        if not alive(entry):
            return False
        if not entry.ribbon:
            return entry.ref.isEnabled()
        return self._can_run(entry)

    def _activated(self, index):
        entry = index.data(ROLE_ENTRY)
        self.execute(entry)

    def _run_first(self):
        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            if item.isEnabled():
                self.execute(item.data(ROLE_ENTRY))
                return

    def execute(self, entry):
        if entry is None or not self._enabled(entry):
            return False
        self.clear()
        self.completer.popup().hide()
        if entry.ribbon:
            self._run(entry)
        else:
            entry.ref.trigger()
        self.executed.emit()
        return True
