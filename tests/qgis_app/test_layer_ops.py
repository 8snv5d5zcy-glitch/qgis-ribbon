"""Operationen der eigenen Befehle auf echten QGIS-Layern."""
import pytest
from qgis.core import (QgsBookmark, QgsCoordinateReferenceSystem, QgsPalLayerSettings, QgsProject,
                       QgsRectangle, QgsReferencedRectangle, QgsRuleBasedLabeling)
from qgis.PyQt.QtGui import QColor, QPainter

from qgis_ribbon.qgis_integration import layer_ops


def styled(layer):
    """Zählt styleChanged, damit Legende und Layer-Styling mitbekommen, dass sich etwas geändert hat."""
    calls = []
    layer.styleChanged.connect(lambda: calls.append(1))
    return calls


def test_scale_range(layers):
    v = layers["vector"]
    assert layer_ops.scale_range(v) == (False, 0.0, 0.0)
    calls = styled(v)
    layer_ops.set_layer_scale(v, "max", 1000)
    layer_ops.set_layer_scale(v, "min", 50000)
    # Eine Grenze setzen schaltet den Bereich ein (wie in Pro)
    assert layer_ops.scale_range(v) == (True, 1000.0, 50000.0)
    layer_ops.set_scale_range_enabled(v, False)
    assert not v.hasScaleBasedVisibility() and v.maximumScale() == 1000.0
    assert calls


@pytest.mark.parametrize("kind", ["vector", "raster"])
def test_opacity_and_blend_mode(layers, kind):
    layer = layers[kind]
    layer_ops.set_opacity(layer, 0.4)
    assert layer_ops.opacity(layer) == pytest.approx(0.4)
    layer_ops.set_opacity(layer, 7)                     # wird begrenzt
    assert layer_ops.opacity(layer) == 1.0
    layer_ops.set_blend_mode(layer, QPainter.CompositionMode_Multiply)
    assert layer_ops.blend_mode(layer) == QPainter.CompositionMode_Multiply


def test_labels_enable_creates_simple_labeling(layers):
    v = layers["vector"]
    assert not layer_ops.labels_enabled(v) and layer_ops.label_settings(v) == []
    layer_ops.set_labels_enabled(v, True)
    assert layer_ops.labels_enabled(v)
    assert layer_ops.label_settings(v)[0].fieldName == "name"
    layer_ops.set_labels_enabled(v, False)
    assert not layer_ops.labels_enabled(v) and v.labeling() is not None
    # Tabellen und Raster haben keine Beschriftung
    layer_ops.set_labels_enabled(layers["table"], True)
    assert not layer_ops.labels_enabled(layers["table"])


def test_label_scale_and_text_format(layers):
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    layer_ops.set_label_scale(v, "max", 500)
    assert layer_ops.label_scale_range(v) == (True, 500.0, 0.0)
    layer_ops.clear_label_scales(v)
    assert layer_ops.label_scale_range(v) == (False, 0.0, 0.0)

    layer_ops.set_font_size(v, 13)
    assert layer_ops.text_format(v).size() == 13
    layer_ops.change_font_size(v, +1)
    assert layer_ops.text_format(v).size() == 14
    layer_ops.change_font_size(v, -1)
    layer_ops.change_font_size(v, -1)
    assert layer_ops.text_format(v).size() == 11
    layer_ops.set_font_color(v, QColor("#ff0000"))
    assert layer_ops.text_format(v).color().name() == "#ff0000"
    family = layer_ops.text_format(v).font().family()
    layer_ops.set_font_family(v, family)
    layer_ops.set_font_style(v, "Bold")
    assert layer_ops.text_format(v).namedStyle() == "Bold"


def test_step_font_size():
    assert layer_ops.step_font_size(10, +1) == 11
    assert layer_ops.step_font_size(12, +1) == 14
    assert layer_ops.step_font_size(13, -1) == 12
    assert layer_ops.step_font_size(72, +1) == 72
    assert layer_ops.step_font_size(6, -1) == 6


