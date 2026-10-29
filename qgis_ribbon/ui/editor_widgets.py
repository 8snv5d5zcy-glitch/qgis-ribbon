"""Bausteine des grafischen Ribbon-Editors.

Eigene, leichte Widgets statt der echten Ribbon-Widgets (die hängen an
Aktionen und Kontextlogik). Sie nutzen dieselben Maße (``theme``) und Icons
(``icons``), damit die Vorschau wie der Ribbon aussieht:

- ``ItemTile``: Eintrag einer Gruppe in seiner Größe (groß, mittel, klein,
  Zeile); Splits und Menüs mit ▾, ihr Inhalt lässt sich nur ansehen;
- ``GroupCard``: Gruppe als Karte mit Kopf (Griff, Beschriftung, Punkt
  „angepasst“, Auge, Menü ⋯) und Einträgen in Spalten wie im Ribbon;
- ``NewGroupCard``: „＋ Gruppe“ am Ende der Vorschau;
- ``TabChip``/``TabStrip``: Tableiste mit Auge und „＋ Tab“;
- ``QuickTile``/``QuickStrip``: Schnellzugriffsleiste über der Vorschau;
- ``Palette``: alle Befehle (oder Gruppen) der Definition als Icon-Kacheln
  mit Suche und Filter.

Auswählbare Teile (``Selectable``) melden Klicks und Tasten an den Editor
(``owner.select``/``owner.key``); der Editor entscheidet, was passiert.
Ziehen und Ablegen läuft ebenfalls über den Editor (``owner.drag_*``).
"""

from qgis.PyQt.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFrame, QHBoxLayout,
                                 QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                                 QScrollArea, QSizePolicy, QStyledItemDelegate, QToolButton,
                                 QVBoxLayout, QWidget)

from ..core import customization as cz
from ..core import extensions as ext
from ..core.model import CommandRef, Menu, Row, Split
from ..core.search import fold
from . import icons, theme
from .controls.buttons import MENU_ARROW
from .qt_compat import event_pos
from ..core.i18n import tr

MIME_TYPE = "application/x-qgis-ribbon-item"
HEADER_HEIGHT = 26
CARD_PADDING = 6
CARD_RADIUS = 8
ROW_ICON_WIDTH = 22
DOT = 6
QUICK_TILE = 26
PALETTE_GRID = QSize(96, 78)
PALETTE_ICON = 32
ROLE = Qt.ItemDataRole.UserRole + 1
ROLE_CHECK = Qt.ItemDataRole.UserRole + 2


def discard(widget, keep=None):
    """Widget abbauen. Während eines Zieh-Vorgangs (``keep`` ist eine Liste) nur verstecken:
    Qt hält die gezogene Kachel noch im Aufrufstapel, ``deleteLater`` liefe in der
    Ereignisschleife von ``QDrag.exec`` und löschte sie darunter weg."""
    widget.hide()  # sonst zeigt Qt sie später als eigenes Fenster
    widget.setParent(None)
    if keep is None:
        widget.deleteLater()
    else:
        keep.append(widget)


def text_width(widget, text):
    fm = widget.fontMetrics()
    return max((fm.horizontalAdvance(line) for line in text.split("\n")), default=0)


def element_icon(element):
    """Icon eines Elements (Befehl, Hauptbefehl, Menü, erster Befehl einer Zeile)."""
    if isinstance(element, CommandRef):
        return icons.command_icon(element.command)
    if isinstance(element, Split):
        return icons.command_icon(element.command)
    if isinstance(element, Menu):
        return icons.menu_icon(element.key or element.label)
    if isinstance(element, Row):
        return icons.command_icon(element.commands[0])
    return QIcon()


def has_menu(element):
    return isinstance(element, (Split, Menu)) or (
        isinstance(element, CommandRef) and element.command.gallery is not None)


def menu_entries(element):
    """Inhalt eines Splits/Menüs/einer Galerie zum Ansehen: [(Ebene, Beschriftung)]."""
    out = []

    def walk(items, level):
        for i in items:
            if hasattr(i, "items") and not hasattr(i, "source"):
                out.append((level, i.label))
                walk(i.items, level + 1)
            else:
                out.append((level, i.label))
                if getattr(i, "gallery", None) is not None:
                    walk(i.gallery.items, level + 1)

    if isinstance(element, Split):
        out.append((0, element.command.label))
        walk(element.items, 0)
    elif isinstance(element, Menu):
        if element.gallery is not None:
            out.append((0, element.gallery.label))
            walk(element.gallery.gallery.items if element.gallery.gallery else (), 1)
        walk(element.items, 0)
    elif isinstance(element, CommandRef) and element.command.gallery is not None:
        walk(element.command.gallery.items, 0)
    return out


def paint_icon(painter, icon, rect, faded=False):
    if icon is None or icon.isNull():
        return
    icon.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Disabled if faded else QIcon.Mode.Normal,
               QIcon.State.Off)


