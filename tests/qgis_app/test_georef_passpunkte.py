"""Georeferenzieren in der Karte: Passpunkte, Transformationen, Punktdatei, Speichern und Entzerren."""
import glob
import os
import tempfile
import time

import pytest
from qgis.analysis import QgsGcpTransformerInterface
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsPointXY,
                       QgsProject, QgsRasterLayer, QgsRectangle)
from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtWidgets import QApplication, QDockWidget, QWidget

from qgis_ribbon.core import georef
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration import georef_commands, georef_ops, georef_session
from qgis_ribbon.ui import georef_panel

WIDTH, HEIGHT = 40, 30
NO_MODS = Qt.KeyboardModifier.NoModifier


def settle():
    for _ in range(3):
        QApplication.processEvents()


def make_image(path, gt=None):
    """Zwei Kanäle verraten den Bildpunkt: Kanal 1 = 6 * Spalte, Kanal 2 = 8 * Zeile."""
    from osgeo import gdal
    import numpy
    ds = gdal.GetDriverByName("GTiff").Create(path, WIDTH, HEIGHT, 2, gdal.GDT_Byte)
    if gt is not None:
        ds.SetGeoTransform(gt)
        ds.SetProjection(QgsCoordinateReferenceSystem("EPSG:25832").toWkt())
    cols, rows = numpy.meshgrid(numpy.arange(WIDTH), numpy.arange(HEIGHT))
    ds.GetRasterBand(1).WriteArray((cols * 6).astype("uint8"))
    ds.GetRasterBand(2).WriteArray((rows * 8).astype("uint8"))
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
    georef_panel.uninstall()
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


def load(fake_iface, settings):
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    return plugin


def command(plugin, cid):
    return plugin.resolver.resolve(plugin.ribbon.commands[cid]).action


def click(canvas, pos, button=Qt.MouseButton.LeftButton):
    for kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        pressed = Qt.MouseButton.NoButton if kind != QEvent.Type.MouseButtonPress else button
        which = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
        QApplication.sendEvent(canvas.viewport(), QMouseEvent(kind, QPointF(pos), which, pressed, NO_MODS))


def map_xy(canvas, pos):
    point = canvas.getCoordinateTransform().toMapCoordinates(pos)
    return point.x(), point.y()


def affine_target(col, row):
    """Wahre Lage für die Prüfpunkte: gedreht, ungleich skaliert, verschoben."""
    return 1100.0 + 2.0 * col + 0.4 * row, 2250.0 + 0.3 * col - 1.8 * row


# Bildpunkte in Pixelmitten, gut verteilt (genug für Polynom 3)
PIXELS = [(2.5, 2.5), (37.5, 3.5), (36.5, 27.5), (3.5, 26.5), (20.5, 14.5), (10.5, 8.5), (29.5, 9.5),
          (28.5, 21.5), (11.5, 20.5), (20.5, 4.5), (5.5, 15.5)]


def true_points(count=len(PIXELS)):
    return [georef.ControlPoint(c, r, *affine_target(c, r)) for c, r in PIXELS[:count]]


@pytest.fixture
def session(fake_iface, canvas, project, image):
    manager = georef_session.install(fake_iface)
    s = manager.start(image)
    settle()
    return s


# -- Passpunkte mit echten Klicks -----------------------------------------------

