"""Laden und Entladen des Plugins: QGIS muss danach exakt wie vorher sein."""
import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.plugin import TOOLBAR_NAME, RibbonPlugin
from qgis_ribbon.qgis_integration.toolbar_manager import SETTINGS_KEY, STATE_KEY


def snapshot(mw):
    """Beobachtbarer Zustand des Hauptfensters."""
    return {
        "state": bytes(mw.saveState()),
        "toolbars": sorted((tb.objectName(), tb.isHidden()) for tb in mw.findChildren(QToolBar)),
        "actions": sorted((a.objectName(), a.text(), a.isEnabled(), a.isChecked(), a.isVisible())
                          for a in mw.findChildren(QAction) if a.objectName()),
        "menus": sorted((m.objectName(), m.title(), len(m.actions())) for m in mw.findChildren(QMenu)
                        if m.objectName()),
        "widgets": len(mw.findChildren(QWidget)),
        "stylesheet": mw.styleSheet(),
        "app_stylesheet": QgsApplication.instance().styleSheet(),
        "palette": [QgsApplication.instance().palette().color(group, role).name()
                    for group in (QPalette.Active, QPalette.Disabled)
                    for role in (QPalette.Window, QPalette.WindowText, QPalette.Base, QPalette.Text,
                                 QPalette.Button, QPalette.Highlight, QPalette.HighlightedText)],
    }


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)  # deleteLater ausführen
    QgsApplication.processEvents()


def test_load_and_unload_restores_main_window_exactly(fake_iface, settings):
    mw = fake_iface.mainWindow()
    settle()
    before = snapshot(mw)

    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    assert mw.findChild(QToolBar, TOOLBAR_NAME) is not None
    assert mw.findChild(QToolBar, "mFileToolBar").isHidden()
    assert mw.findChild(QToolBar, "mPluginToolBar").isHidden()   # Plugin-Leisten stehen im Tab Erweiterungen
    assert plugin.widget.is_built("karte")
    assert plugin.startup_ms is not None

    plugin.unload()
    settle()
    assert mw.findChild(QToolBar, TOOLBAR_NAME) is None
    assert len(plugin.hub) == 0
    assert settings.value(SETTINGS_KEY) is None
    after = snapshot(mw)
    for key in before:
        assert after[key] == before[key], key


def test_quit_order_of_qgis_leaves_state_without_ribbon(fake_iface, settings):
    """QGIS beim Beenden: Zustand speichern (aboutToQuit), dann Plugins entladen.

    Früher landete der Zustand mit ausgeblendeten Leisten im Profil; ein Start
    ohne Plugin zeigte danach keine Werkzeugleiste mehr.
    """
    mw = fake_iface.mainWindow()
    settle()
    before = bytes(mw.saveState())
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    settings.setValue(STATE_KEY, mw.saveState())      # QgisApp::saveWindowState
    plugin.unload()                                     # QgsPluginRegistry::unloadAll
    settle()
    assert bytes(settings.value(STATE_KEY)) == before


def test_rebuild_does_not_write_window_state(fake_iface, settings):
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    plugin.request_rebuild()
    settle()
    assert settings.value(STATE_KEY) is None
    plugin.unload()
    settle()


def test_reload_twice(fake_iface, settings):
    mw = fake_iface.mainWindow()
    settle()
    before = snapshot(mw)
    for _ in range(2):
        plugin = RibbonPlugin(fake_iface, settings=settings)
        plugin.initGui()
        settle()
        plugin.unload()
        settle()
    assert snapshot(mw) == before


def test_startup_waits_for_initialization_completed(fake_iface, settings):
    mw = fake_iface.mainWindow()
    mw.hide()
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    assert plugin.widget is None
    mw.show()
    fake_iface.initializationCompleted.emit()
    assert plugin.widget is not None
    plugin.unload()
    settle()
    assert mw.findChild(QToolBar, TOOLBAR_NAME) is None


def test_broken_definition_loads_nothing(fake_iface, settings, tmp_path):
    path = tmp_path / "kaputt.yaml"
    path.write_text("version: 1\ntabs: []\ncommands: {}\n", encoding="utf-8")
    plugin = RibbonPlugin(fake_iface, config_path=str(path), settings=settings)
    plugin.initGui()
    assert plugin.widget is None
    plugin.unload()


def test_shipped_definition_builds_every_tab(fake_iface, settings):
    """Alle Tabs der mitgelieferten Definition lassen sich aufbauen (fehlende Quellen grau)."""
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    for tab in plugin.ribbon.tabs:
        plugin.widget.select_tab(tab.id)
        assert plugin.widget.is_built(tab.id)
    plugin.unload()
    settle()


def test_shipped_icons_exist(qgis_app):
    from qgis.PyQt.QtCore import QFile
    ribbon = config_loader.load()
    icons = {c.icon for c in ribbon.commands.values() if c.icon}
    missing = [i for i in sorted(icons)
               if not QFile.exists(":/images/themes/default" + i)
               and not QFile.exists(QgsApplication.defaultThemePath() + i)]
    assert not missing, missing


@pytest.mark.parametrize("size", ["large", "medium", "small"])
def test_sizes_have_fixed_heights(size):
    from qgis_ribbon.ui.controls.buttons import _base_button
    from qgis_ribbon.ui import theme
    btn = _base_button(None, size)
    expected = theme.CONTENT_HEIGHT if size == "large" else theme.ROW_HEIGHT
    assert btn.maximumHeight() == expected


def test_controls_with_active_layer_and_clean_unload(fake_iface, settings, layers):
    """Steuerelemente aller Tabs mit aktivem Layer; Entladen hinterlässt nichts."""
    from qgis_ribbon.qgis_integration import custom_commands
    from qgis_ribbon.ui.controls.custom import (LayerControl, MeshGroupControl, PointCloudControl,
                                                RasterEnhanceControl)

    mw = fake_iface.mainWindow()
    settle()
    before = snapshot(mw)
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    fake_iface.set_active_layer(layers["vector"])
    for tab in plugin.ribbon.tabs:
        plugin.widget.select_tab(tab.id)
    settle()
    controls = plugin.widget.findChildren(LayerControl)
    assert len(controls) >= 10
    # Vektorlayer: alle bedienbar außer den Reglern für Raster, Punktwolken und Netze
    other = (RasterEnhanceControl, PointCloudControl, MeshGroupControl)
    assert all(c.isEnabled() != isinstance(c, other) for c in controls)
    fake_iface.set_active_layer(layers["raster"])
    settle()
    raster = [c for c in controls if isinstance(c, RasterEnhanceControl)]
    assert len(raster) == 3 and all(c.isEnabled() for c in raster)
    fake_iface.set_active_layer(layers["vector"])
    # Alle Steuerelemente der Definition sind gebaut, keines bleibt grau
    unbuilt = [c.id for c in plugin.ribbon.commands.values()
               if c.kind == "control" and c.gallery is None
               and not any(w.command.id == c.id for w in controls)]
    assert not unbuilt, unbuilt
    launchers = [w for w in plugin.widget.findChildren(QWidget) if w.objectName().startswith("ribbon_launcher_")]
    assert len(launchers) >= 5
    plugin.unload()
    settle()
    assert custom_commands.registered() == []
    assert len(plugin.hub) == 0
    fake_iface.set_active_layer(None)
    after = snapshot(mw)
    for key in before:
        assert after[key] == before[key], key
