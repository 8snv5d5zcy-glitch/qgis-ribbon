"""Kontextlogik im Ribbon (mitgelieferte Definition): Kontext-Tabs, Bedingungen, Tab-Wechsel."""
from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QToolButton

from qgis_ribbon.plugin import RibbonPlugin

VECTOR_TABS = ("vektor_darstellung", "vektor_beschriftung", "vektor_daten")


def settle():
    for _ in range(3):
        QgsApplication.processEvents()


def load(fake_iface, settings):
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    return plugin


def visible(plugin):
    return {t.id for t in plugin.ribbon.tabs if t.contextual and plugin.widget.is_tab_visible(t.id)}


def felder_buttons(plugin):
    return [b for b in plugin.widget.findChildren(QToolButton, "ribbon_btn_felder")]


def test_context_tabs_follow_active_layer(fake_iface, settings, layers):
    plugin = load(fake_iface, settings)
    w = plugin.widget
    assert visible(plugin) == set()
    assert w.current_tab() == "karte"

    fake_iface.set_active_layer(layers["vector"])
    settle()
    assert visible(plugin) == set(VECTOR_TABS)
    w.select_tab("vektor_daten")
    assert all(b.isEnabled() for b in felder_buttons(plugin))

    fake_iface.set_active_layer(layers["table"])
    settle()
    assert visible(plugin) == {"tabelle_daten"}
    assert w.current_tab() == "tabelle_daten"   # gleiche Beschriftung „Daten“

    fake_iface.set_active_layer(layers["raster"])
    settle()
    assert visible(plugin) == {"raster_darstellung"}
    assert w.current_tab() == "karte"           # zuletzt gewählter Haupt-Tab

    fake_iface.set_active_layer(None)
    settle()
    assert visible(plugin) == set()
    assert felder_buttons(plugin) and not any(b.isEnabled() for b in felder_buttons(plugin))
    plugin.unload()
    settle()


def test_editing_start_switches_to_edit_tab(fake_iface, settings, layers):
    plugin = load(fake_iface, settings)
    v = layers["vector"]
    fake_iface.set_active_layer(v)
    settle()
    plugin.widget.select_tab("vektor_darstellung")
    v.startEditing()
    settle()
    assert plugin.widget.current_tab() == "bearbeiten"
    v.rollBack()
    settle()
    assert plugin.widget.current_tab() == "bearbeiten"  # Beenden wechselt nicht zurück
    plugin.unload()
    settle()


def test_layer_switching_leaves_no_connections(fake_iface, settings, layers):
    plugin = load(fake_iface, settings)
    for tid in VECTOR_TABS:  # alle Kontext-Tabs aufbauen
        fake_iface.set_active_layer(layers["vector"])
        settle()
        plugin.widget.select_tab(tid)
    hub_size = len(plugin.hub)
    for _ in range(100):
        for layer in (layers["vector"], layers["table"], layers["raster"], None):
            fake_iface.set_active_layer(layer)
    settle()
    assert len(plugin.hub) == hub_size
    assert len(plugin.state.layer_hub) == 0
    assert plugin.widget.last_apply_ms is not None
    state = plugin.state
    plugin.unload()
    settle()
    assert len(plugin.hub) == 0 and len(state.layer_hub) == 0


def test_initial_state_with_active_layer(fake_iface, settings, layers):
    fake_iface.active_layer = layers["raster"]
    plugin = load(fake_iface, settings)
    assert visible(plugin) == {"raster_darstellung"}
    plugin.unload()
    settle()
