"""Echte Qt-Ereignisse und echte Dialoge.

Die Abdeckung unter Qt6 zeigte: Viele Tests rufen Methoden direkt auf, die Wege über
``contextMenuEvent``, ``dragMoveEvent`` und statische Dialoge liefen dort nie. Genau da
unterscheiden sich Qt5 und Qt6. Hier gehen die Ereignisse durch ``QApplication.sendEvent``,
Fehler in überschriebenen Methoden meldet ``slot_errors`` aus ``tests/conftest.py``.
"""
import pytest
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QMimeData, QModelIndex, QPoint, QPointF, QRect, Qt, QTimer
from qgis.PyQt.QtGui import (QColor, QContextMenuEvent, QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent,
                             QDropEvent, QEnterEvent, QFont, QFontMetrics, QIcon, QImage, QKeyEvent, QMouseEvent,
                             QPainter, QPalette, QPixmap)
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (QApplication, QSizePolicy, QStyle, QStyleFactory, QStyleOption, QStyleOptionSlider,
                                 QStyleOptionViewItem)

from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration.map_tools import SelectByLineTool
from qgis_ribbon.qgis_integration.user_settings import UserSettings
from qgis_ribbon.ui import arrangement_menu, field_dialogs, ribbon_editor, theme
from qgis_ribbon.ui.editor_widgets import GroupCard, ItemTile, QuickStrip, TabChip, TabStrip
from qgis_ribbon.ui.layer_tree_style import ExclusiveRadioStyle
from qgis_ribbon.ui.ribbon_editor import MIME_TYPE
from qgis_ribbon.ui.ribbon_widget import RibbonPopup, RibbonTabBar

from test_anpassung import settle
from test_feinschliff import tree_with_groups
from test_ribbon_editor import open_editor, shipped  # noqa: F401 (Fixture)

NONE = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton
NO_BUTTON = Qt.MouseButton.NoButton
ACTIONS = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction


def close_active_soon(delay=50):
    """Schließt das nächste Menü oder den nächsten modalen Dialog wie der Nutzer (Esc, Abbrechen)."""
    def close():
        popup = QApplication.activePopupWidget()
        modal = QApplication.activeModalWidget()
        if popup is not None:
            seen.append(type(popup).__name__)
            popup.close()
        elif modal is not None:
            seen.append(type(modal).__name__)
            modal.reject()
        else:
            QTimer.singleShot(delay, close)

    seen = []
    QTimer.singleShot(delay, close)
    return seen


def test_context_menu_event_opens_the_menu(shipped):  # noqa: F811
    seen = close_active_soon()
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(105, 105))
    QApplication.sendEvent(shipped.widget, event)
    settle()
    assert seen == ["QMenu"]


def test_context_menu_event_in_the_popup(shipped, monkeypatch):  # noqa: F811
    popup = RibbonPopup(shipped.widget)
    calls = []
    monkeypatch.setattr(shipped.widget, "show_context_menu", lambda pos, widget: calls.append((pos, widget)))
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(105, 105))
    QApplication.sendEvent(popup, event)
    assert calls[0][0] == QPoint(105, 105)
    popup.deleteLater()


def test_tab_bar_hover(shipped):  # noqa: F811
    bar = shipped.widget.findChild(RibbonTabBar)
    bar.resize(800, 30)
    settle()
    inside = bar.tabRect(0).center()
    QApplication.sendEvent(bar, QMouseEvent(QEvent.Type.MouseMove, QPointF(inside), NO_BUTTON, NO_BUTTON, NONE))
    assert bar._hover == 0
    QApplication.sendEvent(bar, QEvent(QEvent.Type.Leave))
    assert bar._hover == -1


def _mime(text):
    data = QMimeData()
    data.setData(MIME_TYPE, text.encode("utf-8"))
    return data


def _send_drag(widget, data, point):
    """Der ganze Ablauf über einem Ziel, wie ihn Qt beim Ziehen sendet (ohne Ablegen)."""
    enter = QDragEnterEvent(point, ACTIONS, data, LEFT, NONE)
    QApplication.sendEvent(widget, enter)
    move = QDragMoveEvent(point, ACTIONS, data, LEFT, NONE)
    QApplication.sendEvent(widget, move)
    QApplication.sendEvent(widget, QDragLeaveEvent())
    settle()


def test_drag_events_reach_every_target(shipped):  # noqa: F811
    dlg = open_editor(shipped.widget)
    try:
        data = _mime("command:speichern")
        dlg.begin_drag(("command", "speichern"))
        targets = [dlg.findChild(GroupCard), dlg.preview.new_card, dlg.preview, dlg.findChild(TabChip),
                   dlg.findChild(TabStrip), dlg.findChild(QuickStrip), dlg.palette_box.list]
        assert all(target is not None for target in targets)
        for target in targets:
            _send_drag(target, data, QPoint(4, 4))
        dlg.end_drag()
    finally:
        dlg.close()
        settle()


