import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core.inventory import (  # noqa: E402
    INVALID, MISSING, OK, UNCHECKED, InventoryIndex, build_inventory, check_source,
    merge_inventories)


def _raw():
    return {
        "actions": [
            {"object_name": "mActionPan", "text": "Pan Map"},
            {"object_name": "mActionDup", "text": "A"},
            {"object_name": "mActionDup", "text": "B"},
            {"object_name": None, "text": "ohne Namen"},
        ],
        "docks": [{"object_name": "Layers", "title": "Layers"}],
        "menus": [{"object_name": "mMenuMeasure", "title": "Measure", "path": ["View", "Measure"]}],
        "shortcuts": [{"object_name": "ShowLayersPanel", "key": "Ctrl+1"}],
        "plugin_actions": [{"object_name": "demo_actionOpen", "text": "Öffnen",
                            "plugin": "demo_plugin"}],
        "processing": [{"id": "native:clip", "name": "Clip"},
                       {"id": "native:buffer", "name": "Buffer"}],
    }


def _index(quelle="live", plugins=("demo_plugin",)):
    return InventoryIndex(build_inventory(_raw(), quelle, plugins=list(plugins)))


def test_build_inventory_sorts_and_marks_duplicates():
    inv = build_inventory(_raw(), "live", qgis_version="3.40.9")
    names = [a["object_name"] for a in inv["actions"]]
    assert names == ["mActionDup", "mActionDup", "mActionPan", None]
    assert inv["actions"][0]["mehrfach"] == 2
    assert "mehrfach" not in inv["actions"][2]
    assert [a["id"] for a in inv["processing"]] == ["native:buffer", "native:clip"]
    assert inv["schema"] == 1 and inv["quelle"] == "live"


def test_check_qgis_action():
    idx = _index()
    assert check_source({"type": "qgis_action", "object_name": "mActionPan"}, idx)[0] == OK
    res, msg = check_source({"type": "qgis_action", "object_name": "mActionDup"}, idx)
    assert res == OK and "2-mal" in msg
    assert check_source({"type": "qgis_action", "object_name": "mActionNope"}, idx)[0] == MISSING
    # QShortcut zählt als vorhanden, ist aber gekennzeichnet
    res, msg = check_source({"type": "qgis_action", "object_name": "ShowLayersPanel"}, idx)
    assert res == OK and "QShortcut" in msg


def test_check_processing_and_dock():
    idx = _index()
    assert check_source({"type": "processing", "algorithm": "native:clip"}, idx)[0] == OK
    assert check_source({"type": "processing", "algorithm": "native:nope"}, idx)[0] == MISSING
    assert check_source({"type": "dock", "object_name": "Layers"}, idx)[0] == OK
    assert check_source({"type": "dock", "object_name": "Nope"}, idx)[0] == MISSING
    static = _index("static")
    assert check_source({"type": "dock", "object_name": "Nope"}, static)[0] == UNCHECKED


def test_check_menu():
    idx = _index()
    src = {"type": "qgis_menu", "object_name": "mMenuMeasure"}
    assert check_source(src, idx)[0] == OK
    assert idx.label(src) == "View > Measure"
    assert check_source({"type": "qgis_menu", "object_name": "mNope"}, idx)[0] == MISSING


def test_check_plugin_action():
    src = {"type": "plugin_action", "plugin": "demo_plugin",
           "object_name": "demo_actionOpen"}
    assert check_source(src, _index())[0] == OK
    other = dict(src, object_name="demo_actionNope")
    assert check_source(other, _index())[0] == MISSING
    # anderer Ordnername: objectName zählt
    renamed = dict(src, plugin="demo-plugin-main")
    res, msg = check_source(renamed, _index())
    assert res == OK and "anderem" in msg
    # Plugin nicht geladen oder statisches Inventar: nicht prüfbar statt Fehler
    assert check_source(other, _index(plugins=()))[0] == UNCHECKED
    assert check_source(other, _index("static"))[0] == UNCHECKED


def test_check_invalid_and_unchecked_types():
    idx = _index()
    assert check_source({"type": "qgis_action"}, idx)[0] == INVALID
    assert check_source({"type": "zauber"}, idx)[0] == INVALID
    assert check_source("mActionPan", idx)[0] == INVALID
    assert check_source({"type": "iface_method", "method": "showLayerProperties"},
                        idx)[0] == UNCHECKED
    assert check_source({"type": "custom", "id": "ribbon.basemap"}, idx)[0] == UNCHECKED


def test_label():
    idx = _index()
    assert idx.label({"type": "qgis_action", "object_name": "mActionPan"}) == "Pan Map"
    assert idx.label({"type": "processing", "algorithm": "native:clip"}) == "Clip"
    assert idx.label({"type": "processing", "algorithm": "native:nope"}) is None


def test_merge_prefers_primary_and_fills_gaps():
    live = build_inventory({"actions": [{"object_name": "mActionPan", "text": "Verschieben"}]},
                           "live", plugins=["demo_plugin"])
    static = build_inventory(_raw(), "static", plugins=["processing"])
    idx = InventoryIndex(merge_inventories(live, static))
    assert idx.label({"type": "qgis_action", "object_name": "mActionPan"}) == "Verschieben"
    assert "mActionDup" in idx.actions
    assert "native:clip" in idx.processing
    assert idx.plugins == {"demo_plugin", "processing"}
    assert idx.quelle == "live"
