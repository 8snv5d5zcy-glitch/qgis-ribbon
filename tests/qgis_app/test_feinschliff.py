"""Feinschliff: Kreise in exklusiven Gruppen, Plugin-Menüs unter dem Knopf, Deckkraft, Trenner."""
import pytest
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QPoint, QRect, Qt
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (QAction, QMenu, QProxyStyle, QSlider, QStyle, QStyleFactory,
                                 QToolBar, QToolButton, QTreeView, QWidget)

from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.ui import menu_anchor, tab_page
from qgis_ribbon.ui.controls.custom import OPACITY_SLIDER_MIN, OpacityControl
from qgis_ribbon.ui.layer_tree_style import (ExclusiveRadioStyle, LayerTreeRadios,
                                             layer_tree_exclusive, own_style)

EXCLUSIVE = Qt.ItemDataRole.UserRole + 1


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)
    QgsApplication.processEvents()


class Recorder(QProxyStyle):
    """Zeichnet wie Fusion und merkt sich gezeichnete Optionsfelder (Zeile)."""

    def __init__(self):
        QProxyStyle.__init__(self, QStyleFactory.create("Fusion"))
        self.radios = []

    def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802 (Qt)
        if element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
            self.radios.append(QRect(option.rect))
        QProxyStyle.drawPrimitive(self, element, option, painter, widget)


def tree_with_groups():
    model = QStandardItemModel()
    for name, exclusive in (("Exklusiv", True), ("Normal", False)):
        parent = QStandardItem(name)
        parent.setData(exclusive, EXCLUSIVE)
        for i in range(2):
            child = QStandardItem("%s %d" % (name, i))
            child.setCheckable(True)
            child.setCheckState(Qt.CheckState.Checked if i == 0 else Qt.CheckState.Unchecked)
            parent.appendRow(child)
        model.appendRow(parent)
    view = QTreeView()
    view.setModel(model)
    view.expandAll()
    view.resize(300, 200)
    return view


def exclusive_parent(index):
    return bool(index.parent().data(EXCLUSIVE))


def check_rect(view, row, parent_row):
    index = view.model().index(row, 0, view.model().index(parent_row, 0))
    rect = view.visualRect(index)
    return index, rect


@pytest.mark.parametrize("stylesheet", ["", "QTreeView::item { padding: 1px; }"
                                            "QTreeView::item:hover { background: #eeeeee; }"])
def test_exclusive_children_get_radio_buttons(qgis_app, stylesheet):
    view = tree_with_groups()
    view.setStyleSheet(stylesheet)
    view.setStyle(QStyleFactory.create("Fusion"))
    view.show()
    plain = view.viewport().grab().toImage()
    recorder = Recorder()
    view.setStyle(ExclusiveRadioStyle(recorder, exclusive_parent))
    image = view.viewport().grab().toImage()
    # Kreise genau bei den Einträgen der exklusiven Gruppe (Zeilen 0 und 1 unter „Exklusiv“)
    rows = sorted({r.center().y() for r in recorder.radios})
    exclusive = [view.visualRect(view.model().index(i, 0, view.model().index(0, 0))) for i in range(2)]
    normal = [view.visualRect(view.model().index(i, 0, view.model().index(1, 0))) for i in range(2)]
    assert len(rows) == 2 and all(any(r.contains(QPoint(r.center().x(), y)) for r in exclusive)
                                  for y in rows)

    def crop(img, rect):
        return img.copy(QRect(rect.left(), rect.top(), 24, rect.height()))
    # Exklusive Einträge sehen anders aus als vorher, normale unverändert
    for rect in exclusive:
        assert crop(image, rect) != crop(plain, rect)
    for rect in normal:
        assert crop(image, rect) == crop(plain, rect)
    view.close()


