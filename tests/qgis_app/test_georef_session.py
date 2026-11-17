"""Georeferenzieren in der Karte: Sitzung, Befehle, Kartenwerkzeuge, Projekt und Entladen."""
import glob
import os
import tempfile

import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsRectangle
from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QKeyEvent, QMouseEvent
from qgis.PyQt.QtWidgets import QApplication

from qgis_ribbon.core import georef
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration import georef_commands, georef_ops, georef_session

WIDTH, HEIGHT = 40, 30
LEFT = Qt.MouseButton.LeftButton
NO_BUTTON = Qt.MouseButton.NoButton
NO_MODS = Qt.KeyboardModifier.NoModifier


def settle():
    for _ in range(3):
        QApplication.processEvents()


def make_image(path, gt=None):
    from osgeo import gdal
    ds = gdal.GetDriverByName("GTiff").Create(path, WIDTH, HEIGHT, 1, gdal.GDT_Byte)
    if gt is not None:
        ds.SetGeoTransform(gt)
    ds.GetRasterBand(1).Fill(120)
    ds = None
    return path


@pytest.fixture
def image(tmp_path):
    return make_image(str(tmp_path / "blatt.tif"))


@pytest.fixture
def project():
    prj = QgsProject.instance()
    prj.clear()
    yield prj
    georef_session.uninstall()
    prj.clear()


@pytest.fixture
def canvas(fake_iface):
    c = fake_iface.mapCanvas()
    c.resize(400, 300)
    c.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    c.setExtent(QgsRectangle(1000, 2000, 1400, 2300))
    c.show()
    settle()
    return c


def temp_dirs():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), georef_session.TEMP_PREFIX + "*")))


def project_state(prj):
    root = prj.layerTreeRoot()
    layers = sorted((lay.id(), lay.source(), root.findLayer(lay.id()).itemVisibilityChecked())
                    for lay in prj.mapLayers().values())
    return layers, [node.layerId() for node in root.findLayers()]


def load(fake_iface, settings):
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    return plugin


def visible(plugin):
    return {t.id for t in plugin.ribbon.tabs if t.contextual and plugin.widget.is_tab_visible(t.id)}


def command(plugin, cid):
    return plugin.resolver.resolve(plugin.ribbon.commands[cid]).action


def test_start_and_cancel_leave_project_as_before(fake_iface, canvas, project, image, layers):
    original = QgsRasterLayer(image, "Blatt")
    project.addMapLayer(layers["vector"])
    project.addMapLayer(original)
    before, dirs = project_state(project), temp_dirs()
    manager = georef_session.install(fake_iface)
    session = manager.start(image, original)
    settle()
    root = project.layerTreeRoot()
    assert root.findLayers()[0].layerId() == session.layer_id
    assert georef_session.is_work_layer(session.layer) and georef_session.active()
    assert session.layer.name().startswith("blatt")
    assert not root.findLayer(original.id()).itemVisibilityChecked()
    assert os.path.exists(session.vrt)
    # Ohne eigene Georeferenz liegt das Bild mittig im Ausschnitt
    extent = session.layer.extent()
    assert canvas.extent().contains(extent)
    assert extent.center().x() == pytest.approx(1200) and extent.center().y() == pytest.approx(2150)
    assert session.layer.crs() == canvas.mapSettings().destinationCrs()
    manager.cancel()
    settle()
    assert project_state(project) == before
    assert temp_dirs() == dirs and not georef_session.active()


def test_image_with_georeference_starts_there(fake_iface, canvas, project, tmp_path):
    gt = (1100.0, 2.0, 0.0, 2250.0, 0.0, -2.0)
    path = make_image(str(tmp_path / "verortet.tif"), gt)
    session = georef_session.install(fake_iface).start(path)
    assert session.gt == pytest.approx(gt)
    assert georef_ops.read_vrt_geotransform(session.vrt) == pytest.approx(gt)
    # Das Original bleibt unberührt
    assert georef_ops.image_size(path)[2] == pytest.approx(gt)