def test_three_points_by_clicks_give_affine_position(fake_iface, canvas, session):
    manager = georef_session.manager()
    tool = georef_session.GcpTool(canvas, manager)
    canvas.setMapTool(tool)
    try:
        # Halber Punkt: Rechtsklick bricht ihn ab
        click(canvas, QPoint(120, 100))
        assert manager.markers.pending is not None
        click(canvas, QPoint(150, 150), Qt.MouseButton.RightButton)
        assert manager.markers.pending is None and not session.points
        # Klick neben das Bild setzt keinen Punkt
        click(canvas, QPoint(3, 3))
        assert manager.markers.pending is None

        pairs = [(QPoint(80, 60), QPoint(110, 90)), (QPoint(320, 70), QPoint(300, 40)),
                 (QPoint(110, 250), QPoint(150, 260))]
        for number, (on_image, target) in enumerate(pairs, 1):
            col, row = session.image_pixel(*map_xy(canvas, on_image))
            click(canvas, on_image)
            assert manager.markers.pending == pytest.approx((col, row))
            click(canvas, target)
            settle()
            assert len(session.points) == number
            p = session.points[-1]
            assert (p.col, p.row) == pytest.approx((col, row))
            assert (p.x, p.y) == pytest.approx(map_xy(canvas, target))
        assert session.used_method() == georef.AFFINE and session.linear()
        for p in session.points:
            assert georef.apply(session.gt, p.col, p.row) == pytest.approx((p.x, p.y), abs=1e-6)
        assert georef_ops.read_vrt_geotransform(session.vrt) == pytest.approx(session.gt)
        assert session.mean_error() == pytest.approx(0, abs=1e-6)
        # Rückgängig nimmt den letzten Punkt zurück
        session.undo()
        assert len(session.points) == 2 and session.used_method() == georef.HELMERT
    finally:
        canvas.unsetMapTool(tool)
        tool.deleteLater()


@pytest.mark.parametrize("method, count", [(georef.AFFINE, 5), (georef.POLY2, 8), (georef.POLY3, 11),
                                           (georef.PROJECTIVE, 6), (georef.HELMERT, 4)])
def test_residuals_match_qgis_transformer(session, method, count):
    # Gestörte Ziele, damit Restfehler entstehen
    points = true_points(count)
    for i, p in enumerate(points):
        p.x += (-1) ** i * 0.7 * (i % 3)
        p.y += (-1) ** (i + 1) * 0.5 * (i % 2)
    session.replace_points(points)
    session.set_method(method)
    assert session.used_method() == method
    t = QgsGcpTransformerInterface.create(georef_ops.qgis_method(method))
    assert t.updateParametersFromGcps([QgsPointXY(p.col, -p.row) for p in points],
                                      [QgsPointXY(p.x, p.y) for p in points], False)
    res = session.residuals
    for p, r in zip(points, res):
        ok, x, y = t.transform(p.col, -p.row, False)
        assert ok
        assert (r.dx, r.dy) == pytest.approx((x - p.x, y - p.y), abs=1e-6)
    assert session.mean_error() > 0
    if method not in georef.LINEAR:
        assert not session.linear() and os.path.basename(session.layer.source()).startswith("warped_")


def test_method_switch_and_inactive_point(session):
    session.replace_points(true_points(4))
    assert session.used_method() == georef.AFFINE          # automatisch: ab 3 Punkten affin
    session.set_method(georef.PROJECTIVE)
    assert not session.linear() and session.active_count() == 4
    x, y = session.map_point(15.0, 12.0)
    assert (x, y) == pytest.approx(affine_target(15.0, 12.0), abs=1e-6)
    assert session.image_pixel(x, y) == pytest.approx((15.0, 12.0), abs=1e-6)
    # Ein Punkt abgehakt: projektiv braucht 4, die Lage bleibt die letzte von Hand
    session.set_point_active(0, False)
    assert session.active_count() == 3 and session.used_method() is None and session.linear()
    session.set_method(georef.AUTO)
    assert session.used_method() == georef.AFFINE
    assert georef.apply(session.gt, 15.0, 12.0) == pytest.approx(affine_target(15.0, 12.0), abs=1e-6)
    session.set_method(georef.HELMERT)
    assert session.used_method() == georef.HELMERT and session.residuals[1].map > 0
    # Rückgängig in umgekehrter Reihenfolge
    session.undo()
    session.undo()
    assert session.active_count() == 3 and session.method == georef.PROJECTIVE
    session.undo()
    assert session.active_count() == 4 and not session.linear()


