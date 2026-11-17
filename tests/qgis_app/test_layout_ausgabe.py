"""Ausgabe im Layout-Fenster: Auflösung, Georeferenz, Schnellexport, alle Layouts, Atlas, Format übertragen.

Dateidialoge und Rückfragen sind über ``layout_output.DIALOGS`` ersetzt; exportiert wird in
Wegwerf-Ordner von pytest.
"""
import os

import pytest
from qgis.core import (QgsFeature, QgsGeometry, QgsLayoutItemLabel, QgsLayoutItemMap, QgsLayoutItemShape,
                       QgsPointXY, QgsPrintLayout, QgsProject, QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QDialog, QToolButton, QWidget

from qgis_ribbon.qgis_integration import layout_output

from test_designer_ribbon import (FakeDesigner, designer, designer_iface, registry, report, ribbons,  # noqa: F401
                                  settle)


def a4(name="Karte"):
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    layout.setName(name)
    m = QgsLayoutItemMap(layout)
    m.attemptSetSceneRect(m.rect().adjusted(20, 20, 200, 150))
    m.zoomToExtent(QgsRectangle(-10, -10, 210, 110))
    layout.addLayoutItem(m)
    layout.undoStack().stack().clear()
    return layout


def points(name="punkte"):
    layer = QgsVectorLayer("Point?crs=EPSG:25832&field=name:string&field=nr:integer", name, "memory")
    feats = []
    for n, (x, y) in enumerate([(0, 0), (100, 100), (200, 50)]):
        f = QgsFeature(layer.fields())
        f.setAttributes(["P%d" % n, n])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(layer)
    return layer


def index(layout):
    return layout.undoStack().stack().index()


@pytest.fixture
def dialogs(monkeypatch):
    calls = {"folder": [], "overwrite": []}
    answers = {"folder": "", "overwrite": (True, False)}

    def folder(_parent, start):
        calls["folder"].append(start)
        return answers["folder"]

    def overwrite(_parent, path):
        calls["overwrite"].append(path)
        return answers["overwrite"]

    monkeypatch.setitem(layout_output.DIALOGS, "folder", folder)
    monkeypatch.setitem(layout_output.DIALOGS, "overwrite", overwrite)
    yield calls, answers
    project = QgsProject.instance()
    project.removeEntry(layout_output.SCOPE, layout_output.FOLDER_KEY)
    project.removeEntry(layout_output.SCOPE, layout_output.NO_ASK_KEY)


@pytest.fixture
def printed():
    d = FakeDesigner(master=a4())
    d.window().show()
    settle()
    yield d
    d.window().close()
    d.window().deleteLater()
    settle()


@pytest.fixture
def layer():
    lay = points()
    yield lay
    QgsProject.instance().removeMapLayer(lay.id())


# Auflösung und Georeferenz

def test_resolution_is_one_step_and_undoable():
    layout = a4()
    assert layout_output.set_export_dpi(layout, 150)
    assert layout_output.export_dpi(layout) == 150 and index(layout) == 1
    assert not layout_output.set_export_dpi(layout, 150) and index(layout) == 1
    layout.undoStack().stack().undo()
    assert layout_output.export_dpi(layout) == 300


def test_world_file_switch():
    layout = a4()
    assert not layout_output.worldfile_on(layout)
    layout_output.set_worldfile(layout, True)
    assert layout_output.worldfile_on(layout) and index(layout) == 1
    layout.undoStack().stack().undo()
    assert not layout_output.worldfile_on(layout)


def test_resolution_and_world_file_controls(ribbons, printed):  # noqa: F811
    ribbons.start()
    ribbons.opened(printed)
    settle()
    ribbon = ribbons.ribbons[printed.window()]
    ribbon.widget.select_tab("teilen")
    settle()
    control = ribbon.widget.findChild(QWidget, "ribbon_control_export_aufloesung")
    combo = control.findChild(QComboBox)
    assert combo.currentText() == "300 dpi"
    combo.activated.emit(1)
    settle()
    layout = printed.master()
    assert layout_output.export_dpi(layout) == 150
    combo.setEditText("200")
    combo.lineEdit().editingFinished.emit()
    settle()
    assert layout_output.export_dpi(layout) == 200
    layout_output.set_export_dpi(layout, 600)     # Änderung von außen
    settle()
    assert combo.currentText() == "600 dpi"
    check = ribbon.widget.findChild(QWidget, "ribbon_control_export_worldfile").findChild(QCheckBox)
    check.click()
    settle()
    assert layout_output.worldfile_on(layout)


# Schnellexport

def test_quick_export_asks_for_the_folder_once(tmp_path, dialogs):
    calls, answers = dialogs
    answers["folder"] = str(tmp_path)
    layout = a4("Stadt/plan")
    path, error = layout_output.quick_export(layout)
    assert error is None and path == os.path.join(str(tmp_path), "Stadt_plan.pdf") and os.path.isfile(path)
    assert layout_output.quick_folder(QgsProject.instance()) == str(tmp_path)
    assert len(calls["folder"]) == 1
    # Zweiter Aufruf: kein Ordnerdialog, aber Rückfrage zum Überschreiben
    answers["overwrite"] = (False, False)
    assert layout_output.quick_export(layout) == (None, None)
    assert len(calls["folder"]) == 1 and len(calls["overwrite"]) == 1


def test_quick_export_can_stop_asking(tmp_path, dialogs):
    calls, answers = dialogs
    answers["folder"] = str(tmp_path)
    layout = a4()
    layout_output.quick_export(layout)
    answers["overwrite"] = (True, True)
    path, error = layout_output.quick_export(layout)
    assert error is None and len(calls["overwrite"]) == 1
    assert not layout_output.asks_before_overwrite(QgsProject.instance())
    layout_output.quick_export(layout)
    assert len(calls["overwrite"]) == 1


def test_quick_export_cancelled_without_folder(dialogs):
    _calls, answers = dialogs
    answers["folder"] = ""
    assert layout_output.quick_export(a4()) == (None, None)


def test_quick_export_button_reports_the_file(tmp_path, dialogs, ribbons, printed):  # noqa: F811
    _calls, answers = dialogs
    answers["folder"] = str(tmp_path)
    ribbons.start()
    ribbons.opened(printed)
    settle()
    command = ribbons.base.commands["schnellexport_pdf"]
    ribbon = ribbons.ribbons[printed.window()]
    assert ribbon.resolver.resolve(command).available
    layout_output.quick_export_command(ribbon.env, command)()
    assert os.path.isfile(os.path.join(str(tmp_path), "Karte.pdf"))


# Alle Layouts

def test_export_all_layouts_as_pdf_and_png(tmp_path, layer):
    first, second = a4("Erste"), a4("Zweite")
    second.atlas().setCoverageLayer(layer)
    second.atlas().setEnabled(True)
    done = layout_output.export_layouts([first, second], "pdf", str(tmp_path))
    assert done == [("Erste", None), ("Zweite", None)]
    assert sorted(os.listdir(str(tmp_path))) == ["Erste.pdf", "Zweite.pdf"]
    png = tmp_path / "png"
    png.mkdir()
    layout_output.export_layouts([first, second], "png", str(png))
    assert os.path.isfile(str(png / "Erste.png"))
    assert len(os.listdir(str(png / "Zweite"))) == 3       # Atlas: ein Bild je Objekt


def test_export_all_dialog_lists_print_layouts(tmp_path, monkeypatch):
    project = QgsProject.instance()
    layouts = [a4("Eins"), a4("Zwei")]
    for layout in layouts:
        project.layoutManager().addLayout(layout)
    try:
        def accept(dialog):
            assert dialog.list.count() == len(layout_output.print_layouts())
            dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)
            dialog.folder.setText(str(tmp_path))
            return QDialog.DialogCode.Accepted

        monkeypatch.setitem(layout_output.DIALOGS, "export_all", accept)
        done = layout_output.export_all()
        assert [name for name, _error in done] == [lay.name() for lay in layout_output.print_layouts()][1:]
        assert all(error is None for _name, error in done)
    finally:
        for layout in layouts:
            project.layoutManager().removeLayout(layout)


