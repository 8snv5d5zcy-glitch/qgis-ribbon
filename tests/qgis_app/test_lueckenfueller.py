"""Lückenfüller: Raster, Beschriftungsklassen, Karte, Auswahl per Linie, Domänen."""
import copy

import pytest
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransformContext,
                       QgsFeature, QgsField, QgsFields, QgsGeometry, QgsMapLayer, QgsPalLayerSettings,
                       QgsPointXY, QgsProject, QgsRasterLayer, QgsRuleBasedLabeling, QgsVectorFileWriter,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsWkbTypes)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QApplication, QDialogButtonBox, QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.core import domains as dm
from qgis_ribbon.qgis_integration import (builtin_commands, custom_commands, domains, layer_ops,
                                          raster_ops)
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.layer_watch import LayerWatch
from qgis_ribbon.qgis_integration.map_tools import SelectByLineTool, select_by_line
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui import dialog_commands, domain_dialog
from qgis_ribbon.ui.controls import custom as custom_controls
from qgis_ribbon.ui.controls.gallery import COMPACT_TILE_WIDTH, TILE_WIDTH, RibbonGallery
from qgis_ribbon.ui.ribbon_widget import RibbonWidget


def settle():
    for _ in range(3):
        QApplication.processEvents()


# -- Daten ----------------------------------------------------------------------------

@pytest.fixture
def multiband(tmp_path):
    """GeoTIFF mit vier Kanälen (R, G, B, NIR wie ein DOP)."""
    import numpy as np
    from osgeo import gdal
    path = str(tmp_path / "dop.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 20, 10, 4, gdal.GDT_Byte)
    ds.SetGeoTransform((0, 1, 0, 10, 0, -1))
    for b in range(1, 5):
        ds.GetRasterBand(b).WriteArray((np.arange(200).reshape(10, 20) % 250 + b).astype("uint8"))
    ds = None
    layer = QgsRasterLayer(path, "DOP")
    assert layer.isValid() and layer.bandCount() == 4
    return layer


def polygons():
    layer = QgsVectorLayer("Polygon?crs=EPSG:25832&field=name:string", "Flächen", "memory")
    feats = []
    for i in range(3):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromRect(QgsGeometry.fromWkt(
            "POLYGON((%d 0, %d 0, %d 1, %d 1, %d 0))" % (i * 2, i * 2 + 1, i * 2 + 1, i * 2, i * 2))
            .boundingBox()))
        f.setAttributes(["f%d" % i])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    return layer


@pytest.fixture
def gpkg(tmp_path):
    """GeoPackage mit Text-, Ganzzahl- und Dezimalfeld; Layer im Projekt."""
    path = str(tmp_path / "daten.gpkg")
    fields = QgsFields()
    for name, t in (("art", QVariant.String), ("hoehe", QVariant.Int), ("wert", QVariant.Double)):
        fields.append(QgsField(name, t))
    for table in ("punkte", "linien"):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = table
        if table == "linien":
            opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        w = QgsVectorFileWriter.create(path, fields, QgsWkbTypes.Point,
                                       QgsCoordinateReferenceSystem("EPSG:25832"),
                                       QgsCoordinateTransformContext(), opts)
        del w
    layer = QgsVectorLayer(path + "|layername=punkte", "Punkte", "ogr")
    other = QgsVectorLayer(path + "|layername=linien", "Linien", "ogr")
    assert layer.isValid() and other.isValid()
    QgsProject.instance().addMapLayers([layer, other])
    yield layer, other, path
    QgsProject.instance().removeAllMapLayers()


# -- Raster -----------------------------------------------------------------------------

def test_enhancement_is_clamped(multiband):
    raster_ops.set_brightness(multiband, 40)
    raster_ops.set_contrast(multiband, -500)
    raster_ops.set_gamma(multiband, 0.0)
    assert raster_ops.enhancement(multiband) == (40, -100, pytest.approx(0.1))