def test_session_in_ribbon(fake_iface, settings, canvas, project, image):
    plugin = load(fake_iface, settings)
    try:
        assert "georeferenzieren" not in visible(plugin)
        assert not command(plugin, "georef_anpassen").isEnabled()
        georef_commands.start(plugin.resolver.env, path=image)
        settle()
        assert "georeferenzieren" in visible(plugin)
        assert plugin.widget.current_tab() == "georeferenzieren"
        session = georef_session.manager().session
        gt0 = session.gt
        assert command(plugin, "georef_anpassen").isEnabled()
        assert not command(plugin, "georef_rueckgaengig").isEnabled()

        command(plugin, "georef_rechts").trigger()
        turned = georef.rotate90(gt0, WIDTH, HEIGHT, clockwise=True)
        assert session.gt == pytest.approx(turned)
        assert georef_ops.read_vrt_geotransform(session.vrt) == pytest.approx(turned)
        command(plugin, "georef_waagerecht").trigger()
        assert session.gt == pytest.approx(georef.flip_horizontal(turned, WIDTH, HEIGHT))
        command(plugin, "georef_senkrecht").trigger()
        command(plugin, "georef_links").trigger()

        undo, redo = command(plugin, "georef_rueckgaengig"), command(plugin, "georef_wiederholen")
        for _ in range(4):
            assert undo.isEnabled()
            undo.trigger()
        assert session.gt == pytest.approx(gt0) and not undo.isEnabled() and redo.isEnabled()
        redo.trigger()
        assert session.gt == pytest.approx(turned)

        canvas.setExtent(QgsRectangle(0, 0, 80, 60))
        settle()
        command(plugin, "georef_anpassen").trigger()
        fitted = georef.fit_to_extent(WIDTH, HEIGHT, georef_session.canvas_extent(canvas))
        assert session.gt == pytest.approx(fitted)
        assert session.layer.extent().center().x() == pytest.approx(canvas.extent().center().x())

        show = command(plugin, "georef_bild")
        assert show.isChecked()
        show.trigger()
        assert not session.image_visible() and not show.isChecked()
        show.trigger()
        assert session.image_visible()

        command(plugin, "georef_abbrechen").trigger()
        settle()
        assert not georef_session.active() and "georeferenzieren" not in visible(plugin)
        assert not command(plugin, "georef_anpassen").isEnabled()
        assert not project.mapLayers()
    finally:
        plugin.unload()
        settle()


def test_opacity_control_follows_work_layer(fake_iface, settings, canvas, project, image, layers):
    from qgis.PyQt.QtWidgets import QWidget
    project.addMapLayer(layers["vector"])
    plugin = load(fake_iface, settings)
    try:
        georef_commands.start(plugin.resolver.env, path=image)
        settle()
        fake_iface.set_active_layer(layers["vector"])   # anderer Layer aktiv: Tab und Regler bleiben
        settle()
        assert "georeferenzieren" in visible(plugin)
        plugin.widget.select_tab("georeferenzieren")
        settle()
        control = plugin.widget.findChild(QWidget, "ribbon_control_georef_deckkraft")
        assert control is not None and control.isEnabled()
        control.editor.setOpacity(0.4)
        session = georef_session.manager().session
        assert session.layer.renderer().opacity() == pytest.approx(0.4)
        assert layers["vector"].opacity() == pytest.approx(1.0)
        georef_session.manager().cancel()
        settle()
        assert not control.isEnabled()
    finally:
        plugin.unload()
        settle()


def test_unload_during_session_restores_project(fake_iface, settings, canvas, project, image):
    original = QgsRasterLayer(image, "Blatt")
    project.addMapLayer(original)
    before, dirs = project_state(project), temp_dirs()
    plugin = load(fake_iface, settings)
    fake_iface.set_active_layer(original)
    settle()
    command(plugin, "georef_verschieben")       # Werkzeug anlegen
    session = georef_commands.start(plugin.resolver.env, georef_commands._active_raster(plugin.resolver.env))
    assert session is not None and session.original_id == original.id()
    command(plugin, "georef_verschieben").trigger()
    assert isinstance(canvas.mapTool(), georef_session.GeorefTool)
    plugin.unload()
    settle()
    assert project_state(project) == before
    assert temp_dirs() == dirs
    assert georef_session.manager() is None and canvas.mapTool() is None


def test_classic_view_cancels_session(fake_iface, settings, canvas, project, image):
    plugin = load(fake_iface, settings)
    try:
        georef_commands.start(plugin.resolver.env, path=image)
        plugin.set_classic(True)
        settle()
        assert georef_session.manager() is None and not project.mapLayers()
    finally:
        plugin.set_classic(False)
        plugin.unload()
        settle()


# -- Kartenwerkzeuge mit echten Mausereignissen ----------------------------------

def send_mouse(canvas, kind, pos, mods=NO_MODS):
    buttons = NO_BUTTON if kind == QEvent.Type.MouseButtonRelease else LEFT
    button = NO_BUTTON if kind == QEvent.Type.MouseMove else LEFT
    QApplication.sendEvent(canvas.viewport(), QMouseEvent(kind, QPointF(pos), button, buttons, mods))


def drag(canvas, start, end, mods=NO_MODS):
    send_mouse(canvas, QEvent.Type.MouseButtonPress, start, mods)
    middle = QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    send_mouse(canvas, QEvent.Type.MouseMove, middle, mods)
    send_mouse(canvas, QEvent.Type.MouseMove, end, mods)
    send_mouse(canvas, QEvent.Type.MouseButtonRelease, end, mods)


def map_xy(canvas, pos):
    point = canvas.getCoordinateTransform().toMapCoordinates(pos)
    return point.x(), point.y()


@pytest.fixture
def tool_session(fake_iface, canvas, project, image):
    manager = georef_session.install(fake_iface)
    session = manager.start(image)
    tools = {}

    def tool(mode):
        if mode not in tools:
            tools[mode] = georef_session.GeorefTool(canvas, manager, mode)
        canvas.setMapTool(tools[mode])
        return tools[mode]
    yield session, tool
    canvas.unsetMapTool(canvas.mapTool())
    for t in tools.values():
        t.close()


