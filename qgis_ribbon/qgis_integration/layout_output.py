"""Ausgabe im Layout-Fenster: Exportauflösung, Georeferenz, Schnellexport, alle Layouts, Atlas, Format übertragen.

Auflösung und Georeferenz (Worldfile) sind Eigenschaften des Layouts und laufen wie im
Bedienfeld von QGIS über ``undoStack().beginCommand(layout, …)``, ebenso die Einstellungen
des Atlas (``beginCommand(atlas, …)``). Mehrere Änderungen auf einmal (Atlas aus aktivem
Layer, Format einfügen) bilden ein Makro und damit einen Rückgängig-Schritt.

Der Schnellexport merkt seinen Ordner und „nicht mehr fragen“ am Projekt (``writeEntry``
unter ``qgis_ribbon``). Dialoge (Ordnerwahl, Rückfrage) gehen über ``DIALOGS``, damit Tests
sie ersetzen können.
"""

import os
import re

from qgis.core import (Qgis, QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemMap, QgsPrintLayout, QgsProject,
                       QgsVectorLayer)
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                                 QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                                 QPushButton, QVBoxLayout, QWidget)

from ..core.i18n import tr
from . import layout_ops

SCOPE = "qgis_ribbon"
FOLDER_KEY = "schnellexport/ordner"
NO_ASK_KEY = "schnellexport/nicht_fragen"
RESOLUTIONS = (96, 150, 300, 600)
WORLDFILE_PROPERTY = "exportWorldFile"
ATLAS_MARGIN = 0.10
FORMATS = (("pdf", "PDF"), ("png", "PNG"))


# Auflösung und Georeferenz

def export_dpi(layout):
    return layout.renderContext().dpi()


def set_export_dpi(layout, dpi):
    dpi = float(dpi)
    if dpi <= 0 or abs(dpi - export_dpi(layout)) < 1e-9:
        return False
    stack = layout.undoStack()
    stack.beginCommand(layout, tr("Change export resolution"))
    layout.renderContext().setDpi(dpi)
    stack.endCommand()
    return True


def worldfile_on(layout):
    return str(layout.customProperty(WORLDFILE_PROPERTY, False)).lower() in ("true", "1")


def set_worldfile(layout, on):
    if bool(on) == worldfile_on(layout):
        return False
    stack = layout.undoStack()
    stack.beginCommand(layout, tr("Change world file setting"))
    layout.setCustomProperty(WORLDFILE_PROPERTY, bool(on))
    stack.endCommand()
    return True


# Schnellexport

