"""Operationen der Kontext-Tabs Gruppe, Vektorkacheln, Punktwolke, Netz und der Aggregation.

Wie ``layer_ops``: kleine Funktionen auf der QGIS-API ohne Widgets. Jede
Änderung setzt die Eigenschaft, die auch der passende QGIS-Dialog setzt, und
meldet sie wie QGIS (``layer_ops.changed``).

Gruppen: Deckkraft, Mischmodus und Sichtbarkeitsbereich einer Gruppe gibt
es in QGIS nur, wenn sie als Gruppe dargestellt wird (Gruppenebene,
``QgsGroupLayer``). ``ensure_group_layer`` schaltet das ein wie die
Gruppeneigenschaften im Layer-Styling („Als Gruppe darstellen“).
"""

import math

from qgis.core import (Qgis, QgsColorRampShader, QgsCoordinateTransform, QgsFeatureRenderer,
                       QgsGroupLayer, QgsHeatmapRenderer, QgsLayerTreeGroup, QgsMeshDatasetIndex,
                       QgsMeshLayer, QgsPointCloudAttributeByRampRenderer,
                       QgsPointCloudClassifiedRenderer, QgsPointCloudExtentRenderer,
                       QgsPointCloudLayer, QgsPointCloudRendererRegistry, QgsPointCloudRgbRenderer,
                       QgsPointClusterRenderer, QgsPointDisplacementRenderer, QgsProject,
                       QgsRectangle, QgsStyle, QgsVectorTileLayer)

from . import layer_ops
from ..core.i18n import tr


# -- Gruppen ----------------------------------------------------------------

def is_group(node):
    return isinstance(node, QgsLayerTreeGroup)


def group_layer(group):
    """Gruppenebene der Gruppe oder None (Gruppe wird nicht als Gruppe dargestellt)."""
    return group.groupLayer() if is_group(group) else None


def ensure_group_layer(group, project=None):
    """Gruppe als Gruppe darstellen und die Gruppenebene zurückgeben."""
    layer = group.groupLayer()
    if layer is None:
        project = project or QgsProject.instance()
        layer = group.convertToGroupLayer(QgsGroupLayer.LayerOptions(project.transformContext()))
        project.addMapLayer(layer, False)
        project.setDirty(True)
    return layer


def remove_group_layer(group, project=None):
    """Darstellung als Gruppe beenden (Deckkraft, Mischmodus usw. der Gruppe entfallen)."""
    layer = group.groupLayer()
    if layer is None:
        return
    project = project or QgsProject.instance()
    project.removeMapLayer(layer.id())
    group.setGroupLayer(None)
    project.setDirty(True)


def group_layers(group):
    """Layer der Gruppe samt Untergruppen."""
    return [node.layer() for node in group.findLayers() if node.layer() is not None]


def group_extent(group, dest_crs, project=None):
    """Ausdehnung aller räumlichen Layer der Gruppe im Ziel-KBS (leer, wenn keiner)."""
    project = project or QgsProject.instance()
    extent = QgsRectangle()
    extent.setNull()
    for layer in group_layers(group):
        if not layer.isSpatial():
            continue
        rect = layer.extent()
        if rect.isNull():
            continue
        if layer.crs() != dest_crs:
            try:
                rect = QgsCoordinateTransform(layer.crs(), dest_crs, project).transformBoundingBox(rect)
            except Exception:  # noqa: BLE001 (Transformation nicht möglich: Layer überspringen)
                continue
        extent.combineExtentWith(rect)
    return extent


# -- Vektorkacheln --------------------------------------------------------

def is_vector_tile(layer):
    return isinstance(layer, QgsVectorTileLayer)


def vector_tile_labels(layer):
    """(Beschriftung vorhanden, eingeschaltet)."""
    if not is_vector_tile(layer):
        return False, False
    return layer.labeling() is not None, layer.labelsEnabled()


def set_vector_tile_labels(layer, on):
    layer.setLabelsEnabled(bool(on))
    layer_ops.changed(layer)


# -- Punktwolken ------------------------------------------------------------

def is_point_cloud(layer):
    return isinstance(layer, QgsPointCloudLayer)


POINT_CLOUD_RENDERERS = (
    ("ramp", tr("Attribute by Ramp")),
    ("rgb", tr("RGB")),
    ("classified", tr("Classification")),
    ("extent", tr("Extent Only")),
)


def _attribute_names(layer):
    return {a.name() for a in layer.attributes().attributes()}


def point_cloud_choices(layer):
    """[(Typ, Beschriftung)]; RGB und Klassifizierung nur, wenn die Attribute da sind."""
    if not is_point_cloud(layer):
        return []
    names = _attribute_names(layer)
    out = []
    for name, label in POINT_CLOUD_RENDERERS:
        if name == "rgb" and not {"Red", "Green", "Blue"} <= names:
            continue
        if name == "classified" and "Classification" not in names:
            continue
        out.append((name, label))
    return out


def point_cloud_renderer_type(layer):
    if not is_point_cloud(layer) or layer.renderer() is None:
        return None
    return layer.renderer().type()


