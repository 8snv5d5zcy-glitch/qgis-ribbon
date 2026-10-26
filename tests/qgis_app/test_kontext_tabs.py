"""Kontext-Tabs: Gruppe, Vektorkacheln, Punktwolke, Netz, Aggregation, Wischen und Flimmern."""
import copy
import subprocess

import pytest
from qgis.core import (QgsCategorizedSymbolRenderer, QgsFeature, QgsGeometry, QgsMeshLayer,
                       QgsPointCloudLayer, QgsPointXY, QgsProject, QgsRectangle, QgsVectorLayer,
                       QgsVectorTileBasicLabeling, QgsVectorTileLayer)
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QModelIndex, QPoint, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QImage, QPainter
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration import builtin_commands, compare, kontext_ops
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.context_state import current_group, snapshot
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.layer_watch import LayerWatch
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui.controls import custom as custom_controls
from qgis_ribbon.ui.ribbon_widget import RibbonWidget


def settle():
    for _ in range(3):
        QApplication.processEvents()


# -- Daten ----------------------------------------------------------------------------

def points(name="Punkte", offset=0):
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", name, "memory")
    feats = []
    for i in range(3):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(i + offset, i + offset)))
        f.setAttributes(["p%d" % i])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    layer.updateExtents()
    return layer


@pytest.fixture
def project():
    """Projekt mit Gruppe „Gruppe“ (zwei Punktlayer) und einem Layer außerhalb."""
    prj = QgsProject.instance()
    prj.clear()
    a, b, c = points("A", 0), points("B", 10), points("C", 50)
    for layer in (a, b, c):
        prj.addMapLayer(layer, False)
    root = prj.layerTreeRoot()
    group = root.addGroup("Gruppe")
    group.addLayer(a)
    group.addLayer(b)
    root.addLayer(c)
    yield prj, group, (a, b, c)
    prj.clear()


@pytest.fixture
def mesh(tmp_path):
    path = tmp_path / "netz.2dm"
    path.write_text("MESH2D\nND 1 0 0 1\nND 2 1 0 2\nND 3 0 1 3\nND 4 1 1 4\n"
                    "E3T 1 1 2 3 1\nE3T 2 2 4 3 1\n")
    layer = QgsMeshLayer(str(path), "Netz", "mdal")
    assert layer.isValid()
    return layer


