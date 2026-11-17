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
  Buttons plus die Einträge seines Dropdowns. Ein eingebetteter Button ohne Aktion
  und ohne Dropdown (Plugin hängt nur an ``clicked``) bekommt eine Stellvertreter-Aktion
  (``ButtonAction``). Andere eingebettete Widgets
  (Comboboxen …) lassen sich nicht spiegeln und fehlen. Aktionen, die die Definition schon als Befehl enthält
  (``known``: objectNames, z. B. die Werkzeugkiste der Verarbeitung), erscheinen
  nicht noch einmal.
- Plugin-Hauptmenüs: ein Menü der Menüleiste, das in Python erzeugt wurde
  (``sip.ispycreated``), kein Plugin-Menü der Definition ist und nicht unter
  ``extensions.skip_menus`` steht (Verarbeitung). Alles darin zählt; Gruppe ist der
  Menütitel, Schlüsselwurzel ``menubar/<objectName oder Titel>``.
- Untermenüs innerhalb der Gruppe eines Plugins mit mindestens zwei Einträgen werden ein
  Dropdown (``FoundAction.menu``), mit einem Eintrag wird der Eintrag ein Button.
- Menüs und Leisten von QGIS (Layer › Layer hinzufügen, Leiste Layer verwalten …):
  Aktionen, die in Python erzeugt wurden und keinem mit QGIS ausgelieferten Plugin und
  nicht dem Ribbon gehören. Gruppe = Name des besitzenden Plugins, sonst Titel des Menüs
  bzw. der Leiste.
- Ein Name wie von QGIS (``mAction…``) zählt als Plugin-Aktion, wenn die Aktion in Python
  erzeugt wurde und keinem ausgelieferten Plugin gehört (Plugins melden Kürzel so beim
  Tastenkürzel-Manager an).
- Wem eine Aktion gehört, sucht ``_owners`` in den Attributen der geladenen Plugins bis
  Tiefe 3 (Listen, Dicts und Objekte aus dem Paket des Plugins), zyklensicher. Das
  bestimmt nur noch die Beschriftung der Gruppe und nimmt ausgelieferte Plugins aus.
- Gleicher Ort und gleicher Text: der spätere Eintrag bekommt ``#2``, ``#3`` …
- Werkzeugkasten: alle Algorithmen der Processing-Registry.

Menüs werden über ``actions()`` und ``menu()`` abgelaufen (``submenus``): Ein mit
``addMenu(QMenu)`` eingehängtes Untermenü ist kein Kind des Menüs, ``findChildren``
fände es nicht.

Beobachtet wird ereignisgesteuert: Ereignisfilter für ``ActionAdded`` und
``ActionRemoved`` an den Menüs (samt Untermenüs) und Leisten, ``ChildAdded``/``ChildRemoved``
(Widgets) am Hauptfenster für neue Leisten, Signale der Processing-Registry
und ihrer Anbieter über den zentralen Hub. Nach einer Änderung wird nach der
Ereignisschleife neu gesucht; ``changed`` kommt nur, wenn sich der Inhalt
wirklich geändert hat (Plugin geladen oder entladen, benötigtes Werkzeug
dazugekommen oder weggefallen).

