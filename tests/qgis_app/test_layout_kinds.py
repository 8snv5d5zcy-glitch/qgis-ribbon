"""Kontext-Tabs je Elementart im Layout-Fenster und Atlas-Objekt.

Die Elemente sind echte QGIS-Objekte in einem ``QgsPrintLayout``; das Fenster ist die
Attrappe aus ``test_designer_ribbon``. Das Zusammenspiel mit dem Bedienfeld
Elementeigenschaften prüft die Sonde für das Layout-Fenster im echten QGIS.
"""
import pytest
from qgis.core import (Qgis, QgsBookmark, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsLayoutFrame,
                       QgsLayoutItemAttributeTable, QgsLayoutItemHtml, QgsLayoutItemLabel,
                       QgsLayoutItemLegend, QgsLayoutItemManualTable, QgsLayoutItemMap, QgsLayoutItemMarker,
                       QgsLayoutItemPicture, QgsLayoutItemPolygon, QgsLayoutItemPolyline, QgsLayoutItemScaleBar,
                       QgsLayoutItemShape, QgsLayoutPoint, QgsLayoutSize, QgsMapThemeCollection, QgsPrintLayout,
                       QgsProject, QgsRectangle, QgsReferencedRectangle, QgsUnitTypes, QgsVectorLayer)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPolygonF
from qgis.PyQt.QtWidgets import QMenu, QWidget

from qgis_ribbon.core.conditions import Snapshot
from qgis_ribbon.qgis_integration import custom_commands, layout_ops, layout_state
from qgis_ribbon.qgis_integration.layout_state import LayoutSelection
from qgis_ribbon.qgis_integration.signals import SignalHub

from test_designer_ribbon import FakeDesigner, designer, designer_iface, registry, ribbons, settle  # noqa: F401

MM = QgsUnitTypes.LayoutUnit.LayoutMillimeters


def add(layout, item, x=10, y=10, w=60, h=40):
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(w, h, MM))
    return item


def add_map(layout, x=10):
    item = add(layout, QgsLayoutItemMap(layout), x=x)
    item.setExtent(QgsRectangle(0, 0, 1000, 1000))
    item.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    item.setId("Karte %d" % x)
    return item


def add_table(layout, kind=QgsLayoutItemAttributeTable):
    table = kind.create(layout)
    layout.addMultiFrame(table)
    frame = QgsLayoutFrame(layout, table)
    table.addFrame(frame)
    frame.attemptResize(QgsLayoutSize(80, 40, MM))
    return table, frame


