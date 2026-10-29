"""Erweiterte Steuerelemente im Ribbon: Regler, Zustands-Buttons, Galerien, Launcher."""
import copy

import pytest
from qgis.core import QgsApplication
from qgis.gui import QgsOpacityWidget
from qgis.PyQt.QtWidgets import QAction, QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration import builtin_commands, custom_commands, layer_ops
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.layer_watch import LayerWatch
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui.controls import custom as custom_controls
from qgis_ribbon.ui.controls.custom import OpacityControl, ScaleControl
from qgis_ribbon.ui.controls.gallery import RibbonGallery
from qgis_ribbon.ui.ribbon_widget import RibbonWidget


def qa(name):
    return {"type": "qgis_action", "object_name": name}


def custom(cid, *args):
    src = {"type": "custom", "id": cid}
    if args:
        src["args"] = list(args)
    return src


DEFINITION = {
    "version": 1,
    "commands": {
        "verschieben": {"label": "Verschieben", "source": qa("mActionPan")},
        "zoomen": {"label": "Hineinzoomen", "source": qa("mActionZoomIn")},
        "deckkraft": {"label": "Deckkraft", "kind": "control", "source": custom("ribbon.layer_deckkraft"),
                      "description": "Deckkraft des aktiven Layers."},
        "massstab_max": {"label": "Größter Maßstab", "kind": "control",
                         "source": custom("ribbon.layer_massstab_max")},
        "schalten": {"label": "Maßstabsbereich", "source": custom("ribbon.layer_massstab_schalten")},
        "beschriften": {"label": "Beschriften", "source": custom("ribbon.beschriftung_schalten")},
        "groesse": {"label": "Schriftgröße", "kind": "control", "source": custom("ribbon.beschriftung_groesse")},
        "farbe": {"label": "Schriftfarbe", "kind": "control", "source": custom("ribbon.beschriftung_farbe")},
        "abfrage_alle": {"label": "Abfrage: sichtbare Layer", "source": custom("ribbon.abfragemodus", "TopDownAll")},
        "abfrage_aktuell": {"label": "Abfrage: aktueller Layer",
                            "source": custom("ribbon.abfragemodus", "ActiveLayer")},
        "gehe_zu": {"label": "Gehe zu XY", "source": custom("ribbon.locator_fokus", "go ")},
        "werkzeuge": {"label": "Werkzeuge", "kind": "control", "source": custom("ribbon.editor_galerie"),
                      "gallery": {"display": "ribbon", "columns": 1, "items": ["verschieben", "zoomen"]}},
        "darstellung": {"label": "Darstellungsart", "kind": "control",
                        "source": custom("ribbon.renderer_galerie"), "gallery": {}},
        "optionen": {"label": "Optionen Kartenwerkzeuge", "description": "Optionen öffnen.",
                     "source": {"type": "iface_method", "method": "showOptionsDialog",
                                "args": [None, "mOptionsPageMapTools"]}},
    },
    "tabs": [{"id": "karte", "label": "Karte", "groups": [
        {"id": "layer", "label": "Layer", "launcher": "optionen", "items": [
            {"command": "deckkraft", "size": "medium"},
            {"command": "massstab_max", "size": "medium"},
            {"command": "schalten", "size": "large"},
            {"row": ["groesse", "farbe", "beschriften"]},
        ]},
        {"id": "werkzeuge", "label": "Werkzeuge", "items": [
            {"menu": "Werkzeuge", "gallery": "werkzeuge", "items": ["zoomen"]},
            {"split": "verschieben", "items": ["abfrage_alle", "abfrage_aktuell", "darstellung"], "size": "large"},
            {"command": "gehe_zu", "size": "medium"},
        ]},
    ]}],
}


def settle():
    for _ in range(3):
        QgsApplication.processEvents()