``DesignerCatalog`` macht dasselbe für ein Layout-Fenster: Es zählen nur die Leisten
von QGIS, die der Ribbon dort ersetzt. Eigene Leisten fremder Plugins bleiben sichtbar.
Plugins legen ihre Aktionen oft erst in ihrem eigenen Handler von
``layoutDesignerOpened`` ab, also nach dem Aufbau des Ribbons; das meldet der Ereignisfilter.
"""

import dataclasses
import os
import sys

from qgis.core import QgsApplication, QgsProcessingAlgorithm
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar, QToolButton, QWidgetAction

from ..core import extensions as ext
from ..core.model import ExtensionSources
from ..core.text import plain_text
from .action_resolver import clean_text, core_item_tool, edit_actions
from .signals import alive
from ..core.i18n import tr

QGIS_PREFIX = "mAction"
PROCESSING_PREFIX = "mProcessing"
PROCESSING_BUTTON = "mProcessingAlg_"
OWN_PACKAGE = __name__.split(".")[0]   # Paketname des Ribbons, wie QGIS ihn geladen hat
OWN_PREFIX = "mActionQgisRibbon"       # Aktionen des Ribbons in Menüs von QGIS (Ansicht, Hilfe)
OWNER_DEPTH = 3                        # Tiefe der Suche nach dem Besitzer einer Aktion
_ACTION_EVENTS = (QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved)
_CHILD_EVENTS = (QEvent.Type.ChildAdded, QEvent.Type.ChildRemoved)


def _description(act):
    """Tooltip einer Plugin-Aktion als reiner Text; leer, wenn er nur den Text wiederholt."""
    tip = plain_text(act.toolTip())
    return "" if tip == clean_text(act.text()) or act.toolTip() == act.text() else tip


def _plain_action(act):
    """Echte Aktion mit Text (kein Trenner, kein eingebettetes Widget)?"""
    return not act.isSeparator() and not isinstance(act, QWidgetAction) and bool(clean_text(act.text()))


def _own_action(act, known=()):
    """Aktion eines Plugins (nicht von QGIS selbst, kein Trenner, kein eingebettetes Widget)?"""
    if not _plain_action(act):
        return False
    name = act.objectName()
    return not name.startswith((QGIS_PREFIX, PROCESSING_PREFIX)) and name not in known


_SHIPPED = {}   # Modulpfad -> mit QGIS ausgeliefert?


def _shipped(key):
    """Plugin, das mit QGIS ausgeliefert wird (Verarbeitung, DB-Verwaltung …), oder der Ribbon selbst?"""
    if key == OWN_PACKAGE:
        return True
    path = getattr(sys.modules.get(key), "__file__", None)
    if not path:
        return False
    if path not in _SHIPPED:
        base = os.path.normcase(os.path.abspath(os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")))
        try:
            _SHIPPED[path] = os.path.commonpath([os.path.normcase(os.path.abspath(path)), base]) == base
        except ValueError:   # anderes Laufwerk (Windows)
            _SHIPPED[path] = False
    return _SHIPPED[path]


def from_python(obj):
    """In Python erzeugt (Plugin), nicht von QGIS selbst? Tests ersetzen das für ihr Nachbau-QGIS."""
    try:
        return sip.ispycreated(obj)
    except (TypeError, RuntimeError):
        return False


def submenus(menu):
    """Alle Untermenüs von ``menu`` (über ``actions()`` und ``menu()``, zyklensicher)."""
    out, todo, seen = [], [menu], {id(menu)}
    while todo:
        for act in todo.pop().actions():
            sub = act.menu()
            if sub is not None and id(sub) not in seen:
                seen.add(id(sub))
                out.append(sub)
                todo.append(sub)
    return out


def _plugin_name(key, utils):
    try:
        name = utils.pluginMetadata(key, "name") or key
    except Exception:
        name = key
    return key if name == "__error__" else name


_SCALARS = (str, bytes, int, float, bool, type(None))


def _walk_owner(value, package, depth, seen, out):
    """QActions in ``value`` (Attribute, Listen, Dicts, Objekte aus ``package``) bis ``OWNER_DEPTH``."""
    # isinstance statt hasattr: hasattr auf ein Widget, das C++ schon gelöscht hat
    # (z. B. eine Combobox eines Plugins), wirft RuntimeError.
    if isinstance(value, QAction):
        if alive(value):
            out.append(value)
        return
    if depth >= OWNER_DEPTH or isinstance(value, _SCALARS) or id(value) in seen:
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    elif isinstance(value, dict):
        values = list(value.values())
    else:
        module = getattr(type(value), "__module__", None) or ""
        if depth and module != package and not module.startswith(package + "."):
            return
        try:
            values = list(vars(value).values())
        except TypeError:
            return
    seen.add(id(value))
    for v in values:
        _walk_owner(v, package, depth + 1, seen, out)


def _owners():
    """id(QAction) -> (Name des Plugins, ausgeliefert oder Ribbon?) für alle geladenen Plugins.

    Sucht in den Attributen des Plugin-Objekts bis Tiefe 3: durch Listen, Dicts und
    Objekte aus dem Paket des Plugins (``self.steuerung.aktionen``). Erster Besitzer gewinnt.
    """
    try:
        from qgis import utils
    except ImportError:
        return {}
    out = {}
    for key, obj in list(utils.plugins.items()):
        found = []
        _walk_owner(obj, key.split(".")[0], 0, set(), found)
        if not found:
            continue
        name, shipped = _plugin_name(key, utils), _shipped(key)
        for act in found:
            out.setdefault(id(act), (name, shipped))
    return out


def uses_default_icon(alg_id):
    """True, wenn das Werkzeug kein eigenes Icon hat (zeigt das Standardsymbol von QGIS).

    Eigenes Icon = die Python-Klasse überschreibt ``icon()`` oder ``svgIconPath()``
    (Suche in der MRO bis ``QgsProcessingAlgorithm``). Skripte mit ``@alg`` laufen
    über ``AlgWrapper``, das ``icon()`` immer überschreibt; eigenes Icon nur, wenn
    ``@alg(icon=…)`` ein anderes als das Skriptsymbol von QGIS setzt.
    """
    alg = QgsApplication.processingRegistry().algorithmById(alg_id)
    if alg is None:
        return False
    for cls in type(alg).__mro__:
        if cls is QgsProcessingAlgorithm:
            return True
        if "icon" in cls.__dict__ or "svgIconPath" in cls.__dict__:
            if cls.__name__ == "AlgWrapper" and cls.__module__.endswith("processing.algfactory"):
                return getattr(alg, "_icon", None) in (None, "", QgsApplication.iconPath("processingScript.svg"))
            return False
    return True


class ButtonAction(QAction):
    """Stellvertreter für einen eingebetteten Button ohne Aktion (Plugin hängt nur an ``clicked``).

    Text, Tooltip und Icon stehen fest, wie der Button sie beim ersten Fund zeigte: Ändert ein
    Plugin den Text laufend (z. B. das gewählte Kartenthema), baute sonst jede Änderung den
    Ribbon neu. Aktiv und Häkchen folgen dem Button (``sync``, aus dem Ereignisfilter des
    Katalogs bei ``EnabledChange`` und nach jedem Klick). Auslösen klickt den Button.
    ``key_part`` ist der Teil des Schlüssels: objectName bzw. Klassenname des Buttons
    (stabil, auch wenn der Text wechselt), bei mehreren gleichen in einer Leiste mit ``#2`` usw.
    """

    def __init__(self, button, fallback, parent):
        label = clean_text(button.text()) or plain_text(button.toolTip()) or fallback
        QAction.__init__(self, button.icon(), label, parent)
        self.button = button
        self.base_key = button.objectName() or type(button).__name__
        self.key_part = self.base_key
        self.setToolTip(button.toolTip() or label)
        self.setCheckable(button.isCheckable())
        self.sync()
        self.triggered.connect(self._click)

    def sync(self):
        if not alive(self.button):
            self.setEnabled(False)
            return
        self.setEnabled(self.button.isEnabled())
        if self.button.isCheckable():
            self.setChecked(self.button.isChecked())

    def _click(self, _checked=False):
        if alive(self.button) and self.button.isEnabled():
            self.button.click()
        self.sync()


class ExtensionCatalog(QObject):
    changed = pyqtSignal()
    replaced = pyqtSignal(list)     # Schlüssel, deren Aktion ein Plugin durch eine gleichnamige ersetzt hat
    toolboxChanged = pyqtSignal()   # Werkzeuge neu oder weg (Suchindex); ohne Umbau des Ribbons

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
        self._actions = {}              # Schlüssel -> QAction (Untermenüs: ihre menuAction)
        self._owner_map = None          # id(QAction) -> (Plugin, ausgeliefert?), einmal je Suche
        self._bar_cache = None          # direkte Leisten des Hauptfensters während einer Suche
        self._stand_ins = {}            # id(Button) -> ButtonAction (eingebettete Buttons ohne Aktion)
        self._key_of = {}               # id(QAction) -> Schlüssel (Dropdown-Einträge, die schon vorkommen)
        self._buttons = []              # eingebettete Buttons (beobachtet: Einträge ihres Dropdowns)
        self._signature = None          # (Struktur, Schlüssel -> id der Aktion)
        self._swapped = []              # Schlüssel mit ersetzter Aktion seit dem letzten ``replaced``
        self._needed_state = None
        self._watched = []
        self._providers = set()
        self._tools = None              # alle Werkzeuge (Suche), bis sich der Werkzeugkasten ändert
        self._started = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._rescan)

    # Suchen
    def _owners(self):
        if self._owner_map is None:
            self._owner_map = _owners()
        return self._owner_map

    def _owner(self, act):
        """Name des Plugins, dem ``act`` gehört, oder None."""
        hit = self._owners().get(id(act))
        return hit[0] if hit is not None else None

    def _foreign(self, act):
        """In Python erzeugt und keinem ausgelieferten Plugin, nicht dem Ribbon: Aktion eines Plugins."""
        if act.objectName().startswith(OWN_PREFIX) or not from_python(act):
            return False
        hit = self._owners().get(id(act))
        return hit is None or not hit[1]

    def _own(self, act):
        if not _plain_action(act):
            return False
        name = act.objectName()
        if name in self.known or name.startswith((PROCESSING_PREFIX, OWN_PREFIX)):
            return False
        if not name.startswith(QGIS_PREFIX):
            return True
        # Plugins melden Aktionen beim Tastenkürzel-Manager oft mit einem Namen wie von QGIS an
        # (mActionLayoutPanel); maßgeblich ist dann, wer die Aktion erzeugt hat
        return self._foreign(act)

    def _claim(self, k, act):
        """Schlüssel ``k`` für ``act`` belegen; vergeben -> ``k#2`` … -> belegter Schlüssel."""
        k = ext.unique_key(k, self._actions)
        self._actions[k] = act
        self._key_of[id(act)] = k
        return k

    def _bar_menus(self):
        out = []
        for act in self.iface.mainWindow().menuBar().actions():
            menu = act.menu()
            if menu is not None and menu not in out:
                out.append(menu)
        return out

    def _menus(self):
        # Über die Menüleiste: QGIS hängt Raster, Vektor … erst ein, wenn ein Plugin dort etwas ablegt
        menus = {}
        for menu in self._bar_menus():
            if menu.objectName() in self.sources.menus:
                menus.setdefault(menu.objectName(), menu)
        return [menus[n] for n in self.sources.menus if n in menus]

    def _plugin_main_menu(self, menu):
        name = menu.objectName()
        return (name not in self.sources.menus and name not in self.sources.skip_menus
                and not name.startswith(OWN_PREFIX) and from_python(menu))

    def _main_menus(self):
        """Eigene Hauptmenüs von Plugins in der Menüleiste (in Python erzeugt, nicht ausgenommen)."""
        return [m for m in self._bar_menus() if self._plugin_main_menu(m)]

    def _main_bars(self):
        """Direkte Leisten des Hauptfensters; während einer Suche nur einmal gesucht (findChildren ~1,5 ms)."""
        if self._bar_cache is not None:
            return self._bar_cache
        return self.iface.mainWindow().findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly)

    def _bars(self):
        out = []
        for tb in self._main_bars():
            name = tb.objectName()
            if self.exclude and name == self.exclude:
                continue
            if name in self.sources.toolbars or self.sources.plugin_toolbar(name):
                out.append(tb)
        return out

    def _collect_menu(self, menu, top, path, group, found, seen, everything=False, parent=None):
        """Einträge von ``menu`` -> Schlüssel der Einträge dieser Ebene (für das umgebende Dropdown).

        ``top``: Teile der Schlüsselwurzel; ``group``: Gruppe (None: oberste Ebene eines
        Plugin-Menüs, dort ist jedes Untermenü ein Plugin); ``everything``: jede Aktion zählt
        (Plugin-Hauptmenü); ``parent``: Schlüssel des umgebenden Dropdowns.
        """
        keys = []
        for act in menu.actions():
            sub = act.menu()
            if sub is not None:
                title = clean_text(sub.title())
                if not title:
                    continue
                if group is None:
                    self._collect_menu(sub, top, path + (title,), title, found, seen, everything)
                else:
                    keys.extend(self._collect_submenu(sub, act, top, path + (title,), group, found, seen,
                                                      everything, parent))
                continue
            if id(act) in seen:
                continue
            if not (_plain_action(act) and act.objectName() not in self.known if everything else self._own(act)):
                continue
            text = clean_text(act.text())
            seen.add(id(act))
            k = self._claim(ext.key(*(top + path + (text,))), act)
            keys.append(k)
            # Eintrag direkt im Plugin-Menü (ohne Untermenü, z. B. DB-Verwaltung): eigene Gruppe
            found.append(ext.FoundAction(key=k, label=text, group=group or text,
                                         description=_description(act), parent=parent))
        return keys

    def _collect_submenu(self, sub, act, top, path, group, found, seen, everything, parent):
        """Untermenü in der Gruppe eines Plugins: ab zwei Einträgen ein Dropdown, sonst der Eintrag selbst."""
        mk = ext.unique_key(ext.key(*(top + path)), self._actions)
        self._actions[mk] = act          # Platz halten, damit Einträge den Schlüssel nicht belegen
        inner = []
        keys = self._collect_menu(sub, top, path, group, inner, seen, everything, mk)
        if len(keys) < 2:
            del self._actions[mk]
            # Ein Eintrag: kein Dropdown, der Eintrag rückt eine Ebene hoch
            found.extend(dataclasses.replace(f, parent=parent) if f.key in keys else f for f in inner)
            return keys
        self._key_of[id(act)] = mk
        found.append(ext.FoundAction(key=mk, label=clean_text(sub.title()), group=group, items=tuple(keys),
                                     parent=parent, menu=True))
        found.extend(inner)
        return [mk]

    def _collect_bar(self, tb, found, seen):
        name = tb.objectName() or clean_text(tb.windowTitle())
        collecting = tb.objectName() in self.sources.toolbars
        parts = {}
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
                if isinstance(main, ButtonAction):
                    # Schlüssel aus dem Button; gleiche Buttons einer Leiste durchzählen
                    n = parts.get(main.base_key, 0) + 1
                    parts[main.base_key] = n
                    main.key_part = main.base_key if n == 1 else "%s#%d" % (main.base_key, n)
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
        extra = [a for a in extra if a is not main]
        if main is None and not extra:
            # Nur ``clicked`` (z. B. Auswahl des Kartenthemas): Stellvertreter-Aktion
            main = self._stand_in(tb, widget)
        return main, extra

    def _stand_in(self, tb, widget):
        sa = self._stand_ins.get(id(widget))
        if sa is None or sa.button is not widget or not alive(sa):
            sa = ButtonAction(widget, clean_text(tb.windowTitle()), self)
            self._stand_ins[id(widget)] = sa
        sa.sync()
        return sa

    def _add_bar_action(self, tb, name, collecting, act, extra, found, seen):
        if id(act) in self._key_of or not self._own(act):
            return
        if collecting:
            group = self._owner(act) or ext.OTHER_GROUP
        else:
            group = clean_text(tb.windowTitle()) or name or ext.OTHER_GROUP
        text = clean_text(act.text())
        seen.add(id(act))
        k = self._claim(ext.key("toolbar", name, act.key_part if isinstance(act, ButtonAction) else text), act)
        items, subs = [], []
        for sub in extra:
            if sub.menu() is not None or not self._own(sub):
                continue
            if id(sub) in self._key_of:          # kommt schon anderswo vor (Menü)
                items.append(self._key_of[id(sub)])
                continue
            sub_text = clean_text(sub.text())
            seen.add(id(sub))
            sk = self._claim(ext.key("toolbar", name, text, sub_text), sub)
            items.append(sk)
            subs.append(ext.FoundAction(key=sk, label=sub_text, group=group, parent=k,
                                        description=tr("In the menu of “%s”") % text))
        found.append(ext.FoundAction(key=k, label=text, group=group, items=tuple(items),
                                     description=_description(act)))
        found.extend(subs)

    def _qgis_places(self):
        """Menüs der Menüleiste außer den Plugin-Menüs und die Leisten von QGIS.

        Manche Plugins legen ihre Aktion dorthin statt ins Plugin-Menü, z. B. unter
        Layer › Layer hinzufügen und in die Leiste Layer verwalten.
        """
        menus = [m for m in self._bar_menus() if m.objectName() not in self.sources.menus
                 and m.objectName() not in self.sources.skip_menus and not self._plugin_main_menu(m)]
        bars = [tb for tb in self._main_bars() if tb.objectName() in self.sources.qgis_toolbars]
        return menus, bars

    def _collect_qgis_places(self, found, seen):
        """Aktionen von Plugins in Menüs und Leisten von QGIS. Menü vor Leiste.

        Zählt, was in Python erzeugt wurde und keinem ausgelieferten Plugin und nicht dem
        Ribbon gehört (``_foreign``); ``sip.ispycreated`` kostet je Aktion fast nichts.
        """
        menus, bars = self._qgis_places()
        # Jedes Menü einmal ablaufen (actions() kostet), Untermenüs dabei einsammeln
        todo, known_menus = list(menus), {id(m) for m in menus}
        while todo:
            menu = todo.pop(0)
            place = None
            for act in menu.actions():
                sub = act.menu()
                if sub is not None:
                    if id(sub) not in known_menus:
                        known_menus.add(id(sub))
                        todo.append(sub)
                    continue
                if id(act) in seen or not from_python(act):
                    continue
                if place is None:
                    title = clean_text(menu.title())
                    # objectName des Menüs (sprachunabhängig), sonst sein Titel
                    place = (menu.objectName() or title,)
                self._add_owned(act, place, title, found, seen)
        for tb in bars:
            for act in tb.actions():
                if id(act) not in seen and from_python(act):
                    self._add_owned(act, ("toolbar", tb.objectName()), clean_text(tb.windowTitle()), found, seen)

    def _add_owned(self, act, place, title, found, seen):
        if not _plain_action(act):
            return
        name = act.objectName()
        if name in self.known or name.startswith(PROCESSING_PREFIX) or not self._foreign(act):
            return
        text = clean_text(act.text())
        seen.add(id(act))
        k = self._claim(ext.key(*(place + (text,))), act)
        found.append(ext.FoundAction(key=k, label=text, group=self._owner(act) or title or ext.OTHER_GROUP,
                                     description=_description(act)))

    def _drop_stand_ins(self):
        """Stellvertreter für Buttons, die es nicht mehr gibt, abbauen."""
        used = {id(a) for a in self._actions.values()}
        for wid, sa in list(self._stand_ins.items()):
            if id(sa) not in used:
                del self._stand_ins[wid]
                if alive(sa):
                    sa.deleteLater()

    def scan(self):
        """Plugin-Aktionen und Plugin-Leisten neu suchen. -> True, wenn sich etwas geändert hat."""
        found, seen = [], set()
        self._actions = {}
        self._key_of = {}
        self._buttons = []
        self._owner_map = None   # Zuordnung Aktion -> Plugin, nur bei Bedarf
        self._bar_cache = None
        self._bar_cache = self._main_bars()
        for menu in self._menus():
            self._collect_menu(menu, (menu.objectName(),), (), None, found, seen)
        for menu in self._main_menus():
            title = clean_text(menu.title())
            if title:
                self._collect_menu(menu, ("menubar", menu.objectName() or title), (), title, found, seen,
                                   everything=True)
        bars = self._bars()
        for tb in bars:
            self._collect_bar(tb, found, seen)
        self._collect_qgis_places(found, seen)
        self._owner_map = None
        self._bar_cache = None
        self._drop_stand_ins()
        self.found = found
        self.toolbars = bars
        # Struktur (Schlüssel, Texte, Gruppen, Leisten) getrennt von der Identität der Aktionen:
        # Füllt ein Plugin sein Menü bei jedem Öffnen neu, ändert sich nur die Identität. Dann
        # kein Neuaufbau, nur ``replaced`` (der Auflöser verwirft die gemerkten Ergebnisse)
        structure = (tuple(found), tuple(id(tb) for tb in bars))
        identity = {k: id(a) for k, a in self._actions.items()}
        old = self._signature
        self._signature = (structure, identity)
        if old is None or old[0] != structure:
            return True
        swapped = [k for k, i in identity.items() if old[1].get(k) != i]
        if swapped:
            self._swapped.extend(k for k in swapped if k not in self._swapped)
        return False

    def action(self, action_key):
        act = self._actions.get(action_key)
        if act is not None and not alive(act):
            # Plugin entladen oder neu geladen: gleich benannte neue Aktion suchen. Die
            # Signatur bleibt die alte, damit der geplante Durchlauf den Unterschied meldet
            # (Umbau oder nur ``replaced``).
            sig, swapped = self._signature, list(self._swapped)
            self.scan()
            self._signature, self._swapped = sig, swapped
            self.schedule()
            act = self._actions.get(action_key)
        return act if alive(act) else None

    # Werkzeugkasten
    @staticmethod
    def _algorithm(alg, names=None):
        """``names``: Anbieter-ID -> Name (spart je Werkzeug drei Aufrufe, Suchindex mit allen Werkzeugen)."""
        aid = alg.id()
        pid = aid.split(":", 1)[0]
        if names is not None and pid in names:
            label = names[pid]
        else:
            provider = alg.provider()
            pid, label = (provider.id(), provider.name()) if provider is not None else ("", "")
        return ext.Algorithm(id=aid, label=alg.displayName(), provider=pid, provider_label=label,
                             group=alg.group() or "", description=plain_text(alg.shortDescription()),
                             keywords=" ".join(list(alg.tags()) + [alg.name()]))

    def algorithms(self, ids=None):
        """Werkzeuge als ``core.extensions.Algorithm``; ``ids`` (Befehls-IDs) schränkt ein."""
        reg = QgsApplication.processingRegistry()
        if ids is None:
            if self._tools is None or not self._started:
                names = {p.id(): p.name() for p in reg.providers()}
                self._tools = [self._algorithm(a, names) for a in reg.algorithms()]
            return list(self._tools)
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
        self.hub.connect(reg, "providerRemoved", self._toolbox_changed)
        for provider in reg.providers():
            self._connect_provider(provider)

    def _connect_provider(self, provider):
        if provider is None or provider.id() in self._providers:
            return
        self._providers.add(provider.id())
        self.hub.connect(provider, "algorithmsLoaded", self._toolbox_changed)

    def _provider_added(self, pid):
        self._connect_provider(QgsApplication.processingRegistry().providerById(pid))
        self._toolbox_changed()

    def _toolbox_changed(self, *_args):
        self._tools = None
        self.toolboxChanged.emit()
        self.schedule()

    def _watch(self):
        self._unwatch()
        mw = self.iface.mainWindow()
        objs = [mw, mw.menuBar()]
        # Plugin-Menüs, Plugin-Hauptmenüs und Menüs von QGIS (Plugins legen auch dort etwas ab)
        menus, bars = self._qgis_places()
        for menu in self._menus() + self._main_menus() + menus:
            objs.append(menu)
            objs.extend(submenus(menu))
        objs.extend(self.toolbars)
        objs.extend(self._buttons)
        objs.extend(bars)
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
        self._tools = None
        self._started = False

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        t = event.type()
        if t in _ACTION_EVENTS:
            self.schedule()
        elif t == QEvent.Type.EnabledChange:
            sa = self._stand_ins.get(id(obj))
            if sa is not None and sa.button is obj:
                sa.sync()
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
        swapped, self._swapped = self._swapped, []
        if changed:
            self.changed.emit()
        elif swapped:
            self.replaced.emit(swapped)


class DesignerCatalog(ExtensionCatalog):
    """Aktionen, die Plugins in die Leisten eines Layout-Fensters legen."""

    def __init__(self, iface, window, bars, hub, known=(), parent=None):
        ExtensionCatalog.__init__(self, iface, ExtensionSources(toolbars=tuple(bars)), hub, known=known, parent=parent)
        self.window = window

    def _own(self, act):
        # Rückgängig und Wiederholen haben keinen Namen und liegen auch in der Leiste
        return _own_action(act, self.known) and not core_item_tool(act) and act not in edit_actions(self.window)

    def _menus(self):
        return []

    def _main_menus(self):
        return []

    def _qgis_places(self):
        return [], []

    def _bars(self):
        return [tb for tb in self.window.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly)
                if tb.objectName() in self.sources.toolbars]

    def start(self):
        if not self._started:
            self._started = True
            self._needed_state = frozenset()
            self._watch()

    def _watch(self):
        self._unwatch()
        for obj in self.toolbars + self._buttons:
            obj.installEventFilter(self)
            self._watched.append(obj)