# Atlas

def test_atlas_settings_are_undoable(layer):
    layout = a4()
    atlas = layout.atlas()
    layout_output.set_coverage(atlas, layer)
    assert atlas.enabled() and atlas.coverageLayer() is layer and index(layout) == 1
    layout_output.set_page_name(atlas, '"name"')
    layout_output.set_filter(atlas, True, '"nr" > 0')
    layout_output.set_sort(atlas, "nr", ascending=False)
    assert atlas.pageNameExpression() == '"name"' and atlas.filterFeatures() and atlas.filterExpression() == '"nr" > 0'
    assert atlas.sortFeatures() and atlas.sortExpression() == "nr" and not atlas.sortAscending()
    assert index(layout) == 4
    layout_output.set_coverage(atlas, None)
    assert not atlas.enabled()
    layout.undoStack().stack().undo()
    assert atlas.enabled()


def test_atlas_from_layer_is_one_step(layer):
    layout = a4()
    map_item = layout_output.atlas_from_layer(layout, layer)
    assert layout.atlas().enabled() and layout.atlas().coverageLayer() is layer
    assert map_item.atlasDriven() and map_item.atlasScalingMode() == QgsLayoutItemMap.AtlasScalingMode.Auto
    assert abs(map_item.atlasMargin() - 0.10) < 1e-9
    assert index(layout) == 1
    layout.undoStack().stack().undo()
    assert not layout.atlas().enabled() and not map_item.atlasDriven()


