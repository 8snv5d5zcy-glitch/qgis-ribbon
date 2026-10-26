"""Dialog „Domänen“: Domänen anlegen, ändern, löschen und Feldern zuordnen.

Wie die Domänenansicht in Pro für die Datenquelle des aktiven Layers. Liegen
die Domänen im Projekt (Datenformat ohne Domänen), sagt das die Kopfzeile.
Alle Änderungen bleiben im Dialog (``core.domains.DomainSession``), bis
„Speichern“ sie gesammelt schreibt; gespeichert wird nur ohne Fehler.
Gespeicherte Domänen behalten Name, Art und Feldtyp (in der Datenquelle
lassen sie sich nicht umbenennen).

Registriert sich als eigener Befehl ``ribbon.domaenen_dialog``.
"""

from qgis.core import Qgis, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush
from qgis.PyQt.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                                 QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                                 QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                                 QVBoxLayout, QWidget)

from ..core import domains as model
from ..qgis_integration import domains as store_mod
from . import guide, theme
from ..core.i18n import tr

TITLE = tr("Domains")
LOG_TAG = "QGIS Ribbon"
PAGES = {"coded": 0, "range": 1, "glob": 2}


class DomainDialog(QDialog):
    def __init__(self, layer, store, parent=None):
        QDialog.__init__(self, parent)
        self.setObjectName("ribbon_domain_dialog")
        theme.style_dialog(self)
        self.setWindowTitle("%s – %s" % (TITLE, layer.name()))
        self.resize(860, 560)
        self.layer = layer
        self.store = store
        self.current = None         # Name der Domäne im Editor
        self._filling = False

        lay = QVBoxLayout(self)
        head = QLabel(store.title, self)
        head.setObjectName("ribbon_domain_source")
        head.setWordWrap(True)
        head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(head)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._domains_page(), tr("Domains"))
        self.tabs.addTab(self._fields_page(), tr("Fields of “%s”") % layer.name())
        lay.addWidget(self.tabs)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        guide.help_button(self.buttons, "tools", self)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.load()

    # -- Aufbau ------------------------------------------------------------------
    def _domains_page(self):
        page = QWidget(self)
        lay = QHBoxLayout(page)
        left = QVBoxLayout()
        self.list = QListWidget(page)
        self.list.setObjectName("ribbon_domain_list")
        self.list.currentItemChanged.connect(self._selected)
        left.addWidget(self.list)
        row = QHBoxLayout()
        self.new_button = QPushButton(tr("New"), page)
        menu = QMenu(self.new_button)
        menu.addAction(tr("Coded values"), lambda: self.new_domain("coded"))
        menu.addAction(tr("Range"), lambda: self.new_domain("range"))
        self.new_button.setMenu(menu)
        self.delete_button = QPushButton(tr("Delete"), page)
        self.delete_button.clicked.connect(self.delete_current)
        row.addWidget(self.new_button)
        row.addWidget(self.delete_button)
        left.addLayout(row)
        lay.addLayout(left, 1)

        self.editor = QWidget(page)
        form = QFormLayout(self.editor)
        self.name_edit = QLineEdit(self.editor)
        self.desc_edit = QLineEdit(self.editor)
        self.kind_combo = QComboBox(self.editor)
        for kind in model.EDITABLE_KINDS:
            self.kind_combo.addItem(model.KIND_LABELS[kind], kind)
        self.type_combo = QComboBox(self.editor)
        for ftype in model.FIELD_TYPES:
            self.type_combo.addItem(model.TYPE_LABELS[ftype], ftype)
        form.addRow(tr("Name"), self.name_edit)
        form.addRow(tr("Description"), self.desc_edit)
        form.addRow(tr("Kind"), self.kind_combo)
        form.addRow(tr("Field type"), self.type_combo)
        self.stack = QStackedWidget(self.editor)
        self.stack.addWidget(self._coded_page())
        self.stack.addWidget(self._range_page())
        self.glob_label = QLabel(self.editor)
        self.glob_label.setWordWrap(True)
        self.stack.addWidget(self.glob_label)
        form.addRow(self.stack)
        for w in (self.name_edit, self.desc_edit):
            w.textEdited.connect(self._edited)
        for w in (self.kind_combo, self.type_combo):
            w.activated.connect(self._edited)
        lay.addWidget(self.editor, 2)
        return page

    def _coded_page(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.values = QTableWidget(0, 2, page)
        self.values.setObjectName("ribbon_domain_values")
        self.values.setHorizontalHeaderLabels([tr("Code"), tr("Description")])
        self.values.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.values.verticalHeader().setVisible(False)
        self.values.itemChanged.connect(self._edited)
        lay.addWidget(self.values)
        row = QHBoxLayout()
        add = QPushButton(tr("Add Row"), page)
        add.clicked.connect(self.add_value_row)
        remove = QPushButton(tr("Remove Row"), page)
        remove.clicked.connect(self.remove_value_row)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    def _range_page(self):
        page = QWidget(self)
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.min_edit = QLineEdit(page)
        self.max_edit = QLineEdit(page)
        self.min_edit.setPlaceholderText(tr("empty = open"))
        self.max_edit.setPlaceholderText(tr("empty = open"))
        for w in (self.min_edit, self.max_edit):
            w.textEdited.connect(self._edited)
        form.addRow(tr("Minimum"), self.min_edit)
        form.addRow(tr("Maximum"), self.max_edit)
        return page

    def _fields_page(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        self.fields = QTableWidget(0, 3, page)
        self.fields.setObjectName("ribbon_domain_fields")
        self.fields.setHorizontalHeaderLabels([tr("Field"), tr("Type"), tr("Domain")])
        self.fields.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.fields.verticalHeader().setVisible(False)
        self.fields.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.fields)
        return page

    # -- Daten -------------------------------------------------------------------
    def load(self):
        """Stand aus der Ablage lesen (beim Öffnen und nach einem Fehler beim Speichern)."""
        self.session = model.DomainSession(self.store.domains(), store_mod.layer_fields(self.layer),
                                           self.store.assignments())
        self._fill_list()
        self._fill_fields()
        self._update_status()

    def _fill_list(self, select=None):
        self._filling = True
        self.list.clear()
        for d in self.session.domains:
            item = QListWidgetItem(d.name, self.list)
            item.setData(Qt.UserRole, d.name)
            item.setToolTip("%s, %s" % (model.KIND_LABELS.get(d.kind, d.kind),
                                        model.TYPE_LABELS.get(d.field_type, d.field_type)))
        self._filling = False
        names = self.session.names()
        target = select if select in names else (names[0] if names else None)
        if target is None:
            self.current = None
            self._fill_editor(None)
        else:
            self.list.setCurrentRow(names.index(target))

    def _selected(self, item, _previous=None):
        if self._filling:
            return
        self.current = item.data(Qt.UserRole) if item is not None else None
        self._fill_editor(self.session.get(self.current) if self.current else None)

    def _fill_editor(self, d):
        self._filling = True
        try:
            self.editor.setEnabled(d is not None)
            self.delete_button.setEnabled(d is not None)
            if d is None:
                for w in (self.name_edit, self.desc_edit, self.min_edit, self.max_edit):
                    w.clear()
                self.values.setRowCount(0)
                return
            saved = not self.session.is_new(d.name)
            self.name_edit.setText(d.name)
            self.name_edit.setReadOnly(saved)
            self.desc_edit.setText(d.description)
            glob = d.kind == "glob"
            self.desc_edit.setReadOnly(glob)
            self.kind_combo.setEnabled(not saved)
            self.type_combo.setEnabled(not saved)
            idx = self.kind_combo.findData(d.kind)
            self.kind_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(d.field_type)))
            self.stack.setCurrentIndex(PAGES.get(d.kind, 0))
            self.values.setRowCount(0)
            for code, label in d.values:
                self._append_row(model.format_value(code), label)
            self.min_edit.setText(model.format_value(d.minimum))
            self.max_edit.setText(model.format_value(d.maximum))
            self.glob_label.setText(tr("Glob: %s\n(display only)") % d.glob)
        finally:
            self._filling = False

    def _append_row(self, code="", label=""):
        row = self.values.rowCount()
        self.values.insertRow(row)
        self.values.setItem(row, 0, QTableWidgetItem(str(code)))
        self.values.setItem(row, 1, QTableWidgetItem(str(label)))
        return row

    def _editor_domain(self):
        """Domäne aus den Eingaben des Editors (Werte als Text, geprüft wird in der Sitzung)."""
        old = self.session.get(self.current)
        d = old.copy()
        d.name = self.name_edit.text()
        d.description = self.desc_edit.text()
        d.kind = self.kind_combo.currentData() if old.kind != "glob" else "glob"
        d.field_type = self.type_combo.currentData()
        if d.kind == "coded":
            d.values = []
            for row in range(self.values.rowCount()):
                code = self.values.item(row, 0)
                label = self.values.item(row, 1)
                code, label = (code.text() if code else ""), (label.text() if label else "")
                if code.strip() or label.strip():
                    d.values.append((code, label))
        elif d.kind == "range":
            d.minimum = self.min_edit.text().strip() or None
            d.maximum = self.max_edit.text().strip() or None
        return d

    def _edited(self, *_args):
        if self._filling or self.current is None:
            return
        old_name = self.current
        d = self._editor_domain()
        self.session.replace(old_name, d)
        self.current = d.name
        self.stack.setCurrentIndex(PAGES.get(d.kind, 0))
        item = self.list.currentItem()
        if item is not None and old_name != d.name:
            item.setText(d.name)
            item.setData(Qt.UserRole, d.name)
            self._fill_fields()
        if self.sender() in (self.kind_combo, self.type_combo):
            self._fill_fields()
        self._update_status()

    # -- Befehle des Dialogs ---------------------------------------------------
    def new_domain(self, kind):
        ftype = "integer" if kind == "range" else "string"
        d = model.Domain(self.session.unique_name(), kind=kind, field_type=ftype)
        if kind == "coded":
            d.values = []
        self.session.add(d)
        self._fill_list(select=d.name)
        self._fill_fields()
        self._update_status()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def delete_current(self):
        if self.current is None:
            return
        users = self.session.users(self.current)
        if users:
            QMessageBox.warning(self, TITLE, tr("“%s” is still assigned to these fields: %s.\n"
                                                "Remove the assignment first.") % (self.current, ", ".join(users)))
            return
        self.session.remove(self.current)
        self._fill_list()
        self._fill_fields()
        self._update_status()

    def add_value_row(self):
        row = self._append_row()
        self.values.setCurrentCell(row, 0)
        self.values.editItem(self.values.item(row, 0))

    def remove_value_row(self):
        row = self.values.currentRow()
        if row >= 0:
            self.values.removeRow(row)
            self._edited()

    # -- Felder --------------------------------------------------------------------
    def _fill_fields(self):
        self.fields.setRowCount(0)
        self.field_combos = {}
        for name, ftype in self.session.fields.items():
            row = self.fields.rowCount()
            self.fields.insertRow(row)
            self.fields.setItem(row, 0, QTableWidgetItem(name))
            self.fields.setItem(row, 1, QTableWidgetItem(model.TYPE_LABELS.get(ftype, "–")))
            combo = QComboBox(self.fields)
            combo.addItem(model.NONE_LABEL, "")
            current = self.session.assignments.get(name, "")
            choices = self.session.choices(name)
            if current and current not in choices:
                choices.append(current)
            for n in choices:
                combo.addItem(n, n)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.setEnabled(ftype is not None)
            combo.activated.connect(lambda _i, f=name, c=combo: self._assigned(f, c))
            self.fields.setCellWidget(row, 2, combo)
            self.field_combos[name] = combo
        self.fields.resizeColumnsToContents()
        self.fields.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    def _assigned(self, field_name, combo):
        self.session.assign(field_name, combo.currentData())
        self._update_status()

    def assign(self, field_name, domain_name):
        """Zuordnung setzen wie per Auswahl in der Tabelle (für Tests und Tastatur)."""
        combo = self.field_combos[field_name]
        combo.setCurrentIndex(max(0, combo.findData(domain_name or "")))
        self._assigned(field_name, combo)

    # -- Prüfen und Speichern -------------------------------------------------
    def problems(self):
        return self.session.problems()

    def _update_status(self):
        problems = self.problems()
        save = self.buttons.button(QDialogButtonBox.Save)
        save.setEnabled(not problems and self.session.dirty())
        bad = {where for where, _text in problems}
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setForeground(QBrush(theme.color("err")) if item.data(Qt.UserRole) in bad
                               else QBrush(self.list.palette().text().color()))
        if problems:
            self.status.setStyleSheet("color: %s;" % theme.css("err"))
            self.status.setText(tr("Cannot be saved: ") + "; ".join(
                "%s – %s" % p for p in problems[:3]) + (" …" if len(problems) > 3 else ""))
        else:
            self.status.setStyleSheet("")
            self.status.setText(tr("Unsaved changes") if self.session.dirty()
                                else tr("%d domains") % len(self.session.domains))

    def save(self):
        if self.problems():
            return
        try:
            self.store.apply(self.session.changes(), self.session)
        except Exception as exc:  # Datenquelle schreibgeschützt, gesperrt, noch verwendet ...
            QMessageBox.warning(self, TITLE, tr("Saving failed:\n%s") % exc)
            self.load()
            return
        self.accept()


def open_dialog(iface, layer=None):
    """Dialog für den (aktiven) Layer öffnen; Hinweis, wenn er keine Felder hat."""
    layer = layer or iface.activeLayer()
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        iface.messageBar().pushMessage(LOG_TAG, tr("Please select a vector layer or a table."),
                                       level=Qgis.Warning, duration=4)
        return None
    dlg = DomainDialog(layer, store_mod.store_for(layer), iface.mainWindow())
    try:
        dlg.exec_()
    finally:
        dlg.deleteLater()
    return dlg
