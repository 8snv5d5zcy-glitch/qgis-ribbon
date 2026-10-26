"""Dialog „Galerie anpassen“ und Auswahlliste für Befehle.

„Ribbon anpassen“ ist der grafische Editor (``ui/ribbon_editor.py``).

„Galerie anpassen“ (Befehl ``ribbon.galerie_anpassen`` im Menü einer
Galerie, Parameter: ID der Galerie) legt Einträge und Reihenfolge einer
Galerie mit festen Einträgen fest, z. B. Editor- oder Analysewerkzeuge.
Beide Listen zeigen die Kontur-Icons der Befehle; die Reihenfolge
rechts lässt sich auch per Ziehen ändern.
"""

from qgis.core import Qgis
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                                 QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                                 QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import customization as cz
from ..core.model import CommandRef, Menu, Row, Split
from ..core.search import fold, ribbon_entries
from . import guide, icons, theme
from .controls.buttons import MENU_ARROW
from .editor_widgets import element_icon
from ..core.i18n import tr

LOG_TAG = "QGIS Ribbon"
GALLERY_TITLE = tr("Customize Gallery")
ROLE = Qt.UserRole + 1
MODE_COMMANDS, MODE_GROUPS = "commands", "groups"


def tab_title(tab):
    return "%s: %s" % (tab.context, tab.label) if tab.contextual else tab.label


def element_label(element):
    if isinstance(element, CommandRef):
        return element.command.label
    if isinstance(element, Split):
        return "%s %s" % (element.display_label, MENU_ARROW)
    if isinstance(element, Menu):
        return "%s %s" % (element.label, MENU_ARROW)
    if isinstance(element, Row):
        return ", ".join(c.label for c in element.commands)
    return str(element)


def _set_status(label, text, error=False):
    label.setText(text)
    # Eigenes Stylesheet am Label: das Dialog-Stylesheet überschriebe eine Palette
    label.setStyleSheet("color: %s;" % theme.css("err") if error else "")


