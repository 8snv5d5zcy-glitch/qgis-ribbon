"""Dialog „Als neue Datei entzerren“ einer Sitzung „Georeferenzieren in der Karte“."""

import os

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsFileWidget, QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QMessageBox, QVBoxLayout

from ..core.i18n import tr
from ..qgis_integration import georef_session


def resampling_names():
    return (("near", tr("Nearest neighbor")), ("bilinear", tr("Bilinear")), ("cubic", tr("Cubic")))


def compression_names():
    return (("LZW", "LZW"), ("DEFLATE", "Deflate"), ("NONE", tr("None")))


def default_target(source):
    base, _ext = os.path.splitext(source)
    return base + "_georef.tif"


class WarpDialog(QDialog):
    """Zieldatei, Abtastverfahren, Kompression, Zielbezugssystem (Standard: Projekt)."""

    def __init__(self, session, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(tr("Warp to New File"))
        self.setObjectName("QgisRibbonGeorefWarp")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.target = QgsFileWidget(self)
        self.target.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
        self.target.setFilter(tr("GeoTIFF (*.tif *.tiff)"))
        self.target.setFilePath(default_target(session.source))
        form.addRow(tr("Target file"), self.target)
        self.resampling = QComboBox(self)
        for value, text in resampling_names():
            self.resampling.addItem(text, value)
        form.addRow(tr("Resampling"), self.resampling)
        self.compression = QComboBox(self)
        for value, text in compression_names():
            self.compression.addItem(text, value)
        form.addRow(tr("Compression"), self.compression)
        self.crs = QgsProjectionSelectionWidget(self)
        self.crs.setCrs(QgsProject.instance().crs() if QgsProject.instance().crs().isValid()
                        else QgsCoordinateReferenceSystem.fromWkt(session.crs_wkt))
        form.addRow(tr("Target CRS"), self.crs)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons
        lay.addWidget(buttons)

    def values(self):
        return {"out_path": self.target.filePath(), "resampling": self.resampling.currentData(),
                "compression": self.compression.currentData(), "dst_wkt": self.crs.crs().toWkt()}


def ask_replace(parent, session):
    """Soll das Ergebnis den geladenen Originallayer ersetzen? (Ohne Original: nein.)"""
    original = QgsProject.instance().mapLayer(session.original_id) if session.original_id else None
    if original is None:
        return False
    yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
    answer = QMessageBox.question(parent, tr("Warp to New File"),
                                  tr("Replace the layer %s with the result?") % original.name(), yes | no, no)
    return answer == yes


def open_dialog(env, session):
    """Dialog zeigen und die Entzerrung als Hintergrundaufgabe starten."""
    parent = env.iface.mainWindow()
    dialog = WarpDialog(session, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    values = dialog.values()
    if not values["out_path"]:
        return None
    if georef_session.same_file(values["out_path"], session.source):
        georef_session.manager().message(tr("The result must not overwrite the image itself."),
                                         Qgis.MessageLevel.Warning)
        return None
    replace = ask_replace(parent, session)
    return georef_session.install(env.iface).warp(replace=replace, **values)


def georef_entzerren(env, command):
    from ..qgis_integration.georef_commands import SessionAction
    return env.keep(SessionAction(env, command.label, lambda s, _c: open_dialog(env, s)))