@pytest.fixture
def ribbon(fake_iface, settings):
    builtin_commands.register_all()
    custom_controls.register_all()
    hub = SignalHub()
    watch = LayerWatch(fake_iface, hub)
    watch.start()
    resolver = ActionResolver(fake_iface, CommandEnv(fake_iface, watch, settings))
    w = RibbonWidget(config_loader.parse(copy.deepcopy(DEFINITION)), resolver, hub)
    w.resize(1400, 140)
    w.show()
    settle()
    yield w, watch
    watch.stop()
    hub.disconnect_all()
    resolver.clear()
    builtin_commands.unregister_all()
    custom_controls.unregister_all()
    w.deleteLater()
    settle()


def control(w, cid):
    return w.findChild(QWidget, "ribbon_control_" + cid)


def test_controls_follow_active_layer(ribbon, fake_iface, layers):
    w, watch = ribbon
    opacity = control(w, "deckkraft")
    assert isinstance(opacity, OpacityControl) and isinstance(opacity.editor, QgsOpacityWidget)
    assert not opacity.isEnabled()                      # kein aktiver Layer
    assert "Deckkraft des aktiven Layers." in opacity.toolTip()

    v = layers["vector"]
    v.setOpacity(0.25)
    fake_iface.set_active_layer(v)
    settle()
    assert opacity.isEnabled() and opacity.editor.opacity() == pytest.approx(0.25)

    opacity.editor.setOpacity(0.6)                       # Ribbon -> Layer
    assert v.opacity() == pytest.approx(0.6)
    layer_ops.set_opacity(v, 0.1)                        # anderswo geändert -> Ribbon
    settle()
    assert opacity.editor.opacity() == pytest.approx(0.1)

    fake_iface.set_active_layer(layers["raster"])        # Deckkraft gilt auch für Raster
    settle()
    assert opacity.isEnabled() and opacity.editor.opacity() == pytest.approx(1.0)


def test_scale_control_and_toggle(ribbon, fake_iface, layers):
    w, _watch = ribbon
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    settle()
    scale = control(w, "massstab_max")
    assert isinstance(scale, ScaleControl) and scale.editor.isNull()
    scale.editor.setScale(2500)
    assert v.maximumScale() == 2500 and v.hasScaleBasedVisibility()
    settle()

    toggle = w.findChild(QToolButton, "ribbon_btn_schalten").defaultAction()
    assert toggle.isCheckable() and toggle.isChecked()
    toggle.trigger()
    assert not v.hasScaleBasedVisibility() and not toggle.isChecked()
    layer_ops.set_scale_range_enabled(v, True)           # anderswo eingeschaltet
    settle()
    assert toggle.isChecked()


def test_labels_toggle_and_text_controls(ribbon, fake_iface, layers):
    w, _watch = ribbon
    beschriften = w.findChild(QToolButton, "ribbon_btn_beschriften")
    assert not beschriften.isEnabled()                   # ohne Vektorlayer
    fake_iface.set_active_layer(layers["table"])
    settle()
    assert not beschriften.isEnabled() and not control(w, "groesse").isEnabled()

    v = layers["vector"]
    fake_iface.set_active_layer(v)
    settle()
    assert beschriften.isEnabled()
    beschriften.defaultAction().trigger()
    assert layer_ops.labels_enabled(v) and beschriften.defaultAction().isChecked()

    size = control(w, "groesse")
    size.editor.setEditText("15,5")
    size.editor.lineEdit().editingFinished.emit()
    assert layer_ops.text_format(v, "").size() == 15.5
    layer_ops.set_font_size(v, "", 9)
    settle()
    assert size.editor.currentText() == "9"


def test_identify_modes_are_exclusive(ribbon, fake_iface, settings):
    w, _watch = ribbon
    mw = fake_iface.mainWindow()
    identify = QAction("Abfragen", mw)
    identify.setObjectName("mActionIdentify")
    triggered = []
    identify.triggered.connect(lambda: triggered.append(1))
    split = w.findChild(QWidget, "ribbon_split_verschieben")
    acts = {a.text(): a for a in split.menu.actions()}
    acts["Abfrage: sichtbare Layer"].trigger()
    assert layer_ops.identify_mode(settings) == "TopDownAll" and triggered
    split.menu.aboutToShow.emit()
    assert acts["Abfrage: sichtbare Layer"].isChecked()
    assert not acts["Abfrage: aktueller Layer"].isChecked()
    settings.setValue(layer_ops.IDENTIFY_KEY, "ActiveLayer")   # im Abfragefenster geändert
    split.menu.aboutToShow.emit()                              # beim Öffnen neu gelesen
    assert acts["Abfrage: aktueller Layer"].isChecked()