class Picker(QWidget):
    """Liste zum Auswählen: Befehle (mit Ort) oder Gruppen der Definition, mit Filter."""

    def __init__(self, base, parent=None, allowed=None):
        QWidget.__init__(self, parent)
        self.base = base
        self.allowed = allowed
        self.places = {e.ref[0].id: e.path for e in ribbon_entries(base)}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText(tr("Filter (name or location)"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        lay.addWidget(self.filter)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("ribbon_customize_picker")
        self.tree.setHeaderLabels([tr("Name"), tr("Location")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setIconSize(QSize(theme.SMALL_ICON, theme.SMALL_ICON))
        lay.addWidget(self.tree)
        self.mode = None
        self.set_mode(MODE_COMMANDS)

    def set_mode(self, mode):
        self.mode = mode
        self.tree.clear()
        if mode == MODE_COMMANDS:
            for cmd in sorted(self.base.commands.values(), key=lambda c: (fold(c.label), c.id)):
                if self.allowed is not None and not self.allowed(cmd):
                    continue
                item = QTreeWidgetItem(self.tree, [cmd.label, self.places.get(cmd.id, "")])
                item.setIcon(0, icons.command_icon(cmd))
                item.setData(0, ROLE, ("command", cmd.id))
                if cmd.description:
                    item.setToolTip(0, cmd.description)
        else:
            for tab in self.base.tabs:
                for group in tab.groups:
                    item = QTreeWidgetItem(self.tree, [group.label, tab_title(tab)])
                    if group.elements:
                        item.setIcon(0, element_icon(group.elements[0]))
                    item.setData(0, ROLE, ("group", cz.group_ref(tab.id, group.id)))
                    item.setToolTip(0, ", ".join(element_label(e) for e in group.elements))
        self.tree.resizeColumnToContents(0)
        self.apply_filter(self.filter.text())

    def apply_filter(self, text):
        words = fold(text).split()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            hay = fold(item.text(0) + " " + item.text(1))
            item.setHidden(not all(w in hay for w in words))

    def select(self, kind, value):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if tuple(item.data(0, ROLE) or ()) == (kind, value):  # PyQt liefert Tupel als Liste
                self.tree.setCurrentItem(item)
                return item
        raise KeyError(value)

    def current(self):
        item = self.tree.currentItem()
        return tuple(item.data(0, ROLE)) if item is not None and not item.isHidden() else None


class GalleryDialog(QDialog):
    """Einträge und Reihenfolge einer Galerie mit festen Einträgen."""

    def __init__(self, arrangements, gallery_id, parent=None):
        QDialog.__init__(self, parent)
        self.setObjectName("ribbon_gallery_dialog")
        theme.style_dialog(self)
        self.arrangements = arrangements
        self.base = arrangements.base
        self.gallery_id = gallery_id
        self.command = cz.galleries(self.base)[gallery_id]
        self.standard_ids = [c.id for c in self.command.gallery.items]
        self.setWindowTitle("%s: %s" % (GALLERY_TITLE, self.command.label))
        self.resize(760, 520)

        lay = QVBoxLayout(self)
        hint = QLabel(tr("Choose commands on the left and add them (double-click), set the order on the right "
                         "(buttons or drag). The ribbon shows the first items, the rest when expanded."), self)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        body = QHBoxLayout()
        lay.addLayout(body, 1)
        self.picker = Picker(self.base, self, allowed=cz.gallery_item_allowed)
        self.picker.tree.itemDoubleClicked.connect(lambda *_a: self.add())
        body.addWidget(self.picker, 1)
        middle = QVBoxLayout()
        middle.addStretch(1)
        self.add_button = QPushButton(tr("Add ›"), self)
        self.add_button.clicked.connect(self.add)
        self.remove_button = QPushButton(tr("‹ Remove"), self)
        self.remove_button.clicked.connect(self.remove)
        middle.addWidget(self.add_button)
        middle.addWidget(self.remove_button)
        middle.addStretch(1)
        body.addLayout(middle)
        self.list = QListWidget(self)
        self.list.setObjectName("ribbon_gallery_entries")
        self.list.setIconSize(QSize(theme.SMALL_ICON, theme.SMALL_ICON))
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.model().rowsMoved.connect(lambda *_a: self._update_status())
        body.addWidget(self.list, 1)
        right = QVBoxLayout()
        self.up_button = QPushButton(tr("▲ Move Up"), self)
        self.up_button.clicked.connect(lambda: self.move(-1))
        self.down_button = QPushButton(tr("▼ Move Down"), self)
        self.down_button.clicked.connect(lambda: self.move(1))
        right.addWidget(self.up_button)
        right.addWidget(self.down_button)
        right.addStretch(1)
        body.addLayout(right)
        self.status = QLabel(self)
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.reset_button = QPushButton(tr("Restore Defaults"), self)
        self.buttons.addButton(self.reset_button, QDialogButtonBox.ResetRole)
        self.reset_button.clicked.connect(self.reset)
        guide.help_button(self.buttons, "customize", self)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.set_ids(arrangements.gallery_items(gallery_id))

    @property
    def needs_items(self):
        return self.command.gallery.display == "ribbon"

    def ids(self):
        return [self.list.item(i).data(ROLE) for i in range(self.list.count())]

    def set_ids(self, ids, current=None):
        self.list.clear()
        for cid in ids:
            cmd = self.base.commands[cid]
            item = QListWidgetItem(icons.command_icon(cmd), cmd.label, self.list)
            item.setData(ROLE, cid)
            item.setToolTip(self.picker.places.get(cid, ""))
            item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)   # Ziehen ordnet nur um
            if cid == current:
                self.list.setCurrentItem(item)
        self._update_status()

    def _update_status(self):
        ids = self.ids()
        empty = not ids and self.needs_items
        self.buttons.button(QDialogButtonBox.Save).setEnabled(not empty)
        n = len(ids)
        _set_status(self.status, tr("The gallery needs at least one item.") if empty
                    else tr("%d items%s") % (n, tr(" (default)") if ids == self.standard_ids else ""),
                    error=empty)

    def add(self):
        picked = self.picker.current()
        if picked is None:
            return None
        cid = picked[1]
        ids = self.ids()
        if cid in ids:
            self.list.setCurrentRow(ids.index(cid))
            return None
        row = self.list.currentRow()
        ids.insert(row + 1 if row >= 0 else len(ids), cid)
        self.set_ids(ids, current=cid)
        return cid

    def remove(self):
        row = self.list.currentRow()
        if row < 0:
            return None
        ids = self.ids()
        cid = ids.pop(row)
        self.set_ids(ids, current=ids[min(row, len(ids) - 1)] if ids else None)
        return cid

    def move(self, delta):
        row = self.list.currentRow()
        ids = self.ids()
        if row < 0 or cz.move_in_list(ids, row, delta) is None:
            return None
        self.set_ids(ids, current=ids[row + delta])
        return row + delta

    def reset(self):
        self.set_ids(self.standard_ids)

    def save(self):
        ids = self.ids()
        if not ids and self.needs_items:
            return False
        self.arrangements.set_gallery(self.gallery_id, None if ids == self.standard_ids else ids)
        self.accept()
        return True


def open_gallery_dialog(env, command):
    """Galerie aus den Parametern des Befehls anpassen (``args``: ID der Galerie)."""
    args = command.source.get("args") or []
    gallery_id = args[0] if args else None
    host = env.host
    if host is None or gallery_id not in cz.galleries(host.base):
        env.iface.messageBar().pushMessage(LOG_TAG, tr("This gallery cannot be customized."),
                                           level=Qgis.Warning, duration=4)
        return None
    dlg = GalleryDialog(host, gallery_id, env.iface.mainWindow())
    try:
        dlg.exec_()
    finally:
        dlg.deleteLater()
    return dlg
