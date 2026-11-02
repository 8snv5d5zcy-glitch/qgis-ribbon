"""Kontext-Tab Format im Layout-Fenster: Auswahl, Werte, Rückgängig, Abbau.

Das Layout ist ein echtes ``QgsPrintLayout`` mit echten Elementen; das Fenster ist
die Attrappe aus ``test_designer_ribbon``.
"""
import pytest
from qgis.core import (QgsLayoutItem, QgsLayoutItemShape, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout, QgsProject,
                       QgsUnitTypes)
from qgis.gui import QgsColorButton, QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QWidget

from qgis_ribbon.qgis_integration import layout_ops
from qgis_ribbon.qgis_integration.layout_ops import MIXED
from qgis_ribbon.qgis_integration.layout_state import LayoutSelection
from qgis_ribbon.qgis_integration.signals import SignalHub

from test_designer_ribbon import FakeDesigner, designer, designer_iface, registry, ribbons, settle  # noqa: F401

MM = QgsUnitTypes.LayoutUnit.LayoutMillimeters


def make_layout(count=2):
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    items = []
    for n in range(count):
        item = QgsLayoutItemShape(layout)
        layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(10 + 30 * n, 20, MM))
        item.attemptResize(QgsLayoutSize(25, 15 + 5 * n, MM))
        items.append(item)
    layout.undoStack().stack().clear()
    return layout, items


@pytest.fixture
def layout_designer():
    layout, items = make_layout()
    d = FakeDesigner(master=layout)
    d.window().show()
    settle()
    yield d, layout, items
    d.window().close()
    d.window().deleteLater()
    settle()


def select(layout, *items):
    layout.deselectAll()
    for item in items:
        item.setSelected(True)
    settle()


def control(ribbon, command_id):
    ribbon.widget.select_tab("layout_format")
    settle()
    return ribbon.widget.findChild(QWidget, "ribbon_control_" + command_id)


# layout_ops

def test_common_value_or_mixed():
    _layout, (a, b) = make_layout()
    assert layout_ops.common([a, b], lambda i: i.itemRotation()) == 0
    b.setItemRotation(30)
    assert layout_ops.common([a, b], lambda i: i.itemRotation()) is MIXED
    assert layout_ops.common([], lambda i: 1) is None


def test_change_of_several_items_is_one_undo_step():
    layout, (a, b) = make_layout()
    stack = layout.undoStack().stack()
    layout_ops.set_rotation([a, b], 45)
    assert (a.itemRotation(), b.itemRotation()) == (45, 45)
    assert stack.count() == 1
    stack.undo()
    assert (a.itemRotation(), b.itemRotation()) == (0, 0)


def test_position_and_size_keep_the_other_axis_and_the_unit():
    layout, (a, b) = make_layout()
    layout_ops.set_position([a, b], "x", 50)
    assert [i.positionWithUnits().x() for i in (a, b)] == [50, 50]
    assert [i.positionWithUnits().y() for i in (a, b)] == [20, 20]
    layout_ops.set_size([a, b], "w", 40)
    assert [i.sizeWithUnits().width() for i in (a, b)] == [40, 40]
    assert [i.sizeWithUnits().height() for i in (a, b)] == [15, 20]
    assert a.positionWithUnits().units() == MM and a.sizeWithUnits().units() == MM


def test_frame_background_opacity_and_blend_mode():
    layout, (a, b) = make_layout()
    layout_ops.set_frame_enabled([a, b], True)
    layout_ops.set_frame_color([a, b], QColor("#ff0000"))
    layout_ops.set_frame_width([a, b], 1.5)
    layout_ops.set_background_enabled([b], True)
    layout_ops.set_background_color([b], QColor("#00ff00"))
    layout_ops.set_opacity([a, b], 0.5)
    assert all(i.frameEnabled() and i.frameStrokeColor().name() == "#ff0000" for i in (a, b))
    assert a.frameStrokeWidth().length() == 1.5 and a.frameStrokeWidth().units() == MM
    assert not a.hasBackground() and b.hasBackground()
    assert b.backgroundColor().name() == "#00ff00"
    assert a.itemOpacity() == 0.5
    assert layout.undoStack().stack().count() >= 6


def test_reference_point_changes_what_x_and_y_mean():
    layout, (a, _b) = make_layout()
    layout_ops.set_reference_point([a], "LowerRight")
    assert a.referencePoint() == layout_ops.reference_point("LowerRight")
    assert a.positionWithUnits().x() == 35    # 10 + 25


def test_unit_suffix_only_for_equal_units():
    _layout, (a, b) = make_layout()
    assert layout_ops.unit_suffix([a, b], layout_ops.size_of) == " mm"
    b.attemptResize(QgsLayoutSize(1, 1, QgsUnitTypes.LayoutUnit.LayoutCentimeters))
    assert layout_ops.unit_suffix([a, b], layout_ops.size_of) == ""


# Auswahl

def test_selection_reports_count_and_values_once_per_event_loop_turn():
    layout, (a, b) = make_layout()
    seen, values = [], []
    hub = SignalHub()
    selection = LayoutSelection(layout, hub, lambda snap, events: seen.append(snap.selected_items))
    selection.subscribe(lambda items: values.append(len(items)))
    selection.start()
    assert seen == [0]
    a.setSelected(True)
    b.setSelected(True)
    settle()
    assert seen == [0, 2] and set(selection.items()) == {a, b}
    notified = selection.notifications
    a.attemptMove(QgsLayoutPoint(1, 2, MM))
    settle()
    assert selection.notifications > notified and seen == [0, 2]       # nur die Werte
    after = selection.notifications
    selection.stop()
    hub.disconnect_all()
    a.attemptMove(QgsLayoutPoint(3, 4, MM))
    settle()
    assert selection.notifications == after