def test_renderer_choices_and_switch(multiband, layers):
    assert [t for t, _l in raster_ops.renderer_choices(multiband)] == [
        "multibandcolor", "singlebandgray", "singlebandpseudocolor", "hillshade", "contour"]
    single = layers["raster"]
    assert "multibandcolor" not in [t for t, _l in raster_ops.renderer_choices(single)]
    for name in ("singlebandgray", "singlebandpseudocolor", "hillshade", "contour", "multibandcolor"):
        assert raster_ops.set_renderer(multiband, name)
        assert raster_ops.renderer_type(multiband) == name
    assert not raster_ops.set_renderer(multiband, "multibandcolor")     # schon gesetzt
    shader = None
    raster_ops.set_renderer(multiband, "singlebandpseudocolor")
    shader = multiband.renderer().shader().rasterShaderFunction()
    assert shader.colorRampItemList()                                   # klassifiziert


def test_band_combinations(multiband):
    combos = raster_ops.band_combinations(multiband)
    labels = [c[0] for c in combos]
    assert labels[:3] == ["Natürliche Farben (1-2-3)", "Farbinfrarot (4-1-2)", "Umgekehrt (3-2-1)"]
    assert "Kanäle 2-3-4" in labels
    raster_ops.set_bands(multiband, (4, 1, 2))
    assert raster_ops.current_bands(multiband) == (4, 1, 2)
    raster_ops.set_renderer(multiband, "singlebandgray")
    assert raster_ops.current_bands(multiband) is None
    raster_ops.set_bands(multiband, (1, 2, 3))                         # wieder Mehrkanal
    assert raster_ops.current_bands(multiband) == (1, 2, 3)


def test_resampling(multiband):
    assert raster_ops.resampling(multiband) == "nearest"
    for name in ("bilinear", "cubic", "nearest"):
        raster_ops.set_resampling(multiband, name)
        assert raster_ops.resampling(multiband) == name
    with pytest.raises(ValueError):
        raster_ops.set_resampling(multiband, "lanczos")


# -- Beschriftung -------------------------------------------------------------------

def rule_based(layer):
    root = QgsRuleBasedLabeling.Rule(None)
    for name, flt in (("Groß", '"name" = \'p0\''), ("Klein", "")):
        s = QgsPalLayerSettings()
        s.fieldName = "name"
        rule = QgsRuleBasedLabeling.Rule(s)
        rule.setDescription(name)
        rule.setFilterExpression(flt)
        root.appendChild(rule)
    layer.setLabeling(QgsRuleBasedLabeling(root))
    layer.setLabelsEnabled(True)


def test_label_classes_simple_and_rule_based(layers):
    v = layers["vector"]
    assert layer_ops.label_classes(v) == []
    layer_ops.set_labels_enabled(v, True)
    assert layer_ops.label_classes(v) == [("", "Standard", True)]
    layer_ops.set_label_class_active(v, "", False)
    assert not v.labelsEnabled()
    rule_based(v)
    classes = layer_ops.label_classes(v)
    assert [c[1] for c in classes] == ["Groß", "Klein"]
    key = classes[1][0]
    layer_ops.set_label_class_active(v, key, False)
    assert not layer_ops.label_class_active(v, key) and layer_ops.label_class_active(v, classes[0][0])
    layer_ops.set_label_field(v, key, "upper(\"name\")", True)
    s = layer_ops.label_class_settings(v, key)
    assert s.isExpression and s.fieldName == 'upper("name")'
    assert layer_ops.label_class_settings(v, classes[0][0]).fieldName == "name"   # nur diese Klasse
    assert layer_ops.label_class_filter(v, classes[0][0]) == '"name" = \'p0\''


def test_filter_turns_simple_labeling_into_rule(layers):
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    key = layer_ops.set_label_class_filter(v, "", '"name" <> \'p1\'')
    assert isinstance(v.labeling(), QgsRuleBasedLabeling)
    assert layer_ops.label_classes(v) == [(key, "Standard", True)]
    assert layer_ops.label_class_filter(v, key) == '"name" <> \'p1\''
    assert layer_ops.label_expression(layer_ops.label_class_settings(v, key)) == '"name"'