def test_radio_state_follows_check_state(qgis_app):
    style = ExclusiveRadioStyle(QStyleFactory.create("Fusion"), lambda _i: True)
    from qgis.PyQt.QtWidgets import QStyleOptionViewItem
    opt = QStyleOptionViewItem()
    opt.state = QStyle.StateFlag.State_Enabled
    opt.checkState = Qt.CheckState.Checked
    assert style.radio_option(opt, QRect(0, 0, 13, 13)).state & QStyle.StateFlag.State_On
    opt.checkState = Qt.CheckState.Unchecked
    assert style.radio_option(opt, QRect(0, 0, 13, 13)).state & QStyle.StateFlag.State_Off


def test_layer_tree_exclusive_reads_the_parent_group(fake_iface):
    view = fake_iface.layerTreeView()
    root = QgsProject.instance().layerTreeRoot()
    group = root.addGroup("Hintergrund")
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "Punkte", "memory")
    QgsProject.instance().addMapLayer(layer, False)
    node = group.addLayer(layer)
    try:
        check = layer_tree_exclusive(view)
        index = view.node2index(node)
        assert not check(index)
        group.setIsMutuallyExclusive(True)
        assert check(index)
        assert not check(view.node2index(group))     # die Gruppe selbst hängt an der Wurzel
    finally:
        root.removeChildNode(group)
        QgsProject.instance().removeMapLayer(layer.id())


def test_plugin_sets_and_restores_layer_tree_style(fake_iface, settings):
    view = fake_iface.layerTreeView()
    settle()
    before = own_style(view)
    children = [c.metaObject().className() for c in view.findChildren(QStyle)]
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    mw = fake_iface.mainWindow()
    old = mw.styleSheet()
    try:
        assert isinstance(own_style(view), ExclusiveRadioStyle)
        assert own_style(view).base is before
        # Ein Stylesheet am Hauptfenster (Gesamtbild, Hell/Dunkel) behält den Stil
        mw.setStyleSheet("QTreeView { color: red; }")
        settle()
        assert view.style().metaObject().className() == "QStyleSheetStyle"
        assert isinstance(own_style(view), ExclusiveRadioStyle)
    finally:
        mw.setStyleSheet(old)
        plugin.unload()
        settle()
    assert own_style(view) is before
    assert [c.metaObject().className() for c in view.findChildren(QStyle)] == children
    assert len(plugin.hub) == 0


def test_radios_without_own_style_restore_application_style(qgis_app):
    view = QTreeView()
    radios = LayerTreeRadios(view, lambda _i: False)
    radios.install()
    assert isinstance(own_style(view), ExclusiveRadioStyle)
    radios.restore()
    assert view.style() is QgsApplication.style()
    settle()


# Plugin-Menüs unter dem Ribbon-Knopf
class MenuPlugin(object):
    """Ersatz-Plugin: öffnet beim Auslösen sein Menü selbst am eigenen Leistenknopf."""

    def __init__(self, mw, blocking=False):
        self.toolbar = QToolBar("Ersatz-Plugin", mw)
        self.toolbar.setObjectName("ErsatzPluginLeiste")
        mw.addToolBar(self.toolbar)
        self.menu = QMenu(mw)
        for text in ("Deutschland", "Bundesländer", "Einstellungen"):
            self.menu.addAction(text)
        self.action = QAction("Katalog", mw)
        self.action.setObjectName("ersatz_katalog")
        self.action.triggered.connect(self.show_menu)
        self.toolbar.addAction(self.action)
        self.blocking = blocking
        self.shown_at = None

    def show_menu(self):
        button = self.toolbar.widgetForAction(self.action)
        pos = button.mapToGlobal(button.rect().bottomLeft())
        if self.blocking:
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(0, self.close_menu)
            self.menu.exec(pos)
        else:
            self.menu.popup(pos)
            self.shown_at = self.menu.pos()

    def close_menu(self):
        self.shown_at = self.menu.pos()
        self.menu.close()

    def remove(self, mw):
        mw.removeToolBar(self.toolbar)
        self.toolbar.setParent(None)
        self.toolbar.deleteLater()
        self.menu.deleteLater()
        self.action.deleteLater()