def test_atlas_fields_follow_the_atlas(ribbons, printed, layer):  # noqa: F811
    ribbons.start()
    ribbons.opened(printed)
    settle()
    ribbon = ribbons.ribbons[printed.window()]
    ribbon.widget.select_tab("atlas")
    settle()
    fields = {cid: ribbon.widget.findChild(QWidget, "ribbon_control_" + cid)
              for cid in ("atlas_layer", "atlas_seitenname", "atlas_filter", "atlas_sortierung", "atlas_absteigend")}
    assert fields["atlas_layer"].isEnabled()
    assert not any(fields[c].isEnabled() for c in ("atlas_seitenname", "atlas_filter", "atlas_sortierung"))
    atlas = printed.master().atlas()
    layout_output.set_coverage(atlas, layer)       # Änderung über die API
    settle()
    assert fields["atlas_layer"].editor.currentLayer() is layer
    assert fields["atlas_seitenname"].isEnabled() and fields["atlas_sortierung"].isEnabled()
    assert not fields["atlas_absteigend"].isEnabled()
    layout_output.set_sort(atlas, "name")
    settle()
    assert fields["atlas_sortierung"].editor.currentField() == "name" and fields["atlas_absteigend"].isEnabled()
    fields["atlas_absteigend"].editor.click()
    settle()
    assert not atlas.sortAscending()
    fields["atlas_seitenname"].editor.setExpression('"nr" * 2')
    settle()
    assert atlas.pageNameExpression() == '"nr" * 2'


def test_atlas_from_active_layer_starts_the_preview(ribbons, printed, layer, designer_iface):  # noqa: F811
    ribbons.start()
    ribbons.opened(printed)
    settle()
    designer_iface.set_active_layer(layer)
    previews = []
    printed.setAtlasPreviewEnabled = previews.append
    env = ribbons.ribbons[printed.window()].env
    layout_output.atlas_from_layer_command(env, ribbons.base.commands["atlas_aus_layer"])()
    assert printed.master().atlas().coverageLayer() is layer and previews == [True]


# Format übertragen

def test_paste_format_between_shapes_is_one_step():
    layout = a4()
    source, target, other = (QgsLayoutItemShape(layout) for _ in range(3))
    for item in (source, target, other):
        layout.addLayoutItem(item)
    source.setFrameEnabled(True)
    source.setFrameStrokeColor(QColor("red"))
    source.setBackgroundColor(QColor("blue"))
    source.setItemOpacity(0.5)
    layout.undoStack().stack().clear()
    layout_output.copy_format(source)
    assert layout_output.paste_format([target, other]) == 2
    assert target.frameStrokeColor() == QColor("red") and other.backgroundColor() == QColor("blue")
    assert abs(target.itemOpacity() - 0.5) < 1e-9 and index(layout) == 1
    layout.undoStack().stack().undo()
    assert target.frameStrokeColor() != QColor("red") and abs(target.itemOpacity() - 1.0) < 1e-9


def test_paste_format_from_text_to_text_only_texts_get_the_font():
    layout = a4()
    source, label, shape = QgsLayoutItemLabel(layout), QgsLayoutItemLabel(layout), QgsLayoutItemShape(layout)
    for item in (source, label, shape):
        layout.addLayoutItem(item)
    fmt = source.textFormat()
    fmt.setSize(24)
    fmt.setColor(QColor("green"))
    source.setTextFormat(fmt)
    source.setHAlign(Qt.AlignmentFlag.AlignRight)
    layout_output.copy_format(source)
    layout_output.paste_format([label, shape])
    assert label.textFormat().size() == 24 and label.textFormat().color() == QColor("green")
    assert label.hAlign() == Qt.AlignmentFlag.AlignRight
    layout.undoStack().stack().undo()
    assert label.textFormat().size() != 24


def test_format_buttons_in_the_format_tab(ribbons, printed):  # noqa: F811
    ribbons.start()
    ribbons.opened(printed)
    settle()
    layout = printed.master()
    shape = QgsLayoutItemShape(layout)
    layout.addLayoutItem(shape)
    layout.setSelectedItem(shape)
    settle()
    ribbon = ribbons.ribbons[printed.window()]
    ribbon.widget.select_tab("layout_format")
    settle()
    copy = ribbon.widget.findChild(QToolButton, "ribbon_btn_format_kopieren")
    paste = ribbon.widget.findChild(QToolButton, "ribbon_btn_format_einfuegen")
    assert copy is not None and paste is not None and copy.isEnabled() and paste.isEnabled()


def test_report_hides_output_controls(ribbons, report):  # noqa: F811
    ribbons.start()
    ribbons.opened(report)
    settle()
    env = ribbons.ribbons[report.window()].env
    assert layout_output._print_layout(env) is None
