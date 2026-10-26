"""Aktionen anderer Plugins und Werkzeuge des Werkzeugkastens finden und beobachten.

``ExtensionCatalog`` sucht, was Plugins in QGIS ablegen, und liefert es an
``core.extensions``:

- Plugin-Menüs (Abschnitt ``extensions.menus`` der Definition): je Plugin ein
  Untermenü (``iface.addPluginToMenu`` & Co.), dessen Aktionen eine Gruppe im
  Tab „Erweiterungen“ bilden. Ein Eintrag direkt im Menü (ohne Untermenü, wie
  die DB-Verwaltung) bildet eine Gruppe für sich. Aktionen von QGIS selbst (``mAction…``) und die
  Menüeinträge der Verarbeitung (``mProcessing…``) gehören nicht dazu.
- Werkzeugleisten: die Sammelleisten (``extensions.toolbars``) und eigene
  Leisten der Plugins (alle direkten Leisten des Hauptfensters, die weder dort
  noch unter ``qgis_toolbars`` stehen). Aktionen, die schon im Menü
  vorkommen, zählen einmal. Buttons der Verarbeitung (``mProcessingAlg_<id>``)
  werden zum Werkzeug. Ein eingebetteter Button (``toolbar.addWidget(QToolButton)``)
  und eine Aktion mit eigenem Menü werden zum Split-Button: Hauptaktion des
  Buttons plus die Einträge seines Dropdowns. Andere eingebettete Widgets
  (Comboboxen …) lassen sich nicht spiegeln und fehlen. Aktionen, die die Definition schon als Befehl enthält
  (``known``: objectNames, z. B. die Werkzeugkiste der Verarbeitung), erscheinen
  nicht noch einmal.
- Werkzeugkasten: alle Algorithmen der Processing-Registry.

Beobachtet wird ereignisgesteuert: Ereignisfilter für ``ActionAdded`` und
``ActionRemoved`` an den Menüs und Leisten, ``ChildAdded``/``ChildRemoved``
(Widgets) am Hauptfenster für neue Leisten, Signale der Processing-Registry
und ihrer Anbieter über den zentralen Hub. Nach einer Änderung wird nach der
Ereignisschleife neu gesucht; ``changed`` kommt nur, wenn sich der Inhalt
wirklich geändert hat (Plugin geladen oder entladen, benötigtes Werkzeug
dazugekommen oder weggefallen).
"""

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMenu, QToolBar, QToolButton, QWidgetAction

from ..core import extensions as ext
from .action_resolver import clean_text
from ..core.i18n import tr

QGIS_PREFIX = "mAction"
PROCESSING_PREFIX = "mProcessing"
PROCESSING_BUTTON = "mProcessingAlg_"
_ACTION_EVENTS = (QEvent.ActionAdded, QEvent.ActionRemoved)
_CHILD_EVENTS = (QEvent.ChildAdded, QEvent.ChildRemoved)


def _own_action(act, known=()):
    """Aktion eines Plugins (nicht von QGIS selbst, kein Trenner, kein eingebettetes Widget)?"""
    if act.isSeparator() or isinstance(act, QWidgetAction) or not clean_text(act.text()):
        return False
    name = act.objectName()
    return not name.startswith((QGIS_PREFIX, PROCESSING_PREFIX)) and name not in known


def _plugin_names():
    """QAction (id) -> Name des Plugins, dem sie als Attribut gehört (für Leisten-Buttons)."""
    try:
        from qgis import utils
    except ImportError:
        return {}
    out = {}
    for key, obj in list(utils.plugins.items()):
        try:
            name = utils.pluginMetadata(key, "name") or key
        except Exception:
            name = key
        if name == "__error__":
            name = key
        for value in list(vars(obj).values()):
            if isinstance(value, (list, tuple)):
                values = value
            elif isinstance(value, dict):
                values = list(value.values())
            else:
                values = [value]
            for v in values:
                if hasattr(v, "isSeparator") and hasattr(v, "triggered"):
                    out.setdefault(id(v), name)
    return out


