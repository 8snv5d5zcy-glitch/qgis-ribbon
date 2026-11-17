"""Einrast-Einstellungen einzeln im Ribbon: schreiben die Projekt-Konfiguration, folgen ihr, grau wie in QGIS."""
import copy

import pytest
from qgis.core import Qgis, QgsApplication, QgsProject, QgsSnappingConfig
from qgis.gui import QgsDoubleSpinBox, QgsMapCanvasTracer
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration import builtin_commands, snapping_ops
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.layer_watch import LayerWatch
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui.controls import custom as custom_controls


def custom(cid, *args):
    src = {"type": "custom", "id": cid}
    if args:
        src["args"] = list(args)
    return src


def control_cmd(label, cid):
    return {"label": label, "kind": "control", "source": custom(cid), "description": label + "."}


DEFINITION = {
    "version": 1,
    "commands": {
        "modus": control_cmd("Modus", "ribbon.einrasten_modus"),
        "toleranz": control_cmd("Toleranz", "ribbon.einrasten_toleranz"),
        "einheit": control_cmd("Einheit", "ribbon.einrasten_einheit"),
        "massstab_modus": control_cmd("Maßstabsmodus", "ribbon.einrasten_massstab_modus"),
        "massstab_min": control_cmd("Kleinster Maßstab", "ribbon.einrasten_massstab_min"),
        "massstab_max": control_cmd("Größter Maßstab", "ribbon.einrasten_massstab_max"),
        "versatz": control_cmd("Versatz", "ribbon.spurverfolgung_versatz"),
        "stuetzpunkt": {"label": "Stützpunkt", "source": custom("ribbon.einrasttyp", "vertex")},
        "segment": {"label": "Segment", "source": custom("ribbon.einrasttyp", "segment")},
        "ueberschneidungen": {"label": "Überschneidungen", "source": custom("ribbon.einrasten_ueberschneidungen")},
        "erweitert": {"label": "Erweitert", "source": custom("ribbon.einrasten_erweitert")},
    },
    "tabs": [{"id": "bearbeiten", "label": "Bearbeiten", "groups": [
        {"id": "einrasten", "label": "Einrasten", "items": [
            {"command": "modus", "size": "medium"},
            {"command": "toleranz", "size": "medium"},
            {"command": "einheit", "size": "medium"},
            {"row": ["stuetzpunkt", "segment", "erweitert"]},
            {"command": "ueberschneidungen", "size": "large"},
        ]},
        {"id": "massstab", "label": "Maßstab", "items": [
            {"command": "massstab_modus", "size": "medium"},
            {"command": "massstab_min", "size": "medium"},
            {"command": "massstab_max", "size": "medium"},
            {"command": "versatz", "size": "medium"},
        ]},
    ]}],
}


class QgsSnappingWidget(QWidget):
    """Klassenname wie das Einrast-Widget von QGIS (dort nicht in den Python-Bindings)."""


def settle():
    for _ in range(3):
        QgsApplication.processEvents()


def config(**changes):
    """Kopie der Projekt-Konfiguration mit Änderungen (Name des Setters ohne „set“)."""
    cfg = QgsSnappingConfig(QgsProject.instance().snappingConfig())
    for name, value in changes.items():
        getattr(cfg, "set" + name)(value)
    return cfg


@pytest.fixture
def snapping():
    """Einrast-Konfiguration des Projekts: bekannter Ausgangszustand, danach wie vorher."""
    project = QgsProject.instance()
    before = QgsSnappingConfig(project.snappingConfig())
    avoid = project.avoidIntersectionsMode()
    project.setSnappingConfig(config(Enabled=True, Mode=Qgis.SnappingMode.AllLayers,
                                     TypeFlag=Qgis.SnappingTypes(Qgis.SnappingType.Vertex), Tolerance=12.0,
                                     Units=Qgis.MapToolUnit.Pixels,
                                     ScaleDependencyMode=QgsSnappingConfig.ScaleDependencyMode.Disabled,
                                     MinimumScale=0.0, MaximumScale=0.0))
    project.setAvoidIntersectionsMode(Qgis.AvoidIntersectionsMode.AllowIntersections)
    yield project
    project.setSnappingConfig(before)
    project.setAvoidIntersectionsMode(avoid)


@pytest.fixture
def ribbon(fake_iface, settings, snapping):
    from qgis_ribbon.ui.ribbon_widget import RibbonWidget
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
    yield w, hub
    watch.stop()
    hub.disconnect_all()
    resolver.clear()
    builtin_commands.unregister_all()
    custom_controls.unregister_all()
    w.deleteLater()
    settle()