def _ramp_renderer(layer):
    renderer = QgsPointCloudAttributeByRampRenderer()
    renderer.setAttribute("Z")
    stats = layer.statistics()
    low, high = stats.minimum("Z"), stats.maximum("Z")
    if not (math.isfinite(low) and math.isfinite(high) and low < high):
        low, high = renderer.minimum(), renderer.maximum()
    renderer.setMinimum(low)
    renderer.setMaximum(high)
    ramp = QgsStyle.defaultStyle().colorRamp("Viridis")
    if ramp is not None:
        shader = QgsColorRampShader(low, high, ramp)
        shader.classifyColorRamp(5, -1, QgsRectangle(), None)
        renderer.setColorRampShader(shader)
    return renderer


def set_point_cloud_renderer(layer, name):
    old = layer.renderer()
    if old is not None and old.type() == name:
        return False
    if name == "ramp":
        new = _ramp_renderer(layer)
    elif name == "rgb":
        new = QgsPointCloudRgbRenderer()
    elif name == "classified":
        new = QgsPointCloudClassifiedRenderer()
        new.setAttribute("Classification")
        new.setCategories(QgsPointCloudRendererRegistry.classificationAttributeCategories(layer))
    elif name == "extent":
        new = QgsPointCloudExtentRenderer()
    else:
        raise ValueError(tr("Unknown renderer: %s") % name)
    if old is not None:
        old.copyCommonProperties(new)
    layer.setRenderer(new)
    layer_ops.changed(layer)
    return True


POINT_SIZE_RANGE = (0.1, 100.0)
SCREEN_ERROR_RANGE = (0.1, 100.0)


def point_size(layer):
    return layer.renderer().pointSize()


def max_screen_error(layer):
    return layer.renderer().maximumScreenError()


def _change_point_cloud(layer, change):
    renderer = layer.renderer().clone()
    change(renderer)
    layer.setRenderer(renderer)
    layer_ops.changed(layer)


def set_point_size(layer, value):
    _change_point_cloud(layer, lambda r: r.setPointSize(float(value)))


def set_max_screen_error(layer, value):
    _change_point_cloud(layer, lambda r: r.setMaximumScreenError(float(value)))


# -- Netze ----------------------------------------------------------------

def is_mesh(layer):
    return isinstance(layer, QgsMeshLayer)


def mesh_groups(layer, vector=False):
    """[(Index, Name)] der Datensatzgruppen; ``vector``: nur Vektorgruppen."""
    if not is_mesh(layer):
        return []
    out = []
    for index in layer.datasetGroupsIndexes():
        meta = layer.datasetGroupMetadata(QgsMeshDatasetIndex(index, 0))
        if vector and not meta.isVector():
            continue
        out.append((index, meta.name()))
    return out


def mesh_active_group(layer, vector=False):
    """Index der dargestellten Gruppe, -1 = keine."""
    settings = layer.rendererSettings()
    return settings.activeVectorDatasetGroup() if vector else settings.activeScalarDatasetGroup()


def set_mesh_active_group(layer, index, vector=False):
    settings = layer.rendererSettings()
    if vector:
        settings.setActiveVectorDatasetGroup(int(index))
    else:
        settings.setActiveScalarDatasetGroup(int(index))
    layer.setRendererSettings(settings)
    layer_ops.changed(layer)


def mesh_frame(layer):
    return layer.rendererSettings().nativeMeshSettings().isEnabled()


def set_mesh_frame(layer, on):
    settings = layer.rendererSettings()
    mesh = settings.nativeMeshSettings()
    mesh.setEnabled(bool(on))
    settings.setNativeMeshSettings(mesh)
    layer.setRendererSettings(settings)
    layer_ops.changed(layer)


# -- Aggregation ------------------------------------------------------------

AGGREGATIONS = (
    ("none", tr("None")),
    ("pointCluster", tr("Point Cluster")),
    ("pointDisplacement", tr("Point Displacement")),
    ("heatmapRenderer", tr("Heatmap")),
)
_EMBEDDING = ("pointCluster", "pointDisplacement")


def can_aggregate(layer):
    return layer_ops.is_vector(layer) and layer.geometryType() == Qgis.GeometryType.Point


def aggregation(layer):
    if not can_aggregate(layer) or layer.renderer() is None:
        return None
    kind = layer.renderer().type()
    return kind if kind in dict(AGGREGATIONS) else "none"


def _base_renderer(layer, saved):
    """Darstellung ohne Aggregation (eingebettete, vor der Heatmap gemerkte oder Standard)."""
    renderer = layer.renderer()
    kind = renderer.type() if renderer is not None else None
    if kind in _EMBEDDING and renderer.embeddedRenderer() is not None:
        return renderer.embeddedRenderer().clone()
    if kind == "heatmapRenderer" or renderer is None:
        before = saved.pop(layer.id(), None)
        return before if before is not None else QgsFeatureRenderer.defaultRenderer(layer.geometryType())
    return renderer.clone()


def set_aggregation(layer, name, saved):
    """Aggregation setzen. ``saved``: Layer-ID -> Darstellung vor der Heatmap (für „Keine“)."""
    if name not in dict(AGGREGATIONS):
        raise ValueError(tr("Unknown renderer: %s") % name)
    if aggregation(layer) == name:
        return False
    base = _base_renderer(layer, saved)
    if name == "none":
        new = base
    elif name == "pointCluster":
        new = QgsPointClusterRenderer.convertFromRenderer(base)
    elif name == "pointDisplacement":
        new = QgsPointDisplacementRenderer.convertFromRenderer(base)
    else:
        saved[layer.id()] = base
        new = QgsHeatmapRenderer.convertFromRenderer(base)
    layer.setRenderer(new)
    layer_ops.changed(layer)
    return True
