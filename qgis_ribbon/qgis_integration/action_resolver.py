"""Befehlsquellen auflösen: Command -> QGIS-Aktion, Menü, Dock, Methode, Algorithmus.

Grundsatz: vorhandene QActions werden nicht nachgebaut, sondern
gespiegelt. Der Ribbon-Button löst die QGIS-Aktion aus und übernimmt deren
Zustand (aktiv, abgehakt). Fehlt eine Quelle, liefert der Resolver einen
nicht verfügbaren Eintrag mit Begründung; der Button wird ausgegraut statt
abzustürzen.
"""

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QCursor, QIcon, QKeySequence
from qgis.PyQt.QtWidgets import QAction, QDockWidget, QMenu, QToolBar

from . import custom_commands
from ..core.i18n import tr

LOG_TAG = "QGIS Ribbon"
ACTIVE_LAYER = "@aktiver_layer"


def clean_text(text):
    """Mnemonik (&) und Auslassungspunkte aus QGIS-Texten entfernen."""
    if not text:
        return ""
    text = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    return text.replace("…", "").replace("...", "").strip()


class Resolved(object):
    """Ergebnis der Auflösung eines Befehls."""

    __slots__ = ("available", "reason", "action", "callback", "menu", "icon",
                 "qgis_text", "shortcut")

    def __init__(self, available=True, reason=None, action=None, callback=None, menu=None,
                 icon=None, qgis_text=None, shortcut=None):
        self.available = available
        self.reason = reason
        self.action = action          # QAction, deren Zustand gespiegelt wird
        self.callback = callback      # sonst: Funktion beim Klick
        self.menu = menu              # qgis_menu: vorhandenes QGIS-Menü
        self.icon = icon if icon is not None else QIcon()
        self.qgis_text = qgis_text
        self.shortcut = shortcut


def unavailable(reason, icon=None):
    return Resolved(available=False, reason=reason, icon=icon)


