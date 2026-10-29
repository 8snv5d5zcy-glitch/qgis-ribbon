"""Beschriftung je Klasse: Schalter „Beschriftungsklassen“, Lesen/Schreiben über den Klassenschlüssel."""
import copy
from types import SimpleNamespace

import pytest
from qgis.core import (QgsPalLayerSettings, QgsProject, QgsReadWriteContext, QgsRuleBasedLabeling,
                       QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration import builtin_commands, context_state, layer_ops
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.layer_watch import LayerWatch
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui.controls import custom as custom_controls
from qgis_ribbon.ui.ribbon_widget import RibbonWidget
from test_lueckenfueller import control, polygons, rule_based, settle  # noqa: E402 (gleicher Ordner)


def custom(cid):
    return {"type": "custom", "id": cid}


DEFINITION = {
    "version": 1,
    "commands": {
        "klassen": {"label": "Beschriftungsklassen", "source": custom("ribbon.beschriftung_klassen_schalten")},
        "klasse": {"label": "Klasse", "kind": "control", "source": custom("ribbon.beschriftung_regel")},
        "massstab_max": {"label": "Größter Maßstab", "kind": "control",
                         "source": custom("ribbon.beschriftung_massstab_max")},
        "massstab_min": {"label": "Kleinster Maßstab", "kind": "control",
                         "source": custom("ribbon.beschriftung_massstab_min")},
        "groesse": {"label": "Schriftgröße", "kind": "control", "source": custom("ribbon.beschriftung_groesse")},
        "farbe": {"label": "Schriftfarbe", "kind": "control", "source": custom("ribbon.beschriftung_farbe")},
        "schrift": {"label": "Schriftart", "kind": "control", "source": custom("ribbon.beschriftung_schrift")},
    },
    "tabs": [{"id": "karte", "label": "Karte", "groups": [
        {"id": "a", "label": "A", "items": [
            {"command": "klassen", "size": "large"}, {"command": "klasse", "size": "medium"},
            {"command": "massstab_max", "size": "medium"}, {"command": "massstab_min", "size": "medium"},
            {"command": "groesse", "size": "medium"}, {"command": "farbe", "size": "medium"},
            {"command": "schrift", "size": "medium"},
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


def two_classes(layer):
    """Zwei Klassen mit verschiedenen Größen und Maßstäben; gibt ihre Schlüssel zurück."""
    rule_based(layer)
    first, second = [k for k, _n, _a in layer_ops.label_classes(layer)]
    layer_ops.set_font_size(layer, first, 10)
    layer_ops.set_font_size(layer, second, 20)
    layer_ops.set_label_scale(layer, first, "max", 1000)
    layer_ops.set_label_scale(layer, second, "max", 5000)
    layer_ops.set_label_scale(layer, second, "min", 50000)
    return first, second


def labeling_xml(labeling):
    doc = QDomDocument()
    doc.appendChild(labeling.save(doc, QgsReadWriteContext()))
    return doc.toString()


# -- Schalter ------------------------------------------------------------------------

def test_first_switch_on_keeps_simple_as_inactive_default_class(layers):
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    layer_ops.set_label_scale(v, "", "max", 2000)
    layer_ops.set_label_scale(v, "", "min", 40000)
    assert not layer_ops.label_classes_on(v)
    key = layer_ops.to_rule_based(v)
    assert layer_ops.label_classes_on(v)
    assert layer_ops.label_classes(v) == [(key, "Standard", False)]
    # Maßstab steht am Regelbereich, nicht mehr in den Einstellungen
    rule = v.labeling().rootRule().findRuleByKey(key)
    assert (rule.maximumScale(), rule.minimumScale()) == (2000, 40000)
    assert not rule.settings().scaleVisibility
    assert layer_ops.label_scale_range(v, key) == (True, 2000, 40000)
    assert v.customProperty(layer_ops.KEPT_SIMPLE)


def test_switch_off_and_on_restores_both_versions(layers):
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    layer_ops.set_font_size(v, "", 8)
    layer_ops.to_rule_based(v)
    layer_ops.add_label_class(v, layer_ops.label_classes(v)[0][0], "Hauptorte")
    classes = layer_ops.label_classes(v)
    key = classes[1][0]
    layer_ops.set_label_class_filter(v, key, '"name" = \'p0\'')
    layer_ops.set_font_size(v, key, 18)
    layer_ops.set_label_scale(v, key, "max", 700)
    classes_xml = labeling_xml(v.labeling())

    assert layer_ops.set_label_classes(v, False, key)
    assert isinstance(v.labeling(), QgsVectorLayerSimpleLabeling)
    assert layer_ops.text_format(v, "").size() == 8          # gemerkte einfache Beschriftung
    # Änderung an der einfachen Beschriftung dazwischen
    layer_ops.set_font_size(v, "", 9)
    simple_xml = labeling_xml(v.labeling())

    assert layer_ops.set_label_classes(v, True)
    assert labeling_xml(v.labeling()) == classes_xml         # Klassen unverändert
    assert layer_ops.label_classes(v)[1][1] == "Hauptorte"
    assert layer_ops.set_label_classes(v, False)
    assert labeling_xml(v.labeling()) == simple_xml          # einfache Beschriftung unverändert


def test_switch_off_without_kept_simple_takes_selected_class(layers):
    v = layers["vector"]
    first, second = two_classes(v)
    assert layer_ops.set_label_classes(v, False, second)
    assert isinstance(v.labeling(), QgsVectorLayerSimpleLabeling)
    assert layer_ops.text_format(v, "").size() == 20
    assert layer_ops.label_scale_range(v, "") == (True, 5000, 50000)
    assert v.customProperty(layer_ops.KEPT_CLASSES)
    assert layer_ops.set_label_classes(v, True)
    assert [c[1] for c in layer_ops.label_classes(v)] == ["Groß", "Klein"]


def test_kept_versions_survive_project_save_and_load(layers, tmp_path):
    v = layers["vector"]
    QgsProject.instance().addMapLayer(v)
    try:
        layer_ops.set_labels_enabled(v, True)
        layer_ops.to_rule_based(v)
        layer_ops.set_label_classes(v, False)
        layer_ops.set_label_classes(v, True)
        classes_xml = labeling_xml(v.labeling())
        layer_ops.set_label_classes(v, False)
        path = str(tmp_path / "p.qgz")
        assert QgsProject.instance().write(path)
        QgsProject.instance().clear()
        assert QgsProject.instance().read(path)
        loaded = QgsProject.instance().mapLayersByName("Punkte")[0]
        assert isinstance(loaded.labeling(), QgsVectorLayerSimpleLabeling)
        layer_ops.set_label_classes(loaded, True)
        assert labeling_xml(loaded.labeling()) == classes_xml
    finally:
        QgsProject.instance().clear()


def test_new_class_switches_classes_on(layers):
    v = layers["vector"]
    layer_ops.set_labels_enabled(v, True)
    key = layer_ops.add_label_class(v, "", "Neu")
    assert layer_ops.label_classes_on(v)
    assert [(c[1], c[2]) for c in layer_ops.label_classes(v)] == [("Standard", False), ("Neu", True)]
    assert layer_ops.label_classes(v)[1][0] == key


def test_non_vector_has_no_switch(layers):
    assert not layer_ops.set_label_classes(layers["table"], True)
    assert not layer_ops.label_classes_on(layers["raster"])


# -- Lesen und Schreiben je Klasse -------------------------------------------------------

def test_every_setter_changes_only_the_selected_class(layers):
    v = layers["vector"]
    first, second = two_classes(v)
    layer_ops.set_font_color(v, second, QColor("#00ff00"))
    layer_ops.set_font_family(v, second, layer_ops.text_format(v, second).font().family())
    layer_ops.set_label_placement(v, second, "OverPoint")
    layer_ops.change_font_size(v, second, +1)
    assert layer_ops.text_format(v, second).size() == 22
    assert layer_ops.text_format(v, second).color().name() == "#00ff00"
    assert layer_ops.label_placement(v, second) == "OverPoint"
    assert layer_ops.text_format(v, first).size() == 10
    assert layer_ops.text_format(v, first).color().name() != "#00ff00"
    assert layer_ops.label_placement(v, first) != "OverPoint"
    fmt = layer_ops.text_format(v, first)
    fmt.setSize(33)
    layer_ops.set_text_format(v, first, fmt)
    assert layer_ops.text_format(v, first).size() == 33 and layer_ops.text_format(v, second).size() == 22


def test_scale_lives_at_rule_and_clear_removes_rule_and_settings(layers):
    v = layers["vector"]
    first, second = two_classes(v)
    rule = v.labeling().rootRule().findRuleByKey(second)
    assert (rule.maximumScale(), rule.minimumScale()) == (5000, 50000)
    assert layer_ops.label_scale_range(v, first) == (True, 1000, 0)
    assert not layer_ops.label_class_extra_scale(v, second)
    # Zusätzlicher Bereich in den Einstellungen: wirkt, wird angezeigt als Hinweis
    s = QgsPalLayerSettings(rule.settings())
    s.scaleVisibility = True
    s.maximumScale = 300
    rule.setSettings(s)
    assert layer_ops.label_class_extra_scale(v, second)
    assert layer_ops.label_scale_range(v, second) == (True, 5000, 50000)   # Regelbereich
    layer_ops.clear_label_scales(v, second)
    assert layer_ops.label_scale_range(v, second) == (False, 0, 0)
    assert not layer_ops.label_class_settings(v, second).scaleVisibility
    assert not layer_ops.label_class_extra_scale(v, second)
    assert layer_ops.label_scale_range(v, first) == (True, 1000, 0)         # andere Klasse unberührt


def test_parent_rule_scale_counts_as_extra(layers):
    v = layers["vector"]
    parent = QgsRuleBasedLabeling.Rule(None)
    mid = QgsRuleBasedLabeling.Rule(None)
    mid.setMaximumScale(10000)
    s = QgsPalLayerSettings()
    s.fieldName = "name"
    mid.appendChild(QgsRuleBasedLabeling.Rule(s))
    parent.appendChild(mid)
    v.setLabeling(QgsRuleBasedLabeling(parent))
    key = layer_ops.label_classes(v)[0][0]
    assert layer_ops.label_class_extra_scale(v, key)


# -- Steuerelemente im Ribbon ---------------------------------------------------------------

def test_controls_follow_class_selection(ribbon, fake_iface, layers):
    w, _watch, env = ribbon
    v = layers["vector"]
    first, second = two_classes(v)
    fake_iface.set_active_layer(v)
    settle()
    size, vmax, vmin = control(w, "groesse"), control(w, "massstab_max"), control(w, "massstab_min")
    assert size.editor.currentText() == "10" and vmax.editor.scale() == 1000 and vmin.editor.isNull()
    builtin_commands.label_class_state(env).select(v, second)
    settle()
    assert size.editor.currentText() == "20"
    assert vmax.editor.scale() == 5000 and vmin.editor.scale() == 50000
    assert control(w, "farbe").editor.color() == layer_ops.text_format(v, second).color()
    # Schreiben trifft nur die gewählte Klasse
    size.editor.setEditText("14")
    size.editor.lineEdit().editingFinished.emit()
    assert layer_ops.text_format(v, second).size() == 14 and layer_ops.text_format(v, first).size() == 10
    vmax.editor.setScale(2500)
    assert layer_ops.label_scale_range(v, second)[1] == 2500 and layer_ops.label_scale_range(v, first)[1] == 1000


def test_switch_button_toggles_and_follows_layer(ribbon, fake_iface, layers):
    w, _watch, env = ribbon
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    settle()
    act = builtin_commands.beschriftung_klassen_schalten(env, SimpleNamespace(label="Beschriftungsklassen"))
    assert act.isEnabled() and not act.isChecked()
    act.trigger()                                                      # an
    assert layer_ops.label_classes_on(v) and act.isChecked()
    act.trigger()                                                      # aus
    assert not layer_ops.label_classes_on(v) and not act.isChecked()
    layer_ops.to_rule_based(v)                                         # QGIS-seitig gewechselt
    settle()
    assert act.isChecked()
    fake_iface.set_active_layer(layers["table"])
    settle()
    assert not act.isEnabled()


def test_context_snapshot_follows_label_mode(layers):
    v = layers["vector"]
    assert not context_state.snapshot(v).label_classes
    layer_ops.set_labels_enabled(v, True)
    assert not context_state.snapshot(v).label_classes
    layer_ops.to_rule_based(v)
    assert context_state.snapshot(v).label_classes
    assert not context_state.snapshot(layers["table"]).label_classes


def test_class_commands_are_disabled_without_classes(layers):
    from qgis_ribbon.core import conditions
    v = layers["vector"]
    assert not conditions.evaluate("label_classes_on", context_state.snapshot(v))
    layer_ops.to_rule_based(v)
    assert conditions.evaluate("label_classes_on", context_state.snapshot(v))
    ribbon_def = config_loader.load()
    for cid in ("beschriftungsklasse", "beschriftungsklasse_filter", "beschriftungsklasse_aktiv",
                "beschriftungsklasse_loeschen"):
        assert "label_classes_on" in ribbon_def.commands[cid].enabled_when
    for cid in ("beschriftungsklasse_neu", "beschriftungsfeld", "beschriftung_schrift"):
        assert "label_classes_on" not in ribbon_def.commands[cid].enabled_when


def test_polygon_layer_keeps_placement_through_switch():
    poly = polygons()
    layer_ops.set_labels_enabled(poly, True)
    layer_ops.to_rule_based(poly)
    key = layer_ops.label_classes(poly)[0][0]
    assert layer_ops.label_placement(poly, key) == "AroundPoint"