def test_rule_based_labeling_changes_all_rules(layers):
    v = layers["vector"]
    root = QgsRuleBasedLabeling.Rule(None)
    for expr in ("\"name\" = 'p0'", "\"name\" <> 'p0'"):
        s = QgsPalLayerSettings()
        s.fieldName = "name"
        rule = QgsRuleBasedLabeling.Rule(s)
        rule.setFilterExpression(expr)
        root.appendChild(rule)
    v.setLabeling(QgsRuleBasedLabeling(root))
    v.setLabelsEnabled(True)
    layer_ops.set_font_size(v, 20)
    assert [s.format().size() for s in layer_ops.label_settings(v)] == [20, 20]


def test_renderer_switch(layers):
    v = layers["vector"]
    assert layer_ops.renderer_type(v) == "singleSymbol"
    names = [n for n, _label in layer_ops.renderer_choices(v)]
    assert names[:4] == ["singleSymbol", "categorizedSymbol", "graduatedSymbol", "RuleRenderer"]
    assert "heatmapRenderer" in names                   # Punktlayer
    calls = styled(v)
    assert layer_ops.set_renderer(v, "categorizedSymbol")
    assert layer_ops.renderer_type(v) == "categorizedSymbol"
    assert layer_ops.set_renderer(v, "RuleRenderer")
    assert layer_ops.set_renderer(v, "singleSymbol")
    assert not layer_ops.set_renderer(v, "singleSymbol")  # schon gesetzt
    assert calls
    assert layer_ops.renderer_choices(layers["table"]) == []


def test_identify_mode_in_own_settings(settings):
    assert layer_ops.identify_mode(settings) == "ActiveLayer"
    layer_ops.set_identify_mode("TopDownAll", settings)
    assert layer_ops.identify_mode(settings) == "TopDownAll"
    settings.setValue(layer_ops.IDENTIFY_KEY, 1)        # alter Zahlenwert
    assert layer_ops.identify_mode(settings) == "TopDownStopAtFirst"
    with pytest.raises(ValueError):
        layer_ops.set_identify_mode("Alle", settings)


def test_bookmarks_and_zoom(fake_iface):
    manager = QgsProject.instance().bookmarkManager()
    crs = QgsCoordinateReferenceSystem("EPSG:4326")
    b = QgsBookmark()
    b.setName("Testgebiet")
    b.setExtent(QgsReferencedRectangle(QgsRectangle(10, 50, 11, 51), crs))
    manager.addBookmark(b)
    try:
        found = [bm for section, bm in layer_ops.bookmarks() if section == "Projekt"]
        assert [bm.name() for bm in found] == ["Testgebiet"]
        canvas = fake_iface.mapCanvas()
        canvas.setDestinationCrs(crs)
        canvas.resize(400, 400)
        layer_ops.zoom_to_bookmark(canvas, found[0])
        assert canvas.extent().contains(QgsRectangle(10.1, 50.1, 10.9, 50.9))
    finally:
        manager.clear()


def test_xyz_uri_and_basemap():
    uri = layer_ops.xyz_uri("https://example.org/{z}/{x}/{y}.png", 0, 17)
    assert "type=xyz" in uri and "zmax=17" in uri
    project = QgsProject.instance()
    layer = layer_ops.add_basemap("Testkarte", "https://example.org/{z}/{x}/{y}.png", 0, 17, "© Test")
    try:
        assert layer is not None and layer.isValid()
        assert project.layerTreeRoot().findLayer(layer.id()) is not None
        # Grundkarte liegt unten
        assert project.layerTreeRoot().children()[-1].layerId() == layer.id()
        assert "© Test" in layer.metadata().rights()
    finally:
        project.removeAllMapLayers()


def test_xyz_connections_returns_list():
    for name, url, zmin, zmax in layer_ops.xyz_connections():
        assert name and url and zmin <= zmax