class ExtensionCatalog(QObject):
    changed = pyqtSignal()

    def __init__(self, iface, sources, hub, exclude=None, known=(), parent=None):
        QObject.__init__(self, parent)
        self.iface = iface
        self.sources = sources
        self.hub = hub
        self.exclude = exclude          # eigene Leiste des Ribbons (objectName)
        self.known = frozenset(n for n in known if n)   # objectNames, die die Definition schon nutzt
        self.found = []                 # core.extensions.FoundAction
        self.toolbars = []              # Plugin-Leisten (zum Ausblenden)
        self.needed = set()             # Werkzeug-IDs, die der Ribbon zeigt
        self._actions = {}              # Schlüssel -> QAction
        self._owners = None
        self._key_of = {}               # id(QAction) -> Schlüssel (Dropdown-Einträge, die schon vorkommen)
        self._buttons = []              # eingebettete Buttons (beobachtet: Einträge ihres Dropdowns)
        self._signature = None
        self._needed_state = None
        self._watched = []
        self._providers = set()
        self._started = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._rescan)

    # Suchen
    def _menus(self):
        # Über die Menüleiste: QGIS hängt Raster, Vektor … erst ein, wenn ein Plugin dort etwas ablegt
        menus = {}
        for act in self.iface.mainWindow().menuBar().actions():
            menu = act.menu()
            if menu is not None and menu.objectName() in self.sources.menus:
                menus.setdefault(menu.objectName(), menu)
        return [menus[n] for n in self.sources.menus if n in menus]

    def _bars(self):
        mw = self.iface.mainWindow()
        out = []
        for tb in mw.findChildren(QToolBar, options=Qt.FindDirectChildrenOnly):
            name = tb.objectName()
            if self.exclude and name == self.exclude:
                continue
            if name in self.sources.toolbars or self.sources.plugin_toolbar(name):
                out.append(tb)
        return out

    def _collect_menu(self, menu, top, path, group, found, seen):
        for act in menu.actions():
            sub = act.menu()
            if sub is not None:
                title = clean_text(sub.title())
                if not title:
                    continue
                self._collect_menu(sub, top, path + (title,), group or title, found, seen)
                continue
            if not _own_action(act, self.known) or id(act) in seen:
                continue
            text = clean_text(act.text())
            k = ext.key(top, *(path + (text,)))
            seen.add(id(act))
            self._actions[k] = act
            self._key_of[id(act)] = k
            # Eintrag direkt im Plugin-Menü (ohne Untermenü, z. B. DB-Verwaltung): eigene Gruppe
            found.append(ext.FoundAction(key=k, label=text, group=group or text,
                                         description=clean_text(act.toolTip()) if act.toolTip() != act.text() else ""))

    def _collect_bar(self, tb, found, seen):
        name = tb.objectName() or clean_text(tb.windowTitle())
        collecting = tb.objectName() in self.sources.toolbars
        for act in tb.actions():
            if act.isSeparator() or id(act) in seen:
                continue
            obj = act.objectName()
            if obj.startswith(PROCESSING_BUTTON):
                seen.add(id(act))
                alg = obj[len(PROCESSING_BUTTON):]
                found.append(ext.FoundAction(key=ext.key("toolbar", name, alg), label=clean_text(act.text()) or alg,
                                             group=clean_text(tb.windowTitle()) or tr("Tools"), algorithm=alg))
                continue
            seen.add(id(act))
            if isinstance(act, QWidgetAction):
                main, extra = self._embedded_button(tb, act)
            else:
                main = act
                extra = act.menu().actions() if act.menu() is not None else []
            if main is None:
                # Button ohne Hauptaktion: die Einträge seines Dropdowns als einzelne Buttons
                for sub in extra:
                    self._add_bar_action(tb, name, collecting, sub, [], found, seen)
                continue
            self._add_bar_action(tb, name, collecting, main, extra, found, seen)

    def _embedded_button(self, tb, act):
        """Eingebetteter Button: (Hauptaktion oder None, Einträge des Dropdowns); sonst (None, [])."""
        widget = tb.widgetForAction(act)
        if not isinstance(widget, QToolButton):
            return None, []
        self._buttons.append(widget)
        main = widget.defaultAction()
        menu = widget.menu()
        extra = menu.actions() if menu is not None else widget.actions()
        return main, [a for a in extra if a is not main]

    def _add_bar_action(self, tb, name, collecting, act, extra, found, seen):
        if id(act) in self._key_of or not _own_action(act, self.known):
            return
        if collecting:
            if self._owners is None:
                self._owners = _plugin_names()
            group = self._owners.get(id(act), ext.OTHER_GROUP)
        else:
            group = clean_text(tb.windowTitle()) or name or ext.OTHER_GROUP
        text = clean_text(act.text())
        k = ext.key("toolbar", name, text)
        seen.add(id(act))
        self._actions[k] = act
        self._key_of[id(act)] = k
        items, subs = [], []
        for sub in extra:
            if sub.menu() is not None or not _own_action(sub, self.known):
                continue
            if id(sub) in self._key_of:          # kommt schon anderswo vor (Menü)
                items.append(self._key_of[id(sub)])
                continue
            sub_text = clean_text(sub.text())
            sk = ext.key("toolbar", name, text, sub_text)
            seen.add(id(sub))
            self._actions[sk] = sub
            self._key_of[id(sub)] = sk
            items.append(sk)
            subs.append(ext.FoundAction(key=sk, label=sub_text, group=group, parent=k,
                                        description=tr("In the menu of “%s”") % text))
        found.append(ext.FoundAction(key=k, label=text, group=group, items=tuple(items),
                                     description=clean_text(act.toolTip()) if act.toolTip() != act.text() else ""))
        found.extend(subs)

    def scan(self):
        """Plugin-Aktionen und Plugin-Leisten neu suchen. -> True, wenn sich etwas geändert hat."""
        found, seen = [], set()
        self._actions = {}
        self._key_of = {}
        self._buttons = []
        for menu in self._menus():
            self._collect_menu(menu, menu.objectName(), (), None, found, seen)
        bars = self._bars()
        self._owners = None   # Zuordnung Button -> Plugin, nur bei Bedarf
        for tb in bars:
            self._collect_bar(tb, found, seen)
        self.found = found
        self.toolbars = bars
        sig = (tuple(found), tuple(id(tb) for tb in bars))
        changed = sig != self._signature
        self._signature = sig
        return changed

    def action(self, action_key):
        act = self._actions.get(action_key)
        if act is None:
            return None
        try:
            act.objectName()
        except RuntimeError:   # Plugin entladen, Aktion gelöscht
            return None
        return act

    # Werkzeugkasten
    @staticmethod
    def _algorithm(alg):
        provider = alg.provider()
        return ext.Algorithm(id=alg.id(), label=alg.displayName(),
                             provider=provider.id() if provider is not None else "",
                             provider_label=provider.name() if provider is not None else "",
                             group=alg.group() or "", description=alg.shortDescription() or "")

    def algorithms(self, ids=None):
        """Werkzeuge als ``core.extensions.Algorithm``; ``ids`` (Befehls-IDs) schränkt ein."""
        reg = QgsApplication.processingRegistry()
        if ids is None:
            return [self._algorithm(a) for a in reg.algorithms()]
        out = []
        for cid in sorted(ids):
            if not ext.is_toolbox(cid):
                continue
            alg = reg.algorithmById(cid[len(ext.TOOLBOX_PREFIX):])
            if alg is not None:
                out.append(self._algorithm(alg))
        return out

    def _needed_available(self):
        reg = QgsApplication.processingRegistry()
        return frozenset(cid for cid in self.needed
                         if reg.algorithmById(cid[len(ext.TOOLBOX_PREFIX):]) is not None)

    def icon(self, command):
        """QGIS-Icon eines Laufzeitbefehls (Rückfall, wo das eigene Icon-Set kein Motiv hat)."""
        if ext.is_plugin(command.id):
            act = self.action(command.source.get("key"))
            return act.icon() if act is not None else QIcon()
        if ext.is_toolbox(command.id):
            alg = QgsApplication.processingRegistry().algorithmById(command.source.get("algorithm"))
            return alg.icon() if alg is not None else QIcon()
        return QIcon()

    # Beobachten
    def start(self):
        if self._started:
            return
        self._started = True
        self._needed_state = self._needed_available()
        self._watch()
        reg = QgsApplication.processingRegistry()
        self.hub.connect(reg, "providerAdded", self._provider_added)
        self.hub.connect(reg, "providerRemoved", lambda _pid: self.schedule())
        for provider in reg.providers():
            self._connect_provider(provider)

    def _connect_provider(self, provider):
        if provider is None or provider.id() in self._providers:
            return
        self._providers.add(provider.id())
        self.hub.connect(provider, "algorithmsLoaded", self.schedule)

    def _provider_added(self, pid):
        self._connect_provider(QgsApplication.processingRegistry().providerById(pid))
        self.schedule()

    def _watch(self):
        self._unwatch()
        mw = self.iface.mainWindow()
        objs = [mw, mw.menuBar()]
        for menu in self._menus():
            objs.append(menu)
            objs.extend(m for m in menu.findChildren(QMenu))
        objs.extend(self.toolbars)
        objs.extend(self._buttons)
        for obj in objs:
            obj.installEventFilter(self)
            self._watched.append(obj)

    def _unwatch(self):
        while self._watched:
            obj = self._watched.pop()
            try:
                obj.removeEventFilter(self)
            except RuntimeError:
                pass

    def stop(self):
        self._timer.stop()
        self._unwatch()
        self._providers.clear()
        self._started = False

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        t = event.type()
        if t in _ACTION_EVENTS:
            self.schedule()
        elif t in _CHILD_EVENTS and obj is self.iface.mainWindow():
            child = event.child()
            if child is not None and child.isWidgetType():
                self.schedule()
        return False

    def schedule(self, *_args):
        if self._started:
            self._timer.start()

    def _rescan(self):
        changed = self.scan()
        needed = self._needed_available()
        if needed != self._needed_state:
            self._needed_state = needed
            changed = True
        self._watch()
        if changed:
            self.changed.emit()
