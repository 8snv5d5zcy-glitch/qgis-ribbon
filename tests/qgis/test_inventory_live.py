"""Live-Inventar gegen Qt/QGIS-Attrappen.

Prüft die Sammellogik (Menüpfade, Toolbars, Docks, Plugin-Aktionen,
Processing) ohne laufendes QGIS. Ob die echten objectNames stimmen, zeigt
erst der Lauf in QGIS (siehe Modul-Docstring von inventory.py).
"""
import importlib
import os
import sys
import types

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)


class _Obj(object):
    def __init__(self, name="", parent=None):
        self._name = name
        self._parent = parent

    def objectName(self):
        return self._name

    def parent(self):
        return self._parent


class QKeySequence(object):
    class SequenceFormat(object):
        PortableText = 0

    def __init__(self, text):
        self._t = text

    def toString(self, fmt=None):
        return self._t


class QIcon(object):
    def __init__(self, null=True):
        self._null = null

    def isNull(self):
        return self._null


class QAction(_Obj):
    def __init__(self, name="", text="", shortcut=None, menu=None, separator=False,
                 checkable=False):
        _Obj.__init__(self, name)
        self._text, self._menu, self._sep = text, menu, separator
        self._sc = [QKeySequence(shortcut)] if shortcut else []
        self._checkable = checkable

    def text(self):
        return self._text

    def toolTip(self):
        return self._text

    def shortcuts(self):
        return self._sc

    def icon(self):
        return QIcon(null=False)

    def isCheckable(self):
        return self._checkable

    def menu(self):
        return self._menu

    def isSeparator(self):
        return self._sep


class QMenu(_Obj):
    def __init__(self, name, title, actions):
        _Obj.__init__(self, name)
        self._title, self._actions = title, actions

    def title(self):
        return self._title

    def actions(self):
        return self._actions


class QToolBar(_Obj):
    def __init__(self, name, title, actions):
        _Obj.__init__(self, name)
        self._title, self._actions = title, actions

    def windowTitle(self):
        return self._title

    def actions(self):
        return self._actions

    def isVisible(self):
        return True


class QDockWidget(_Obj):
    def __init__(self, name, title):
        _Obj.__init__(self, name)
        self._title = title

    def windowTitle(self):
        return self._title

    def toggleViewAction(self):
        return QAction("")


class QShortcut(_Obj):
    def __init__(self, name, key):
        _Obj.__init__(self, name)
        self._key = QKeySequence(key)

    def key(self):
        return self._key


class _MenuBar(object):
    def __init__(self, menus):
        self._menus = menus

    def actions(self):
        return [QAction(menu=m) for m in self._menus]


class _MainWindow(object):
    def __init__(self, menubar, children):
        self._mb, self._children = menubar, children

    def menuBar(self):
        return self._mb

    def findChildren(self, cls):
        return [c for c in self._children if isinstance(c, cls)]


class _Alg(object):
    def __init__(self, ident, name, provider):
        self._id, self._name, self._prov = ident, name, provider

    def id(self):
        return self._id

    def displayName(self):
        return self._name

    def group(self):
        return "Gruppe"

    def provider(self):
        prov = self._prov
        return type("P", (), {"id": lambda self: prov})()


def _install_stubs(plugins):
    mods = {}
    qgis = types.ModuleType("qgis")
    core = types.ModuleType("qgis.core")
    reg = type("R", (), {"algorithms": lambda self: [
        _Alg("native:clip", "Ausschneiden", "native")]})()
    core.QgsApplication = type("QgsApplication", (), {
        "processingRegistry": staticmethod(lambda: reg)})
    core.Qgis = type("Qgis", (), {"version": staticmethod(lambda: "3.40.99-Test")})
    core.QgsSettings = type("QgsSettings", (), {"value": lambda self, k, d=None: "de"})
    pyqt = types.ModuleType("qgis.PyQt")
    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    qtcore.QLocale = type("QLocale", (), {"name": lambda self: "de_DE"})
    qtgui = types.ModuleType("qgis.PyQt.QtGui")
    qtgui.QKeySequence = QKeySequence
    qtwidgets = types.ModuleType("qgis.PyQt.QtWidgets")
    for c in (QAction, QDockWidget, QMenu, QShortcut, QToolBar):
        setattr(qtwidgets, c.__name__, c)
    utils = types.ModuleType("qgis.utils")
    utils.plugins = plugins
    utils.active_plugins = sorted(plugins)
    qgis.utils = utils
    for name, mod in (("qgis", qgis), ("qgis.core", core), ("qgis.PyQt", pyqt),
                      ("qgis.PyQt.QtCore", qtcore), ("qgis.PyQt.QtGui", qtgui),
                      ("qgis.PyQt.QtWidgets", qtwidgets), ("qgis.utils", utils)):
        mods[name] = sys.modules.get(name)
        sys.modules[name] = mod
    return mods


def _restore(mods):
    for name, mod in mods.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("qgis_ribbon.qgis_integration.inventory", None)


def test_collect_menu_paths_toolbars_docks_plugins():
    pan = QAction("mActionPan", "&Verschieben", shortcut="Space", checkable=True)
    clip = QAction("mActionClip", "Ausschneiden")
    noname = QAction("", "Ohne Namen")
    sep = QAction(separator=True)
    sub = QMenu("mSub", "&Unter", [clip])
    view = QMenu("mViewMenu", "&Ansicht", [pan, sep, QAction(menu=sub)])
    demo = QAction("demo_actionOpen", "Öffnen")
    plugin = type("Plugin", (), {})()
    plugin.actions = [demo]
    plugin.other = 42
    mw = _MainWindow(_MenuBar([view]), [
        pan, clip, noname, sep, demo,
        QToolBar("mMapNavToolBar", "Kartennavigation", [pan]),
        QDockWidget("Layers", "Layer"),
        QShortcut("ShowLayersPanel", "Ctrl+1"),
    ])
    iface = type("Iface", (), {"mainWindow": lambda self: mw})()
    mods = _install_stubs({"demo_plugin": plugin})
    try:
        inventory = importlib.import_module("qgis_ribbon.qgis_integration.inventory")
        inv = inventory.build(iface)
    finally:
        _restore(mods)
    acts = dict((a["object_name"], a) for a in inv["actions"] if a["object_name"])
    assert acts["mActionPan"]["text"] == "Verschieben"
    assert acts["mActionPan"]["shortcut"] == "Space"
    assert acts["mActionPan"]["menus"] == [["Ansicht"]]
    assert acts["mActionPan"]["toolbars"] == ["mMapNavToolBar"]
    assert acts["mActionClip"]["menus"] == [["Ansicht", "Unter"]]
    assert any(a["object_name"] is None for a in inv["actions"])
    assert len(inv["actions"]) == 4  # Trenner nicht
    assert inv["docks"][0]["object_name"] == "Layers"
    assert inv["shortcuts"][0]["key"] == "Ctrl+1"
    assert inv["plugin_actions"] == [{"object_name": "demo_actionOpen",
                                      "text": "Öffnen", "plugin": "demo_plugin"}]
    assert inv["plugins"] == ["demo_plugin"]
    assert inv["processing"][0]["id"] == "native:clip"
    assert inv["quelle"] == "live" and inv["qgis_version"] == "3.40.99-Test"
    assert [m["path"] for m in inv["menus"]] == [["Ansicht"], ["Ansicht", "Unter"]]