def test_drop_event_runs_through_the_card(shipped):  # noqa: F811
    dlg = open_editor(shipped.widget)
    try:
        data = _mime("command:speichern")
        dlg.begin_drag(("command", "speichern"))
        card = dlg.findChild(GroupCard)
        event = QDropEvent(QPointF(card.width() - 2, 10), ACTIONS, data, LEFT, NONE)
        QApplication.sendEvent(card, event)
        settle()
        dlg.end_drag()
    finally:
        dlg.close()
        settle()


def test_mouse_on_a_tile_selects_and_starts_the_drag(shipped, monkeypatch):  # noqa: F811
    dlg = open_editor(shipped.widget)
    try:
        started = []
        monkeypatch.setattr(dlg, "start_drag", started.append)
        tile = dlg.findChild(ItemTile)
        QApplication.sendEvent(tile, QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(2, 2)))
        assert tile._hover
        QTest.mousePress(tile, LEFT, NONE, QPoint(2, 2))
        assert tile.selected
        far = QPointF(2 + 4 * QApplication.startDragDistance(), 2)
        QApplication.sendEvent(tile, QMouseEvent(QEvent.Type.MouseMove, far, LEFT, LEFT, NONE))
        assert started == [tile]
        QTest.mouseRelease(tile, LEFT, NONE, QPoint(2, 2))
        QApplication.sendEvent(tile, QEvent(QEvent.Type.Leave))
        assert not tile._hover
    finally:
        dlg.close()
        settle()


class _NoLoopDrag(QDrag):
    """Echtes QDrag bis auf die Ereignisschleife des Ziehens (offscreen endet sie nicht)."""

    def exec(self, *_args):
        return Qt.DropAction.MoveAction


def test_start_drag_builds_the_real_drag(shipped, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ribbon_editor, "QDrag", _NoLoopDrag)
    dlg = open_editor(shipped.widget)
    try:
        dlg.start_drag(dlg.findChild(ItemTile))
        settle()
        assert dlg._drag is None
        palette = dlg.palette_box.list
        palette.setCurrentRow(0)
        item = palette.currentItem()
        assert item is not None
        palette.startDrag(Qt.DropAction.MoveAction)
        settle()
        assert dlg._drag is None
    finally:
        dlg.close()
        settle()


def test_palette_keys(shipped):  # noqa: F811
    dlg = open_editor(shipped.widget)
    try:
        palette = dlg.palette_box.list
        palette.setCurrentRow(0)
        QTest.keyClick(palette, Qt.Key.Key_Down)
        settle()
    finally:
        dlg.close()
        settle()


def test_search_keys_and_completer_signal(shipped):  # noqa: F811
    search = shipped.widget.search
    QTest.keyClicks(search, "Spei")
    settle()
    assert search.text() == "Spei"
    assert search.model.rowCount() > 0
    # Überladenes Signal: unter PyQt6 und PyQt5 mit QModelIndex wählbar
    search.completer.activated[QModelIndex].emit(QModelIndex())
    QTest.keyClick(search, Qt.Key.Key_Escape)
    settle()
    assert search.text() == ""


@pytest.fixture
def plain_palette():
    app = QApplication.instance()
    before = QPalette(app.palette())
    yield app
    app.setPalette(before)
    settle()


def _palette_with_window(color):
    palette = QPalette(QApplication.instance().palette())
    palette.setColor(QPalette.ColorRole.Window, QColor(color))
    return palette


def test_automatic_follows_a_real_palette_change(plain_palette, settings):
    plain_palette.setPalette(_palette_with_window("#ffffff"))
    settle()
    manager = theme.ThemeManager(UserSettings(settings))
    try:
        manager.set("mode", "auto")
        assert manager.tokens["mode"] == "hell"
        plain_palette.setPalette(_palette_with_window("#202020"))
        settle()
        assert manager.tokens["mode"] == "dunkel"
    finally:
        manager.stop()


def test_stopped_manager_no_longer_follows(plain_palette, settings):
    plain_palette.setPalette(_palette_with_window("#ffffff"))
    settle()
    manager = theme.ThemeManager(UserSettings(settings))
    manager.set("mode", "auto")
    manager.stop()
    plain_palette.setPalette(_palette_with_window("#202020"))
    settle()
    assert manager.tokens["mode"] == "hell"


def test_high_contrast_tokens_come_from_the_palette():
    palette = _palette_with_window("#000000")
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#112233"))
    tokens = theme.palette_tokens(palette)
    assert tokens["win"] == "#000000" and tokens["acc"] == "#112233"
    assert tokens["mode"] == "dunkel" and tokens["accent"] == "system"


@pytest.mark.parametrize("call, expected", [
    (lambda: arrangement_menu.ask_name(None, "T", "L", "x"), None),
    (lambda: arrangement_menu.confirm(None, "T", "F"), False),
    (lambda: arrangement_menu.ask_save_path(None, "a.json"), None),
    (lambda: arrangement_menu.ask_open_path(None), None),
    (lambda: ribbon_editor.confirm_discard(None), False),
    (lambda: ribbon_editor.confirm_remove_tab(None, "Tab"), False),
], ids=["name", "frage", "speichern", "oeffnen", "verwerfen", "tab_loeschen"])
def test_real_dialogs_cancel_cleanly(call, expected):
    # Statische Dialoge von Qt, so wie das Plugin sie aufruft; nativ gibt es offscreen nicht
    seen = close_active_soon()
    assert call() == expected
    settle()
    assert seen