def control(w, cid):
    return w.findChild(QWidget, "ribbon_control_" + cid)


def button(w, cid):
    return w.findChild(QToolButton, "ribbon_btn_" + cid)


def test_controls_write_the_project_config(ribbon, snapping):
    w, _hub = ribbon
    mode = control(w, "modus")
    assert mode.editor.currentData() == Qgis.SnappingMode.AllLayers
    mode.editor.setCurrentIndex(mode.editor.findData(Qgis.SnappingMode.ActiveLayer))
    assert snapping.snappingConfig().mode() == Qgis.SnappingMode.ActiveLayer

    tolerance = control(w, "toleranz")
    assert tolerance.value.value() == 12 and tolerance.value.decimals() == 0
    tolerance.value.setValue(20)
    assert snapping.snappingConfig().tolerance() == 20
    tolerance.units.setCurrentIndex(tolerance.units.findData(Qgis.MapToolUnit.Project))
    assert snapping.snappingConfig().units() == Qgis.MapToolUnit.Project
    settle()
    assert tolerance.value.decimals() == 5                 # Projekteinheiten mit Nachkommastellen
    units = control(w, "einheit")
    assert units.editor.currentData() == Qgis.MapToolUnit.Project

    scale_mode = control(w, "massstab_modus")
    scale_min, scale_max = control(w, "massstab_min"), control(w, "massstab_max")
    assert not scale_min.isEnabled() and not scale_max.isEnabled()   # nur bei einer Grenze für alle Layer
    scale_mode.editor.setCurrentIndex(scale_mode.editor.findData(QgsSnappingConfig.ScaleDependencyMode.Global))
    assert snapping.snappingConfig().scaleDependencyMode() == QgsSnappingConfig.ScaleDependencyMode.Global
    settle()
    assert scale_min.isEnabled() and scale_max.isEnabled()
    scale_min.editor.setScale(50000)
    scale_max.editor.setScale(500)
    cfg = snapping.snappingConfig()
    assert cfg.minimumScale() == 50000 and cfg.maximumScale() == 500


def test_type_buttons_toggle_flags(ribbon, snapping):
    w, _hub = ribbon
    vertex, segment = button(w, "stuetzpunkt").defaultAction(), button(w, "segment").defaultAction()
    assert vertex.isChecked() and not segment.isChecked()
    segment.trigger()
    flags = snapping.snappingConfig().typeFlag()
    assert flags & Qgis.SnappingType.Segment and flags & Qgis.SnappingType.Vertex
    assert segment.isChecked()
    vertex.trigger()
    flags = snapping.snappingConfig().typeFlag()
    assert not flags & Qgis.SnappingType.Vertex and flags & Qgis.SnappingType.Segment


def test_external_changes_are_shown(ribbon, snapping):
    """Geändert außerhalb des Ribbons (Einrast-Widget, Projekt laden): der Ribbon zeigt es an."""
    w, _hub = ribbon
    snapping.setSnappingConfig(config(Mode=Qgis.SnappingMode.ActiveLayer, Tolerance=3.5,
                                      Units=Qgis.MapToolUnit.Layer,
                                      TypeFlag=Qgis.SnappingTypes(Qgis.SnappingType.Segment)))
    settle()
    assert control(w, "modus").editor.currentData() == Qgis.SnappingMode.ActiveLayer
    tolerance = control(w, "toleranz")
    assert tolerance.value.value() == pytest.approx(3.5)
    assert tolerance.units.currentData() == Qgis.MapToolUnit.Layer
    assert control(w, "einheit").editor.currentData() == Qgis.MapToolUnit.Layer
    assert button(w, "segment").defaultAction().isChecked()
    assert not button(w, "stuetzpunkt").defaultAction().isChecked()


def test_advanced_mode_greys_per_layer_settings(ribbon, snapping, fake_iface):
    w, _hub = ribbon
    triggered = []
    options = QAction("Einrastoptionen", fake_iface.mainWindow())
    options.setObjectName("mActionSnappingOptions")
    options.triggered.connect(lambda: triggered.append(1))
    button(w, "erweitert").defaultAction().trigger()
    settle()
    assert snapping.snappingConfig().mode() == Qgis.SnappingMode.AdvancedConfiguration and triggered
    for cid in ("toleranz", "einheit"):
        assert not control(w, cid).isEnabled(), cid
        assert snapping_ops.PER_LAYER in control(w, cid).toolTip(), cid
    assert not button(w, "stuetzpunkt").isEnabled()
    assert control(w, "modus").isEnabled()                 # zurück geht es über den Modus
    mode = control(w, "modus")
    mode.editor.setCurrentIndex(mode.editor.findData(Qgis.SnappingMode.AllLayers))
    settle()
    assert control(w, "toleranz").isEnabled() and button(w, "stuetzpunkt").isEnabled()
    assert snapping_ops.PER_LAYER not in control(w, "toleranz").toolTip()