def test_new_and_deleted_label_class(layers):
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    key = layer_ops.add_label_class(v, "", "Hauptorte")
    assert isinstance(v.labeling(), QgsRuleBasedLabeling)
    classes = layer_ops.label_classes(v)
    assert [c[1] for c in classes] == ["Standard", "Hauptorte"] and classes[1][0] == key
    assert layer_ops.label_class_filter(v, key) == ""
    assert layer_ops.label_class_settings(v, key).fieldName == "name"      # Muster der gewählten Klasse
    first = classes[0][0]
    assert layer_ops.remove_label_class(v, first) == key
    assert [c[1] for c in layer_ops.label_classes(v)] == ["Hauptorte"]
    assert layer_ops.remove_label_class(v, key) is None                    # die letzte bleibt
    # Ohne Beschriftung: neue Klasse legt Standard und die neue an und schaltet ein
    other = polygons()
    layer_ops.add_label_class(other, None, "Neu")
    assert [c[1] for c in layer_ops.label_classes(other)] == ["Standard", "Neu"] and other.labelsEnabled()


def test_label_on_gives_lines_parallel_placement():
    line = QgsVectorLayer("LineString?crs=EPSG:25832&field=name:string", "Linien", "memory")
    layer_ops.set_labels_enabled(line, True)
    assert layer_ops.label_placement(line) == "Line"                       # „Parallel“
    # Vorhandene Beschriftung mit „Um Punkt“ (QGIS beschriftet Linien damit nicht)
    s = QgsPalLayerSettings()
    s.fieldName = "name"
    s.placement = Qgis.LabelPlacement.AroundPoint
    line.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer_ops.set_labels_enabled(line, True)
    assert layer_ops.label_placement(line) == "Line"
    # Punkte und Flächen behalten ihre (passende) Platzierung
    poly = polygons()
    layer_ops.set_labels_enabled(poly, True)
    assert layer_ops.label_placement(poly) == "AroundPoint"


def test_label_class_commands_update_class_list(ribbon, fake_iface, layers, monkeypatch):
    from types import SimpleNamespace
    w, _watch, env = ribbon
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    fake_iface.set_active_layer(v)
    settle()
    klasse = control(w, "klasse")
    monkeypatch.setattr(builtin_commands.QInputDialog, "getText", lambda *a, **k: ("Groß", True))
    builtin_commands.beschriftung_regel_neu(env, SimpleNamespace(label="Neue Klasse"))()
    settle()
    assert [klasse.editor.itemText(i) for i in range(klasse.editor.count())] == ["Standard", "Groß"]
    assert klasse.editor.currentText() == "Groß"
    delete = builtin_commands.beschriftung_regel_loeschen(env, SimpleNamespace(label="Klasse löschen"))
    assert delete.isEnabled()
    monkeypatch.setattr(builtin_commands.QMessageBox, "question", lambda *a, **k: builtin_commands.QMessageBox.No)
    delete.trigger()
    assert len(layer_ops.label_classes(v)) == 2                            # abgelehnt
    monkeypatch.setattr(builtin_commands.QMessageBox, "question", lambda *a, **k: builtin_commands.QMessageBox.Yes)
    delete.trigger()
    settle()
    assert [klasse.editor.itemText(i) for i in range(klasse.editor.count())] == ["Standard"]
    assert not delete.isEnabled()                                          # die letzte bleibt


def test_discard_edits_of_active_layer_only(ribbon, fake_iface, layers, monkeypatch):
    from types import SimpleNamespace
    _w, _watch, env = ribbon
    v, other = layers["vector"], polygons()
    fake_iface.set_active_layer(v)
    settle()
    discard = builtin_commands.layer_aenderungen_verwerfen(env, SimpleNamespace(label="Verwerfen"))
    assert not discard.isEnabled()
    v.startEditing()
    other.startEditing()
    settle()
    assert not discard.isEnabled()                                         # nichts geändert
    for layer, geom in ((v, "POINT(5 5)"), (other, "POLYGON((0 0, 1 0, 1 1, 0 0))")):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromWkt(geom))
        layer.addFeature(f)
    settle()
    assert discard.isEnabled()                                             # über layerModified
    monkeypatch.setattr(builtin_commands.QMessageBox, "question", lambda *a, **k: builtin_commands.QMessageBox.No)
    discard.trigger()
    assert v.isModified()                                                  # abgelehnt
    monkeypatch.setattr(builtin_commands.QMessageBox, "question", lambda *a, **k: builtin_commands.QMessageBox.Yes)
    discard.trigger()
    settle()
    assert v.featureCount() == 3 and v.isEditable() and not v.isModified()
    assert other.isModified()                                              # anderer Layer bleibt
    assert not discard.isEnabled()
    f = QgsFeature(v.fields())
    f.setGeometry(QgsGeometry.fromWkt("POINT(6 6)"))
    assert v.addFeature(f)                                                 # weiter bearbeitbar
    v.rollBack()
    other.rollBack()