def memory_layer(name="Punkte", count=3):
    layer = QgsVectorLayer("Point?crs=EPSG:3857&field=name:string", name, "memory")
    features = []
    for n in range(count):
        feature = QgsFeature(layer.fields())
        feature.setAttribute("name", "Objekt %d" % n)
        feature.setGeometry(QgsGeometry.fromWkt("POINT(%d %d)" % (n, n)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


@pytest.fixture
def layout():
    value = QgsPrintLayout(QgsProject.instance())
    value.initializeDefaults()
    yield value
    QgsProject.instance().removeAllMapLayers()


@pytest.fixture
def ribbon_in(ribbons, layout):  # noqa: F811
    """Ribbon über einem echten Layout; liefert ``(ribbon, designer)``."""
    d = FakeDesigner(master=layout)
    d.window().show()
    settle()
    ribbons.start()
    ribbons.opened(d)
    settle()
    yield ribbons.ribbons[d.window()], d
    ribbons.closing(d)
    d.window().close()
    d.window().deleteLater()
    settle()


def select(layout, *items):
    layout.deselectAll()
    for item in items:
        item.setSelected(True)
    settle()


def control(ribbon, tab, command_id):
    ribbon.widget.select_tab(tab)
    settle()
    return ribbon.widget.findChild(QWidget, "ribbon_control_" + command_id)


def undo_count(layout):
    return layout.undoStack().stack().count()


def clear_undo(layout):
    layout.undoStack().stack().clear()


# Elementart

def add_html(layout):
    html = QgsLayoutItemHtml.create(layout)
    layout.addMultiFrame(html)
    frame = QgsLayoutFrame(layout, html)
    html.addFrame(frame)
    return frame


def test_kind_of_every_item_type(layout):
    _table, frame = add_table(layout)
    _manual, manual_frame = add_table(layout, QgsLayoutItemManualTable)
    expected = [(QgsLayoutItemMap(layout), "map"), (QgsLayoutItemLabel(layout), "label"),
                (QgsLayoutItemLegend(layout), "legend"), (QgsLayoutItemScaleBar(layout), "scalebar"),
                (QgsLayoutItemPicture(layout), "picture"), (QgsLayoutItemShape(layout), "shape"),
                (QgsLayoutItemMarker(layout), "shape"), (QgsLayoutItemPolygon(QPolygonF(), layout), "shape"),
                (QgsLayoutItemPolyline(QPolygonF(), layout), "shape")]
    for item, kind in expected:
        layout.addLayoutItem(item)
        assert layout_state.kind_of(item) == kind, type(item).__name__
    assert layout_state.kind_of(frame) == "table"
    assert layout_state.kind_of(manual_frame) == "table"
    assert layout_state.kind_of(add_html(layout)) == "other"


def test_snapshot_names_the_kind_of_a_single_item_only(layout):
    a, b = add_map(layout), add(layout, QgsLayoutItemLabel(layout))
    assert layout_state.snapshot([]) == Snapshot()
    assert layout_state.snapshot([a]) == Snapshot(selected_items=1, item_kind="map")
    assert layout_state.snapshot([a, b]) == Snapshot(selected_items=2)


def test_selection_reports_a_new_kind_with_the_same_count(layout):
    a, b = add_map(layout), add(layout, QgsLayoutItemLabel(layout))
    seen = []
    hub = SignalHub()
    selection = LayoutSelection(layout, hub, lambda snap, events: seen.append(snap.item_kind))
    selection.start()
    select(layout, a)
    select(layout, b)
    a.attemptMove(QgsLayoutPoint(1, 2, MM))
    settle()
    assert seen == [None, "map", "label"]
    selection.stop()
    hub.disconnect_all()


def test_table_values_changed_elsewhere_are_reported(layout):
    table, frame = add_table(layout)
    hub = SignalHub()
    selection = LayoutSelection(layout, hub)
    selection.start()
    select(layout, frame)
    before = selection.notifications
    table.setMaximumNumberOfFeatures(7)
    table.update()
    settle()
    assert selection.notifications > before
    selection.stop()
    hub.disconnect_all()
    assert len(selection.item_hub) == 0


# Tabs im Ribbon

def test_tabs_follow_the_kind_without_jumping(ribbon_in, layout):
    ribbon, _d = ribbon_in
    a, b = add_map(layout), add(layout, QgsLayoutItemLabel(layout))
    ribbon.widget.select_tab("ansicht")
    select(layout, a)
    assert ribbon.widget.is_tab_visible("layout_karte") and ribbon.widget.is_tab_visible("layout_format")
    assert ribbon.widget.current_tab() == "ansicht"
    select(layout, b)
    assert ribbon.widget.is_tab_visible("layout_text") and not ribbon.widget.is_tab_visible("layout_karte")
    select(layout, a, b)
    assert ribbon.widget.is_tab_visible("layout_format")
    assert not ribbon.widget.is_tab_visible("layout_text") and not ribbon.widget.is_tab_visible("layout_karte")
    assert ribbon.widget.current_tab() == "ansicht"


def test_leaving_a_kind_tab_goes_to_the_last_main_tab(ribbon_in, layout):
    ribbon, _d = ribbon_in
    a = add_map(layout)
    select(layout, a)
    ribbon.widget.select_tab("layout_karte")
    select(layout)
    assert ribbon.widget.current_tab() == "layout"


def test_item_without_own_tab_shows_only_format(ribbon_in, layout):
    ribbon, _d = ribbon_in
    select(layout, add_html(layout))
    assert ribbon.widget.is_tab_visible("layout_format")
    assert not any(ribbon.widget.is_tab_visible(t) for t in (
        "layout_karte", "layout_text", "layout_legende", "layout_massstab", "layout_bild", "layout_form",
        "layout_tabelle"))


def test_every_kind_tab_builds_with_all_controls_registered(ribbon_in, layout):
    ribbon, _d = ribbon_in
    cases = {"layout_karte": add_map(layout), "layout_text": add(layout, QgsLayoutItemLabel(layout)),
             "layout_legende": add(layout, QgsLayoutItemLegend(layout)),
             "layout_massstab": add(layout, QgsLayoutItemScaleBar(layout)),
             "layout_bild": add(layout, QgsLayoutItemPicture(layout)),
             "layout_form": add(layout, QgsLayoutItemShape(layout)),
             "layout_tabelle": add_table(layout)[1]}
    for tab_id, item in cases.items():
        select(layout, item)
        ribbon.widget.select_tab(tab_id)
        settle()
        assert ribbon.widget.current_tab() == tab_id
        for group in ribbon.logic.ribbon.tab(tab_id).groups:
            for element in group.elements:
                command = getattr(element, "command", None)
                if command is None or command.source.type != "custom":
                    continue
                assert custom_commands.get(command.source.get("id")) is not None, command.id
                if command.kind == "control":
                    assert ribbon.widget.findChild(QWidget, "ribbon_control_" + command.id) is not None, command.id


# Karte

def test_map_scale_and_rotation(ribbon_in, layout):
    ribbon, _d = ribbon_in
    item = add_map(layout)
    clear_undo(layout)
    select(layout, item)
    scale = control(ribbon, "layout_karte", "item_karte_massstab")
    assert abs(scale.editor.scale() - item.scale()) < 1            # das Feld rundet auf ganze Zahlen
    scale.editor.setScale(5000)
    settle()
    assert item.scale() == pytest.approx(5000)
    assert undo_count(layout) == 1
    drehung = control(ribbon, "layout_karte", "item_karte_drehung")
    drehung.editor.setValue(30)
    settle()
    assert item.mapRotation() == 30
    assert undo_count(layout) == 2
    layout.undoStack().stack().undo()
    settle()
    assert item.mapRotation() == 0 and drehung.editor.value() == 0


def test_map_extent_follows_bookmark_in_another_crs(layout):
    item = add_map(layout)
    extent = QgsReferencedRectangle(QgsRectangle(7, 50, 8, 51), QgsCoordinateReferenceSystem("EPSG:4326"))
    bookmark = QgsBookmark()
    bookmark.setExtent(extent)
    clear_undo(layout)
    layout_ops.map_to_bookmark(item, bookmark)
    center = item.extent().center()
    assert 770000 < center.x() < 900000 and 6400000 < center.y() < 6700000
    assert undo_count(layout) == 1


def test_map_extent_from_and_to_canvas(ribbon_in, layout, designer_iface):  # noqa: F811
    item = add_map(layout)
    canvas = designer_iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    canvas.resize(400, 400)
    canvas.setExtent(QgsRectangle(100000, 100000, 200000, 200000))
    wanted = canvas.mapSettings().visibleExtent().center()
    clear_undo(layout)
    layout_ops.map_from_canvas(item, canvas)
    assert item.extent().center().x() == pytest.approx(wanted.x(), abs=1)
    assert undo_count(layout) == 1
    item.zoomToExtent(QgsRectangle(0, 0, 5000, 5000))
    layout_ops.canvas_from_map(item, canvas)
    assert canvas.extent().center().x() == pytest.approx(item.extent().center().x(), abs=1)


def test_lock_layers_uses_the_canvas_and_styles_need_it(ribbon_in, layout, designer_iface):  # noqa: F811
    ribbon, _d = ribbon_in
    item = add_map(layout)
    layer = memory_layer()
    designer_iface.mapCanvas().setLayers([layer])
    select(layout, item)
    layers = control(ribbon, "layout_karte", "item_karte_layer_sperren")
    styles = control(ribbon, "layout_karte", "item_karte_stile_sperren")
    assert layers.isEnabled() and not styles.isEnabled()
    layers.editor.click()
    settle()
    assert item.keepLayerSet() and item.layers() == [layer]
    assert styles.isEnabled()
    styles.editor.click()
    settle()
    assert item.keepLayerStyles() and layer.id() in item.layerStyleOverrides()
    layers.editor.click()
    settle()
    assert not item.keepLayerSet() and item.layers() == []
    assert not item.keepLayerStyles() and item.layerStyleOverrides() == {}
    assert not styles.isEnabled()


def test_map_theme_excludes_locked_layers(layout, designer_iface):  # noqa: F811
    item = add_map(layout)
    layout_ops.set_keep_layers(item, True, designer_iface.mapCanvas())
    layout_ops.set_map_theme(item, "Thema")
    assert item.followVisibilityPreset() and item.followVisibilityPresetName() == "Thema"
    assert not item.keepLayerSet()
    layout_ops.set_map_theme(item, None)
    assert not item.followVisibilityPreset()
    layout_ops.set_map_theme(item, "Thema")
    layout_ops.set_keep_layers(item, True, designer_iface.mapCanvas())
    assert not item.followVisibilityPreset() and item.keepLayerSet()


def test_theme_menu_lists_project_themes_and_marks_the_current(ribbon_in, layout):
    ribbon, _d = ribbon_in
    item = add_map(layout)
    collection = QgsProject.instance().mapThemeCollection()
    collection.insert("Thema A", QgsMapThemeCollection.MapThemeRecord())
    item.setFollowVisibilityPreset(True)
    item.setFollowVisibilityPresetName("Thema A")
    select(layout, item)
    menu = layout_ops.map_theme_menu(ribbon.env, ribbon.logic.ribbon.commands["item_karte_thema"])
    assert isinstance(menu, QMenu)
    menu.aboutToShow.emit()
    entries = [a for a in menu.actions() if not a.isSeparator()]
    assert [a.isChecked() for a in entries] == [False, True]
    entries[0].trigger()
    assert not item.followVisibilityPreset()
    collection.removeMapTheme("Thema A")


def test_bookmark_menu_says_so_when_empty(ribbon_in, layout):
    ribbon, _d = ribbon_in
    select(layout, add_map(layout))
    menu = layout_ops.map_bookmarks_menu(ribbon.env, ribbon.logic.ribbon.commands["item_karte_lesezeichen"])
    menu.aboutToShow.emit()
    assert menu.actions()


def test_map_buttons_do_nothing_without_a_map(ribbon_in, layout):
    ribbon, _d = ribbon_in
    select(layout, add(layout, QgsLayoutItemLabel(layout)))
    clear_undo(layout)
    layout_ops.map_from_canvas_command(ribbon.env, None)()
    layout_ops.refresh_map_command(ribbon.env, None)()
    assert undo_count(layout) == 0


# Text

def test_label_text_font_and_alignment(ribbon_in, layout):
    ribbon, _d = ribbon_in
    item = add(layout, QgsLayoutItemLabel(layout))
    item.setText("Alt")
    clear_undo(layout)
    select(layout, item)
    text = control(ribbon, "layout_text", "item_text_inhalt")
    assert text.editor.text() == "Alt"
    text.editor.setText("Neu")
    text.editor.editingFinished.emit()
    settle()
    assert item.text() == "Neu" and undo_count(layout) == 1
    text.editor.editingFinished.emit()              # ohne Änderung kein Schritt
    assert undo_count(layout) == 1
    size = control(ribbon, "layout_text", "item_text_groesse")
    size.editor.setEditText("21,5")
    size.editor.lineEdit().editingFinished.emit()
    settle()
    assert item.textFormat().size() == 21.5
    color = control(ribbon, "layout_text", "item_text_farbe")
    color.editor.setColor(QColor("#ff0000"))
    settle()
    assert item.textFormat().color().name() == "#ff0000"
    horizontal = control(ribbon, "layout_text", "item_text_horizontal")
    horizontal.editor.setCurrentIndex(2)
    horizontal.editor.activated.emit(2)
    settle()
    assert item.hAlign() == Qt.AlignmentFlag.AlignRight
    vertical = control(ribbon, "layout_text", "item_text_vertikal")
    item.setVAlign(Qt.AlignmentFlag.AlignBottom)
    item.update()
    item.refresh()
    settle()
    vertical.refresh()
    assert vertical.editor.currentIndex() == 2


def test_multiline_text_is_read_only_and_keeps_its_line_breaks(ribbon_in, layout):
    ribbon, _d = ribbon_in
    item = add(layout, QgsLayoutItemLabel(layout))
    item.setText("Zeile 1\nZeile 2")
    select(layout, item)
    text = control(ribbon, "layout_text", "item_text_inhalt")
    assert text.editor.isReadOnly() and text.editor.toolTip()
    text.editor.editingFinished.emit()
    settle()
    assert item.text() == "Zeile 1\nZeile 2"


def test_dynamic_text_is_appended_and_names_maps(layout):
    item = add(layout, QgsLayoutItemLabel(layout))
    add_map(layout)
    item.setText("Stand: ")
    layout_ops.insert_dynamic_text(item, "[% @layout_page %]")
    assert item.text() == "Stand: [% @layout_page %]"
    texts = dict(layout_ops.dynamic_texts(layout))
    scale = next(v for k, v in texts.items() if "Karte 10" in k)
    assert "item_variables('Karte 10')" in scale
    item.setText(scale)
    assert item.currentText() and "%" not in item.currentText()


# Legende

def test_legend_values(ribbon_in, layout):
    ribbon, _d = ribbon_in
    first, second = add_map(layout), add_map(layout, 80)
    item = add(layout, QgsLayoutItemLegend(layout))
    item.setLinkedMap(first)
    clear_undo(layout)
    select(layout, item)
    linked = control(ribbon, "layout_legende", "item_legende_karte")
    assert linked.editor.currentItem() == first
    linked.editor.setItem(second)
    linked.editor.activated.emit(linked.editor.currentIndex())
    settle()
    assert item.linkedMap() == second
    control(ribbon, "layout_legende", "item_legende_filter").editor.click()
    settle()
    assert item.legendFilterByMapEnabled()
    was_auto = layout_ops.legend_auto_update(item)
    control(ribbon, "layout_legende", "item_legende_auto").editor.click()
    settle()
    assert layout_ops.legend_auto_update(item) != was_auto
    title = control(ribbon, "layout_legende", "item_legende_titel")
    title.editor.setText("Zeichenerklärung")
    title.editor.editingFinished.emit()
    settle()
    assert item.title() == "Zeichenerklärung"
    columns = control(ribbon, "layout_legende", "item_legende_spalten")
    columns.editor.setValue(3)
    settle()
    assert item.columnCount() == 3
    fit = control(ribbon, "layout_legende", "item_legende_anpassen")
    was_fit = item.resizeToContents()
    fit.editor.click()
    settle()
    assert item.resizeToContents() != was_fit
    assert undo_count(layout) == 6


# Maßstab

def test_scale_bar_values(ribbon_in, layout):
    ribbon, _d = ribbon_in
    linked = add_map(layout)
    item = add(layout, QgsLayoutItemScaleBar(layout))
    item.setLinkedMap(linked)
    item.applyDefaultSettings()
    clear_undo(layout)
    select(layout, item)
    style = control(ribbon, "layout_massstab", "item_massstab_stil")
    assert style.values == [s for s, _name in layout_ops.scalebar_styles()]
    style.editor.setCurrentIndex(style.values.index("Line Ticks Up"))
    style.editor.activated.emit(style.values.index("Line Ticks Up"))
    settle()
    assert item.style() == "Line Ticks Up"
    units = control(ribbon, "layout_massstab", "item_massstab_einheit")
    row = units.values.index(Qgis.DistanceUnit.Kilometers)
    units.editor.setCurrentIndex(row)
    units.editor.activated.emit(row)
    settle()
    assert item.units() == Qgis.DistanceUnit.Kilometers
    assert item.unitLabel() == "km"
    segments = control(ribbon, "layout_massstab", "item_massstab_segmente")
    segments.editor.setValue(4)
    settle()
    assert item.numberOfSegments() == 4
    length = control(ribbon, "layout_massstab", "item_massstab_laenge")
    length.editor.setValue(25)
    settle()
    assert item.unitsPerSegment() == 25
    assert undo_count(layout) == 4
    layout.undoStack().stack().undo()
    settle()
    assert item.unitsPerSegment() != 25


def test_scale_bar_map_units_are_listed(ribbon_in, layout):
    """Ohne Liste wäre das Feld bei Karteneinheiten leer, wie bei einem Maßstab ohne Vorgabe."""
    ribbon, _d = ribbon_in
    item = add(layout, QgsLayoutItemScaleBar(layout))
    item.setLinkedMap(add_map(layout))
    item.applyDefaultSize(Qgis.DistanceUnit.Unknown)
    select(layout, item)
    settle()
    units = control(ribbon, "layout_massstab", "item_massstab_einheit")
    assert item.units() == Qgis.DistanceUnit.Unknown
    assert units.editor.currentIndex() == units.values.index(Qgis.DistanceUnit.Unknown)
    assert units.editor.currentText() != ""


def test_segment_length_is_off_when_qgis_fits_the_segments(ribbon_in, layout):
    from qgis.core import QgsScaleBarSettings
    ribbon, _d = ribbon_in
    item = add(layout, QgsLayoutItemScaleBar(layout))
    item.setLinkedMap(add_map(layout))
    select(layout, item)
    length = control(ribbon, "layout_massstab", "item_massstab_laenge")
    assert length.isEnabled()
    item.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeMode.SegmentSizeFitWidth)
    length.refresh()
    assert not length.isEnabled()


def test_scale_bar_font_button(ribbon_in, layout):
    ribbon, _d = ribbon_in
    item = add(layout, QgsLayoutItemScaleBar(layout))
    select(layout, item)
    button = control(ribbon, "layout_massstab", "item_massstab_schrift")
    fmt = item.textFormat()
    fmt.setSize(23)
    button.editor.setTextFormat(fmt)
    settle()
    assert item.textFormat().size() == 23


# Bild

def test_picture_values(ribbon_in, layout):
    ribbon, _d = ribbon_in
    linked = add_map(layout)
    item = add(layout, QgsLayoutItemPicture(layout))
    clear_undo(layout)
    select(layout, item)
    source = control(ribbon, "layout_bild", "item_bild_quelle")
    source.editor.setText("C:/bilder/logo.png")
    source.editor.editingFinished.emit()
    settle()
    assert item.picturePath() == "C:/bilder/logo.png"
    mode = control(ribbon, "layout_bild", "item_bild_modus")
    row = mode.values.index(QgsLayoutItemPicture.ResizeMode.Clip)
    mode.editor.setCurrentIndex(row)
    mode.editor.activated.emit(row)
    settle()
    assert item.resizeMode() == QgsLayoutItemPicture.ResizeMode.Clip
    anchor = control(ribbon, "layout_bild", "item_bild_anker")
    row = anchor.values.index("LowerRight")
    anchor.editor.setCurrentIndex(row)
    anchor.editor.activated.emit(row)
    settle()
    assert item.pictureAnchor() == layout_ops.reference_point("LowerRight")
    rotate = control(ribbon, "layout_bild", "item_bild_karte")
    assert rotate.editor.currentItem() is None
    rotate.editor.setItem(linked)
    rotate.editor.activated.emit(rotate.editor.currentIndex())
    settle()
    assert item.linkedMap() == linked
    rotate.editor.setItem(None)
    rotate.editor.activated.emit(rotate.editor.currentIndex())
    settle()
    assert item.linkedMap() is None


# Form

def test_shape_type_radius_and_symbol(ribbon_in, layout):
    ribbon, _d = ribbon_in
    item = add(layout, QgsLayoutItemShape(layout))
    item.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    clear_undo(layout)
    select(layout, item)
    radius = control(ribbon, "layout_form", "item_form_radius")
    assert radius.isEnabled() and radius.editor.suffix() == " mm"
    radius.editor.setValue(4)
    settle()
    assert item.cornerRadius().length() == 4 and item.cornerRadius().units() == MM
    symbol = control(ribbon, "layout_form", "item_form_symbol")
    changed = item.symbol().clone()
    changed.setColor(QColor("#123456"))
    symbol.editor.setSymbol(changed)
    settle()
    assert item.symbol().color().name() == "#123456"
    shape = control(ribbon, "layout_form", "item_form_typ")
    row = shape.values.index(QgsLayoutItemShape.Shape.Ellipse)
    shape.editor.setCurrentIndex(row)
    shape.editor.activated.emit(row)
    settle()
    assert item.shapeType() == QgsLayoutItemShape.Shape.Ellipse
    assert not radius.isEnabled()                   # Eckenradius nur am Rechteck
    assert undo_count(layout) == 3


@pytest.mark.parametrize("factory", [
    lambda layout: QgsLayoutItemMarker(layout),
    lambda layout: QgsLayoutItemPolygon(QPolygonF(), layout),
    lambda layout: QgsLayoutItemPolyline(QPolygonF(), layout),
])
def test_marker_and_node_items_have_a_symbol_but_no_shape_type(ribbon_in, layout, factory):
    ribbon, _d = ribbon_in
    item = add(layout, factory(layout))
    select(layout, item)
    symbol = control(ribbon, "layout_form", "item_form_symbol")
    assert symbol.isEnabled() and symbol.editor.symbolType() == item.symbol().type()
    assert not control(ribbon, "layout_form", "item_form_typ").isEnabled()
    assert not control(ribbon, "layout_form", "item_form_radius").isEnabled()


# Tabelle

def test_table_values_are_written_to_the_multi_frame(ribbon_in, layout):
    ribbon, _d = ribbon_in
    first, second = memory_layer("Erster"), memory_layer("Zweiter")
    table, frame = add_table(layout)
    table.setVectorLayer(first)
    clear_undo(layout)
    select(layout, frame)
    layer = control(ribbon, "layout_tabelle", "item_tabelle_layer")
    assert layer.editor.currentLayer() == first
    layer.editor.setLayer(second)
    layer.editor.activated.emit(layer.editor.currentIndex())
    settle()
    assert table.vectorLayer() == second
    rows = control(ribbon, "layout_tabelle", "item_tabelle_zeilen")
    rows.editor.setValue(12)
    settle()
    assert table.maximumNumberOfFeatures() == 12
    filter_edit = control(ribbon, "layout_tabelle", "item_tabelle_filter")
    filter_edit.editor.setText("\"name\" = 'Objekt 1'")
    filter_edit.editor.editingFinished.emit()
    settle()
    assert table.filterFeatures() and table.featureFilter() == "\"name\" = 'Objekt 1'"
    filter_edit.editor.setText("")
    filter_edit.editor.editingFinished.emit()
    settle()
    assert not table.filterFeatures()
    visible = control(ribbon, "layout_tabelle", "item_tabelle_nur_karte")
    visible.editor.click()
    settle()
    assert table.displayOnlyVisibleFeatures()
    assert undo_count(layout) == 5
    layout.undoStack().stack().undo()
    settle()
    assert not table.displayOnlyVisibleFeatures()
    # Rückgängig an einem Multiframe hebt in QGIS die Auswahl auf, der Tab geht mit
    assert list(layout.selectedLayoutItems()) == [] and not ribbon.widget.is_tab_visible("layout_tabelle")
    select(layout, table.frame(0))
    visible = control(ribbon, "layout_tabelle", "item_tabelle_nur_karte")
    assert not visible.editor.isChecked()


def test_lists_do_not_write_when_only_the_project_changes(ribbon_in, layout):
    ribbon, _d = ribbon_in
    first = memory_layer("Erster")
    table, frame = add_table(layout)
    table.setVectorLayer(first)
    legend_map = add_map(layout)
    legend = add(layout, QgsLayoutItemLegend(layout))
    legend.setLinkedMap(legend_map)
    select(layout, frame)
    control(ribbon, "layout_tabelle", "item_tabelle_layer")
    clear_undo(layout)
    memory_layer("Weiterer")                         # die Layerliste ändert sich, nicht die Tabelle
    settle()
    assert undo_count(layout) == 0 and table.vectorLayer() == first
    select(layout, legend)
    control(ribbon, "layout_legende", "item_legende_karte")
    add_map(layout, 90)                              # die Kartenliste ändert sich, nicht die Legende
    settle()
    assert legend.linkedMap() == legend_map


def test_table_fields_are_off_for_a_fixed_table(ribbon_in, layout):
    ribbon, _d = ribbon_in
    _table, frame = add_table(layout, QgsLayoutItemManualTable)
    select(layout, frame)
    assert ribbon.widget.is_tab_visible("layout_tabelle")
    for command_id in ("item_tabelle_layer", "item_tabelle_zeilen", "item_tabelle_filter", "item_tabelle_nur_karte"):
        assert not control(ribbon, "layout_tabelle", command_id).isEnabled()


def test_table_layer_is_off_when_the_atlas_is_the_source(ribbon_in, layout):
    ribbon, _d = ribbon_in
    table, frame = add_table(layout)
    select(layout, frame)
    layer = control(ribbon, "layout_tabelle", "item_tabelle_layer")
    assert layer.isEnabled()
    table.setSource(QgsLayoutItemAttributeTable.ContentSource.AtlasFeature)
    layer.refresh()
    assert not layer.isEnabled()


def test_attributes_button_opens_the_panel_for_the_frame(ribbon_in, layout):
    ribbon, d = ribbon_in
    shown = []
    d.showItemOptions = lambda item, front: shown.append((item, front))
    _table, frame = add_table(layout)
    select(layout, frame)
    layout_ops.item_options_command(ribbon.env, None)()
    assert shown == [(frame, True)]


# Atlas

@pytest.fixture
def atlas_layout(layout):
    atlas = layout.atlas()
    atlas.setCoverageLayer(memory_layer("Abdeckung"))
    atlas.setPageNameExpression('"name"')
    atlas.setEnabled(True)
    return atlas


def atlas_control(ribbon):
    return control(ribbon, "atlas", "atlas_objekt")


def test_atlas_control_is_off_until_preview_runs(ribbon_in, atlas_layout):
    ribbon, d = ribbon_in
    box = atlas_control(ribbon)
    assert not box.isEnabled()
    d.atlas_preview = True
    atlas_layout.beginRender()
    atlas_layout.first()
    settle()
    assert box.isEnabled()
    assert [box.editor.itemText(n) for n in range(box.editor.count())] == ["Objekt 0", "Objekt 1", "Objekt 2"]
    assert box.editor.currentIndex() == 0
    d.atlas_preview = False
    atlas_layout.endRender()
    settle()
    assert not box.isEnabled()


def test_atlas_control_seeks_and_follows_the_buttons(ribbon_in, atlas_layout):
    ribbon, d = ribbon_in
    box = atlas_control(ribbon)
    d.atlas_preview = True
    atlas_layout.beginRender()
    atlas_layout.first()
    settle()
    box.editor.setCurrentIndex(2)
    box.editor.activated.emit(2)
    settle()
    assert atlas_layout.currentFeatureNumber() == 2
    atlas_layout.previous()                          # wie der Knopf „Zurück“
    settle()
    assert box.editor.currentIndex() == 1
    atlas_layout.endRender()
    d.atlas_preview = False
    settle()


def test_atlas_control_rereads_a_changed_feature_list(ribbon_in, layout, atlas_layout):
    ribbon, d = ribbon_in
    box = atlas_control(ribbon)
    d.atlas_preview = True
    atlas_layout.beginRender()
    atlas_layout.first()
    settle()
    assert box.editor.count() == 3
    atlas_layout.setCoverageLayer(memory_layer("Kleiner", 2))
    atlas_layout.updateFeatures()
    settle()
    assert box.editor.count() == 2
    atlas_layout.endRender()
    d.atlas_preview = False
    settle()


def test_teardown_leaves_atlas_and_selection_disconnected(ribbons, layout, atlas_layout):  # noqa: F811
    d = FakeDesigner(master=layout)
    d.window().show()
    settle()
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, add_map(layout))
    ribbons.closing(d)
    settle()
    assert len(ribbon.hub) == 0 and ribbon.selection is None
    atlas_layout.beginRender()
    atlas_layout.first()
    atlas_layout.endRender()
    settle()
    d.window().close()
    d.window().deleteLater()
    settle()