def test_avoid_overlap_menu_is_exclusive(ribbon, snapping):
    w, _hub = ribbon
    menu = button(w, "ueberschneidungen").menu()
    assert isinstance(menu, QMenu)
    menu.aboutToShow.emit()
    acts = menu.actions()
    assert [a.isChecked() for a in acts] == [True, False, False]
    acts[1].trigger()
    assert snapping.avoidIntersectionsMode() == Qgis.AvoidIntersectionsMode.AvoidIntersectionsCurrentLayer
    snapping.setAvoidIntersectionsMode(Qgis.AvoidIntersectionsMode.AvoidIntersectionsLayers)
    menu.aboutToShow.emit()
    assert [a.isChecked() for a in menu.actions()] == [False, False, True]


def test_tracing_offset_goes_to_qgis_field_and_tracer(ribbon, fake_iface):
    """Der Versatz steht nicht im Projekt: Zahlenfeld im Spurverfolgungs-Menü von QGIS und Tracer der Karte."""
    w, _hub = ribbon
    canvas = fake_iface.mapCanvas()
    tracer = QgsMapCanvasTracer(canvas)
    snapping_widget = QgsSnappingWidget(fake_iface.mainWindow())
    menu = QMenu(snapping_widget)                       # ohne Namen wie in QGIS 3.44
    box = QgsDoubleSpinBox(menu)
    box.setRange(-100.0, 100.0)
    box.valueChanged.connect(tracer.setOffset)
    try:
        offset = control(w, "versatz")
        offset.editor.setValue(2.5)
        assert box.value() == pytest.approx(2.5) and tracer.offset() == pytest.approx(2.5)
        offset.refresh()
        box.setValue(-1.0)                              # in QGIS geändert -> Ribbon
        settle()
        assert offset.editor.value() == pytest.approx(-1.0)
        other = QMenu(fake_iface.mainWindow())          # Menü außerhalb des Einrast-Widgets zählt nicht
        QgsDoubleSpinBox(other)
        assert snapping_ops.tracing_spin_boxes(fake_iface.mainWindow()) == [box]
        other.deleteLater()
    finally:
        snapping_widget.deleteLater()
        del tracer
        settle()


def test_controls_drop_their_label_before_the_group_collapses(ribbon):
    """Wenig Platz: Steuerelemente zeigen nur Icon und Feld, erst danach klappt die Gruppe ein."""
    from qgis_ribbon.ui.group_widget import COLLAPSED, GroupWidget
    w, _hub = ribbon
    group = next(g for g in w.findChildren(GroupWidget) if g.group.id == "massstab")
    variants = group.variants()
    modes = [m for m, _w in variants]
    assert modes[0] == COLLAPSED and ["small"] * 4 in modes and modes[-1] == ["medium"] * 4
    compact = modes.index(["small"] * 4)
    scale_mode = control(w, "massstab_modus")
    full = scale_mode.width_for(False)
    group.apply(compact)
    assert scale_mode._text_label.isHidden() and scale_mode.width_for(True) < full
    assert variants[compact][1] < variants[-1][1]
    group.apply(len(variants) - 1)
    assert not scale_mode._text_label.isHidden()


def test_teardown_leaves_no_connections(fake_iface, settings, snapping):
    from qgis_ribbon.ui.ribbon_widget import RibbonWidget
    builtin_commands.register_all()
    custom_controls.register_all()
    hub = SignalHub()
    env = CommandEnv(fake_iface, None, settings, hub)
    resolver = ActionResolver(fake_iface, env)
    w = RibbonWidget(config_loader.parse(copy.deepcopy(DEFINITION)), resolver, hub)
    w.show()
    settle()
    try:
        assert len(hub) > 0
        hub.disconnect_all()
        assert len(hub) == 0
        snapping.setSnappingConfig(config(Tolerance=42.0))   # kein Steuerelement hört noch zu
        settle()
        assert control(w, "toleranz").value.value() != 42
    finally:
        resolver.clear()
        builtin_commands.unregister_all()
        custom_controls.unregister_all()
        w.deleteLater()
        settle()
