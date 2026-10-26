"""Befehlssuche im Ribbon: Suchfeld rechts neben den Tabs.

Findet die Befehle des Ribbons (deutsche Beschriftung, Beschreibung, Ort) und
alle übrigen QGIS-Aktionen aus Menüs und Werkzeugleisten (``core.search``).
Der Index entsteht beim ersten Gebrauch, nicht beim Start. Ergebnisse
zeigen den Ort („Karte › Auswahl“ bzw. „QGIS: Vektor › Geoverarbeitung“);
graue Befehle stehen grau in der Liste und lassen sich nicht auslösen.

Auslösen: Buttons direkt; Steuerelemente, Galerien und Menüs über ihren Tab
(der Tab wird gewählt und das Element wie per KeyTip bedient).
"""

import time

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QModelIndex, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QPainter, QPen, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import QCompleter, QLineEdit, QToolBar

from ..core.search import PATH_SEP, Entry, SearchIndex, ribbon_entries
from ..qgis_integration.action_resolver import clean_text
from . import icons, theme
from ..core.i18n import tr

PLACEHOLDER = tr("Search commands")
HINT = "Alt Q"          # KeyTip-Hinweis rechts im leeren Feld
WIDTH = 220
LIMIT = 15
ROLE_ENTRY = Qt.UserRole + 1


def qgis_action_entries(main_window, skip_names):
    """QGIS-Aktionen aus Menüleiste und Werkzeugleisten mit ihrem Ort."""
    out = []
    seen = set()

    def add(act, path):
        if act.isSeparator() or act.menu() is not None or id(act) in seen:
            return
        name = act.objectName()
        text = clean_text(act.text())
        if not text or name in skip_names or name.startswith("ribbon_"):
            return
        seen.add(id(act))
        tip = clean_text(act.toolTip())
        out.append(Entry(text, act, path="QGIS: " + path,
                         description=tip if tip != text else "", ribbon=False))

    def walk(menu, path):
        for act in menu.actions():
            sub = act.menu()
            if sub is not None:
                walk(sub, path + PATH_SEP + clean_text(sub.title()))
            else:
                add(act, path)

    for act in main_window.menuBar().actions():
        if act.menu() is not None:
            walk(act.menu(), clean_text(act.menu().title()))
    for tb in main_window.findChildren(QToolBar, options=Qt.FindDirectChildrenOnly):
        if tb.objectName().startswith("QgisRibbon"):
            continue
        for act in tb.actions():
            add(act, tr("Toolbar ") + clean_text(tb.windowTitle()))
    return out


class SearchBox(QLineEdit):
    """Suchfeld mit Ergebnisliste.

    ``run(entry)`` löst einen Ribbon-Befehl aus, ``can_run(entry)`` sagt, ob er
    gerade bedienbar ist (beides vom ``RibbonWidget``, das Tabs und Elemente kennt).
    """

    executed = pyqtSignal()

    def __init__(self, ribbon, ctx, run, can_run, parent=None):
        QLineEdit.__init__(self, parent)
        self.setObjectName("ribbon_search")
        self.setPlaceholderText(PLACEHOLDER)
        self.setClearButtonEnabled(True)
        self.setFixedWidth(WIDTH)
        self.addAction(icons.ui_icon("suchen", QgsApplication.getThemeIcon("/search.svg")),
                       QLineEdit.LeadingPosition)
        self._ribbon = ribbon
        self._ctx = ctx
        self._run = run
        self._can_run = can_run
        self.index = None
        self.last_ms = None   # Messpunkt: Suche je Tastendruck
        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self)
        self.completer.setModel(self.model)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setMaxVisibleItems(LIMIT)
        self.completer.setWidget(self)
        # setWidget statt setCompleter: das Feld übernimmt den Treffertext nicht
        self.completer.activated[QModelIndex].connect(self._activated)
        self.textEdited.connect(self.update_results)
        self.returnPressed.connect(self._run_first)

    def build_index(self):
        if self.index is None:
            entries = ribbon_entries(self._ribbon)
            # Nur Befehle mit Ort im Ribbon; Befehle, die nur im Editor zur
            # Auswahl stehen, findet die Suche als QGIS-Aktion
            mirrored = {e.ref[0].source.get("object_name") for e in entries
                        if e.ref[0].source.type in ("qgis_action", "plugin_action")}
            entries += qgis_action_entries(self._ctx.env.iface.mainWindow(), mirrored)
            self.index = SearchIndex(entries)
        return self.index

    def paintEvent(self, event):  # noqa: N802 (Qt)
        QLineEdit.paintEvent(self, event)
        if self.text() or self.hasFocus():
            return
        # KeyTip-Hinweis als kleine Marke rechts im leeren Feld
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
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
        painter.drawText(rect, Qt.AlignCenter, HINT)
        painter.end()

    def focusInEvent(self, event):
        QLineEdit.focusInEvent(self, event)
        self.build_index()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clear()
            self.completer.popup().hide()
            canvas = self._ctx.env.iface.mapCanvas()
            if canvas is not None:
                canvas.setFocus()
            return
        QLineEdit.keyPressEvent(self, event)

    def results(self, text):
        start = time.perf_counter()
        hits = self.build_index().search(text, LIMIT)
        self.last_ms = (time.perf_counter() - start) * 1000.0
        return hits

    def update_results(self, text):
        self.model.clear()
        hits = self.results(text)
        for e in hits:
            item = QStandardItem("%s  —  %s" % (e.label, e.path) if e.path else e.label)
            item.setData(e, ROLE_ENTRY)
            item.setToolTip(e.description or e.label)
            icon = self._icon(e)
            if icon is not None:
                item.setIcon(icon)
            item.setEnabled(self._enabled(e))
            item.setEditable(False)
            self.model.appendRow(item)
        if hits:
            self.completer.complete()
        else:
            self.completer.popup().hide()

    def _icon(self, entry):
        if entry.ribbon:
            cmd = entry.ref[0]
            res = self._ctx.resolver.resolve(cmd)
            fallback = res.icon
            if fallback.isNull() and cmd.icon:
                fallback = self._ctx.resolver.theme_icon(cmd.icon)
            icon = icons.command_icon(cmd, fallback)
            return None if icon is None or icon.isNull() else icon
        return entry.ref.icon()

    def _enabled(self, entry):
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
