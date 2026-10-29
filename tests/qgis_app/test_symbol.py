"""Gruppe Symbol im Kontext-Tab Darstellung: Klasse, Farben, Breite, Symboleditor."""
import copy

import pytest
from qgis.core import (QgsApplication, QgsCategorizedSymbolRenderer, QgsHeatmapRenderer, QgsPointClusterRenderer,
                       QgsProject, QgsProperty, QgsRendererCategory, QgsRuleBasedRenderer, QgsSingleSymbolRenderer,
                       QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration import builtin_commands, symbol_ops
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.custom_commands import CommandEnv
from qgis_ribbon.qgis_integration.layer_watch import LayerWatch
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui.controls import custom as custom_controls
from qgis_ribbon.ui.ribbon_widget import RibbonWidget


def custom(cid):
    return {"type": "custom", "id": cid}


DEFINITION = {
    "version": 1,
    "commands": {
        "bearbeiten": {"label": "Symbol bearbeiten", "source": custom("ribbon.symbol_bearbeiten")},
        "klasse": {"label": "Klasse", "kind": "control", "source": custom("ribbon.symbolklasse")},
        "fuellung": {"label": "Füllfarbe", "kind": "control", "source": custom("ribbon.symbol_fuellfarbe")},
        "rand": {"label": "Randfarbe", "kind": "control", "source": custom("ribbon.symbol_randfarbe")},
        "breite": {"label": "Breite", "kind": "control", "source": custom("ribbon.symbol_breite")},
    },
    "tabs": [{"id": "darstellung", "label": "Darstellung", "groups": [
        {"id": "symbol", "label": "Symbol", "items": [
            {"command": "bearbeiten", "size": "large"},
            {"command": "klasse", "size": "medium"},
            {"command": "fuellung", "size": "medium"},
            {"command": "rand", "size": "medium"},
            {"command": "breite", "size": "medium"},
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
    resolver = ActionResolver(fake_iface, CommandEnv(fake_iface, watch, settings, hub))
    w = RibbonWidget(config_loader.parse(copy.deepcopy(DEFINITION)), resolver, hub)
    w.resize(1400, 140)
    w.show()
    settle()
    yield w
    watch.stop()
    hub.disconnect_all()
    resolver.clear()
    builtin_commands.unregister_all()
    custom_controls.unregister_all()
    w.deleteLater()
    settle()


@pytest.fixture
def project():
    added = []

    def add(layer):
        QgsProject.instance().addMapLayer(layer)
        added.append(layer.id())
        return layer
    yield add
    QgsProject.instance().removeMapLayers(added)


def control(w, cid):
    return w.findChild(QWidget, "ribbon_control_" + cid)


def edit_button(w):
    return w.findChild(QToolButton, "ribbon_btn_bearbeiten")


def layer(geometry, renderer=None):
    lyr = QgsVectorLayer("%s?crs=EPSG:4326&field=art:string" % geometry, geometry, "memory")
    assert lyr.isValid()
    if renderer is not None:
        lyr.setRenderer(renderer)
    return lyr


def categorized(lyr):
    cats = []
    for value, color in (("a", "#ff0000"), ("b", "#0000ff")):
        sym = QgsSymbol.defaultSymbol(lyr.geometryType())
        sym.setColor(QColor(color))
        cats.append(QgsRendererCategory(value, sym, value.upper()))
    lyr.setRenderer(QgsCategorizedSymbolRenderer("art", cats))
    return lyr


def category_symbol(lyr, value):
    """Kopie: das Symbol gehört der (kopierten) Kategorie und stirbt mit ihr."""
    cat = [c for c in lyr.renderer().categories() if c.value() == value][0]
    return cat.symbol().clone()


def choose(w, label):
    combo = control(w, "klasse").editor
    index = combo.findText(label)
    assert index >= 0, [combo.itemText(i) for i in range(combo.count())]
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    settle()


def test_fill_color_per_category_with_undo(ribbon, fake_iface):
    w = ribbon
    poly = categorized(layer("Polygon"))
    fake_iface.set_active_layer(poly)
    settle()
    combo = control(w, "klasse").editor
    assert [combo.itemText(i) for i in range(combo.count())] == ["Alle Kategorien", "A", "B"]
    fill = control(w, "fuellung")
    assert not fill.isEnabled() and "eigene Farbe" in fill.toolTip()   # „Alle …“: Farbe je Klasse
    assert control(w, "breite").isEnabled()

    choose(w, "A")
    assert fill.isEnabled() and fill.editor.color().name() == "#ff0000"
    fill.editor.setColor(QColor("#00ff00"))
    assert category_symbol(poly, "a").color().name() == "#00ff00"
    assert category_symbol(poly, "b").color().name() == "#0000ff"   # andere Klasse bleibt
    stack = poly.undoStackStyles()
    assert stack.count() == 1
    stack.undo()
    settle()
    assert category_symbol(poly, "a").color().name() == "#ff0000"
    assert fill.editor.color().name() == "#ff0000"                   # Ribbon liest neu
    stack.redo()
    assert category_symbol(poly, "a").color().name() == "#00ff00"

    choose(w, "B")                                                   # Randfarbe nur für B
    control(w, "rand").editor.setColor(QColor("#123456"))
    assert category_symbol(poly, "b").symbolLayer(0).strokeColor().name() == "#123456"
    assert category_symbol(poly, "a").symbolLayer(0).strokeColor().name() != "#123456"


def test_width_for_all_classes_is_one_step(ribbon, fake_iface):
    w = ribbon
    poly = categorized(layer("Polygon"))
    before = [category_symbol(poly, v).symbolLayer(0).strokeWidth() for v in "ab"]
    fake_iface.set_active_layer(poly)
    settle()
    width = control(w, "breite")
    assert width.editor.suffix() == " mm"
    width.editor.setValue(1.5)
    width.editor.setValue(2.0)
    assert [category_symbol(poly, v).symbolLayer(0).strokeWidth() for v in "ab"] == [2.0, 2.0]
    assert poly.undoStackStyles().count() == 1                       # zusammengefasst
    poly.undoStackStyles().undo()
    assert [category_symbol(poly, v).symbolLayer(0).strokeWidth() for v in "ab"] == before


def test_single_line_symbol(ribbon, fake_iface):
    w = ribbon
    line = layer("LineString")
    fake_iface.set_active_layer(line)
    settle()
    combo = control(w, "klasse").editor
    assert [combo.itemText(i) for i in range(combo.count())] == ["Alle Objekte"]
    fill = control(w, "fuellung")
    assert not fill.isEnabled() and "keine Füllfarbe" in fill.toolTip()
    control(w, "rand").editor.setColor(QColor("#aa00aa"))
    assert line.renderer().symbol().color().name() == "#aa00aa"
    control(w, "breite").editor.setValue(1.2)
    assert line.renderer().symbol().width() == pytest.approx(1.2)


def test_data_defined_size_blocks_width(ribbon, fake_iface):
    w = ribbon
    points = layer("Point")
    sym = points.renderer().symbol().clone()
    sym.setDataDefinedSize(QgsProperty.fromExpression("3 + 1"))
    points.setRenderer(QgsSingleSymbolRenderer(sym))
    fake_iface.set_active_layer(points)
    settle()
    width = control(w, "breite")
    assert not width.isEnabled() and "datendefiniert" in width.toolTip()
    assert control(w, "fuellung").isEnabled()


def test_heatmap_has_no_symbols(ribbon, fake_iface):
    w = ribbon
    points = layer("Point", QgsHeatmapRenderer())
    fake_iface.set_active_layer(points)
    settle()
    for cid in ("klasse", "fuellung", "rand", "breite"):
        assert not control(w, cid).isEnabled(), cid
    assert "Heatmap" in control(w, "breite").toolTip()
    assert not edit_button(w).isEnabled()


def test_click_on_class_in_layer_tree_selects_it(ribbon, fake_iface, project):
    w = ribbon
    poly = project(categorized(layer("Polygon")))
    fake_iface.set_active_layer(poly)
    settle()
    view = fake_iface.layerTreeView()
    model = view.layerTreeModel()
    node = QgsProject.instance().layerTreeRoot().findLayer(poly.id())
    key_b = [it.ruleKey() for it in poly.renderer().legendSymbolItems() if it.label() == "B"][0]
    legend = [n for n in model.layerLegendNodes(node)
              if n.data(symbol_ops.QgsLayerTreeModelLegendNode.CustomRole.RuleKey) == key_b][0]
    view.setCurrentIndex(view.proxyModel().mapFromSource(model.legendNode2index(legend)))  # Ansicht mit Proxy
    settle()
    assert control(w, "klasse").editor.currentText() == "B"
    assert control(w, "fuellung").editor.color().name() == "#0000ff"


def test_rule_based_and_cluster(ribbon, fake_iface):
    w = ribbon
    root = QgsRuleBasedRenderer.Rule(None)
    for name, expr in (("Eins", "\"art\" = 'a'"), ("Zwei", "\"art\" = 'b'")):
        sym = QgsSymbol.defaultSymbol(QgsVectorLayer("Point", "x", "memory").geometryType())
        root.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, expr, name))
    rules = layer("Point", QgsRuleBasedRenderer(root))
    fake_iface.set_active_layer(rules)
    settle()
    combo = control(w, "klasse").editor
    assert [combo.itemText(i) for i in range(combo.count())] == ["Alle Regeln", "Eins", "Zwei"]
    choose(w, "Zwei")
    control(w, "fuellung").editor.setColor(QColor("#00aa00"))
    colors = [r.symbol().color().name() for r in rules.renderer().rootRule().children()]
    assert colors[1] == "#00aa00" and colors[0] != "#00aa00"

    points = categorized(layer("Point"))
    cluster = QgsPointClusterRenderer()
    cluster.setEmbeddedRenderer(points.renderer().clone())
    points.setRenderer(cluster)
    fake_iface.set_active_layer(points)
    settle()
    assert "A" in [combo.itemText(i) for i in range(combo.count())]
    choose(w, "A")
    control(w, "breite").editor.setValue(4.0)
    cats = points.renderer().embeddedRenderer().categories()
    assert [c.symbol().size() for c in cats if c.value() == "a"] == [4.0]


def test_edit_symbol_opens_symbol_editor_for_class(ribbon, fake_iface, monkeypatch):
    w = ribbon
    poly = categorized(layer("Polygon"))
    fake_iface.set_active_layer(poly)
    settle()
    seen = []

    class FakeDialog(object):
        def __init__(self, sym, _style, lyr, _parent):
            seen.append((sym.color().name(), lyr))
            self.sym = sym

        def setContext(self, _context):
            pass

        def exec(self):
            self.sym.setColor(QColor("#abcdef"))
            return True
    monkeypatch.setattr(builtin_commands, "QgsSymbolSelectorDialog", FakeDialog)
    choose(w, "B")
    edit_button(w).click()
    settle()
    assert seen == [("#0000ff", poly)]
    assert category_symbol(poly, "b").color().name() == "#abcdef"
    assert poly.undoStackStyles().count() == 1

    choose(w, "Alle Kategorien")            # „Alle …“: kein Editor, das Panel Layer-Styling
    edit_button(w).click()
    settle()
    assert len(seen) == 1