class Selectable(QWidget):
    """Auswählbarer Teil des Editors (Kachel, Gruppenkopf, Tab, Schnellzugriff)."""

    def __init__(self, owner, sel, parent=None):
        QWidget.__init__(self, parent)
        self.owner = owner
        self.sel = sel
        self.selected = False
        self.marked = False      # ausgeschnitten (Strg+X)
        self.faded = False       # ausgeblendet
        self._hover = False
        self._press = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.update()

    def enterEvent(self, event):  # noqa: N802 (Qt)
        self._hover = True
        self.update()
        QWidget.enterEvent(self, event)

    def leaveEvent(self, event):  # noqa: N802 (Qt)
        self._hover = False
        self.update()
        QWidget.leaveEvent(self, event)

    def mousePressEvent(self, event):  # noqa: N802 (Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event_pos(event)
            self.owner.select(self.sel, focus=True)
            self.clicked(event_pos(event))
        QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt)
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event_pos(event) - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.owner.start_drag(self)
            return
        QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt)
        self._press = None
        QWidget.mouseReleaseEvent(self, event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt)
        self.owner.rename(self.sel)

    def keyPressEvent(self, event):  # noqa: N802 (Qt)
        if not self.owner.key(self.sel, event):
            QWidget.keyPressEvent(self, event)

    def focusInEvent(self, event):  # noqa: N802 (Qt)
        if not self.selected:
            self.owner.focus_in(self.sel)
        self.update()
        QWidget.focusInEvent(self, event)

    def focusOutEvent(self, event):  # noqa: N802 (Qt)
        self.update()
        QWidget.focusOutEvent(self, event)

    def clicked(self, pos):
        """Klick an ``pos`` (für Teile wie den Pfeil ▾)."""

    def frame_colors(self):
        """(Fläche, Rand) je nach Zustand."""
        if self.selected:
            return theme.color("accS"), theme.color("acc")
        if self._hover:
            return theme.color("hover"), QColor(0, 0, 0, 0)
        return QColor(0, 0, 0, 0), QColor(0, 0, 0, 0)

    def paint_frame(self, painter, rect=None, radius=theme.RADIUS):
        fill, border = self.frame_colors()
        rect = QRectF(rect if rect is not None else self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pen = QPen(border)
        pen.setWidthF(1.0)
        if self.marked:
            pen = QPen(theme.color("muted"))
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

    def text_color(self):
        if self.faded or self.marked:
            return theme.color("faint")
        return theme.color("accT") if self.selected else theme.color("text")


class ItemTile(Selectable):
    """Eintrag einer Gruppe in der Vorschau (Größe wie im Ribbon)."""

    def __init__(self, owner, base, item, place, parent=None):
        Selectable.__init__(self, owner, ("item", place), parent)
        self.base = base
        self.item = item
        self.element = cz.item_element(base, item)
        self.label = cz.item_label(base, item)
        self.kind = "row" if isinstance(self.element, Row) else (item.size or "large")
        self.menu = has_menu(self.element)
        self.missing = self.element is None
        self.drop_into = False   # Ziehen: Befehl landet im Dropdown dieses Buttons
        self.setFixedSize(self._size())

    def _size(self):
        if self.kind == "row":
            n = len(self.element.commands)
            return QSize(n * ROW_ICON_WIDTH + 4, theme.ROW_HEIGHT)
        if self.kind == "large":
            label = theme.wrap_label(self.label)
            w = text_width(self, label + ((" " + MENU_ARROW) if self.menu else ""))
            return QSize(max(theme.LARGE_MIN_WIDTH, w + theme.LARGE_PADDING), theme.CONTENT_HEIGHT)
        if self.kind == "medium":
            w = text_width(self, self.label) + theme.SMALL_ICON + theme.MEDIUM_PADDING
            return QSize(w + (14 if self.menu else 0), theme.ROW_HEIGHT)
        return QSize(theme.SMALL_WIDTH + (10 if self.menu else 0), theme.ROW_HEIGHT)

    def arrow_rect(self):
        if not self.menu:
            return QRect()
        if self.kind == "large":
            return QRect(0, self.height() - 22, self.width(), 22)
        return QRect(self.width() - 14, 0, 14, self.height())

    def clicked(self, pos):
        if self.menu and self.arrow_rect().contains(pos):
            self.owner.show_contents(self)

    def frame_colors(self):
        if self.drop_into:
            return theme.color("accS"), theme.color("acc")
        return Selectable.frame_colors(self)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_frame(p)
        faded = self.faded or self.marked or self.missing
        p.setPen(self.text_color())
        if self.kind == "row":
            for i, c in enumerate(self.element.commands):
                r = QRect(2 + i * ROW_ICON_WIDTH + 3, 4, theme.SMALL_ICON, theme.SMALL_ICON)
                paint_icon(p, icons.command_icon(c), r, faded)
            p.end()
            return
        icon = element_icon(self.element) if self.element is not None else QIcon()
        if self.kind == "large":
            s = theme.LARGE_ICON
            paint_icon(p, icon, QRect((self.width() - s) // 2, 6, s, s), faded)
            label = theme.wrap_label(self.label) + ((" " + MENU_ARROW) if self.menu else "")
            p.drawText(QRect(2, 6 + s + 2, self.width() - 4, self.height() - s - 10),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, label)
        else:
            s = theme.SMALL_ICON
            y = (self.height() - s) // 2
            paint_icon(p, icon, QRect(4, y, s, s), faded)
            if self.kind == "medium":
                p.drawText(QRect(4 + s + 6, 0, self.width() - s - 10, self.height()),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label)
            if self.menu:
                p.drawText(self.arrow_rect(), Qt.AlignmentFlag.AlignCenter, MENU_ARROW)
        p.end()


def place_tiles(tiles):
    """Kacheln -> Spalten wie im Ribbon: große je eine Spalte, sonst je ``ROWS`` gestapelt."""
    cols, stack = [], []
    for t in tiles:
        if t.kind == "large":
            if stack:
                cols.append(stack)
                stack = []
            cols.append([t])
        else:
            stack.append(t)
            if len(stack) == theme.ROWS:
                cols.append(stack)
                stack = []
    if stack:
        cols.append(stack)
    return cols


class GroupHeader(Selectable):
    """Kopf einer Gruppenkarte: Griff, Beschriftung, Punkt „angepasst“, Auge, Menü ⋯."""

    def __init__(self, owner, place, label, modified, visible, parent=None):
        Selectable.__init__(self, owner, ("group", place), parent)
        self.label = label
        self.modified = modified
        self.faded = not visible
        self.setFixedHeight(HEADER_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(2)
        self.grip = QLabel(self)
        self.grip.setPixmap(icons.ui_icon("griff").pixmap(14, 14))
        self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
        self.grip.setToolTip(tr("Drag to move the group"))
        lay.addWidget(self.grip)
        lay.addStretch(1)
        self.eye = QToolButton(self)
        self.eye.setObjectName("ribbon_editor_eye")
        self.eye.setAutoRaise(True)
        self.eye.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.eye.setIcon(icons.ui_icon("auge" if visible else "auge_aus"))
        self.eye.setIconSize(QSize(14, 14))
        self.eye.setToolTip(tr("Hide group") if visible else tr("Show group"))
        self.eye.clicked.connect(lambda: owner.toggle_visible(self.sel))
        lay.addWidget(self.eye)
        self.more = QToolButton(self)
        self.more.setObjectName("ribbon_editor_more")
        self.more.setAutoRaise(True)
        self.more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more.setIcon(icons.ui_icon("mehr"))
        self.more.setIconSize(QSize(14, 14))
        self.more.setToolTip(tr("More commands for the group"))
        self.more.clicked.connect(lambda: owner.group_menu(self.sel, self.more))
        lay.addWidget(self.more)

    def minimum_text_width(self):
        return text_width(self, self.label) + 14 + 18 + 18 + 6 + 2 * DOT + 16

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_frame(p, radius=5)
        p.setPen(self.text_color() if (self.selected or self.faded) else theme.color("muted"))
        left = 20
        right = self.width() - 40
        fm = QFontMetrics(self.font())
        text = fm.elidedText(self.label, Qt.TextElideMode.ElideRight, max(10, right - left - 2 * DOT))
        tw = fm.horizontalAdvance(text)
        x = left + max(0, (right - left - tw - (2 * DOT if self.modified else 0)) // 2)
        p.drawText(QRect(x, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if self.modified:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("acc"))
            p.drawEllipse(QRectF(x + tw + DOT, self.height() / 2.0 - DOT / 2.0, DOT, DOT))
        p.end()


class GroupCard(QFrame):
    """Gruppe in der Vorschau: Kopf und Einträge in Spalten."""

    HEIGHT = 4 + HEADER_HEIGHT + 4 + theme.CONTENT_HEIGHT + CARD_PADDING

    def __init__(self, owner, base, arr, tab_id, gi, parent=None):
        QFrame.__init__(self, parent)
        self.owner = owner
        tab = arr.tab(tab_id)
        group = tab.groups[gi]
        self.group = group
        self.visible_ = group.visible
        from ..core.editor import Place
        self.place = Place(tab_id, gi)
        self.setObjectName("ribbon_editor_group")
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(CARD_PADDING, 4, CARD_PADDING, CARD_PADDING)
        lay.setSpacing(4)
        self.header = GroupHeader(owner, self.place, group.label, cz.is_modified(base, group),
                                  group.visible, self)
        lay.addWidget(self.header)
        self.body = QWidget(self)
        self.body.setFixedHeight(theme.CONTENT_HEIGHT)
        row = QHBoxLayout(self.body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.GROUP_SPACING)
        self.tiles = []
        for ii, item in enumerate(cz.group_items(base, group)):
            tile = ItemTile(owner, base, item, Place(tab_id, gi, ii), self.body)
            tile.faded = not group.visible
            self.tiles.append(tile)
        self.columns = place_tiles(self.tiles)
        for ci, col in enumerate(self.columns):
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(theme.ROW_SPACING)
            for ri, tile in enumerate(col):
                tile.col, tile.row = ci, ri
                box.addWidget(tile, 0, Qt.AlignmentFlag.AlignLeft)
            box.addStretch(1)
            row.addLayout(box)
        self.empty = None
        if not self.tiles:
            self.empty = QLabel(tr("Drag commands here"), self.body)
            self.empty.setObjectName("ribbon_editor_empty")
            self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty.setWordWrap(True)
            self.empty.setMinimumWidth(110)
            row.addWidget(self.empty)
        row.addStretch(1)
        lay.addWidget(self.body)
        self.drop_index = None   # Einfügemarke
        width = max(self.header.minimum_text_width(),
                    self.body.sizeHint().width()) + 2 * CARD_PADDING
        self.setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def selectables(self):
        return [self.header] + self.tiles

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        target = self.owner.is_target(self.place)
        pen = QPen(theme.color("acc") if (target or self.drop_index is not None) else theme.color("bord"))
        pen.setWidthF(1.5 if (target or self.drop_index is not None) else 1.0)
        if not self.visible_:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(theme.color("surf") if self.visible_ else theme.color("win"))
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
        if self.drop_index is not None:
            x, top, bottom = self.drop_line()
            pen = QPen(theme.color("acc"))
            pen.setWidthF(2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(x, top, x, bottom)
        p.end()

    def drop_line(self):
        """(x, oben, unten) der Einfügemarke für ``drop_index``."""
        body = self.body.geometry()
        if not self.tiles:
            return body.center().x(), body.top() + 4, body.bottom() - 4
        idx = self.drop_index
        if idx >= len(self.tiles):
            g = self.tiles[-1].geometry().translated(body.topLeft())
            return g.right() + 2, g.top(), g.bottom()
        g = self.tiles[idx].geometry().translated(body.topLeft())
        return g.left() - 2, g.top(), g.bottom()

    def tile_onto(self, pos):
        """Kachel mit Dropdown, auf deren Mitte ``pos`` (Kartenkoordinaten) liegt; die Ränder
        (je ein Fünftel) bleiben Einfügemarken daneben."""
        body = self.body.geometry()
        for t in self.tiles:
            if not t.menu:
                continue
            g = t.geometry().translated(body.topLeft())
            margin = g.width() // 5
            if g.top() <= pos.y() <= g.bottom() and g.left() + margin <= pos.x() <= g.right() - margin:
                return t
        return None

    def index_at(self, pos):
        """Einfügeindex für einen Punkt in der Karte (nächste Kachel, links/rechts davon)."""
        if not self.tiles:
            return 0
        body = self.body.geometry()
        best, best_d = len(self.tiles), None
        for i, t in enumerate(self.tiles):
            g = t.geometry().translated(body.topLeft())
            if g.top() - 2 <= pos.y() <= g.bottom() + 2 or len(self.columns[t.col]) == 1:
                d = abs(pos.x() - g.center().x())
                if best_d is None or d < best_d:
                    best_d = d
                    best = i if pos.x() < g.center().x() else i + 1
        return best

    # Ablegen
    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_group(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_group(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_leave()

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drop_on_group(self, event)


class NewGroupCard(Selectable):
    """„＋ Gruppe“: Klick legt eine Gruppe an, Ablegen eine Gruppe mit dem Eintrag."""

    def __init__(self, owner, tab_id, parent=None):
        Selectable.__init__(self, owner, ("newgroup", tab_id), parent)
        self.setObjectName("ribbon_editor_new_group")
        self.setAcceptDrops(True)
        self.active = False
        self.setFixedSize(112, HEADER_HEIGHT + theme.CONTENT_HEIGHT + CARD_PADDING + 8)
        self.setToolTip(tr("Create a new group (drop commands here)"))
        self.setAccessibleName(tr("New Group"))

    def clicked(self, _pos):
        self.owner.new_group()

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        pen = QPen(theme.color("acc") if (self.active or self.selected) else theme.color("bord"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.5 if self.active else 1.0)
        p.setPen(pen)
        p.setBrush(theme.color("accS") if self.active else QColor(0, 0, 0, 0))
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
        p.setPen(theme.color("acc") if (self.active or self.selected) else theme.color("muted"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("＋ Group"))
        p.end()

    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_new_group(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_new_group(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_leave()

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drop_on_new_group(self, event)


class Preview(QWidget):
    """Gruppen des gewählten Tabs nebeneinander (im Rollbereich)."""

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setObjectName("ribbon_editor_preview")
        self.setAcceptDrops(True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 8, 8, 8)
        self.lay.setSpacing(8)
        self.cards = []
        self.new_card = None
        self.drop_gap = None     # Einfügemarke zwischen Gruppen (Gruppen ziehen)

    def clear(self, keep=None):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                discard(w, keep)
        self.cards = []
        self.new_card = None

    def gap_x(self, index):
        if not self.cards:
            return 8
        if index >= len(self.cards):
            return self.cards[-1].geometry().right() + 4
        return self.cards[index].geometry().left() - 4

    def gap_at(self, pos):
        for i, card in enumerate(self.cards):
            if pos.x() < card.geometry().center().x():
                return i
        return len(self.cards)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        if self.drop_gap is None:
            return
        p = QPainter(self)
        pen = QPen(theme.color("acc"))
        pen.setWidthF(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        x = self.gap_x(self.drop_gap)
        p.drawLine(x, 10, x, self.height() - 10)
        p.end()

    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.window().drag_over_preview(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.window().drag_over_preview(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.window().drag_leave()

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.window().drop_on_preview(self, event)


class TabChip(Selectable):
    """Tab in der Tableiste des Editors (Auge blendet aus, Doppelklick benennt eigene Tabs um)."""

    def __init__(self, owner, tab, title, context, current, parent=None):
        Selectable.__init__(self, owner, ("tab", tab.id), parent)
        self.setObjectName("ribbon_editor_tab")
        self.tab = tab
        self.title = title
        self.context = context
        self.current = current
        self.drop_active = False   # Gruppe hier ablegen
        self.faded = not tab.visible
        self.setAcceptDrops(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 2, 0)
        lay.addSpacing(text_width(self, title) + 4)
        self.eye = QToolButton(self)
        self.eye.setObjectName("ribbon_editor_eye")
        self.eye.setAutoRaise(True)
        self.eye.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.eye.setIcon(icons.ui_icon("auge" if tab.visible else "auge_aus"))
        self.eye.setIconSize(QSize(14, 14))
        self.eye.setToolTip(tr("Hide tab") if tab.visible else tr("Show tab"))
        self.eye.clicked.connect(lambda: owner.toggle_visible(self.sel))
        lay.addWidget(self.eye)
        self.setFixedHeight(32)
        self.setFixedWidth(text_width(self, title) + 10 + 4 + 26 + 4)
        if context:
            self.setToolTip(tr("Contextual tab: %s") % context)

    def set_current(self, on):
        if on != self.current:
            self.current = on
            self.update()

    def frame_colors(self):
        if self.drop_active:
            return theme.color("accS"), theme.color("acc")
        return Selectable.frame_colors(self)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_frame(p, QRect(0, 3, self.width(), self.height() - 6), radius=6)
        if self.context:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("ctx"))
            p.drawRoundedRect(QRectF(6, 1, self.width() - 12, 3), 1.5, 1.5)
        p.setPen(self.text_color())
        font = p.font()
        font.setStrikeOut(self.faded)
        font.setBold(self.current)
        p.setFont(font)
        p.drawText(QRect(10, 0, self.width() - 36, self.height()), Qt.AlignmentFlag.AlignLeft
                   | Qt.AlignmentFlag.AlignVCenter, self.title)
        if self.current:
            pen = QPen(theme.color("ctx") if self.context else theme.color("acc"))
            pen.setWidthF(3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(12, self.height() - 2, self.width() - 30, self.height() - 2)
        p.end()

    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_tab(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_tab(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_leave_tab(self)

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drop_on_tab(self, event)


class TabStrip(QWidget):
    """Tableiste: Chips der Tabs, „＋ Tab“; Einfügemarke beim Ziehen von Tabs."""

    def __init__(self, owner, parent=None):
        QWidget.__init__(self, parent)
        self.owner = owner
        self.setObjectName("ribbon_editor_tabs")
        self.setAcceptDrops(True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(4, 0, 4, 0)
        self.lay.setSpacing(2)
        self.chips = []
        self.add_button = None
        self.drop_gap = None

    def fill(self, chips, add_button, keep=None):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None and w is not add_button:
                discard(w, keep)
        self.chips = chips
        for c in chips:
            self.lay.addWidget(c)
        self.add_button = add_button
        self.lay.addSpacing(6)
        self.lay.addWidget(add_button)
        self.lay.addStretch(1)

    def gap_at(self, pos):
        for i, chip in enumerate(self.chips):
            if pos.x() < chip.geometry().center().x():
                return i
        return len(self.chips)

    def gap_x(self, index):
        if index >= len(self.chips):
            return self.chips[-1].geometry().right() + 1 if self.chips else 4
        return self.chips[index].geometry().left() - 1

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        if self.drop_gap is None:
            return
        p = QPainter(self)
        pen = QPen(theme.color("acc"))
        pen.setWidthF(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        x = self.gap_x(self.drop_gap)
        p.drawLine(x, 4, x, self.height() - 4)
        p.end()

    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_strip(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_strip(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_leave()

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drop_on_strip(self, event)


class QuickTile(Selectable):
    """Befehl der Schnellzugriffsleiste im Editor."""

    def __init__(self, owner, command, index, parent=None):
        Selectable.__init__(self, owner, ("quick", index), parent)
        self.command = command
        self.setFixedSize(QUICK_TILE, QUICK_TILE)
        self.setToolTip(command.label)
        self.setAccessibleName(tr("%s, Quick Access") % command.label)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_frame(p, radius=5)
        s = theme.SMALL_ICON
        paint_icon(p, icons.command_icon(self.command),
                   QRect((self.width() - s) // 2, (self.height() - s) // 2, s, s), self.marked)
        p.end()


class QuickStrip(QWidget):
    """Schnellzugriffsleiste über der Vorschau: Befehle hineinziehen, sortieren, herausziehen."""

    def __init__(self, owner, parent=None):
        QWidget.__init__(self, parent)
        self.owner = owner
        self.setObjectName("ribbon_editor_quick")
        self.setAcceptDrops(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(2)
        self.title = QLabel(tr("Quick Access"), self)
        self.title.setObjectName("ribbon_editor_caption")
        lay.addWidget(self.title)
        lay.addSpacing(6)
        self.tiles_box = QHBoxLayout()
        self.tiles_box.setSpacing(2)
        lay.addLayout(self.tiles_box)
        self.hint = QLabel(tr("Drag commands here"), self)
        self.hint.setObjectName("ribbon_editor_empty")
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self.tiles = []
        self.drop_gap = None
        self.setFixedHeight(QUICK_TILE + 8)

    def fill(self, commands, keep=None):
        for t in self.tiles:
            discard(t, keep)
        self.tiles = []
        for i, cmd in enumerate(commands):
            tile = QuickTile(self.owner, cmd, i, self)
            self.tiles_box.addWidget(tile)
            self.tiles.append(tile)
        self.hint.setVisible(not commands)

    def gap_at(self, pos):
        for i, t in enumerate(self.tiles):
            if pos.x() < t.geometry().center().x():
                return i
        return len(self.tiles)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.drop_gap is not None
        pen = QPen(theme.color("acc") if active else theme.color("div"))
        p.setPen(pen)
        p.setBrush(theme.color("surf"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        if active:
            if self.tiles:
                g = self.tiles[min(self.drop_gap, len(self.tiles) - 1)].geometry()
                x = g.left() - 1 if self.drop_gap < len(self.tiles) else g.right() + 1
            else:
                x = self.hint.geometry().left()
            pen = QPen(theme.color("acc"))
            pen.setWidthF(2.5)
            p.setPen(pen)
            p.drawLine(x, 4, x, self.height() - 4)
        p.end()

    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_quick(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_quick(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_leave()

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drop_on_quick(self, event)


# Palette
class PaletteDelegate(QStyledItemDelegate):
    """Kachel der Palette mit Häkchen, wenn der Befehl schon im gewählten Tab steht."""

    def paint(self, painter, option, index):
        QStyledItemDelegate.paint(self, painter, option, index)
        if not index.data(ROLE_CHECK):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect.right() - 20, option.rect.top() + 4, 14, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("acc"))
        painter.drawEllipse(r)
        pen = QPen(theme.color("surf"))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(r.left() + 3.5, r.center().y())
        path.lineTo(r.left() + 6, r.bottom() - 4)
        path.lineTo(r.right() - 3.2, r.top() + 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()


class PaletteList(QListWidget):
    """Kacheln der Palette; Eingabe fügt ein, Ziehen startet über den Editor."""

    activatedKey = pyqtSignal()

    def __init__(self, owner, parent=None):
        QListWidget.__init__(self, parent)
        self.owner = owner
        self.setObjectName("ribbon_editor_palette")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(PALETTE_ICON, PALETTE_ICON))
        self.setGridSize(PALETTE_GRID)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        # Rollbereich: Qt verwirft Zieh-Ereignisse an der Liste selbst, nur der Viewport reicht sie weiter
        self.viewport().setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setItemDelegate(PaletteDelegate(self))
        self.drop_active = False   # Loslassen entfernt

    def keyPressEvent(self, event):  # noqa: N802 (Qt)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activatedKey.emit()
            event.accept()
            return
        if self.owner.palette_key(event):
            return
        QListWidget.keyPressEvent(self, event)

    def startDrag(self, actions):  # noqa: N802 (Qt)
        item = self.currentItem()
        if item is not None:
            self.owner.start_palette_drag(tuple(item.data(ROLE)))

    def dragEnterEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_palette(self, event)

    def dragMoveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_over_palette(self, event)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drag_leave()

    def dropEvent(self, event):  # noqa: N802 (Qt)
        self.owner.drop_on_palette(self, event)

    def set_drop_active(self, on):
        if on != self.drop_active:
            self.drop_active = on
            self.viewport().update()

    def paintEvent(self, event):  # noqa: N802 (Qt)
        QListWidget.paintEvent(self, event)
        if not self.drop_active:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(theme.color("err"))
        pen.setWidthF(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        fill = QColor(theme.color("err"))
        fill.setAlpha(24)
        p.setBrush(fill)
        vp = self.viewport().rect()
        p.drawRoundedRect(QRectF(vp).adjusted(2, 2, -2, -2), 8, 8)
        # Hinweis als Schild über den Kacheln (sonst unleserlich)
        text = tr("Drop here to remove")
        fm = QFontMetrics(self.font())
        w, h = fm.horizontalAdvance(text) + 28, fm.height() + 12
        pill = QRectF(vp.center().x() - w / 2.0, vp.bottom() - h - 12, w, h)
        p.setPen(QPen(theme.color("err")))
        p.setBrush(theme.color("surf"))
        p.drawRoundedRect(pill, h / 2.0, h / 2.0)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


class Palette(QWidget):
    """Befehle oder Gruppen der Definition mit Suche, Filter und Umschalter."""

    MODE_COMMANDS, MODE_GROUPS = "commands", "groups"
    FILTER_ALL, FILTER_UNUSED = "all", "unused"
    # Laufzeitbefehle. „Alle“ und „Nicht im Ribbon“ zeigen vom Werkzeugkasten
    # nur die eigenen Skripte und Modelle, die übrigen Werkzeuge stehen unter FILTER_TOOLBOX.
    FILTER_PLUGINS, FILTER_OWN, FILTER_TOOLBOX = "plugins", "own", "toolbox"

    def __init__(self, owner, base, parent=None):
        QWidget.__init__(self, parent)
        self.owner = owner
        self.base = base
        self.mode = self.MODE_COMMANDS
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        caption = QLabel(tr("Commands"), self)
        caption.setObjectName("ribbon_editor_caption")
        self.caption = caption
        top.addWidget(caption)
        self.search = QLineEdit(self)
        self.search.setObjectName("ribbon_editor_search")
        self.search.setPlaceholderText(tr("Search (name or description)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        top.addWidget(self.search, 1)
        self.filter = QComboBox(self)
        self.filter.setObjectName("ribbon_editor_filter")
        self.filter.addItem(tr("All"), self.FILTER_ALL)
        self.filter.addItem(tr("Not in the ribbon"), self.FILTER_UNUSED)
        ids = list(base.commands)
        if any(ext.is_plugin(c) for c in ids):
            self.filter.addItem(tr("Extensions (plugins)"), self.FILTER_PLUGINS)
        if any(ext.own_tool(c) for c in ids):
            self.filter.addItem(tr("Own scripts and models"), self.FILTER_OWN)
        if any(ext.is_toolbox(c) for c in ids):
            self.filter.addItem(tr("Toolbox (all tools)"), self.FILTER_TOOLBOX)
        for t in base.tabs:
            self.filter.addItem(tr("Tab “%s”") % (("%s: %s" % (t.context, t.label)) if t.contextual else t.label),
                                "tab:" + t.id)
        self.filter.currentIndexChanged.connect(lambda _i: self.apply_filter())
        top.addWidget(self.filter)
        self.mode_commands = QToolButton(self)
        self.mode_commands.setText(tr("Commands"))
        self.mode_groups = QToolButton(self)
        self.mode_groups.setText(tr("Groups"))
        for b, m in ((self.mode_commands, self.MODE_COMMANDS), (self.mode_groups, self.MODE_GROUPS)):
            b.setCheckable(True)
            b.setObjectName("ribbon_editor_mode")
            b.clicked.connect(lambda _c=False, m=m: self.set_mode(m))
            top.addWidget(b)
        lay.addLayout(top)
        self.list = PaletteList(owner, self)
        self.list.currentItemChanged.connect(self._current_changed)
        self.list.activatedKey.connect(owner.insert_from_palette)
        self.list.itemDoubleClicked.connect(lambda _i: owner.insert_from_palette())
        lay.addWidget(self.list, 1)
        self._tab_commands = {}
        self.unused = set()
        self.checked = set()
        # Kacheln der übrigen Werkzeuge (hunderte) erst mit dem Filter „Werkzeugkasten“ anlegen
        self._all_tools = False
        self.set_mode(self.MODE_COMMANDS)

    def _tab_command_ids(self, tab_id):
        ids = self._tab_commands.get(tab_id)
        if ids is None:
            from ..core.model import iter_commands
            ids = {c.id for c in iter_commands(self.base.tab(tab_id))}
            self._tab_commands[tab_id] = ids
        return ids

    def set_mode(self, mode):
        self.mode = mode
        self.mode_commands.setChecked(mode == self.MODE_COMMANDS)
        self.mode_groups.setChecked(mode == self.MODE_GROUPS)
        self.caption.setText(tr("Commands") if mode == self.MODE_COMMANDS else tr("Groups"))
        self.list.clear()
        if mode == self.MODE_COMMANDS:
            commands = [c for c in self.base.commands.values()
                        if self._all_tools or not ext.is_toolbox(c.id) or ext.own_tool(c.id)]
            for cmd in sorted(commands, key=lambda c: (fold(c.label), c.id)):
                item = QListWidgetItem(icons.command_icon(cmd), cmd.label, self.list)
                item.setData(ROLE, ("command", cmd.id))
                item.setToolTip("<b>%s</b>%s" % (cmd.label, ("<br>" + cmd.description) if cmd.description else ""))
                item.setData(Qt.ItemDataRole.AccessibleTextRole, cmd.label)
                item.setSizeHint(PALETTE_GRID)
                item.setData(Qt.ItemDataRole.UserRole + 3, fold(" ".join([cmd.label, cmd.description or "", cmd.id])))
        else:
            for tab in self.base.tabs:
                for group in tab.groups:
                    first = group.elements[0] if group.elements else None
                    icon = element_icon(first) if first is not None else QIcon()
                    title = ("%s: %s" % (tab.context, tab.label)) if tab.contextual else tab.label
                    item = QListWidgetItem(icon, "%s\n(%s)" % (group.label, tab.label), self.list)
                    ref = cz.group_ref(tab.id, group.id)
                    item.setData(ROLE, ("group", ref))
                    item.setToolTip(tr("<b>%s</b> (tab “%s”)<br>%s") % (group.label, title, ", ".join(
                        cz.item_label(self.base, i) for i in cz.standard_items(self.base, ref))))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("Group %s from %s") % (group.label, title))
                    item.setSizeHint(PALETTE_GRID)
                    item.setData(Qt.ItemDataRole.UserRole + 3, fold(" ".join([group.label, title])))
        self.apply_filter()
        self.update_checks(self.checked)
        self.owner.palette_mode_changed()

    def set_unused(self, unused):
        self.unused = unused
        if self.filter.currentData() == self.FILTER_UNUSED:
            self.apply_filter()

    def apply_filter(self):
        words = fold(self.search.text()).split()
        flt = self.filter.currentData()
        if flt == self.FILTER_TOOLBOX and not self._all_tools and self.mode == self.MODE_COMMANDS:
            self._all_tools = True
            current = self.current()
            self.set_mode(self.mode)   # legt alle Kacheln an und filtert erneut
            if current is not None:
                try:
                    self.select(*current)
                except KeyError:
                    pass
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            kind, value = tuple(item.data(ROLE))
            hay = item.data(Qt.ItemDataRole.UserRole + 3) or ""
            show = all(w in hay for w in words)
            if show and kind == "command" and flt in (self.FILTER_ALL, self.FILTER_UNUSED):
                show = not ext.is_toolbox(value) or ext.own_tool(value)
            if show and flt == self.FILTER_UNUSED:
                show = value in self.unused
            elif show and flt == self.FILTER_PLUGINS:
                show = kind == "command" and ext.is_plugin(value)
            elif show and flt == self.FILTER_OWN:
                show = kind == "command" and ext.own_tool(value)
            elif show and flt == self.FILTER_TOOLBOX:
                show = kind == "command" and ext.is_toolbox(value)
            elif show and flt and flt.startswith("tab:"):
                tab_id = flt[4:]
                show = (value in self._tab_command_ids(tab_id)) if kind == "command" \
                    else value.split("/", 1)[0] == tab_id
            item.setHidden(not show)

    def update_checks(self, checked):
        self.checked = checked
        for i in range(self.list.count()):
            item = self.list.item(i)
            kind, value = tuple(item.data(ROLE))
            item.setData(ROLE_CHECK, value in checked)

    def visible_values(self):
        return [tuple(self.list.item(i).data(ROLE)) for i in range(self.list.count())
                if not self.list.item(i).isHidden()]

    def select(self, kind, value):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if tuple(item.data(ROLE)) == (kind, value):
                self.list.setCurrentItem(item)
                return item
        if kind == "command" and ext.is_toolbox(value) and not self._all_tools:
            self._all_tools = True
            self.set_mode(self.mode)
            return self.select(kind, value)
        raise KeyError(value)

    def current(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return None
        return tuple(item.data(ROLE))

    def _current_changed(self, current, _previous):
        if current is not None:
            kind, value = tuple(current.data(ROLE))
            self.owner.select(("palette", kind, value))


def drag_pixmap(widget):
    """Bild der gezogenen Kachel für den Mauszeiger (wie die Kachel, leicht durchscheinend)."""
    pix = QPixmap(widget.size() * widget.devicePixelRatioF())
    pix.setDevicePixelRatio(widget.devicePixelRatioF())
    pix.fill(Qt.GlobalColor.transparent)
    widget.render(pix, QPoint(), QRegion(widget.rect()), QWidget.RenderFlag.DrawChildren)
    out = QPixmap(pix.size())
    out.setDevicePixelRatio(pix.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setOpacity(0.85)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


def chip_pixmap(widget, icon, text):
    """Bild einer gezogenen Palettenkachel: Icon und Beschriftung als kleines Schild."""
    fm = widget.fontMetrics()
    text = text.split("\n")[0]
    w, h = fm.horizontalAdvance(text) + theme.SMALL_ICON + 20, theme.ROW_HEIGHT + 4
    ratio = widget.devicePixelRatioF()
    pix = QPixmap(QSize(w, h) * ratio)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setOpacity(0.9)
    p.setPen(QPen(theme.color("acc")))
    p.setBrush(theme.color("surf"))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 5, 5)
    s = theme.SMALL_ICON
    paint_icon(p, icon, QRect(6, (h - s) // 2, s, s))
    p.setPen(theme.color("text"))
    p.setFont(widget.font())
    p.drawText(QRect(s + 12, 0, w - s - 14, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    p.end()
    return pix


def mime(payload):
    """MIME-Daten eines Zieh-Vorgangs (Inhalt nur zur Erkennung, die Daten hält der Editor)."""
    data = QMimeData()
    data.setData(MIME_TYPE, payload.encode("utf-8"))
    return data


def scroll_area(widget, horizontal=True):
    area = QScrollArea()
    area.setObjectName("ribbon_editor_scroll")
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidgetResizable(True)
    area.setWidget(widget)
    if horizontal:
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    else:
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area
