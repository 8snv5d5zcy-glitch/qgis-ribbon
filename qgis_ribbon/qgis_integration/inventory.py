"""Live-Inventar der laufenden QGIS-Instanz.

Exportiert alle QActions (objectName, Text, Tooltip, Shortcut, Menüpfade,
Toolbars), Docks, QShortcuts, Aktionen geladener Plugins und
Processing-Algorithmen als JSON im Format von ``core.inventory``.

Aufruf in der QGIS-Python-Konsole (Plugin muss nicht aktiviert sein, nur
installiert bzw. per Junction verlinkt)::

    from qgis_ribbon.qgis_integration import inventory
    inventory.export()

Ohne Pfad landet die Datei im Ordner ``docs`` neben dem Plugin-Ordner,
falls vorhanden, sonst im Home-Verzeichnis. Die Datei bleibt
lokal (``.gitignore``), weil sie die installierten Plugins nennt.

Vorher sinnvoll: alle Plugins laden, die der Ribbon ansprechen soll, und
einmal einen Vektorlayer aktiv haben. Manche Aktionen
entstehen erst beim ersten Öffnen eines Fensters; die ergänzt das statische
Inventar.
"""
import io
import json
import os

from qgis.core import Qgis, QgsApplication, QgsSettings
from qgis.PyQt.QtCore import QLocale
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import QAction, QDockWidget, QShortcut, QToolBar

from ..core.inventory import build_inventory
from ..core.i18n import tr

DEFAULT_NAME = "qgis_inventory_live.json"


def _clean(text):
    if text is None:
        return None
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _shortcut(action):
    seqs = action.shortcuts()
    if not seqs:
        return None
    return ", ".join(s.toString(QKeySequence.PortableText) for s in seqs)


def _menu_paths(menubar):
    """QAction → Liste der Menüpfade (Titel ohne Mnemonik)."""
    paths = {}

    def walk(menu, path, depth):
        if depth > 8:
            return
        for act in menu.actions():
            sub = act.menu()
            if sub is not None:
                walk(sub, path + [_clean(sub.title())], depth + 1)
            elif not act.isSeparator():
                paths.setdefault(act, []).append(path)

    for top in menubar.actions():
        sub = top.menu()
        if sub is not None:
            walk(sub, [_clean(sub.title())], 1)
    return paths


def _menus(menubar):
    out = []

    def walk(menu, path, depth):
        if depth > 8:
            return
        title = _clean(menu.title())
        p = path + [title]
        out.append({"object_name": menu.objectName() or None, "title": title, "path": p})
        for act in menu.actions():
            if act.menu() is not None:
                walk(act.menu(), p, depth + 1)

    for top in menubar.actions():
        if top.menu() is not None:
            walk(top.menu(), [], 1)
    return out


def _plugin_actions():
    """Aktionen, die geladene Plugins als Attribute halten (self.action, Listen, dicts)."""
    try:
        from qgis import utils
    except ImportError:
        return [], []
    out = []
    for name, obj in sorted(utils.plugins.items()):
        seen = set()
        for value in list(vars(obj).values()):
            candidates = []
            if isinstance(value, QAction):
                candidates = [value]
            elif isinstance(value, (list, tuple)):
                candidates = [v for v in value if isinstance(v, QAction)]
            elif isinstance(value, dict):
                candidates = [v for v in value.values() if isinstance(v, QAction)]
            for act in candidates:
                if id(act) in seen:
                    continue
                seen.add(id(act))
                out.append({
                    "object_name": act.objectName() or None,
                    "text": _clean(act.text()),
                    "plugin": name,
                })
    return out, list(utils.active_plugins)


def collect(iface):
    """Rohdaten aus der laufenden QGIS-Instanz einsammeln."""
    mw = iface.mainWindow()
    menubar = mw.menuBar()
    paths = _menu_paths(menubar)
    toolbars = []
    in_toolbar = {}
    for tb in mw.findChildren(QToolBar):
        toolbars.append({"object_name": tb.objectName() or None,
                         "title": tb.windowTitle(),
                         "sichtbar": tb.isVisible()})
        for act in tb.actions():
            in_toolbar.setdefault(act, []).append(tb.objectName() or tb.windowTitle())

    actions = []
    for act in mw.findChildren(QAction):
        if act.isSeparator():
            continue
        actions.append({
            "object_name": act.objectName() or None,
            "text": _clean(act.text()),
            "tooltip": act.toolTip() or None,
            "shortcut": _shortcut(act),
            "icon": None,
            "hat_icon": not act.icon().isNull(),
            "checkable": act.isCheckable(),
            "hat_menu": act.menu() is not None,
            "menus": paths.get(act, []),
            "toolbars": in_toolbar.get(act, []),
            "herkunft": "live",
        })

    docks = []
    for dock in mw.findChildren(QDockWidget):
        docks.append({
            "object_name": dock.objectName() or None,
            "title": dock.windowTitle(),
            "toggle_action": dock.toggleViewAction().objectName() or None,
        })

    shortcuts = []
    for sc in mw.findChildren(QShortcut):
        shortcuts.append({
            "object_name": sc.objectName() or None,
            "key": sc.key().toString(QKeySequence.PortableText),
        })

    processing = []
    registry = QgsApplication.processingRegistry()
    for alg in registry.algorithms():
        provider = alg.provider()
        processing.append({
            "id": alg.id(),
            "name": alg.displayName(),
            "group": alg.group(),
            "provider": provider.id() if provider else None,
        })

    plugin_actions, plugins = _plugin_actions()
    return {
        "actions": actions,
        "menus": _menus(menubar),
        "toolbars": toolbars,
        "docks": docks,
        "shortcuts": shortcuts,
        "plugin_actions": plugin_actions,
        "processing": processing,
    }, plugins


def build(iface):
    raw, plugins = collect(iface)
    locale = QgsSettings().value("locale/userLocale", QLocale().name())
    return build_inventory(raw, "live", qgis_version=Qgis.version(),
                           locale=locale, plugins=plugins)


def default_path():
    here = os.path.realpath(os.path.dirname(__file__))
    docs = os.path.join(os.path.dirname(os.path.dirname(here)), "docs")
    if os.path.isdir(docs):
        return os.path.join(docs, DEFAULT_NAME)
    return os.path.join(os.path.expanduser("~"), DEFAULT_NAME)


def export(path=None, iface=None):
    """Inventar schreiben und den Pfad zurückgeben."""
    if iface is None:
        from qgis.utils import iface as _iface
        iface = _iface
    path = path or default_path()
    inv = build(iface)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(inv, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(tr("Inventory written: %s (actions %d, docks %d, plugin actions %d, algorithms %d)")
          % (path, len(inv["actions"]), len(inv["docks"]), len(inv["plugin_actions"]), len(inv["processing"])))
    return path