def test_label_placement(layers):
    v = layers["vector"]
    assert [n for n, _l in layer_ops.placement_choices(v)] == [
        "OrderedPositionsAroundPoint", "AroundPoint", "OverPoint"]
    assert [n for n, _l in layer_ops.placement_choices(polygons())][-1] == "OutsidePolygons"
    layer_ops.set_labels_enabled(v, True)
    layer_ops.set_label_placement(v, "OverPoint")
    assert layer_ops.label_placement(v) == "OverPoint"
    assert isinstance(v.labeling(), QgsVectorLayerSimpleLabeling)


def test_identifiable_and_source_path(gpkg, layers):
    layer, other, path = gpkg
    states = dict((l.name(), on) for l, on in layer_ops.identifiable_layers())
    assert states == {"Punkte": True, "Linien": True}
    layer_ops.set_identifiable(other, False)
    assert not other.flags() & QgsMapLayer.Identifiable
    assert layer_ops.source_path(layer) == path + "|layername=punkte"
    assert layer_ops.source_path(layers["vector"]).startswith("Point?")
    assert layer_ops.source_path(None) == ""


# -- Auswahl per Linie -------------------------------------------------------------------

def test_select_by_line_behaviors():
    layer = polygons()
    crs = layer.crs()
    line = QgsGeometry.fromPolylineXY([QgsPointXY(-1, 0.5), QgsPointXY(2.5, 0.5)])
    assert select_by_line(layer, line, crs) == 2
    assert sorted(layer.selectedFeatureIds()) == [1, 2]
    third = QgsGeometry.fromPolylineXY([QgsPointXY(4.5, -1), QgsPointXY(4.5, 2)])
    select_by_line(layer, third, crs, Qgis.SelectBehavior.AddToSelection)
    assert sorted(layer.selectedFeatureIds()) == [1, 2, 3]
    select_by_line(layer, line, crs, Qgis.SelectBehavior.RemoveFromSelection)
    assert layer.selectedFeatureIds() == [3]
    # Linie in anderem KBS (Web-Mercator-Koordinaten sind hier nur verschoben gedacht)
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    far = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(1, 1)])
    assert select_by_line(layer, far, wgs) == 0


def test_tool_finish_uses_active_layer(fake_iface):
    layer = polygons()
    canvas = fake_iface.mapCanvas()
    canvas.setDestinationCrs(layer.crs())
    tool = SelectByLineTool(canvas, lambda: layer)
    tool._points = [QgsPointXY(-1, 0.5), QgsPointXY(0.5, 0.5)]
    assert tool.finish() == 1 and layer.selectedFeatureIds() == [1]
    tool._points = [QgsPointXY(0, 0)]
    assert tool.finish() is None                                       # zu kurz
    tool.close()


# -- Steuerelemente und Befehle im Ribbon -------------------------------------------------

def custom(cid):
    return {"type": "custom", "id": cid}