@pytest.mark.parametrize("mode, mods", [
    (georef_session.MOVE, NO_MODS),
    (georef_session.SCALE, NO_MODS),
    (georef_session.SCALE, Qt.KeyboardModifier.ShiftModifier),
    (georef_session.ROTATE, NO_MODS),
    (georef_session.ROTATE, Qt.KeyboardModifier.ControlModifier),
])
def test_tools_change_geotransform_like_core(canvas, tool_session, mode, mods):
    session, tool = tool_session
    session.apply(georef.rotate(session.gt, 20, *session.center()))   # gedreht beginnen
    tool(mode)
    before = session.gt
    start, end = QPoint(260, 120), QPoint(300, 80)
    drag(canvas, start, end, mods)
    expected = georef_session.dragged(mode, before, (WIDTH, HEIGHT), map_xy(canvas, start), map_xy(canvas, end), mods)
    assert session.gt == pytest.approx(expected)
    assert session.gt != pytest.approx(before)
    assert georef_ops.read_vrt_geotransform(session.vrt) == pytest.approx(expected)
    if mode == georef_session.ROTATE and mods:
        assert (georef.rotation(session.gt) - georef.rotation(before)) % 15 == pytest.approx(0, abs=1e-6)
    session.undo()
    assert session.gt == pytest.approx(before)


def test_drag_shows_preview_and_escape_cancels(canvas, tool_session):
    session, tool = tool_session
    t = tool(georef_session.MOVE)
    before = session.gt
    opacity = session.layer.renderer().opacity()
    send_mouse(canvas, QEvent.Type.MouseButtonPress, QPoint(200, 150))
    send_mouse(canvas, QEvent.Type.MouseMove, QPoint(230, 170))
    assert t.dragging()
    assert t.preview.isVisible() and t.preview.image is not None
    assert not t.preview.transform.isIdentity()
    assert session.layer.renderer().opacity() == 0.0      # der Layer selbst ist während des Zuges verborgen
    QApplication.sendEvent(canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NO_MODS))
    send_mouse(canvas, QEvent.Type.MouseButtonRelease, QPoint(230, 170))
    assert not t.dragging() and not t.preview.isVisible()
    assert session.gt == pytest.approx(before) and not session.history.can_undo()
    assert session.layer.renderer().opacity() == pytest.approx(opacity)


def test_screen_transform_matches_map(canvas):
    m2p = canvas.mapSettings().mapToPixel()
    before = (1000.0, 1.0, 0.0, 2300.0, 0.0, -1.0)
    change = georef.change(before, georef.rotate(georef.translate(before, 10, -5), 30, 1200, 2150))
    t = georef_session.screen_transform(m2p, change)
    for px, py in ((0, 0), (123, 45), (399, 299)):
        m = m2p.toMapCoordinates(px, py)
        x, y = georef.apply(change, m.x(), m.y())
        want = m2p.transform(x, y)
        got = t.map(QPointF(px, py))
        assert got.x() == pytest.approx(want.x(), abs=1e-6) and got.y() == pytest.approx(want.y(), abs=1e-6)


# -- Projekt ----------------------------------------------------------------------

def test_project_saved_without_work_layer(fake_iface, canvas, project, image, tmp_path, layers):
    project.addMapLayer(layers["vector"])
    name = layers["vector"].name()
    session = georef_session.install(fake_iface).start(image)
    path = str(tmp_path / "projekt.qgs")
    assert project.write(path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert georef_session.TEMP_PREFIX not in text and "<maplayer" in text
    # Übrig bleibt höchstens der Eintrag in der Layerreihenfolge (schreibt QGIS nach dem Signal; harmlos)
    assert all(line.strip().startswith("<layer id=") for line in text.splitlines() if session.layer_id in line)
    # Das geleerte Element des Layers hängt QGIS nach dem Signal an; beim Lesen zählt es nicht
    assert text.count(georef_session.DROPPED_TAG) == text.count("<%s/>" % georef_session.DROPPED_TAG) <= 1
    assert project.mapLayer(session.layer_id) is not None     # in der Sitzung bleibt er
    assert fake_iface.messageBar().items()                    # Hinweis auf die laufende Sitzung
    georef_session.manager().cancel()
    project.clear()
    assert project.read(path)
    assert [lay.name() for lay in project.mapLayers().values()] == [name]


def test_removing_work_layer_or_clearing_ends_session(fake_iface, canvas, project, image):
    original = QgsRasterLayer(image, "Blatt")
    project.addMapLayer(original)
    manager = georef_session.install(fake_iface)
    session = manager.start(image, original)
    folder = session.dir
    project.removeMapLayer(session.layer_id)
    settle()
    assert not manager.active() and not os.path.exists(folder)
    assert project.layerTreeRoot().findLayer(original.id()).itemVisibilityChecked()

    session = manager.start(image, original)
    folder = session.dir
    project.removeMapLayer(original.id())        # Original weg: Sitzung läuft weiter
    assert manager.active() and session.original_id is None
    project.clear()
    assert not manager.active() and not os.path.exists(folder)