def test_inform_and_field_confirmation(qgis_app):
    class Layer:
        def name(self):
            return "L"

    close_active_soon()
    assert arrangement_menu.inform(None, "T", "I") is None
    close_active_soon()
    assert arrangement_menu.inform(None, "T", "W", warning=True) is None
    close_active_soon()
    assert field_dialogs.confirm_direct(None, Layer()) is False
    settle()


def test_map_tool_keys_and_double_click(fake_iface):
    canvas = fake_iface.mapCanvas()
    tool = SelectByLineTool(canvas, lambda: None)
    press = QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonPress, QPoint(5, 5), LEFT, LEFT, NONE)
    tool.canvasPressEvent(press)
    assert len(tool._points) == 1
    backspace = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, NONE)
    tool.keyPressEvent(backspace)
    assert backspace.isAccepted() and not tool._points
    other = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, NONE)
    tool.keyPressEvent(other)
    assert not other.isAccepted()
    tool.canvasPressEvent(press)
    double = QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonDblClick, QPoint(5, 5), LEFT, LEFT, NONE)
    tool.canvasDoubleClickEvent(double)
    assert not tool._points
    tool.close()


def test_style_passes_everything_on(qgis_app):
    base = QStyleFactory.create("Fusion")
    style = ExclusiveRadioStyle(base, lambda _index: True)
    image = QImage(60, 60, QImage.Format.Format_ARGB32)
    pixmap = QPixmap(8, 8)
    painter = QPainter(image)
    try:
        rect = QRect(0, 0, 40, 40)
        slider = QStyleOptionSlider()
        slider.rect = rect
        control = QStyle.ComplexControl.CC_Slider
        style.drawComplexControl(control, slider, painter)
        assert style.subControlRect(control, slider, QStyle.SubControl.SC_SliderHandle) is not None
        assert style.hitTestComplexControl(control, slider, QPoint(1, 1)) is not None
        standard = QStyle.StandardPixmap.SP_DialogOkButton
        assert not style.standardIcon(standard).isNull()
        assert not style.standardPixmap(standard).isNull()
        assert style.generatedIconPixmap(QIcon.Mode.Disabled, pixmap, QStyleOption()) is not None
        assert isinstance(style.standardPalette(), QPalette)
        button = QSizePolicy.ControlType.PushButton
        assert isinstance(style.layoutSpacing(button, button, Qt.Orientation.Horizontal), int)
        left = int(Qt.AlignmentFlag.AlignLeft.value) if hasattr(Qt.AlignmentFlag.AlignLeft, "value") else 1
        assert style.itemPixmapRect(rect, left, pixmap) is not None
        assert style.itemTextRect(QFontMetrics(QFont()), rect, left, True, "x") is not None
        style.drawItemPixmap(painter, rect, left, pixmap)
        palette = QPalette()
        style.drawItemText(painter, rect, left, palette, True, "x")
        style.drawItemText(painter, rect, left, palette, True, "x", QPalette.ColorRole.WindowText)
    finally:
        painter.end()


def test_primitive_and_control_draw_radios_in_all_variants(qgis_app):
    view = tree_with_groups()
    model = view.model()
    drawn = []
    style = ExclusiveRadioStyle(QStyleFactory.create("Fusion"), lambda _index: True)
    original = style.draw_radio
    style.draw_radio = lambda *args: (drawn.append(args[1]), original(*args))
    image = QImage(200, 60, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 100, 20)
        option.index = model.index(0, 0)
        option.features = QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        option.checkState = Qt.CheckState.Checked
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, option, painter)
        assert drawn == [option.rect]
        # Hintergrund: eigener Pinsel, wechselnde Zeilen, sonst Grundfarbe
        option.features = (QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
                           | QStyleOptionViewItem.ViewItemFeature.Alternate)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter)
        option.backgroundBrush = QColor("#ff0000")
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter)
        assert len(drawn) == 3
        # Ohne Kontrollkästchen und ohne gültigen Index bleibt es bei QGIS
        option.features = QStyleOptionViewItem.ViewItemFeature.None_
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, option, painter)
        option.index = QModelIndex()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, option, painter)
        assert len(drawn) == 3
    finally:
        painter.end()
        view.deleteLater()


def test_failing_exclusive_check_does_not_break_drawing(qgis_app):
    view = tree_with_groups()
    model = view.model()

    def fails(_index):
        raise ValueError("kaputt")

    style = ExclusiveRadioStyle(QStyleFactory.create("Fusion"), fails)
    option = QStyleOptionViewItem()
    option.index = model.index(0, 0)
    option.features = QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    assert style._exclusive(option) is False
    view.deleteLater()


def test_plugin_survives_a_real_context_menu_after_rebuild(fake_iface, settings):
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    try:
        plugin.request_rebuild()
        settle()
        seen = close_active_soon()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(2, 2), QPoint(2, 2))
        QApplication.sendEvent(plugin.widget, event)
        settle()
        assert seen == ["QMenu"]
    finally:
        plugin.unload()
        settle()