def safe_name(name):
    """Dateiname aus dem Namen des Layouts (ohne Zeichen, die Windows verbietet)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "").strip().rstrip(".")
    return cleaned or tr("Layout")


def quick_folder(project):
    return project.readEntry(SCOPE, FOLDER_KEY, "")[0]


def set_quick_folder(project, folder):
    project.writeEntry(SCOPE, FOLDER_KEY, folder)


def asks_before_overwrite(project):
    return not project.readBoolEntry(SCOPE, NO_ASK_KEY, False)[0]


def choose_folder(parent, start):
    return QFileDialog.getExistingDirectory(parent, tr("Folder for Quick Export"), start)


def ask_overwrite(parent, path):
    """(überschreiben?, nicht mehr fragen?)"""
    box = QMessageBox(QMessageBox.Icon.Question, tr("Quick Export"),
                      tr("The file already exists:\n%s\n\nOverwrite it?") % path,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    check = QCheckBox(tr("Don't ask again for this project"), box)
    box.setCheckBox(check)
    answer = box.exec()
    return answer == QMessageBox.StandardButton.Yes, check.isChecked()


DIALOGS = {"folder": choose_folder, "overwrite": ask_overwrite}


def export_pdf(layout, path):
    """Layout als PDF (ein Atlas: eine Datei mit allen Seiten). Gibt den Fehlertext zurück oder None."""
    settings = QgsLayoutExporter.PdfExportSettings()
    atlas = layout.atlas() if isinstance(layout, QgsPrintLayout) else None
    if atlas is not None and atlas.enabled() and atlas.coverageLayer() is not None:
        result, error = QgsLayoutExporter.exportToPdf(atlas, path, settings)
    else:
        result = QgsLayoutExporter(layout).exportToPdf(path, settings)
        error = ""
    if result != QgsLayoutExporter.ExportResult.Success:
        return error or tr("Export failed (code %s).") % getattr(result, "value", result)
    return None


def export_png(layout, folder, name):
    """Layout als PNG. Ein Atlas schreibt eine Datei je Objekt nach seinem Namensmuster, deshalb in einen
    Unterordner mit dem Namen des Layouts (sonst überschreiben sich Atlanten mit gleichem Muster)."""
    settings = QgsLayoutExporter.ImageExportSettings()
    atlas = layout.atlas() if isinstance(layout, QgsPrintLayout) else None
    if atlas is not None and atlas.enabled() and atlas.coverageLayer() is not None:
        target = os.path.join(folder, name)
        os.makedirs(target, exist_ok=True)
        result, error = QgsLayoutExporter.exportToImage(atlas, os.path.join(target, name), "png", settings)
    else:
        result = QgsLayoutExporter(layout).exportToImage(os.path.join(folder, name + ".png"), settings)
        error = ""
    if result != QgsLayoutExporter.ExportResult.Success:
        return error or tr("Export failed (code %s).") % getattr(result, "value", result)
    return None


def quick_export(layout, parent=None, project=None):
    """PDF in den Ordner des Projekts. Gibt (Pfad, Fehler) zurück; (None, None) bei Abbruch."""
    project = project or QgsProject.instance()
    folder = quick_folder(project)
    if not folder or not os.path.isdir(folder):
        start = folder or project.homePath() or os.path.expanduser("~")
        folder = DIALOGS["folder"](parent, start)
        if not folder:
            return None, None
        set_quick_folder(project, folder)
    path = os.path.join(folder, safe_name(layout.name()) + ".pdf")
    if os.path.exists(path) and asks_before_overwrite(project):
        overwrite, never = DIALOGS["overwrite"](parent, path)
        if not overwrite:
            return None, None
        if never:
            project.writeEntry(SCOPE, NO_ASK_KEY, True)
    return path, export_pdf(layout, path)


def change_quick_folder(parent=None, project=None):
    project = project or QgsProject.instance()
    start = quick_folder(project) or project.homePath() or os.path.expanduser("~")
    folder = DIALOGS["folder"](parent, start)
    if folder:
        set_quick_folder(project, folder)
    return folder or None


def _bar(env):
    designer = env.designer
    return designer.messageBar() if designer is not None and hasattr(designer, "messageBar") else None


def _report(env, path, error):
    bar = _bar(env)
    if bar is None or path is None:
        return
    if error:
        bar.pushMessage(tr("Quick Export"), error, Qgis.MessageLevel.Critical)
        return
    url = QUrl.fromLocalFile(path).toString()
    bar.pushMessage(tr("Quick Export"), tr('Saved as <a href="%s">%s</a>') % (url, path), Qgis.MessageLevel.Success)


def _print_layout(env):
    designer = env.designer
    layout = designer.layout() if designer is not None else None
    return layout if isinstance(layout, QgsPrintLayout) else None


def quick_export_command(env, _command):
    def run():
        layout = _print_layout(env)
        if layout is not None:
            window = env.designer.window() if env.designer is not None else None
            path, error = quick_export(layout, window)
            _report(env, path, error)

    return run


def quick_folder_command(env, _command):
    def run():
        window = env.designer.window() if env.designer is not None else None
        change_quick_folder(window)

    return run


# Alle Layouts exportieren

def print_layouts(project=None):
    project = project or QgsProject.instance()
    return [lay for lay in project.layoutManager().layouts() if isinstance(lay, QgsPrintLayout)]


def export_layouts(layouts, fmt, folder):
    """Jedes Layout als eine Datei (Atlas als ein PDF bzw. ein Bild je Objekt). [(Name, Fehler oder None)]"""
    done = []
    for layout in layouts:
        name = safe_name(layout.name())
        if fmt == "pdf":
            error = export_pdf(layout, os.path.join(folder, name + ".pdf"))
        else:
            error = export_png(layout, folder, name)
        done.append((layout.name(), error))
    return done


class ExportAllDialog(QDialog):
    """Layouts zum Abhaken, Format, Ordner."""

    def __init__(self, layouts, folder, parent=None):
        QDialog.__init__(self, parent)
        self.setObjectName("ribbon_alle_layouts_dialog")
        self.setWindowTitle(tr("Export All Layouts"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Layouts to export:"), self))
        self.list = QListWidget(self)
        for layout in layouts:
            item = QListWidgetItem(layout.name(), self.list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, layout.name())
        lay.addWidget(self.list)
        form = QFormLayout()
        self.format = QComboBox(self)
        for key, label in FORMATS:
            self.format.addItem(label, key)
        form.addRow(tr("Format:"), self.format)
        row = QWidget(self)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        self.folder = QLineEdit(folder, row)
        browse = QPushButton(tr("Browse …"), row)
        browse.clicked.connect(self._browse)
        row_lay.addWidget(self.folder)
        row_lay.addWidget(browse)
        form.addRow(tr("Folder:"), row)
        lay.addLayout(form)
        lay.addWidget(QLabel(tr("A layout with an atlas becomes one PDF, or one image per feature."), self))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _browse(self):
        folder = DIALOGS["folder"](self, self.folder.text())
        if folder:
            self.folder.setText(folder)

    def chosen(self):
        names = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                names.append(item.data(Qt.ItemDataRole.UserRole))
        return names, self.format.currentData(), self.folder.text()


def export_all(parent=None, project=None):
    """Dialog zeigen und exportieren; [(Name, Fehler)] oder None bei Abbruch."""
    project = project or QgsProject.instance()
    layouts = print_layouts(project)
    start = quick_folder(project) or project.homePath() or os.path.expanduser("~")
    dialog = ExportAllDialog(layouts, start, parent)
    if DIALOGS.get("export_all", lambda d: d.exec())(dialog) != QDialog.DialogCode.Accepted:
        return None
    names, fmt, folder = dialog.chosen()
    if not folder or not os.path.isdir(folder):
        return [(name, tr("The folder does not exist.")) for name in names]
    wanted = [lay for lay in layouts if lay.name() in names]
    return export_layouts(wanted, fmt, folder)


def export_all_command(env, _command):
    def run():
        designer = env.designer
        parent = designer.window() if designer is not None else env.iface.mainWindow()
        done = export_all(parent)
        if done is None:
            return
        failed = [name for name, error in done if error]
        bar = _bar(env) if designer is not None else env.iface.messageBar()
        if bar is None:
            return
        if failed:
            bar.pushMessage(tr("Export All Layouts"), tr("Not exported: %s") % ", ".join(failed),
                            Qgis.MessageLevel.Warning)
        else:
            bar.pushMessage(tr("Export All Layouts"), tr("%d layouts exported.") % len(done),
                            Qgis.MessageLevel.Success)

    return run


# Atlas

def change_atlas(atlas, text, apply):
    """``apply(atlas)`` als ein Rückgängig-Schritt (Befehl am Atlas wie im Bedienfeld von QGIS)."""
    stack = atlas.layout().undoStack()
    stack.beginCommand(atlas, text)
    apply(atlas)
    stack.endCommand()


def set_coverage(atlas, layer):
    """Abdeckungslayer setzen; None schaltet den Atlas aus."""
    def apply(a):
        if layer is None:
            a.setEnabled(False)
        else:
            a.setCoverageLayer(layer)
            a.setEnabled(True)

    change_atlas(atlas, tr("Change atlas coverage layer"), apply)


def set_page_name(atlas, expression):
    change_atlas(atlas, tr("Change atlas page name"), lambda a: a.setPageNameExpression(expression))


def set_filter(atlas, on, expression=None):
    def apply(a):
        a.setFilterFeatures(bool(on))
        if expression is not None:
            a.setFilterExpression(expression)

    change_atlas(atlas, tr("Change atlas filter"), apply)


def set_sort(atlas, field, ascending=None):
    """Sortierfeld (leer: nicht sortieren) und optional Richtung."""
    def apply(a):
        a.setSortFeatures(bool(field))
        if field:
            a.setSortExpression(field)
        if ascending is not None:
            a.setSortAscending(bool(ascending))

    change_atlas(atlas, tr("Change atlas sorting"), apply)


def atlas_map(layout):
    """Karte, die dem Atlas folgen soll: Referenzkarte, sonst die erste."""
    ref = layout.referenceMap()
    if ref is not None:
        return ref
    maps = layout_ops.layout_maps(layout)
    return maps[0] if maps else None


def atlas_from_layer(layout, layer):
    """Atlas mit ``layer`` einschalten, Bezugskarte folgt (Rand 10 %). Ein Schritt. Gibt die Karte zurück."""
    atlas = layout.atlas()
    map_item = atlas_map(layout)
    stack = layout.undoStack()
    stack.beginMacro(tr("Atlas from active layer"))
    try:
        set_coverage(atlas, layer)
        if map_item is not None:
            map_item.beginCommand(tr("Map follows atlas"))
            map_item.setAtlasDriven(True)
            map_item.setAtlasScalingMode(QgsLayoutItemMap.AtlasScalingMode.Auto)
            map_item.setAtlasMargin(ATLAS_MARGIN)
            map_item.endCommand()
    finally:
        stack.endMacro()
    return map_item


def atlas_from_layer_command(env, _command):
    def run():
        layout = _print_layout(env)
        layer = env.iface.activeLayer()
        if layout is None or not isinstance(layer, QgsVectorLayer):
            bar = _bar(env)
            if bar is not None:
                bar.pushMessage(tr("Atlas"), tr("Select a vector layer in the main window first."),
                                Qgis.MessageLevel.Info)
            return
        atlas_from_layer(layout, layer)
        env.designer.setAtlasPreviewEnabled(True)

    return run


# Format übertragen

FORMAT = {}


def copy_format(item):
    """Darstellung eines Elements merken; bei Text zusätzlich Schrift, Farbe und Ausrichtung."""
    FORMAT.clear()
    FORMAT.update({
        "frame": item.frameEnabled(), "frame_color": item.frameStrokeColor(),
        "frame_width": item.frameStrokeWidth(), "frame_join": item.frameJoinStyle(),
        "background": item.hasBackground(), "background_color": item.backgroundColor(),
        "opacity": item.itemOpacity(), "blend": item.blendMode(),
    })
    if isinstance(item, QgsLayoutItemLabel):
        FORMAT.update({"text_format": item.textFormat(), "h_align": item.hAlign(), "v_align": item.vAlign()})
    return dict(FORMAT)


def has_format():
    return bool(FORMAT)


def _apply_format(item, fmt):
    item.setFrameEnabled(fmt["frame"])
    item.setFrameStrokeColor(fmt["frame_color"])
    item.setFrameStrokeWidth(fmt["frame_width"])
    item.setFrameJoinStyle(fmt["frame_join"])
    item.setBackgroundEnabled(fmt["background"])
    item.setBackgroundColor(fmt["background_color"])
    item.setItemOpacity(fmt["opacity"])
    item.setBlendMode(fmt["blend"])
    if isinstance(item, QgsLayoutItemLabel) and "text_format" in fmt:
        item.setTextFormat(fmt["text_format"])
        item.setHAlign(fmt["h_align"])
        item.setVAlign(fmt["v_align"])
    item.update()


def paste_format(items, fmt=None):
    """Gemerkte Darstellung auf alle Elemente setzen, ein Rückgängig-Schritt. Gibt die Zahl zurück."""
    fmt = dict(fmt or FORMAT)
    items = [i for i in items if i is not None]
    if not fmt or not items:
        return 0
    stack = items[0].layout().undoStack()
    stack.beginMacro(tr("Paste format"))
    try:
        for item in items:
            item.beginCommand(tr("Paste format"))
            _apply_format(item, fmt)
            item.endCommand()
            item.changed.emit()
    finally:
        stack.endMacro()
    return len(items)


def copy_format_command(env, _command):
    def run():
        items = env.items.items() if env.items is not None else []
        if len(items) == 1:
            copy_format(items[0])

    return run


def paste_format_command(env, _command):
    def run():
        items = env.items.items() if env.items is not None else []
        if not has_format():
            bar = _bar(env)
            if bar is not None:
                bar.pushMessage(tr("Paste Format"), tr("Copy the format of an item first."), Qgis.MessageLevel.Info)
            return
        paste_format(items)

    return run