@pytest.fixture
def point_cloud(tmp_path):
    """Kleine COPC-Datei mit RGB und Klassifizierung (mit PDAL aus QGIS erzeugt)."""
    csv = tmp_path / "punkte.csv"
    rows = ["X,Y,Z,Red,Green,Blue,Classification"]
    rows += ["%d,%d,%s,%d,%d,30000,%d" % (i % 10, i // 10, i * 0.5, i * 1000, 65535 - i * 1000, 2 + i % 3)
             for i in range(50)]
    csv.write_text("\n".join(rows) + "\n")
    out = tmp_path / "punkte.copc.laz"
    try:
        subprocess.run(["pdal", "translate", str(csv), str(out)], check=True, capture_output=True,
                       timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("PDAL nicht verfügbar")
    layer = QgsPointCloudLayer(str(out), "Wolke", "copc")
    assert layer.isValid()
    return layer


@pytest.fixture
def vector_tiles(tmp_path):
    url = (tmp_path / "{z}" / "{x}" / "{y}.pbf").as_uri().replace("%7B", "{").replace("%7D", "}")
    layer = QgsVectorTileLayer("type=xyz&url=%s&zmin=0&zmax=14" % url, "Kacheln")
    assert layer.isValid()
    return layer


# -- Operationen ----------------------------------------------------------------------

def test_snapshot_kinds(mesh, vector_tiles, project):
    _prj, group, _layers = project
    assert snapshot(mesh).layer_kind == "mesh"
    assert snapshot(vector_tiles).layer_kind == "vector_tile"
    assert snapshot(None, group).layer_kind == "group"
    assert snapshot(None).layer_kind is None


def test_tree_root_is_no_group(fake_iface, project):
    """Ohne Auswahl meldet die Layerliste die Wurzel; das ist keine gewählte Gruppe."""
    _prj, group, _layers = project
    view = fake_iface.layerTreeView()
    view.setCurrentIndex(QModelIndex())
    assert view.currentNode() is not None and current_group(fake_iface) is None
    fake_iface.select_group(group)
    assert current_group(fake_iface).name() == "Gruppe"


def test_point_cloud_snapshot_and_renderers(point_cloud):
    assert snapshot(point_cloud).layer_kind == "point_cloud"
    names = [n for n, _l in kontext_ops.point_cloud_choices(point_cloud)]
    assert names == ["ramp", "rgb", "classified", "extent"]
    kontext_ops.set_point_size(point_cloud, 4.5)
    for name in names:
        kontext_ops.set_point_cloud_renderer(point_cloud, name)
        assert kontext_ops.point_cloud_renderer_type(point_cloud) == name
        assert kontext_ops.point_size(point_cloud) == pytest.approx(4.5)   # gemeinsame Einstellungen bleiben
    kontext_ops.set_point_cloud_renderer(point_cloud, "classified")
    assert {c.value() for c in point_cloud.renderer().categories()} >= {2, 3, 4}
    kontext_ops.set_max_screen_error(point_cloud, 2.5)
    assert kontext_ops.max_screen_error(point_cloud) == pytest.approx(2.5)


def test_mesh_groups_and_frame(mesh):
    groups = kontext_ops.mesh_groups(mesh)
    assert groups and kontext_ops.mesh_groups(mesh, vector=True) == []
    index = groups[0][0]
    kontext_ops.set_mesh_active_group(mesh, -1)
    assert kontext_ops.mesh_active_group(mesh) == -1
    kontext_ops.set_mesh_active_group(mesh, index)
    assert kontext_ops.mesh_active_group(mesh) == index
    kontext_ops.set_mesh_frame(mesh, True)
    assert kontext_ops.mesh_frame(mesh)
    kontext_ops.set_mesh_frame(mesh, False)
    assert not kontext_ops.mesh_frame(mesh)


def test_vector_tile_labels(vector_tiles):
    assert kontext_ops.vector_tile_labels(vector_tiles) == (False, vector_tiles.labelsEnabled())
    vector_tiles.setLabeling(QgsVectorTileBasicLabeling())
    kontext_ops.set_vector_tile_labels(vector_tiles, False)
    assert kontext_ops.vector_tile_labels(vector_tiles) == (True, False)
    kontext_ops.set_vector_tile_labels(vector_tiles, True)
    assert kontext_ops.vector_tile_labels(vector_tiles) == (True, True)


def test_aggregation_round_trip_keeps_symbology():
    layer = points()
    layer.setRenderer(QgsCategorizedSymbolRenderer.convertFromRenderer(layer.renderer(), layer))
    layer.renderer().setClassAttribute("name")
    saved = {}
    assert kontext_ops.aggregation(layer) == "none"
    kontext_ops.set_aggregation(layer, "pointCluster", saved)
    assert layer.renderer().type() == "pointCluster"
    assert layer.renderer().embeddedRenderer().type() == "categorizedSymbol"
    kontext_ops.set_aggregation(layer, "pointDisplacement", saved)
    assert layer.renderer().embeddedRenderer().type() == "categorizedSymbol"
    kontext_ops.set_aggregation(layer, "heatmapRenderer", saved)
    assert kontext_ops.aggregation(layer) == "heatmapRenderer"
    kontext_ops.set_aggregation(layer, "none", saved)
    assert layer.renderer().type() == "categorizedSymbol"
    assert layer.renderer().classAttribute() == "name" and not saved


def test_only_point_layers_aggregate():
    lines = QgsVectorLayer("LineString?crs=EPSG:4326", "Linien", "memory")
    assert not kontext_ops.can_aggregate(lines) and kontext_ops.aggregation(lines) is None
    assert kontext_ops.can_aggregate(points())


def test_group_layer_on_off_and_extent(project):
    prj, group, (a, b, _c) = project
    assert kontext_ops.group_layer(group) is None
    gl = kontext_ops.ensure_group_layer(group)
    assert kontext_ops.group_layer(group) is gl and prj.mapLayer(gl.id()) is gl
    assert kontext_ops.ensure_group_layer(group) is gl          # nur einmal
    gl_id = gl.id()
    kontext_ops.remove_group_layer(group)
    assert group.groupLayer() is None and prj.mapLayer(gl_id) is None
    extent = kontext_ops.group_extent(group, a.crs())
    assert (extent.xMinimum(), extent.xMaximum()) == pytest.approx((0, 12))
    assert {lyr.name() for lyr in kontext_ops.group_layers(group)} == {"A", "B"}


def test_layers_without_resolves_group_layer(project):
    _prj, group, (a, b, c) = project
    gl = kontext_ops.ensure_group_layer(group)
    assert [lyr.name() for lyr in compare.layers_without([gl, c], {a.id()})] == ["B", "C"]
    assert compare.layers_without([gl, c], {c.id()}) == [gl]       # Gruppe bleibt Gruppe
    assert compare.layers_without([gl, c], {gl.id(), a.id(), b.id()}) == [c]


def test_clip_rect():
    assert compare.clip_rect(100, 50, "v", 30, True) == QRectF(0, 0, 30, 50)
    assert compare.clip_rect(100, 50, "v", 30, False) == QRectF(30, 0, 70, 50)
    assert compare.clip_rect(100, 50, "h", 20, True) == QRectF(0, 0, 100, 20)
    assert compare.clip_rect(100, 50, "h", 80, False) == QRectF(0, 50, 100, 0)   # außerhalb begrenzt


# -- Ribbon ---------------------------------------------------------------------------

def custom(cid):
    return {"type": "custom", "id": cid}


DEFINITION = {
    "version": 1,
    "commands": {
        "deckkraft": {"label": "Deckkraft", "kind": "control", "source": custom("ribbon.layer_deckkraft")},
        "mischmodus": {"label": "Mischmodus", "kind": "control", "source": custom("ribbon.layer_mischmodus")},
        "objekt": {"label": "Objekt-Mischmodus", "kind": "control", "source": custom("ribbon.objekt_mischmodus")},
        "massstab": {"label": "Maßstabsbereich", "source": custom("ribbon.layer_massstab_schalten")},
        "max": {"label": "Größter Maßstab", "kind": "control", "source": custom("ribbon.layer_massstab_max")},
        "wischen": {"label": "Wischen", "source": custom("ribbon.swipe")},
        "flimmern": {"label": "Flimmern", "source": custom("ribbon.flimmern")},
        "takt": {"label": "Takt", "kind": "control", "source": custom("ribbon.flimmer_intervall")},
        "aggregation": {"label": "Aggregation", "kind": "control", "source": custom("ribbon.aggregation_galerie"),
                        "gallery": {}},
        "als_gruppe": {"label": "Als Gruppe darstellen", "source": custom("ribbon.gruppe_als_ebene")},
        "exklusiv": {"label": "Exklusiv", "source": custom("ribbon.gruppe_exklusiv")},
        "zoomen": {"label": "Auf Gruppe zoomen", "source": custom("ribbon.gruppe_zoomen")},
        "skalar": {"label": "Skalar", "kind": "control", "source": custom("ribbon.netz_skalar")},
        "gitter": {"label": "Netzgitter", "source": custom("ribbon.netz_gitter")},
    },
    "tabs": [{"id": "t", "label": "T", "groups": [
        {"id": "a", "label": "A", "items": [
            {"command": "deckkraft", "size": "medium"}, {"command": "mischmodus", "size": "medium"},
            {"command": "objekt", "size": "medium"}, {"command": "max", "size": "medium"},
            {"command": "takt", "size": "medium"}, {"command": "skalar", "size": "medium"},
        ]},
        {"id": "b", "label": "B", "items": [
            {"command": "massstab", "size": "large"}, {"command": "wischen", "size": "large"},
            {"command": "flimmern", "size": "large"}, {"command": "aggregation", "size": "large"},
            {"command": "als_gruppe", "size": "large"}, {"command": "exklusiv", "size": "large"},
            {"command": "zoomen", "size": "large"}, {"command": "gitter", "size": "large"},
        ]},
    ]}],
}


@pytest.fixture
def ribbon(fake_iface, settings):
    builtin_commands.register_all()
    custom_controls.register_all()
    hub = SignalHub()
    watch = LayerWatch(fake_iface, hub)
    watch.start()
    env = CommandEnv(fake_iface, watch, settings, hub)
    resolver = ActionResolver(fake_iface, env)
    w = RibbonWidget(config_loader.parse(copy.deepcopy(DEFINITION)), resolver, hub)
    w.resize(2600, 140)
    w.show()
    settle()
    yield w, watch, env
    env.close()
    watch.stop()
    hub.disconnect_all()
    resolver.clear()
    builtin_commands.unregister_all()
    custom_controls.unregister_all()
    w.deleteLater()
    settle()


def control(w, cid):
    return w.findChild(QWidget, "ribbon_control_" + cid)


def action(w, label):
    for b in w.findChildren(QToolButton):
        if b.defaultAction() is not None and b.defaultAction().text() == label:
            return b.defaultAction()
    raise AssertionError(label)


def test_group_controls_create_group_layer_on_first_change(ribbon, fake_iface, project):
    w, watch, _env = ribbon
    _prj, group, (a, _b, _c) = project
    fake_iface.select_group(group)
    settle()
    assert watch.group() is not None
    opacity, blend, feature = control(w, "deckkraft"), control(w, "mischmodus"), control(w, "objekt")
    assert opacity.isEnabled() and blend.isEnabled() and not feature.isEnabled()
    assert opacity.editor.opacity() == pytest.approx(1.0) and group.groupLayer() is None
    opacity.editor.setOpacity(0.4)
    settle()
    gl = group.groupLayer()
    assert gl is not None and gl.opacity() == pytest.approx(0.4)
    assert action(w, "Als Gruppe darstellen").isChecked()
    gl.setOpacity(0.7)                               # außerhalb geändert: Ribbon folgt
    settle()
    assert opacity.editor.opacity() == pytest.approx(0.7)
    blend.editor.setBlendMode(QPainter.CompositionMode_Multiply)
    assert gl.blendMode() == QPainter.CompositionMode_Multiply
    fake_iface.set_active_layer(a)                   # Layer statt Gruppe
    settle()
    assert feature.isEnabled() and opacity.editor.opacity() == pytest.approx(1.0)


def test_group_scale_range_and_toggles(ribbon, fake_iface, project):
    w, _watch, _env = ribbon
    _prj, group, (a, b, _c) = project
    fake_iface.select_group(group)
    settle()
    scale = action(w, "Maßstabsbereich")
    assert scale.isEnabled() and not scale.isChecked()
    scale.trigger()
    settle()
    assert group.groupLayer().hasScaleBasedVisibility() and scale.isChecked()
    render = action(w, "Als Gruppe darstellen")
    render.trigger()                                 # aus: Gruppenebene entfällt
    settle()
    assert group.groupLayer() is None and not render.isChecked() and not scale.isChecked()
    exclusive = action(w, "Exklusiv")
    exclusive.trigger()
    assert group.isMutuallyExclusive() and exclusive.isChecked()
    canvas = fake_iface.mapCanvas()
    canvas.setDestinationCrs(a.crs())
    action(w, "Auf Gruppe zoomen").trigger()
    assert canvas.extent().contains(QgsRectangle(0, 0, 12, 12))
    fake_iface.set_active_layer(b)
    settle()
    assert not exclusive.isEnabled() and not render.isEnabled()


def test_feature_blend_and_aggregation_gallery(ribbon, fake_iface):
    w, _watch, _env = ribbon
    layer = points()
    fake_iface.set_active_layer(layer)
    settle()
    feature = control(w, "objekt")
    feature.editor.setBlendMode(QPainter.CompositionMode_Darken)
    assert layer.featureBlendMode() == QPainter.CompositionMode_Darken
    btn = w.findChild(QToolButton, "ribbon_gallery_btn_aggregation")
    btn.menu().aboutToShow.emit()
    acts = {a.text(): a for a in btn.menu().actions() if a.text()}
    assert acts["Keine"].isChecked() and acts["Punktcluster"].isEnabled()
    acts["Punktcluster"].trigger()
    assert layer.renderer().type() == "pointCluster"


def test_mesh_controls(ribbon, fake_iface, mesh):
    w, _watch, _env = ribbon
    fake_iface.set_active_layer(mesh)
    settle()
    skalar = control(w, "skalar")
    assert skalar.isEnabled() and skalar.editor.count() == 1 + len(kontext_ops.mesh_groups(mesh))
    skalar.editor.setCurrentIndex(0)
    skalar.editor.activated.emit(0)
    assert kontext_ops.mesh_active_group(mesh) == -1
    gitter = action(w, "Netzgitter")
    gitter.setChecked(not kontext_ops.mesh_frame(mesh))
    gitter.triggered.emit(gitter.isChecked())
    assert kontext_ops.mesh_frame(mesh) == gitter.isChecked()


def wait_rendered(comparison):
    for _ in range(250):
        QTest.qWait(20)
        if comparison.overlay is not None and comparison.overlay.image is not None and not comparison._jobs:
            return
    raise AssertionError("nicht gerendert")


def mouse(canvas, kind, x, y, button=Qt.LeftButton):
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
    return QgsMapMouseEvent(canvas, kind, QPoint(x, y), button, buttons, Qt.NoModifier)


def test_swipe_tool_and_flicker(ribbon, fake_iface, project, settings):
    w, _watch, env = ribbon
    _prj, _group, (a, _b, c) = project
    canvas = fake_iface.mapCanvas()
    canvas.setLayers([a, c])
    canvas.setDestinationCrs(a.crs())
    canvas.setExtent(QgsRectangle(-1, -1, 60, 60))
    fake_iface.set_active_layer(a)
    settle()
    comparison = builtin_commands.comparison(env)
    swipe = action(w, "Wischen")
    swipe.trigger()
    settle()
    assert isinstance(canvas.mapTool(), compare.SwipeTool) and comparison.swiping
    wait_rendered(comparison)
    tool = canvas.mapTool()
    tool.canvasPressEvent(mouse(canvas, QEvent.MouseButtonPress, 10, 10))
    tool.canvasMoveEvent(mouse(canvas, QEvent.MouseMove, 60, 12))
    orientation, _point, hide_before = comparison.overlay.edge
    assert orientation == "v" and hide_before
    tool.canvasReleaseEvent(mouse(canvas, QEvent.MouseButtonRelease, 60, 12))
    assert comparison.overlay.edge is None
    # Qt zeichnet das Bild über die Karte (Aufruf mit drei Argumenten)
    overlay = comparison.overlay
    green = QImage(overlay.image.size(), QImage.Format_ARGB32)
    green.fill(QColor(0, 255, 0))
    overlay.image, overlay.full = green, True
    scene = canvas.scene()
    out = QImage(int(scene.width()), int(scene.height()), QImage.Format_ARGB32)
    out.fill(QColor(0, 0, 0, 0))
    painter = QPainter(out)
    scene.render(painter, QRectF(out.rect()), scene.sceneRect())
    painter.end()
    center = overlay.mapToScene(overlay.boundingRect().center())
    assert QColor(out.pixel(int(center.x()), int(center.y()))) == QColor(0, 255, 0)
    overlay.full = False
    swipe.trigger()                                  # Werkzeug aus
    settle()
    assert not comparison.swiping and comparison.overlay.image is None

    takt = control(w, "takt")
    takt.editor.setValue(200)
    assert comparison.interval() == 200 and int(settings.value(compare.FLICKER_KEY)) == 200
    flicker = action(w, "Flimmern")
    flicker.trigger()
    assert comparison.flickering and flicker.isChecked()
    wait_rendered(comparison)
    full = comparison.overlay.full
    comparison._tick()
    assert comparison.overlay.full != full
    fake_iface.layerTreeView().setCurrentIndex(QModelIndex())
    fake_iface.set_active_layer(None)                # weder Layer noch Gruppe: nichts zu vergleichen
    settle()
    assert not comparison.flickering and not flicker.isChecked()


def test_close_removes_overlay_and_tool(ribbon, fake_iface, project):
    w, _watch, env = ribbon
    _prj, _group, (a, _b, _c) = project
    canvas = fake_iface.mapCanvas()
    canvas.setLayers([a])
    fake_iface.set_active_layer(a)
    settle()
    action(w, "Wischen").trigger()
    settle()
    comparison = builtin_commands.comparison(env)
    wait_rendered(comparison)
    overlay = comparison.overlay
    assert overlay.scene() is canvas.scene()
    env.close()                                      # wie beim Entladen
    settle()
    assert canvas.mapTool() is None
    assert overlay not in canvas.scene().items()