DEFINITION = {
    "version": 1,
    "commands": {
        "verschieben": {"label": "Verschieben", "source": {"type": "qgis_action", "object_name": "mActionPan"}},
        "zoomen": {"label": "Hineinzoomen", "source": {"type": "qgis_action", "object_name": "mActionZoomIn"}},
        "werkzeuge": {"label": "Werkzeuge", "kind": "control", "source": custom("ribbon.editor_galerie"),
                      "gallery": {"display": "ribbon", "columns": 1, "items": ["verschieben", "zoomen"]}},
        "drehung": {"label": "Drehung", "kind": "control", "source": custom("ribbon.kartendrehung")},
        "lupe": {"label": "Lupe", "kind": "control", "source": custom("ribbon.lupe")},
        "helligkeit": {"label": "Helligkeit", "kind": "control", "source": custom("ribbon.raster_helligkeit")},
        "gamma": {"label": "Gamma", "kind": "control", "source": custom("ribbon.raster_gamma")},
        "klasse": {"label": "Klasse", "kind": "control", "source": custom("ribbon.beschriftung_regel")},
        "aktiv": {"label": "Klasse beschriften", "kind": "control",
                  "source": custom("ribbon.beschriftung_regel_aktiv")},
        "feld": {"label": "Feld", "kind": "control", "source": custom("ribbon.beschriftung_feld")},
        "linie": {"label": "Auswahl per Linie", "source": custom("ribbon.auswahl_linie")},
        "groesse": {"label": "Galeriegröße", "source": custom("ribbon.galerie_groesse")},
        "pfad": {"label": "Pfad kopieren", "source": custom("ribbon.layerpfad_kopieren")},
        "abfragbar": {"label": "Abfragbare Layer", "kind": "control", "source": custom("ribbon.abfragbare_layer"),
                      "gallery": {}},
        "platzierung": {"label": "Platzierung", "kind": "control", "source": custom("ribbon.platzierung_galerie"),
                        "gallery": {}},
        "kanaele": {"label": "Kanalkombination", "kind": "control", "source": custom("ribbon.raster_kanaele"),
                    "gallery": {}},
    },
    "tabs": [{"id": "karte", "label": "Karte", "groups": [
        {"id": "a", "label": "A", "items": [
            {"menu": "Werkzeuge", "gallery": "werkzeuge", "items": ["zoomen"]},
            {"command": "drehung", "size": "medium"}, {"command": "lupe", "size": "medium"},
            {"command": "helligkeit", "size": "medium"}, {"command": "gamma", "size": "medium"},
        ]},
        {"id": "b", "label": "B", "items": [
            {"command": "klasse", "size": "medium"}, {"command": "aktiv", "size": "medium"},
            {"command": "feld", "size": "medium"},
            {"command": "linie", "size": "large"}, {"command": "groesse", "size": "large"},
            {"command": "pfad", "size": "large"},
            {"command": "abfragbar", "size": "large"}, {"command": "platzierung", "size": "large"},
            {"command": "kanaele", "size": "large"},
            {"split": "verschieben", "items": ["platzierung"], "size": "large"},
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
    w.resize(1600, 140)
    w.show()
    settle()
    yield w, watch, env
    watch.stop()
    hub.disconnect_all()
    resolver.clear()
    builtin_commands.unregister_all()
    custom_controls.unregister_all()
    w.deleteLater()
    settle()


def control(w, cid):
    return w.findChild(QWidget, "ribbon_control_" + cid)


def button(w, label):
    for b in w.findChildren(QToolButton):
        if b.defaultAction() is not None and b.defaultAction().text() == label:
            return b
    raise AssertionError(label)


def test_map_rotation_and_magnifier(ribbon, fake_iface):
    w, _watch, _env = ribbon
    canvas = fake_iface.mapCanvas()
    rot, mag = control(w, "drehung"), control(w, "lupe")
    assert rot.isEnabled() and mag.isEnabled()
    rot.editor.setValue(30.0)
    assert canvas.rotation() == pytest.approx(30.0)
    canvas.setRotation(270.0)                       # außerhalb geändert (Statusleiste)
    settle()
    assert rot.editor.value() == pytest.approx(-90.0)
    mag.editor.setValue(200.0)
    assert canvas.magnificationFactor() == pytest.approx(2.0)
    canvas.setMagnificationFactor(1.5)
    settle()
    assert mag.editor.value() == pytest.approx(150.0)


def test_raster_controls_follow_active_layer(ribbon, fake_iface, multiband, layers):
    w, _watch, _env = ribbon
    bright, gamma = control(w, "helligkeit"), control(w, "gamma")
    fake_iface.set_active_layer(layers["vector"])
    settle()
    assert not bright.isEnabled()
    fake_iface.set_active_layer(multiband)
    settle()
    assert bright.isEnabled() and gamma.editor.value() == pytest.approx(1.0)
    bright.editor.setValue(25)
    gamma.editor.setValue(1.8)
    assert raster_ops.enhancement(multiband)[0] == 25
    assert raster_ops.enhancement(multiband)[2] == pytest.approx(1.8)


def test_label_class_controls_share_selection(ribbon, fake_iface, layers):
    w, _watch, _env = ribbon
    v = layers["vector"]
    rule_based(v)
    fake_iface.set_active_layer(v)
    settle()
    klasse, aktiv, feld = control(w, "klasse"), control(w, "aktiv"), control(w, "feld")
    assert [klasse.editor.itemText(i) for i in range(klasse.editor.count())] == ["Groß", "Klein"]
    assert aktiv.editor.isChecked() and aktiv.editor.text() == "Klasse beschriften"
    key_small = layer_ops.label_classes(v)[1][0]
    layer_ops.set_label_class_active(v, key_small, False)
    klasse.editor.setCurrentIndex(1)
    klasse.editor.activated.emit(1)
    settle()
    assert not aktiv.editor.isChecked()              # zeigt die gewählte Klasse
    aktiv.editor.setChecked(True)
    assert layer_ops.label_class_active(v, key_small)
    feld.editor.setExpression('"name" || \'!\'')
    feld.editor.fieldChanged[str, bool].emit('"name" || \'!\'', True)
    assert layer_ops.label_class_settings(v, key_small).fieldName == '"name" || \'!\''
    assert layer_ops.label_class_settings(v, layer_ops.label_classes(v)[0][0]).fieldName == "name"


def test_select_by_line_button_toggles_tool_and_unsets_on_close(ribbon, fake_iface):
    w, _watch, env = ribbon
    canvas = fake_iface.mapCanvas()
    fake_iface.set_active_layer(polygons())
    settle()
    btn = button(w, "Auswahl per Linie")
    act = btn.defaultAction()
    assert act.isEnabled() and act.isCheckable() and not act.isChecked()
    act.trigger()
    settle()
    assert isinstance(canvas.mapTool(), SelectByLineTool) and act.isChecked()
    act.trigger()
    settle()
    assert canvas.mapTool() is None and not act.isChecked()
    act.trigger()
    settle()
    env.close()                                     # wie beim Entladen
    assert canvas.mapTool() is None


def test_gallery_size_toggles_ribbon_gallery_and_is_saved(ribbon, settings):
    w, _watch, _env = ribbon
    gallery = w.findChild(RibbonGallery)
    tiles = gallery.grid.tiles
    assert [t.isHidden() for t in tiles] == [False, True]
    assert tiles[0].width() == TILE_WIDTH
    act = button(w, "Galeriegröße").defaultAction()
    act.trigger()
    settle()
    assert [t.isHidden() for t in tiles] == [False, False]
    assert tiles[0].width() == COMPACT_TILE_WIDTH and act.isChecked()
    assert str(settings.value(builtin_commands.GALLERY_COMPACT_KEY)).lower() == "true"
    act.trigger()
    settle()
    assert tiles[1].isHidden() and not act.isChecked()


def test_copy_path(ribbon, fake_iface, gpkg):
    w, _watch, _env = ribbon
    layer, _other, path = gpkg
    fake_iface.set_active_layer(layer)
    settle()
    button(w, "Pfad kopieren").defaultAction().trigger()
    assert QApplication.clipboard().text() == path + "|layername=punkte"


def gallery_actions(w, label):
    btn = [b for b in w.findChildren(QToolButton) if b.objectName().startswith("ribbon_gallery_btn_")
           and b.text().replace("\n", " ") == label][0]
    btn.menu().aboutToShow.emit()
    return {a.text(): a for a in btn.menu().actions() if a.text()}


def test_identifiable_layers_gallery(ribbon, fake_iface, gpkg, settings):
    w, _watch, _env = ribbon
    layer, other, _path = gpkg
    acts = gallery_actions(w, "Abfragbare Layer")
    assert acts["Punkte"].isChecked() and acts["Linien"].isChecked()
    acts["Linien"].trigger()
    assert not other.flags() & QgsMapLayer.Identifiable
    acts = gallery_actions(w, "Abfragbare Layer")
    assert not acts["Linien"].isChecked()
    acts["Alle abfragbaren Layer abfragen"].trigger()
    assert layer_ops.identify_mode(settings) == "TopDownAll"


def test_placement_and_band_galleries(ribbon, fake_iface, layers, multiband):
    w, _watch, _env = ribbon
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    settle()
    acts = gallery_actions(w, "Platzierung")
    acts["Versetzt zum Punkt"].trigger()
    assert layer_ops.label_placement(v) == "OverPoint" and v.labelsEnabled()
    fake_iface.set_active_layer(multiband)
    settle()
    acts = gallery_actions(w, "Kanalkombination")
    assert acts["Natürliche Farben (1-2-3)"].isChecked()
    assert "Rot: " in acts["Farbinfrarot (4-1-2)"].toolTip()
    acts["Farbinfrarot (4-1-2)"].trigger()
    assert raster_ops.current_bands(multiband) == (4, 1, 2)


def test_split_with_only_a_runtime_gallery_is_usable(ribbon):
    """Menü nur mit Laufzeit-Galerie (Platzhalter unsichtbar): Menüteil trotzdem bedienbar."""
    w, _watch, _env = ribbon
    split = w.findChild(QWidget, "ribbon_split_verschieben")
    assert split.bottom.isEnabled()


def test_every_custom_command_of_the_shipped_ribbon_is_registered():
    ribbon = config_loader.load(config_loader.DEFAULT_CONFIG)
    builtin_commands.register_all()
    custom_controls.register_all()
    dialog_commands.register_all()
    try:
        ids = {c.source.get("id") for c in ribbon.commands.values() if c.source.type == "custom"}
        missing = sorted(i for i in ids if custom_commands.kind_of(i) is None
                         and i not in ("ribbon.editor_galerie", "ribbon.processing_galerie"))
        assert not missing, missing
    finally:
        builtin_commands.unregister_all()
        custom_controls.unregister_all()
        dialog_commands.unregister_all()


# -- Domänen ----------------------------------------------------------------------------------

def test_store_kind_depends_on_data_source(gpkg, layers):
    layer, _other, path = gpkg
    store = domains.store_for(layer)
    assert store.where == "source" and store.table == "punkte" and path in store.title
    assert domains.store_for(layers["vector"]).where == "project"
    assert domains.layer_fields(layer) == {"fid": "integer", "art": "string", "hoehe": "integer",
                                           "wert": "real"}


def make_session(store, layer):
    return dm.DomainSession(store.domains(), domains.layer_fields(layer), store.assignments())


def test_source_domains_add_assign_update_remove(gpkg):
    layer, other, path = gpkg
    store = domains.store_for(layer)
    s = make_session(store, layer)
    s.add(dm.Domain("Arten", "coded", "string", "Baumarten", values=[("E", "Eiche"), ("B", "Buche")]))
    s.add(dm.Domain("Höhen", "range", "integer", minimum="0", maximum="100"))
    s.assign("art", "Arten")
    s.assign("hoehe", "Höhen")
    assert s.problems() == []
    store.apply(s.changes(), s)
    assert sorted(store.conn.fieldDomainNames()) == ["Arten", "Höhen"]
    f = layer.fields().field("art")
    assert f.constraints().domainName() == "Arten"
    assert f.editorWidgetSetup().type() == "ValueMap"
    assert f.editorWidgetSetup().config() == {"map": [{"Eiche": "E"}, {"Buche": "B"}]}
    assert layer.fields().field("hoehe").editorWidgetSetup().config()["Max"] == 100

    # Zweiter Layer derselben Datei nutzt die Domäne auch
    store2 = domains.store_for(other)
    s2 = make_session(store2, other)
    s2.assign("art", "Arten")
    store2.apply(s2.changes(), s2)

    # Werte ändern: alle Layer der Datei bekommen die neue Wertzuordnung
    s = make_session(store, layer)
    d = s.get("Arten").copy()
    d.values = [("E", "Eiche"), ("K", "Kiefer")]
    s.replace("Arten", d)
    store.apply(s.changes(), s)
    assert [v.value() for v in store.conn.fieldDomain("Arten").values()] == ["Eiche", "Kiefer"]
    for lyr in (layer, other):
        assert {"Kiefer": "K"} in lyr.fields().field("art").editorWidgetSetup().config()["map"]

    # Löschen, solange ein anderer Layer sie nutzt: abgelehnt
    s = make_session(store, layer)
    s.assign("art", "")
    s.remove("Arten")
    with pytest.raises(domains.DomainError, match="linien.art"):
        store.apply(s.changes(), s)
    assert layer.fields().field("art").constraints().domainName() == ""   # Zuordnung ist weg
    s2 = make_session(store2, other)
    s2.assign("art", "")
    s2.remove("Arten")
    store2.apply(s2.changes(), s2)
    assert store.conn.fieldDomainNames() == ["Höhen"]
    assert other.fields().field("art").editorWidgetSetup().type() in ("", "TextEdit")


def test_project_domains(layers):
    v, t = layers["vector"], layers["table"]
    project = QgsProject.instance()
    project.addMapLayers([v, t])
    try:
        store = domains.store_for(t)
        assert store.where == "project"
        s = make_session(store, t)
        s.add(dm.Domain("Stufen", "coded", "integer", values=[("1", "Gering"), ("2", "Hoch")]))
        s.assign("wert", "Stufen")
        store.apply(s.changes(), s)
        assert [d.name for d in domains.store_for(v).domains()] == ["Stufen"]   # im Projekt
        assert t.fields().field("wert").editorWidgetSetup().config() == {
            "map": [{"Gering": 1}, {"Hoch": 2}]}
        assert store.assignments() == {"wert": "Stufen"}
        # Ein anderer Layer nutzt sie: Löschen über den ersten Layer abgelehnt
        sv = make_session(domains.store_for(v), v)
        sv.remove("Stufen")
        with pytest.raises(domains.DomainError, match="Tabelle.wert"):
            domains.store_for(v).apply(sv.changes(), sv)
        s = make_session(store, t)
        s.assign("wert", "")
        s.remove("Stufen")
        store.apply(s.changes(), s)
        assert store.domains() == [] and store.assignments() == {}
    finally:
        project.removeMapLayers([v.id(), t.id()])
        project.removeEntry(domains.PROJECT_SCOPE, domains.PROJECT_KEY)


def test_domain_dialog_creates_and_assigns(gpkg, fake_iface, monkeypatch):
    layer, _other, _path = gpkg
    warnings = []
    monkeypatch.setattr(domain_dialog.QMessageBox, "warning",
                        lambda *args: warnings.append(args[2]))
    dlg = domain_dialog.DomainDialog(layer, domains.store_for(layer), fake_iface.mainWindow())
    save = dlg.buttons.button(QDialogButtonBox.Save)
    assert dlg.list.count() == 0 and not save.isEnabled()
    dlg.new_domain("coded")
    assert dlg.list.currentItem().text() == "Neue Domäne"
    assert "Werteliste ist leer" in dlg.status.text() and not save.isEnabled()
    dlg.name_edit.setText("Arten")
    dlg.name_edit.textEdited.emit("Arten")
    dlg.add_value_row()
    dlg.values.item(0, 0).setText("E")
    dlg.values.item(0, 1).setText("Eiche")
    assert dlg.list.currentItem().text() == "Arten"
    assert dlg.problems() == []
    assert dlg.field_combos["hoehe"].findData("Arten") < 0          # passt nicht zu Ganzzahl
    dlg.assign("art", "Arten")
    assert save.isEnabled()
    dlg.save()
    assert dlg.result() == dlg.Accepted
    assert layer.fields().field("art").constraints().domainName() == "Arten"
    # Erneut geöffnet: gespeicherte Domäne mit festem Namen, Art und Feldtyp
    dlg2 = domain_dialog.DomainDialog(layer, domains.store_for(layer), fake_iface.mainWindow())
    assert dlg2.name_edit.isReadOnly() and not dlg2.kind_combo.isEnabled()
    assert dlg2.field_combos["art"].currentData() == "Arten"
    dlg2.delete_current()                                          # noch zugeordnet: bleibt
    assert dlg2.list.count() == 1 and "art" in warnings[-1]
    dlg.deleteLater()
    dlg2.deleteLater()


def test_domain_dialog_command_needs_vector_layer(fake_iface, layers):
    assert domain_dialog.open_dialog(fake_iface, layers["raster"]) is None
