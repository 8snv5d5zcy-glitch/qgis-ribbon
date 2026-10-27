"""Dialoge „Feld hinzufügen“, „Feld löschen“ und „Feld umbenennen“.

QGIS hat für Python keinen fertigen Dialog dafür (``QgsAddAttrDialog`` ist
Teil der Anwendung). Die Dialoge prüfen ihre Eingaben mit ``core.fields`` und
schreiben über ``qgis_integration.field_ops``: im Bearbeitungsmodus in den
Puffer, sonst nach Rückfrage direkt in die Datenquelle.

``exec_dialog`` und ``confirm_direct`` werden in Tests ersetzt.
"""

from qgis.core import Qgis, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                                 QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QSpinBox,
                                 QVBoxLayout)

from ..core import fields as fm
from ..core.i18n import tr
from ..qgis_integration import field_ops
from . import theme

LOG_TAG = "QGIS Ribbon"
DIRECT_TEXT = tr("The layer “%s” is not in edit mode. The change is written to the data source "
                 "immediately and cannot be undone. Continue?")


def exec_dialog(dlg):
    return dlg.exec_()


def confirm_direct(parent, layer):
    answer = QMessageBox.question(parent, tr("Change Data Source"), DIRECT_TEXT % layer.name(),
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return answer == QMessageBox.Yes


class _Base(QDialog):
    def __init__(self, layer, title, name, parent=None):
        QDialog.__init__(self, parent)
        self.setObjectName(name)
        theme.style_dialog(self)
        self.setWindowTitle("%s – %s" % (title, layer.name()))
        self.layer = layer
        self.lay = QVBoxLayout(self)
        self.form = QFormLayout()
        self.lay.addLayout(self.form)
        self.hint = QLabel(self)
        self.hint.setObjectName("ribbon_field_hint")
        self.hint.setWordWrap(True)
        self.lay.addWidget(self.hint)
        mode = QLabel(tr("Changes go into the edit buffer and can be undone.") if layer.isEditable()
                      else tr("The layer is not in edit mode: changes are written to the data source."), self)
        mode.setWordWrap(True)
        self.lay.addWidget(mode)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.lay.addWidget(self.buttons)

    def problems(self):
        return []

    def check(self):
        problems = self.problems()
        self.hint.setText(problems[0] if problems else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not problems)
        return not problems


class AddFieldDialog(_Base):
    def __init__(self, layer, parent=None):
        _Base.__init__(self, layer, tr("Add Field"), "ribbon_add_field_dialog", parent)
        self.existing = field_ops.names(layer)
        self.name = QLineEdit(self)
        self.type = QComboBox(self)
        for key in field_ops.supported_types(layer):
            self.type.addItem(fm.type_label(key), key)
        self.length = QSpinBox(self)
        self.length.setRange(0, fm.MAX_LENGTH)
        self.precision = QSpinBox(self)
        self.precision.setRange(0, 99)
        self.alias = QLineEdit(self)
        self.comment = QLineEdit(self)
        self.form.addRow(tr("Name"), self.name)
        self.form.addRow(tr("Type"), self.type)
        self.form.addRow(tr("Length"), self.length)
        self.form.addRow(tr("Precision"), self.precision)
        self.form.addRow(tr("Alias"), self.alias)
        self.form.addRow(tr("Comment"), self.comment)
        self.name.textChanged.connect(self.check)
        self.type.currentIndexChanged.connect(self._type_changed)
        self.length.valueChanged.connect(self.check)
        self.precision.valueChanged.connect(self.check)
        self._type_changed()
        self.resize(420, self.sizeHint().height())

    def _type_changed(self, *_args):
        key = self.type.currentData()
        if key is None:
            self.length.setEnabled(False)
            self.precision.setEnabled(False)
        else:
            has_length, has_precision = field_ops.sizes(self.layer, key)
            self.length.setEnabled(has_length)
            self.precision.setEnabled(has_precision)
            self.length.setValue(fm.default_length(key) if has_length else 0)
            self.precision.setValue(0)
        self.check()

    def spec(self):
        return fm.FieldSpec(name=self.name.text(), type=self.type.currentData() or "string",
                            length=self.length.value(), precision=self.precision.value(),
                            alias=self.alias.text(), comment=self.comment.text())

    def problems(self):
        if self.type.count() == 0:
            return [tr("The data source offers no field types.")]
        return fm.errors(self.spec(), self.existing)


class DeleteFieldsDialog(_Base):
    def __init__(self, layer, parent=None):
        _Base.__init__(self, layer, tr("Delete Field"), "ribbon_delete_field_dialog", parent)
        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        for name in field_ops.own_fields(layer):
            item = QListWidgetItem(name, self.list)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        self.form.addRow(QLabel(tr("Fields to delete:"), self))
        self.form.addRow(self.list)
        self.list.itemChanged.connect(self.check)
        self.check()

    def chosen(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def problems(self):
        if self.list.count() == 0:
            return [tr("The layer has no fields that can be deleted.")]
        return [] if self.chosen() else [tr("Check the fields to delete.")]


class RenameFieldDialog(_Base):
    def __init__(self, layer, parent=None):
        _Base.__init__(self, layer, tr("Rename Field"), "ribbon_rename_field_dialog", parent)
        self.existing = field_ops.names(layer)
        self.field = QComboBox(self)
        self.field.addItems(field_ops.own_fields(layer))
        self.new_name = QLineEdit(self)
        self.form.addRow(tr("Field"), self.field)
        self.form.addRow(tr("New name"), self.new_name)
        self.field.currentIndexChanged.connect(self._field_changed)
        self.new_name.textChanged.connect(self.check)
        self._field_changed()

    def _field_changed(self, *_args):
        self.new_name.setText(self.field.currentText())
        self.new_name.selectAll()
        self.check()

    def problems(self):
        if self.field.count() == 0:
            return [tr("The layer has no fields that can be renamed.")]
        old, new = self.field.currentText(), self.new_name.text()
        problems = fm.rename_errors(old, new, self.existing)
        trap = field_ops.rename_trap(self.layer, old, new)
        return problems or ([trap] if trap else [])


def _layer(iface):
    layer = iface.activeLayer()
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        iface.messageBar().pushMessage(LOG_TAG, tr("Please select a vector layer or a table."),
                                       level=Qgis.Warning, duration=4)
        return None
    return layer


def _report(iface, ok, message):
    iface.messageBar().pushMessage(LOG_TAG, message, level=Qgis.Success if ok else Qgis.Warning, duration=4)
    return ok


def _open(iface, make, apply):
    layer = _layer(iface)
    if layer is None:
        return None
    dlg = make(layer, iface.mainWindow())
    try:
        if exec_dialog(dlg) != QDialog.Accepted or not dlg.check():
            return False
        if not layer.isEditable() and not confirm_direct(iface.mainWindow(), layer):
            return False
        return _report(iface, *apply(layer, dlg))
    finally:
        dlg.deleteLater()


def open_add(iface):
    return _open(iface, AddFieldDialog, lambda layer, dlg: field_ops.add_field(layer, dlg.spec()))


def open_delete(iface):
    return _open(iface, DeleteFieldsDialog, lambda layer, dlg: field_ops.delete_fields(layer, dlg.chosen()))


def open_rename(iface):
    return _open(iface, RenameFieldDialog,
                 lambda layer, dlg: field_ops.rename_field(layer, dlg.field.currentText(), dlg.new_name.text()))