def test_ribbon_gallery_mirrors_exclusive_map_tools(ribbon, fake_iface):
    w, _watch = ribbon
    mw = fake_iface.mainWindow()
    pan, zoom = mw.findChild(QAction, "mActionPan"), mw.findChild(QAction, "mActionZoomIn")
    gallery = w.findChild(RibbonGallery, "ribbon_gallery_werkzeuge")
    assert gallery is not None
    tile = gallery.findChild(QToolButton, "ribbon_tile_verschieben")
    assert tile.defaultAction().isChecked()
    # columns: 1 -> im Ribbon nur der erste Eintrag (kompakt: zwei), alle im Aufklapp-Menü
    assert gallery.grid.findChild(QToolButton, "ribbon_tile_zoomen").isHidden()
    assert gallery.menu.findChildren(QToolButton) == []   # Raster erst beim Öffnen
    gallery.menu.aboutToShow.emit()
    popup_tiles = gallery.menu.findChildren(QToolButton)
    zoom_tile = [t for t in popup_tiles if t.objectName() == "ribbon_tile_zoomen"][0]
    zoom_tile.click()
    assert zoom.isChecked() and not pan.isChecked()
    assert not tile.defaultAction().isChecked()          # Werkzeuge schließen sich aus
    split = w.findChild(QWidget, "ribbon_split_verschieben")
    assert not split.top.defaultAction().isChecked()
    pan.trigger()
    assert tile.defaultAction().isChecked()


def test_dynamic_gallery_in_menu(ribbon, fake_iface, layers):
    w, _watch = ribbon
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    settle()
    menu = w.findChild(QWidget, "ribbon_split_verschieben").menu
    menu.aboutToShow.emit()
    entries = {a.text(): a for a in menu.actions() if a.isVisible() and not a.isSeparator()}
    assert entries["Einzelsymbol"].isChecked() and not entries["Kategorisiert"].isChecked()
    entries["Kategorisiert"].trigger()
    assert layer_ops.renderer_type(v) == "categorizedSymbol"
    menu.aboutToShow.emit()                              # neu gelesen, ohne Dubletten
    texts = [a.text() for a in menu.actions() if a.isVisible() and not a.isSeparator()]
    assert texts.count("Kategorisiert") == 1
    assert {a.text(): a for a in menu.actions()}["Kategorisiert"].isChecked()


def test_launcher_and_locator(ribbon, fake_iface):
    w, _watch = ribbon
    launcher = w.findChild(QToolButton, "ribbon_launcher_optionen")
    assert launcher is not None and "Optionen öffnen." in launcher.defaultAction().toolTip()
    launcher.click()
    assert ("showOptionsDialog", None, "mOptionsPageMapTools") in fake_iface.calls
    w.findChild(QToolButton, "ribbon_btn_gehe_zu").click()
    assert ("locatorSearch", "go ") in fake_iface.calls


def test_layer_watch_keeps_few_connections(ribbon, fake_iface, layers):
    _w, watch = ribbon
    for _ in range(20):
        for layer in layers.values():
            fake_iface.set_active_layer(layer)
    settle()
    assert len(watch.layer_hub) <= 7
    fake_iface.set_active_layer(None)
    assert len(watch.layer_hub) == 0


def test_registry_is_empty_after_unregister():
    builtin_commands.register_all()
    custom_controls.register_all()
    assert "ribbon.layer_deckkraft" in custom_commands.registered()
    builtin_commands.unregister_all()
    custom_controls.unregister_all()
    assert custom_commands.registered() == []