def test_points_file_round_trip(fake_iface, session, tmp_path):
    points = true_points(5)
    points[2].active = False
    session.replace_points(points)
    path = str(tmp_path / "blatt.points")
    session.save_points(path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith(georef.CRS_PREFIX) and georef.POINTS_HEADER in text
    source = session.source
    georef_session.manager().cancel()
    other = georef_session.manager().start(source)
    other.load_points(path)
    assert len(other.points) == 5
    for a, b in zip(points, other.points):
        assert a.astuple() == pytest.approx(b.astuple())
    assert other.used_method() == georef.AFFINE and other.active_count() == 4


def test_points_from_other_crs_are_transformed(fake_iface, session, tmp_path):
    points = true_points(3)
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    from qgis.core import QgsCoordinateTransform
    to_wgs = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:25832"), wgs, QgsProject.instance())
    moved = []
    for p in points:
        q = to_wgs.transform(QgsPointXY(p.x + 500000, p.y + 5500000))
        moved.append(georef.ControlPoint(p.col, p.row, q.x(), q.y()))
    path = str(tmp_path / "wgs.points")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(georef.write_points(moved, wgs.toWkt(), session.source_gt))
    session.load_points(path)
    for a, b in zip(points, session.points):
        assert (b.x, b.y) == pytest.approx((a.x + 500000, a.y + 5500000), abs=1e-3)


# -- Bedienfeld und Auswahl der Transformation ----------------------------------

def test_panel_follows_session(fake_iface, settings, canvas, project, image):
    plugin = load(fake_iface, settings)
    mw = fake_iface.mainWindow()
    try:
        assert mw.findChild(QDockWidget, georef_panel.DOCK_NAME) is None
        georef_commands.start(plugin.resolver.env, path=image)
        settle()
        panel = mw.findChild(QDockWidget, georef_panel.DOCK_NAME)
        assert panel is not None and panel.isVisible()
        assert panel.table.rowCount() == 0
        session = georef_session.manager().session
        session.replace_points(true_points(4))
        settle()
        assert panel.table.rowCount() == 4
        # Abhaken in der Tabelle schaltet den Punkt
        item = panel.table.item(1, 1)
        item.setCheckState(Qt.CheckState.Unchecked)
        settle()
        assert not session.points[1].active and session.active_count() == 3
        # Zeile wählen hebt den Punkt hervor, Löschen entfernt ihn
        panel.table.selectRow(0)
        settle()
        assert session.highlight == 0
        panel.delete_button.click()
        settle()
        assert len(session.points) == 3 and panel.table.rowCount() == 3
        # Button „Passpunkttabelle“ verbirgt und zeigt das Bedienfeld
        table = command(plugin, "georef_tabelle")
        assert table.isEnabled() and table.isChecked()
        table.trigger()
        settle()
        assert not panel.isVisible() and not table.isChecked()
        table.trigger()
        settle()
        assert panel.isVisible()
        georef_session.manager().cancel()
        settle()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert mw.findChild(QDockWidget, georef_panel.DOCK_NAME) is None
        assert not table.isEnabled()
    finally:
        plugin.unload()
        settle()
    assert georef_panel.controller() is None


def test_method_control(fake_iface, settings, canvas, project, image):
    plugin = load(fake_iface, settings)
    try:
        georef_commands.start(plugin.resolver.env, path=image)
        settle()
        plugin.widget.select_tab("georeferenzieren")
        settle()
        control = plugin.widget.findChild(QWidget, "ribbon_control_georef_verfahren")
        assert control is not None and control.isEnabled()
        combo = control.editor
        session = georef_session.manager().session
        session.replace_points(true_points(4))
        settle()

        def entry(method):
            return combo.model().item(combo.findData(method))
        assert entry(georef.PROJECTIVE).isEnabled() and entry(georef.AFFINE).isEnabled()
        assert not entry(georef.POLY2).isEnabled() and entry(georef.POLY2).toolTip()
        combo.setCurrentIndex(combo.findData(georef.PROJECTIVE))
        settle()
        assert session.method == georef.PROJECTIVE and not session.linear()
        # Ohne Punktmehrheit für die Lage von Hand nicht mehr erreichbar
        assert not command(plugin, "georef_anpassen").isEnabled()
        assert not command(plugin, "georef_speichern").isEnabled()
        assert command(plugin, "georef_entzerren").isEnabled()
        session.set_method(georef.AFFINE)
        settle()
        assert combo.currentData() == georef.AFFINE and command(plugin, "georef_speichern").isEnabled()
        georef_session.manager().cancel()
        settle()
        assert not control.isEnabled()
    finally:
        plugin.unload()
        settle()


# -- Abschließen -----------------------------------------------------------------

def test_save_georeference_next_to_image(fake_iface, settings, canvas, project, image):
    original = QgsRasterLayer(image, "Blatt")
    project.addMapLayer(original)
    original.dataProvider().bandStatistics(1)      # GDAL schriebe beim Schließen seine Begleitdatei zurück
    dirs = temp_dirs()
    plugin = load(fake_iface, settings)
    try:
        fake_iface.set_active_layer(original)
        settle()
        session = georef_commands.start(plugin.resolver.env, georef_commands._active_raster(plugin.resolver.env))
        session.replace_points(true_points(4))
        gt = session.gt
        assert gt == pytest.approx((1100.0, 2.0, 0.4, 2250.0, 0.3, -1.8), abs=1e-6)
        written = georef_commands.save_georeference(plugin.resolver.env)
        settle()
        assert written and all(os.path.exists(p) for p in written)
        assert written[0].endswith(".tfw") and written[1].endswith(".tif.aux.xml")
        # Sitzung zu Ende, Original wieder sichtbar und in der neuen Lage
        assert not georef_session.active() and temp_dirs() == dirs
        assert list(project.mapLayers()) == [original.id()]
        assert project.layerTreeRoot().findLayer(original.id()).itemVisibilityChecked()
        assert georef_ops.image_size(image)[2] == pytest.approx(gt)
        # Gedrehte Bilder zeigt QGIS über ein eigenes entzerrtes VRT: Ausdehnung auf ein Pixel genau
        want = QgsRectangle(*georef.bounds(gt, WIDTH, HEIGHT))
        for layer in (original, QgsRasterLayer(image, "neu")):
            ext = layer.extent()
            assert (ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()) == pytest.approx(
                (want.xMinimum(), want.yMinimum(), want.xMaximum(), want.yMaximum()), abs=2.1)
            assert layer.crs().authid() == "EPSG:25832"
            layer.dataProvider().bandStatistics(1)
    finally:
        plugin.unload()
        settle()
    # Auch nach dem Schließen aller Zugriffe (Statistik berechnet) bleibt die Georeferenz in der Begleitdatei
    project.clear()
    settle()
    with open(image + ".aux.xml", encoding="utf-8") as fh:
        aux = fh.read()
    assert "<SRS" in aux and "<GeoTransform" in aux


def wait_for_tasks(timeout=30):
    end = time.time() + timeout
    while QgsApplication.taskManager().countActiveTasks() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    settle()


def pixel_at(path, x, y):
    """Spalte und Zeile des Quellbildes, die das entzerrte Bild an (x, y) zeigt (aus den Kanälen)."""
    from osgeo import gdal
    ds = gdal.Open(path)
    col, row = georef.to_pixel(ds.GetGeoTransform(), x, y)
    values = [int(ds.GetRasterBand(b).ReadAsArray(int(col), int(row), 1, 1)[0][0]) for b in (1, 2, 3)]
    ds = None
    return values[0] / 6.0, values[1] / 8.0, values[2]


@pytest.mark.parametrize("method, count", [(None, 0), (georef.AFFINE, 3), (georef.POLY2, 7), (georef.TPS, 6),
                                           (georef.PROJECTIVE, 5)])
def test_warp_puts_control_points_in_place(fake_iface, session, tmp_path, method, count):
    manager = georef_session.manager()
    if count:
        session.replace_points(true_points(count))
        session.set_method(method)
        assert session.used_method() == method
        check = true_points(count)
    else:
        check = [georef.ControlPoint(c, r, *georef.apply(session.gt, c, r)) for c, r in PIXELS[:4]]
    out = str(tmp_path / "entzerrt.tif")
    layer = manager.warp(out, background=False)
    assert layer is not None and layer.isValid() and os.path.exists(out)
    assert not georef_session.active()
    for p in check:
        col, row, alpha = pixel_at(out, p.x, p.y)
        assert alpha == 255
        assert abs(col - int(p.col)) <= 1 and abs(row - int(p.row)) <= 1, (p, col, row)


def test_warp_in_background_replaces_original(fake_iface, canvas, project, image, tmp_path, layers):
    project.addMapLayer(layers["vector"])
    original = QgsRasterLayer(image, "Blatt")
    project.addMapLayer(original)
    root = project.layerTreeRoot()
    original_id = original.id()
    position = [n.layerId() for n in root.findLayers()].index(original_id)
    manager = georef_session.install(fake_iface)
    session = manager.start(image, original)
    session.replace_points(true_points(6))
    session.set_method(georef.TPS)
    out = str(tmp_path / "blatt_georef.tif")
    results = []
    task = manager.warp(out, compression="DEFLATE", replace=True, done=results.append)
    assert task is not None and manager.tasks == [task]
    wait_for_tasks()
    assert len(results) == 1 and results[0] is not None
    layer = results[0]
    assert project.mapLayer(original_id) is None
    assert [n.layerId() for n in root.findLayers()].index(layer.id()) == position
    assert layer.source().endswith("blatt_georef.tif") and not manager.tasks
    from osgeo import gdal
    ds = gdal.Open(out)
    assert ds.GetMetadata("IMAGE_STRUCTURE").get("COMPRESSION") == "DEFLATE" and ds.RasterCount == 3
    ds = None


def test_warp_to_other_crs(fake_iface, session, tmp_path):
    session.replace_points(true_points(3))
    out = str(tmp_path / "wgs.tif")
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    # Ziele in der Nähe echter UTM-Koordinaten, damit die Umrechnung sinnvoll ist
    points = [georef.ControlPoint(p.col, p.row, p.x + 500000, p.y + 5500000) for p in true_points(3)]
    session.replace_points(points)
    layer = georef_session.manager().warp(out, dst_wkt=wgs.toWkt(), background=False)
    assert layer is not None and layer.crs().authid() == "EPSG:4326"


def test_cancel_during_warp_leaves_nothing_behind(fake_iface, session, tmp_path):
    manager = georef_session.manager()
    session.replace_points(true_points(6))
    session.set_method(georef.TPS)
    before = temp_dirs()
    results = []
    task = manager.warp(str(tmp_path / "x.tif"), done=results.append)
    task.cancel()
    wait_for_tasks()
    assert results == [None] and not manager.tasks
    assert temp_dirs() == before and georef_session.active()
    manager.cancel()
    settle()
    assert not georef_session.active()


def test_warp_dialog(fake_iface, settings, canvas, project, image, monkeypatch):
    from qgis.PyQt.QtWidgets import QDialog, QMessageBox
    from qgis_ribbon.ui import georef_dialog
    original = QgsRasterLayer(image, "Blatt")
    project.addMapLayer(original)
    plugin = load(fake_iface, settings)
    try:
        fake_iface.set_active_layer(original)
        settle()
        session = georef_commands.start(plugin.resolver.env, georef_commands._active_raster(plugin.resolver.env))
        session.replace_points(true_points(3))
        dialog = georef_dialog.WarpDialog(session)
        values = dialog.values()
        assert values["out_path"].endswith("blatt_georef.tif") and values["resampling"] == "near"
        assert values["compression"] == "LZW"
        assert QgsCoordinateReferenceSystem.fromWkt(values["dst_wkt"]).authid() == "EPSG:25832"
        dialog.deleteLater()

        shown, path = [], {"value": values["out_path"]}

        def accept(dlg):
            dlg.target.setFilePath(path["value"])
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(georef_dialog.WarpDialog, "exec", accept)
        monkeypatch.setattr(QMessageBox, "question", lambda *args: shown.append(args) or QMessageBox.StandardButton.No)
        # Das Bild selbst als Ziel wird abgelehnt, die Sitzung läuft weiter
        path["value"] = image
        command(plugin, "georef_entzerren").trigger()
        assert georef_session.active() and not georef_session.manager().tasks and not shown
        path["value"] = values["out_path"]
        command(plugin, "georef_entzerren").trigger()
        assert len(shown) == 1
        wait_for_tasks()
        assert not georef_session.active() and os.path.exists(values["out_path"])
        names = sorted(lay.name() for lay in project.mapLayers().values())
        assert names == ["Blatt", "blatt_georef"]
    finally:
        plugin.unload()
        settle()