def test_selection_leaves_no_connections_after_stop():
    layout, (a, _b) = make_layout()
    hub = SignalHub()
    selection = LayoutSelection(layout, hub)
    selection.start()
    a.setSelected(True)
    settle()
    selection.stop()
    hub.disconnect_all()
    assert len(hub) == 0 and len(selection.item_hub) == 0


# Ribbon

def test_format_tab_follows_the_selection_without_jumping(ribbons, layout_designer):
    d, layout, (a, b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    settle()
    assert not ribbon.widget.is_tab_visible("layout_format")
    ribbon.widget.select_tab("ansicht")
    select(layout, a)
    assert ribbon.widget.is_tab_visible("layout_format")
    assert ribbon.widget.current_tab() == "ansicht"
    select(layout, a, b)
    assert ribbon.widget.is_tab_visible("layout_format")
    select(layout)
    assert not ribbon.widget.is_tab_visible("layout_format")
    assert ribbon.widget.current_tab() == "ansicht"


def test_leaving_the_format_tab_when_the_selection_ends(ribbons, layout_designer):
    d, layout, (a, _b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a)
    ribbon.widget.select_tab("layout_format")
    select(layout)
    assert ribbon.widget.current_tab() == "layout"


def test_controls_show_values_and_blank_for_different_values(ribbons, layout_designer):
    d, layout, (a, b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a)
    x = control(ribbon, "item_x")
    breite = control(ribbon, "item_breite")
    hoehe = control(ribbon, "item_hoehe")
    assert x.editor.value() == 10 and x.editor.suffix() == " mm"
    assert breite.editor.value() == 25 and hoehe.editor.value() == 15
    select(layout, a, b)
    assert x.editor.value() == x.editor.minimum()           # 10 und 40: leer
    assert x.editor.text().strip() == ""
    assert breite.editor.value() == 25                      # beide 25
    assert hoehe.editor.text().strip() == ""


def test_typing_a_value_writes_all_items_as_one_undo_step(ribbons, layout_designer):
    d, layout, (a, b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a, b)
    breite = control(ribbon, "item_breite")
    breite.editor.setValue(60)
    settle()
    assert [i.sizeWithUnits().width() for i in (a, b)] == [60, 60]
    assert layout.undoStack().stack().count() == 1
    layout.undoStack().stack().undo()
    settle()
    assert [i.sizeWithUnits().width() for i in (a, b)] == [25, 25]
    assert breite.editor.value() == 25                      # das Ribbon folgt dem Rückgängig


def test_ribbon_follows_changes_made_elsewhere(ribbons, layout_designer):
    d, layout, (a, _b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a)
    drehung = control(ribbon, "item_drehung")
    a.setItemRotation(90)               # wie das Bedienfeld Elementeigenschaften
    settle()
    assert drehung.editor.value() == 90


def test_check_color_and_combo_controls(ribbons, layout_designer):
    d, layout, (a, b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    b.setFrameEnabled(True)
    select(layout, a, b)
    rahmen = control(ribbon, "item_rahmen")
    assert rahmen.editor.checkState() == Qt.CheckState.PartiallyChecked
    rahmen.editor.click()
    settle()
    assert a.frameEnabled() and b.frameEnabled()
    farbe = control(ribbon, "item_rahmenfarbe")
    farbe.editor.setColor(QColor("#0000ff"))
    settle()
    assert a.frameStrokeColor().name() == "#0000ff" == b.frameStrokeColor().name()
    bezug = control(ribbon, "item_bezugspunkt")
    bezug.editor.setCurrentIndex(8)
    bezug.editor.activated.emit(8)
    settle()
    assert a.referencePoint() == layout_ops.reference_point("LowerRight")
    assert isinstance(farbe.editor, QgsColorButton) and isinstance(bezug.editor, QComboBox)
    assert isinstance(rahmen.editor, QCheckBox) and isinstance(control(ribbon, "item_x").editor, QgsDoubleSpinBox)


def test_controls_are_disabled_without_selection(ribbons, layout_designer):
    d, layout, (a, _b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a)
    x = control(ribbon, "item_x")
    assert x.isEnabled()
    select(layout)
    assert not x.isEnabled()


def test_item_options_launcher_shows_the_panel(ribbons, layout_designer):
    d, layout, (a, _b) = layout_designer
    shown = []
    d.showItemOptions = lambda item, front: shown.append((item, front))
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a)
    layout_ops.item_options_command(ribbon.env, None)()
    assert shown == [(a, True)]


def test_teardown_disconnects_selection_and_leaves_items_untouched(ribbons, layout_designer):
    d, layout, (a, _b) = layout_designer
    ribbons.start()
    ribbons.opened(d)
    ribbon = ribbons.ribbons[d.window()]
    select(layout, a)
    ribbons.closing(d)
    settle()
    assert len(ribbon.hub) == 0 and ribbon.selection is None
    a.attemptMove(QgsLayoutPoint(77, 7, MM))     # kein Aufruf an ein abgebautes Ribbon
    select(layout)
    assert layout.undoStack().stack().count() == 0
    assert isinstance(a, QgsLayoutItem)
