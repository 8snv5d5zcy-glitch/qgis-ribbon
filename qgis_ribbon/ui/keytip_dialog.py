"""Dialog „Kürzel anpassen“: eigene KeyTips je Tab und Element.

Zeigt alle Tabs und darunter die Elemente jedes Tabs mit dem automatischen,
dem eigenen und dem wirksamen Kürzel. Eigene Kürzel (1–2 Buchstaben) gehen
der automatischen Vergabe vor; die übrigen Kürzel der Ebene passen sich an.
Ein eigenes Kürzel, das ungültig ist oder mit einem anderen kollidiert
(gleich oder Anfang eines anderen), wird rot markiert; gespeichert wird erst
ohne Konflikte. Leer = automatisch. Gespeichert pro Nutzer
(``UserSettings.set_keytips``).

Schnellzugriff (1–9) und Suche (Q) sind fest.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush
from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QPushButton,
                                 QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..core import keytips
from . import guide, theme
from .keytips import element_codes, tab_codes
from ..core.i18n import tr

TITLE = tr("Customize KeyTips")
COL_ELEMENT, COL_PLACE, COL_AUTO, COL_OWN, COL_EFFECTIVE = range(5)
ROLE_KEY = Qt.UserRole + 1
ROLE_LEVEL = Qt.UserRole + 2
TABS_LEVEL = "__tabs__"
HINT = tr("Press and release Alt to show the KeyTips in the ribbon. Own KeyTip: double-click in the “Own” "
          "column, 1–2 letters, empty = automatic. The other KeyTips of a level adapt. Quick Access (1–9) "
          "and search (Q) are fixed.")


class _OwnColumnDelegate(QStyledItemDelegate):
    """Bearbeiten nur in der Spalte „Eigenes“ und nur in Zeilen mit Schlüssel."""

    def createEditor(self, parent, option, index):
        if index.column() != COL_OWN or not index.data(ROLE_KEY):
            return None
        editor = QLineEdit(parent)
        editor.setMaxLength(keytips.MAX_LEN)
        return editor


class KeyTipDialog(QDialog):
    def __init__(self, ribbon_widget, parent=None):
        QDialog.__init__(self, parent or ribbon_widget.window())
        self.setObjectName("ribbon_keytip_dialog")
        theme.style_dialog(self)
        self.setWindowTitle(TITLE)
        self.resize(720, 560)
        self.rw = ribbon_widget
        self.overrides = dict(ribbon_widget.user.keytips())
        self._items = {}            # Schlüssel -> QTreeWidgetItem
        self._levels = {}           # Ebene (Tab-ID oder TABS_LEVEL) -> [Schlüssel]
        self._filling = False

        lay = QVBoxLayout(self)
        hint = QLabel(HINT, self)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText(tr("Filter (item, tab or KeyTip)"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        lay.addWidget(self.filter)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("ribbon_keytip_tree")
        self.tree.setHeaderLabels([tr("Item"), tr("Location"), tr("Automatic"), tr("Own"), tr("Effective")])
        self.tree.setItemDelegate(_OwnColumnDelegate(self.tree))
        self.tree.setEditTriggers(QTreeWidget.DoubleClicked | QTreeWidget.EditKeyPressed
                                  | QTreeWidget.SelectedClicked)
        self.tree.itemChanged.connect(self._changed)
        lay.addWidget(self.tree)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.reset_button = QPushButton(tr("Reset All"), self)
        self.buttons.addButton(self.reset_button, QDialogButtonBox.ResetRole)
        self.reset_button.clicked.connect(self.reset_all)
        guide.help_button(self.buttons, "keyboard", self)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._fill()

    # Aufbau
    def _fill(self):
        self._filling = True
        self.tree.clear()
        self._items.clear()
        self._levels.clear()
        rw = self.rw
        tabs_root = QTreeWidgetItem(self.tree, [tr("Tabs")])
        tabs_root.setFirstColumnSpanned(True)
        auto, _eff = tab_codes(rw, {})
        for tab, code in zip(rw.ribbon.tabs, auto):
            place = tab.context or ""
            self._add(tabs_root, TABS_LEVEL, keytips.tab_key(tab.id), tab.label, place, code)
        for tab in rw.ribbon.tabs:
            title = "%s: %s" % (tab.context, tab.label) if tab.contextual else tab.label
            root = QTreeWidgetItem(self.tree, [tr("Tab “%s”") % title])
            root.setFirstColumnSpanned(True)
            targets, keys, auto, _eff = element_codes(rw, tab.id, {})
            groups = self._group_labels(tab)
            for t, k, code in zip(targets, keys, auto):
                self._add(root, tab.id, keytips.element_key(tab.id, k), t.label,
                          groups.get(t.widget, ""), code)
        self.tree.expandAll()
        for col in range(5):
            self.tree.resizeColumnToContents(col)
        self._filling = False
        for level in self._levels:
            self._recompute(level)

    def _group_labels(self, tab):
        """Widget -> Gruppenbeschriftung (für die Spalte „Ort“)."""
        out = {}
        page = self.rw.page(tab.id)
        for gw in getattr(page, "groups", ()):
            for t in self.rw.ctx.targets.get(tab.id, ()):
                if gw.isAncestorOf(t.widget):
                    out[t.widget] = gw.group.label
        return out

    def _add(self, parent, level, key, label, place, auto):
        item = QTreeWidgetItem(parent, [label, place, auto, self.overrides.get(key, ""), ""])
        item.setData(COL_OWN, ROLE_KEY, key)
        item.setData(COL_OWN, ROLE_LEVEL, level)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        # Automatisch gedämpft, damit nur Konflikte (rot) und Wirksam auffallen
        item.setForeground(COL_AUTO, QBrush(theme.muted_text(self.tree.palette())))
        self._items[key] = item
        self._levels.setdefault(level, []).append(key)
        return item

    # Bearbeiten
    def _changed(self, item, column):
        if self._filling or column != COL_OWN:
            return
        key = item.data(COL_OWN, ROLE_KEY)
        if not key:
            return
        code = keytips.normalize(item.text(COL_OWN))
        self._filling = True
        item.setText(COL_OWN, code)
        self._filling = False
        if code:
            self.overrides[key] = code
        else:
            self.overrides.pop(key, None)
        self._recompute(item.data(COL_OWN, ROLE_LEVEL))

    def set_override(self, key, code):
        """Eigenes Kürzel setzen (wie Eingabe in der Tabelle; leer = automatisch)."""
        self._items[key].setText(COL_OWN, code)

    def _recompute(self, level):
        keys = self._levels[level]
        rw = self.rw
        if level == TABS_LEVEL:
            _auto, eff = tab_codes(rw, self.overrides)
        else:
            _t, _k, _auto, eff = element_codes(rw, level, self.overrides)
        self._filling = True
        for key, code in zip(keys, eff):
            item = self._items[key]
            item.setText(COL_EFFECTIVE, code or "")
            own = self.overrides.get(key)
            problem = None
            if own:
                problem = keytips.code_error(own)
                if problem is None and code != own:
                    problem = self._conflict_text(level, key, own)
            item.setData(COL_OWN, Qt.ToolTipRole, problem or "")
            item.setForeground(COL_OWN, QBrush(theme.color("err")) if problem
                               else QBrush(self.tree.palette().text().color()))
            item.setData(COL_EFFECTIVE, Qt.UserRole + 3, problem)
        self._filling = False
        self._update_status()

    def _conflict_text(self, level, key, own):
        reserved = [keytips.SEARCH_KEY] if level == TABS_LEVEL else []
        if any(own == r or own.startswith(r) or r.startswith(own) for r in reserved):
            return tr("“%s” is reserved for search") % own
        for other in self._levels[level]:
            code = self.overrides.get(other)
            if other != key and code and (code == own or code.startswith(own) or own.startswith(code)):
                return tr("Conflicts with “%s” (%s)") % (self._items[other].text(COL_ELEMENT), code)
        return tr("Conflicts with another KeyTip")

    def problems(self):
        return [(self._items[k].text(COL_ELEMENT), self._items[k].data(COL_EFFECTIVE, Qt.UserRole + 3))
                for k in self._items if self._items[k].data(COL_EFFECTIVE, Qt.UserRole + 3)]

    def _update_status(self):
        problems = self.problems()
        save = self.buttons.button(QDialogButtonBox.Save)
        save.setEnabled(not problems)
        if problems:
            self.status.setText(tr("Cannot be saved: ") + "; ".join(
                "%s – %s" % p for p in problems[:3]) + (" …" if len(problems) > 3 else ""))
        else:
            n = len([k for k in self.overrides if k in self._items])
            self.status.setText(tr("%d own KeyTips") % n if n else tr("All KeyTips automatic"))

    def reset_all(self):
        for key in list(self.overrides):
            if key in self._items:
                self.set_override(key, "")
        self.overrides = {}
        for level in self._levels:
            self._recompute(level)

    def apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(root.childCount()):
                child = root.child(j)
                hay = " ".join(child.text(c) for c in range(5)).lower() + " " + root.text(0).lower()
                visible = not text or text in hay
                child.setHidden(not visible)
                any_visible = any_visible or visible
            root.setHidden(not any_visible)

    def save(self):
        if self.problems():
            return
        self.rw.user.set_keytips(self.overrides)
        self.accept()