class ActionResolver(object):
    def __init__(self, iface, env=None):
        self.iface = iface
        # Umgebung der eigenen Befehle (iface, Layer-Beobachter)
        self.env = env if env is not None else custom_commands.CommandEnv(iface)
        # Aktionen anderer Plugins (qgis_integration.extensions.ExtensionCatalog)
        self.extensions = None
        self._actions = None
        self._missing = set()   # rekursiv gesucht und nicht gefunden (bis refresh)
        self._cache = {}
        self._icons = {}

    # Index der QActions des Hauptfensters
    def refresh(self):
        """Fehlgriffe vergessen, damit inzwischen entstandene Aktionen (Plugins) gefunden werden."""
        self._missing.clear()

    def _build_index(self):
        # Die meisten Aktionen sind direkte Kinder des Hauptfensters.
        index = {}
        for act in self.iface.mainWindow().findChildren(QAction, options=Qt.FindDirectChildrenOnly):
            name = act.objectName()
            if name and name not in index:
                index[name] = act
        self._actions = index

    def find_action(self, name):
        if self._actions is None:
            self._build_index()
        act = self._actions.get(name)
        if act is None and name not in self._missing:
            # Gezielte rekursive Suche nach diesem einen Namen. Ein vollständiger
            # rekursiver Index kostete im echten QGIS 30–40 ms je Aufbau.
            act = self._find_nested(name)
            if act is None:
                self._missing.add(name)
            else:
                self._actions[name] = act
        return act

    def _find_nested(self, name):
        """Aktion, die kein direktes Kind des Hauptfensters ist.

        Solche Aktionen sitzen meist in Widgets der Werkzeugleisten (Einrasten,
        Topologisch bearbeiten) oder in Menüs. Dort zuerst suchen: rekursiv über
        das ganze Hauptfenster kostete im echten QGIS 9 ms je Aktion.
        """
        mw = self.iface.mainWindow()
        scopes = mw.findChildren(QToolBar, options=Qt.FindDirectChildrenOnly)
        if hasattr(mw, "menuBar"):
            scopes.append(mw.menuBar())
        for scope in scopes:
            act = scope.findChild(QAction, name)
            if act is not None:
                return act
        return mw.findChild(QAction, name)

    def theme_icon(self, name):
        if not name:
            return QIcon()
        icon = self._icons.get(name)
        if icon is None:
            icon = QgsApplication.getThemeIcon(name)
            self._icons[name] = icon
        return icon

    # Auflösen
    def resolve(self, command):
        """Command -> Resolved. Verfügbare Ergebnisse werden zwischengespeichert."""
        cached = self._cache.get(command.id)
        if cached is not None:
            return cached
        handler = getattr(self, "_resolve_" + command.source.type)
        try:
            res = handler(command)
        except Exception as exc:  # Resolver darf den Aufbau nie abbrechen
            QgsMessageLog.logMessage(tr("Command %s cannot be resolved: %s") % (command.id, exc),
                                     LOG_TAG, Qgis.Warning)
            res = unavailable(tr("Error while resolving: %s") % exc)
        if command.icon:
            res.icon = self.theme_icon(command.icon)
        if res.available:
            self._cache[command.id] = res
        return res

    def clear(self):
        self._cache.clear()
        self._actions = None
        self.env.close()

    def _from_action(self, act):
        seq = act.shortcut()
        return Resolved(action=act, icon=act.icon(), qgis_text=clean_text(act.text()),
                        shortcut=seq.toString(QKeySequence.NativeText) if not seq.isEmpty() else None)

    def _resolve_qgis_action(self, command):
        name = command.source.get("object_name")
        act = self.find_action(name)
        if act is None:
            return unavailable(tr("QGIS action %s not found") % name)
        return self._from_action(act)

    def _resolve_plugin_action(self, command):
        name = command.source.get("object_name")
        plugin = command.source.get("plugin")
        act = self.find_action(name)
        if act is None:
            act = _plugin_attribute_action(plugin, name)
        if act is None:
            return unavailable(tr("Action %s not found (plugin %s not loaded?)") % (name, plugin))
        return self._from_action(act)

    def _resolve_extension(self, command):
        act = self.extensions.action(command.source.get("key")) if self.extensions is not None else None
        if act is None:
            return unavailable(tr("Extension not loaded or item removed"))
        # Ein Menü der Aktion wird zum Split-Button (core.extensions), nicht zum reinen Dropdown
        return self._from_action(act)

    def _resolve_qgis_menu(self, command):
        name = command.source.get("object_name")
        mw = self.iface.mainWindow()
        # Erst in der Menüleiste suchen: rekursiv über das ganze Hauptfenster
        # kostete im echten QGIS 6 ms je Menü
        bar = mw.menuBar() if hasattr(mw, "menuBar") else None
        menu = bar.findChild(QMenu, name) if bar is not None else None
        if menu is None:
            menu = mw.findChild(QMenu, name)
        if menu is None:
            return unavailable(tr("QGIS menu %s not found") % name)
        return Resolved(menu=menu, icon=menu.icon(), qgis_text=clean_text(menu.title()))

    def _resolve_dock(self, command):
        name = command.source.get("object_name")
        mw = self.iface.mainWindow()
        dock = (mw.findChild(QDockWidget, name, options=Qt.FindDirectChildrenOnly)
                or mw.findChild(QDockWidget, name))
        if dock is None:
            return unavailable(tr("Panel %s not found") % name)
        title = clean_text(dock.windowTitle())
        if command.source.get("modus") == "zeigen":
            # Nur öffnen und nach vorn holen; ein zweiter Klick schließt nicht.
            def show():
                if hasattr(dock, "setUserVisible"):  # QgsDockWidget
                    dock.setUserVisible(True)
                else:
                    dock.show()
                dock.raise_()

            return Resolved(callback=show, icon=dock.toggleViewAction().icon(), qgis_text=title)
        act = dock.toggleViewAction()
        return Resolved(action=act, icon=act.icon(), qgis_text=title)

    def _resolve_iface_method(self, command):
        method = command.source.get("method")
        args = list(command.source.get("args") or [])
        parts = method.split(".")
        obj = self.iface
        for i, part in enumerate(parts):
            if not hasattr(obj, part):
                return unavailable(tr("iface method %s not available") % method)
            if i < len(parts) - 1:
                attr = getattr(obj, part)
                obj = attr() if callable(attr) else attr
        if not callable(getattr(obj, parts[-1])):
            return unavailable(tr("iface method %s not callable") % method)
        iface = self.iface

        def call():
            target = iface
            for part in parts[:-1]:
                attr = getattr(target, part)
                target = attr() if callable(attr) else attr
            values = []
            for a in args:
                if a == ACTIVE_LAYER:
                    layer = iface.activeLayer()
                    if layer is None:
                        iface.messageBar().pushMessage(
                            LOG_TAG, tr("No active layer selected."), level=Qgis.Warning, duration=4)
                        return
                    a = layer
                values.append(a)
            getattr(target, parts[-1])(*values)

        return Resolved(callback=call)

    def _resolve_iface_action(self, command):
        """QAction, die ``iface`` über einen Methodenpfad liefert.

        Für Aktionen ohne eindeutigen objectName, die nicht am Hauptfenster
        hängen, z. B. ``cadDockWidget.enableAction`` (Schalter der erweiterten
        Digitalisierung, sitzt im Panel und hat keinen Text).
        """
        method = command.source.get("method")
        obj = self.iface
        for part in method.split("."):
            attr = getattr(obj, part, None)
            if attr is None:
                return unavailable(tr("iface method %s not available") % method)
            obj = attr() if callable(attr) else attr
        if not isinstance(obj, QAction):
            return unavailable(tr("QGIS action %s not found") % method)
        return self._from_action(obj)

    def _resolve_processing(self, command):
        alg_id = command.source.get("algorithm")
        alg = QgsApplication.processingRegistry().algorithmById(alg_id)
        if alg is None:
            return unavailable(tr("Processing algorithm %s not found") % alg_id)

        def call():
            import processing
            processing.execAlgorithmDialog(alg_id)

        return Resolved(callback=call, icon=alg.icon(), qgis_text=alg.displayName())

    def _resolve_custom(self, command):
        cid = command.source.get("id")
        factory = custom_commands.get(cid)
        if factory is None:
            if command.gallery is not None and command.gallery.items:
                return Resolved()  # Galerie nur mit festen Einträgen
            if command.kind == "control":
                return unavailable(tr("Control not available yet"))
            return unavailable(tr("Command not available yet"))
        kind = custom_commands.kind_of(cid)
        if kind != "button":
            # Steuerelemente und Galerien baut die Oberfläche (ui.controls)
            return Resolved()
        result = factory(self.env, command)
        if isinstance(result, QAction):
            # Eigene Aktion mit Zustand: wird wie eine QGIS-Aktion gespiegelt
            return Resolved(action=result, icon=result.icon())
        return Resolved(callback=result)

    # Ausführen
    def trigger(self, command):
        res = self.resolve(command)
        if not res.available:
            return False
        if res.action is not None:
            return self.call(command, res.action.trigger)
        if res.callback is not None:
            return self.call(command, res.callback)
        if res.menu is not None:
            return self.call(command, lambda: res.menu.popup(QCursor.pos()))
        return True

    def call(self, command, fn):
        """``fn`` für ``command`` ausführen; Fehler melden statt den Ribbon abzubrechen."""
        try:
            fn()
        except Exception as exc:
            self.report(command, exc)
            return False
        return True

    def report(self, command, exc):
        QgsMessageLog.logMessage(tr("Command %s failed: %s") % (command.id, exc),
                                 LOG_TAG, Qgis.Critical)
        self.iface.messageBar().pushMessage(
            LOG_TAG, tr("“%s” failed: %s") % (command.label, exc),
            level=Qgis.Critical, duration=6)


def _plugin_attribute_action(plugin, name):
    """QAction eines geladenen Plugins über dessen Attribute finden (wie im Inventar)."""
    try:
        from qgis import utils
    except ImportError:
        return None
    obj = utils.plugins.get(plugin)
    if obj is None:
        return None
    for value in list(vars(obj).values()):
        if isinstance(value, QAction):
            candidates = [value]
        elif isinstance(value, (list, tuple)):
            candidates = [v for v in value if isinstance(v, QAction)]
        elif isinstance(value, dict):
            candidates = [v for v in value.values() if isinstance(v, QAction)]
        else:
            continue
        for act in candidates:
            if act.objectName() == name:
                return act
    return None
