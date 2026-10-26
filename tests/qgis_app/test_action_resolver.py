from qgis.PyQt.QtWidgets import QAction, QDockWidget

from qgis_ribbon.core.model import Command, Source
from qgis_ribbon.qgis_integration import custom_commands
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver, clean_text


def cmd(cid, stype, kind="button", icon=None, **params):
    return Command(id=cid, label=cid, source=Source(stype, params), kind=kind, icon=icon)


def test_clean_text():
    assert clean_text("&Öffnen…") == "Öffnen"
    assert clean_text("Drag && Drop...") == "Drag & Drop"


def test_qgis_action_is_found_and_mirrored(fake_iface):
    r = ActionResolver(fake_iface)
    res = r.resolve(cmd("pan", "qgis_action", object_name="mActionPan"))
    assert res.available
    assert res.action is fake_iface.mainWindow().findChild(QAction, "mActionPan")
    assert res.qgis_text == "Karte verschieben"


def test_missing_action_is_unavailable_with_reason(fake_iface):
    res = ActionResolver(fake_iface).resolve(cmd("x", "qgis_action", object_name="mActionGibtEsNicht"))
    assert not res.available
    assert "mActionGibtEsNicht" in res.reason


def test_action_added_later_is_found_after_refresh(fake_iface):
    r = ActionResolver(fake_iface)
    assert not r.resolve(cmd("late", "qgis_action", object_name="mActionLate")).available
    act = QAction("Spät", fake_iface.mainWindow())
    act.setObjectName("mActionLate")
    r.refresh()
    assert r.resolve(cmd("late", "qgis_action", object_name="mActionLate")).available


def test_plugin_action_dock_and_menu(fake_iface):
    r = ActionResolver(fake_iface)
    assert r.resolve(cmd("tb", "plugin_action", plugin="processing", object_name="toolboxAction")).available
    assert not r.resolve(cmd("no", "plugin_action", plugin="fehlt", object_name="nope")).available
    dock = r.resolve(cmd("layers", "dock", object_name="Layers"))
    assert dock.available and dock.action.isCheckable()
    dock_widget = fake_iface.mainWindow().findChild(QDockWidget, "Layers")
    dock_widget.hide()
    show = cmd("zeigen", "dock", object_name="Layers", modus="zeigen")
    assert r.resolve(show).action is None
    r.trigger(show)
    r.trigger(show)  # zweiter Klick schließt nicht
    assert not dock_widget.isHidden()
    menu = r.resolve(cmd("add", "qgis_menu", object_name="mAddLayerMenu"))
    assert menu.available and menu.menu.objectName() == "mAddLayerMenu"


def test_iface_method_chain_and_active_layer(fake_iface):
    r = ActionResolver(fake_iface)
    zoom = cmd("zoom", "iface_method", method="mapCanvas.zoomIn")
    assert r.resolve(zoom).available
    assert r.trigger(zoom)
    assert not r.resolve(cmd("bad", "iface_method", method="mapCanvas.gibtEsNicht")).available

    fields = cmd("felder", "iface_method", method="showLayerProperties",
                 args=["@aktiver_layer", "mOptsPage_SourceFields"])
    r.trigger(fields)
    assert fake_iface.calls == []  # kein aktiver Layer: nur Hinweis
    fake_iface.active_layer = "LAYER"
    r.trigger(fields)
    assert fake_iface.calls == [("showLayerProperties", "LAYER", "mOptsPage_SourceFields")]


def test_processing_algorithm(fake_iface):
    r = ActionResolver(fake_iface)
    res = r.resolve(cmd("puffer", "processing", algorithm="native:buffer"))
    assert res.available and res.qgis_text
    assert not r.resolve(cmd("x", "processing", algorithm="native:gibtesnicht")).available


def test_custom_commands(fake_iface):
    r = ActionResolver(fake_iface)
    missing = r.resolve(cmd("dom", "custom", id="ribbon.test_fehlt"))
    assert not missing.available and "folgt" in missing.reason
    control = r.resolve(cmd("reg", "custom", kind="control", id="ribbon.test_regler"))
    assert "Steuerelement" in control.reason

    calls = []
    custom_commands.register("ribbon.test_da", lambda env, command: lambda: calls.append(env.iface))
    try:
        c = cmd("da", "custom", id="ribbon.test_da")
        assert r.trigger(c)
        assert calls == [fake_iface]
    finally:
        custom_commands.unregister("ribbon.test_da")


def test_failing_command_reports_instead_of_raising(fake_iface):
    custom_commands.register("ribbon.test_kaputt", lambda env, command: lambda: 1 / 0)
    try:
        assert ActionResolver(fake_iface).trigger(cmd("k", "custom", id="ribbon.test_kaputt")) is False
    finally:
        custom_commands.unregister("ribbon.test_kaputt")


def test_theme_icon_from_definition(fake_iface):
    res = ActionResolver(fake_iface).resolve(
        cmd("zoom", "iface_method", icon="/mActionZoomIn.svg", method="mapCanvas.zoomIn"))
    assert not res.icon.isNull()