def ribbon_button(widget, tab, text):
    widget.select_tab(tab)
    settle()
    for b in widget.findChildren(QToolButton):
        act = b.defaultAction()
        if act is not None and act.objectName().startswith("ribbon_") and b.isVisible() \
                and act.text() == text:
            return b
    return None


@pytest.mark.parametrize("blocking", [False, True])
def test_plugin_menu_opens_under_ribbon_button(fake_iface, settings, blocking):
    mw = fake_iface.mainWindow()
    plugin_ui = MenuPlugin(mw, blocking=blocking)
    settle()
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    try:
        assert plugin_ui.toolbar.isHidden()
        button = ribbon_button(plugin.widget, "erweiterungen", "Katalog")
        assert button is not None
        button.defaultAction().trigger()
        settle()
        below = button.mapToGlobal(QPoint(0, button.height()))
        assert plugin_ui.shown_at is not None
        assert abs(plugin_ui.shown_at.x() - below.x()) <= 1
        assert abs(plugin_ui.shown_at.y() - below.y()) <= 1 or plugin_ui.shown_at.y() < below.y()
        plugin_ui.menu.close()
    finally:
        plugin.unload()
        plugin_ui.remove(mw)
        settle()


def test_anchor_moves_only_a_menu_shown_first_and_only_once(qgis_app):
    from qgis.PyQt.QtWidgets import QDialog
    host = QWidget()
    host.setGeometry(100, 100, 200, 50)
    host.show()
    dialog = QDialog()
    menu = QMenu()
    menu.addAction("Eintrag")
    far = QPoint(400, 300)
    menu.popup(far)
    reference = menu.pos()
    menu.close()
    with menu_anchor.anchored(host) as watcher:
        dialog.show()                   # zuerst ein Dialog: nichts verschieben
        menu.popup(far)
    assert watcher.moved is None and menu.pos() == reference
    menu.close()
    dialog.close()
    with menu_anchor.anchored(host) as watcher:
        menu.popup(far)
    assert watcher.moved is menu
    assert menu.pos() == host.mapToGlobal(QPoint(0, host.height()))
    menu.close()
    menu.popup(far)                     # nach dem Klick ist der Filter weg
    assert menu.pos() == reference
    menu.close()
    host.close()


# Deckkraft und Trenner
def test_opacity_slider_is_wide_enough(fake_iface, settings):
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    try:
        for tab_id in plugin.widget.tab_ids():
            plugin.widget.targets(tab_id)      # alle Tabs aufbauen (sonst erst beim Öffnen)
        controls = plugin.widget.findChildren(OpacityControl)
        assert len(controls) >= 4              # Vektor, Raster, Gruppe, weitere Layerarten
        assert controls
        for c in controls:
            slider = c.editor.findChild(QSlider)
            assert slider.minimumWidth() >= OPACITY_SLIDER_MIN
            assert c.editor.width() >= 200
    finally:
        plugin.unload()
        settle()


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 2.0])
def test_dividers_are_whole_device_pixels(ratio):
    pixels = tab_page.divider_pixels(ratio)
    assert pixels == (2 if ratio >= 1.5 else 1)
    for left in (37, 120, 251):
        x = tab_page.divider_x(left, 5, ratio, pixels)
        first = x * ratio - pixels / 2.0
        assert abs(first - round(first)) < 1e-6           # beginnt auf einer Pixelkante
        assert abs(x - (left - 2.5)) <= 1.0                # mitten in der Lücke


def test_group_divider_token_is_stronger_than_plain_dividers():
    from qgis_ribbon.core import theme_tokens
    themes = theme_tokens.load()
    for mode in theme_tokens.MODES:
        t = themes.tokens(mode)
        assert theme_tokens.contrast(t["gdiv"], t["surf"]) >= 1.5 * theme_tokens.contrast(t["div"], t["surf"])
