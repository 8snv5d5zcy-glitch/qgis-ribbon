"""Ribbon-Definition (YAML) laden und prüfen (ohne qgis-Imports).

``parse(data)`` wandelt das geladene YAML (dict) in das Modell aus
``core.model`` um und sammelt dabei alle Fehler. Bei Fehlern wird
``ConfigError`` mit der vollständigen Liste ausgelöst, damit eine kaputte
Konfiguration auf einen Blick korrigiert werden kann.

Das gelesene YAML läuft über ``core.yaml_cache`` (Zwischenspeicher).
"""

import dataclasses
import io
import os
import re

from . import yaml_cache
from .conditions import CONDITIONS, EVENTS
from .inventory import REQUIRED_PARAMS, SOURCE_TYPES
from .extensions import DYNAMIC_KINDS
from .model import (COMMAND_KINDS, GALLERY_DISPLAYS, SIZES, Command, CommandRef, ExtensionSources,
                    Gallery, Group, Menu, Ribbon, Row, Source, Split, SubMenu, Tab)
from .i18n import tr

SCHEMA_VERSION = 1
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config",
                              "ribbon_arcgis.yaml")

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_MENU_DEPTH = 3

_TOP_KEYS = {"version", "hide_toolbars", "quick_access", "tabs", "contextual_tabs", "commands",
             "extensions"}
_EXTENSION_KEYS = {"menus", "toolbars", "qgis_toolbars", "hide"}
_COMMAND_KEYS = {"label", "source", "kind", "icon", "enabled_when", "description", "gallery"}
_GALLERY_KEYS = {"display", "items", "columns"}
_TAB_KEYS = {"id", "label", "groups", "activate_on", "dynamic"}
_CONTEXT_TAB_KEYS = (_TAB_KEYS - {"dynamic"}) | {"context", "visible_when"}
_GROUP_KEYS = {"id", "label", "items", "launcher"}
_ELEMENT_KEYS = {
    "command": {"command", "size"},
    "split": {"split", "items", "size", "label"},
    "menu": {"menu", "items", "size", "icon", "gallery", "key"},
    "row": {"row"},
}
_SUBMENU_KEYS = {"menu", "items", "icon", "gallery", "key"}
# Optionale Parameter je Quelltyp (Pflichtparameter: core.inventory)
_OPTIONAL_PARAMS = {"iface_method": {"args"}, "dock": {"modus"}, "custom": {"args"}}
# Dock: umschalten (Standard, Button zeigt Sichtbarkeit) oder nur zeigen
DOCK_MODES = ("umschalten", "zeigen")


class ConfigError(Exception):
    def __init__(self, errors):
        Exception.__init__(self, tr("Ribbon definition has errors:\n- ") + "\n- ".join(errors))
        self.errors = list(errors)


class _Parser(object):
    def __init__(self):
        self.errors = []
        self.commands = {}
        self.broken = set()  # fehlerhafte Befehle, nicht noch einmal als fehlend melden

    def err(self, path, msg):
        self.errors.append("%s: %s" % (path, msg))

    def _keys(self, obj, allowed, path):
        for k in sorted(set(obj) - allowed, key=str):
            self.err(path, tr("unknown key %r") % k)

    def _text(self, obj, key, path, required=True):
        value = obj.get(key)
        if value is None:
            if required:
                self.err(path, tr("%s is missing") % key)
            return None
        if not isinstance(value, str) or not value.strip():
            self.err(path, tr("%s must be a non-empty text") % key)
            return None
        return value

    def _names(self, obj, key, path, known, what, required=False):
        """Liste von Bedingungen oder Ereignissen; unbekannte Namen sind Fehler."""
        names = self._list(obj, key, path, required=required)
        for n in names:
            if not isinstance(n, str) or n not in known:
                self.err(path, tr("%s %r unknown (known: %s)") % (what, n, ", ".join(sorted(known))))
        if required and not names and key in obj:
            self.err(path, tr("%s must not be empty") % key)
        return tuple(n for n in names if isinstance(n, str) and n in known)

    def _list(self, obj, key, path, required=True):
        value = obj.get(key)
        if value is None:
            if required:
                self.err(path, tr("%s is missing") % key)
            return []
        if not isinstance(value, list):
            self.err(path, tr("%s must be a list") % key)
            return []
        return value

    # Quellen und Befehle
    def source(self, raw, path):
        if not isinstance(raw, dict):
            self.err(path, tr("source must be an object"))
            return None
        stype = raw.get("type")
        if stype not in SOURCE_TYPES:
            self.err(path, tr("source type %r unknown (allowed: %s)") % (stype, ", ".join(SOURCE_TYPES)))
            return None
        required = set(REQUIRED_PARAMS[stype])
        allowed = required | _OPTIONAL_PARAMS.get(stype, set()) | {"type"}
        self._keys(raw, allowed, path)
        ok = True
        for name in sorted(required):
            value = raw.get(name)
            if not isinstance(value, str) or not value:
                self.err(path, tr("%s needs %s (text)") % (stype, name))
                ok = False
        if "args" in raw and not isinstance(raw["args"], list):
            self.err(path, tr("args must be a list"))
            ok = False
        if "modus" in raw and raw["modus"] not in DOCK_MODES:
            self.err(path, tr("modus %r unknown (allowed: %s)") % (raw["modus"], ", ".join(DOCK_MODES)))
            ok = False
        if not ok:
            return None
        return Source(stype, {k: v for k, v in raw.items() if k != "type"})

    def command(self, cid, raw):
        path = "commands.%s" % cid
        if not isinstance(cid, str) or not ID_PATTERN.match(cid):
            self.err(path, tr("invalid ID (allowed: a-z, 0-9, _)"))
        if not isinstance(raw, dict):
            self.err(path, tr("must be an object"))
            return None
        self._keys(raw, _COMMAND_KEYS, path)
        label = tr(self._text(raw, "label", path))
        src = self.source(raw.get("source"), path + ".source")
        kind = raw.get("kind", "button")
        if kind not in COMMAND_KINDS:
            self.err(path, tr("kind %r unknown (allowed: %s)") % (kind, ", ".join(COMMAND_KINDS)))
            return None
        icon = self._text(raw, "icon", path, required=False)
        description = tr(self._text(raw, "description", path, required=False))
        enabled_when = self._names(raw, "enabled_when", path, CONDITIONS, tr("Condition"))
        if "gallery" in raw and kind != "control":
            self.err(path, tr("gallery only on controls (kind: control)"))
        if label is None or src is None:
            return None
        return Command(id=cid, label=label, source=src, kind=kind, icon=icon,
                       enabled_when=enabled_when, description=description)

    def gallery_spec(self, cmd, raw):
        """Galerie eines Steuerelements; Einträge verweisen auf andere Befehle."""
        path = "commands.%s.gallery" % cmd.id
        if not isinstance(raw, dict):
            self.err(path, tr("must be an object"))
            return cmd
        self._keys(raw, _GALLERY_KEYS, path)
        display = raw.get("display", "dropdown")
        if display not in GALLERY_DISPLAYS:
            self.err(path, tr("display %r unknown (allowed: %s)") % (display, ", ".join(GALLERY_DISPLAYS)))
            display = "dropdown"
        columns = raw.get("columns", 4)
        if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
            self.err(path, tr("columns must be an integer of at least 1"))
            columns = 4
        items = []
        for i, cid in enumerate(self._list(raw, "items", path, required=False)):
            p = "%s.items[%d]" % (path, i)
            item = self.ref(cid, p)
            if item is None:
                continue
            if item.kind == "control":
                self.err(p, tr("gallery item %r must not be a control") % item.id)
                continue
            items.append(item)
        if display == "ribbon" and not items:
            self.err(path, tr("display ribbon needs fixed items (items)"))
        return dataclasses.replace(cmd, gallery=Gallery(items=tuple(items), display=display,
                                                        columns=columns))

    def ref(self, cid, path):
        if not isinstance(cid, str):
            self.err(path, tr("command ID expected, not %r") % (cid,))
            return None
        cmd = self.commands.get(cid)
        if cmd is None and cid not in self.broken:
            self.err(path, tr("command %r not defined") % cid)
        return cmd

    def _size(self, raw, path):
        size = raw.get("size", "large")
        if size not in SIZES:
            self.err(path, tr("size %r invalid (allowed: %s)") % (size, ", ".join(SIZES)))
            return "large"
        return size

    # Menüs und Elemente
    def menu_items(self, raw_items, path, depth):
        if not raw_items:
            self.err(path, tr("items must not be empty"))
        items = []
        for i, raw in enumerate(raw_items):
            p = "%s[%d]" % (path, i)
            if isinstance(raw, dict):
                sub = self.submenu(raw, p, depth + 1)
                if sub is not None:
                    items.append(sub)
            else:
                cmd = self.ref(raw, p)
                if cmd is not None:
                    items.append(cmd)
        return tuple(items)

    def _gallery(self, raw, path):
        if "gallery" not in raw:
            return None
        cmd = self.ref(raw["gallery"], path + ".gallery")
        if cmd is not None and cmd.kind != "control":
            self.err(path, tr("gallery %r must be a control (kind: control)") % cmd.id)
        return cmd

    def submenu(self, raw, path, depth):
        if "menu" not in raw:
            self.err(path, tr("submenu needs menu (label)"))
            return None
        self._keys(raw, _SUBMENU_KEYS, path)
        if depth > MAX_MENU_DEPTH:
            self.err(path, tr("menus at most %d levels deep") % MAX_MENU_DEPTH)
            return None
        label = self._text(raw, "menu", path)
        items = self.menu_items(self._list(raw, "items", path), path + ".items", depth)
        icon = self._text(raw, "icon", path, required=False)
        gallery = self._gallery(raw, path)
        if label is None:
            return None
        key = self._text(raw, "key", path, required=False) or label
        return SubMenu(label=tr(label), items=items, icon=icon, gallery=gallery, key=key)

    def element(self, raw, path):
        if not isinstance(raw, dict):
            self.err(path, tr("element must be an object"))
            return None
        kinds = [k for k in _ELEMENT_KEYS if k in raw]
        if len(kinds) != 1:
            self.err(path, tr("exactly one of the keys %s expected") % ", ".join(sorted(_ELEMENT_KEYS)))
            return None
        kind = kinds[0]
        self._keys(raw, _ELEMENT_KEYS[kind], path)
        if kind == "command":
            cmd = self.ref(raw["command"], path)
            size = self._size(raw, path)
            return CommandRef(cmd, size) if cmd else None
        if kind == "split":
            cmd = self.ref(raw["split"], path)
            items = self.menu_items(self._list(raw, "items", path), path + ".items", 1)
            label = tr(self._text(raw, "label", path, required=False))
            size = self._size(raw, path)
            return Split(cmd, items, size, label) if cmd else None
        if kind == "menu":
            label = self._text(raw, "menu", path)
            items = self.menu_items(self._list(raw, "items", path), path + ".items", 1)
            icon = self._text(raw, "icon", path, required=False)
            gallery = self._gallery(raw, path)
            size = self._size(raw, path)
            # Schlüssel für Anpassungen: unabhängig von der Sprache
            key = self._text(raw, "key", path, required=False) or label
            return Menu(tr(label), items, size, icon, gallery, key) if label else None
        ids = self._list(raw, "row", path)
        if not ids:
            self.err(path, tr("row must not be empty"))
        cmds = [self.ref(cid, "%s.row[%d]" % (path, i)) for i, cid in enumerate(ids)]
        return Row(tuple(c for c in cmds if c))

    def group(self, raw, path):
        if not isinstance(raw, dict):
            self.err(path, tr("group must be an object"))
            return None
        self._keys(raw, _GROUP_KEYS, path)
        gid = self._id(raw, path)
        label = tr(self._text(raw, "label", path))
        raw_items = self._list(raw, "items", path)
        if not raw_items:
            self.err(path, tr("items must not be empty"))
        elements = [self.element(e, "%s.items[%d]" % (path, i)) for i, e in enumerate(raw_items)]
        launcher = None
        if "launcher" in raw:
            launcher = self.ref(raw["launcher"], path + ".launcher")
            if launcher is not None and launcher.kind != "button":
                self.err(path, tr("launcher %r must be a button, not a control") % launcher.id)
                launcher = None
        return Group(id=gid or "", label=label or "", elements=tuple(e for e in elements if e),
                     launcher=launcher)

    def _id(self, raw, path):
        gid = raw.get("id")
        if not isinstance(gid, str) or not ID_PATTERN.match(gid):
            self.err(path, tr("id missing or invalid (allowed: a-z, 0-9, _)"))
            return None
        return gid

    def tab(self, raw, path, contextual):
        if not isinstance(raw, dict):
            self.err(path, tr("tab must be an object"))
            return None
        self._keys(raw, _CONTEXT_TAB_KEYS if contextual else _TAB_KEYS, path)
        tid = self._id(raw, path)
        label = tr(self._text(raw, "label", path))
        dynamic = raw.get("dynamic")
        if dynamic is not None:
            # Inhalt entsteht zur Laufzeit (core.extensions): keine festen Gruppen
            if dynamic not in DYNAMIC_KINDS:
                self.err(path, tr("dynamic %r unknown (allowed: %s)") % (dynamic, ", ".join(DYNAMIC_KINDS)))
            if raw.get("groups"):
                self.err(path, tr("tab with dynamic has no fixed groups"))
            if tid is None or label is None:
                return None
            return Tab(id=tid, label=label, dynamic=dynamic if dynamic in DYNAMIC_KINDS else None)
        context, visible_when = None, ()
        if contextual:
            context = tr(self._text(raw, "context", path))
            visible_when = self._names(raw, "visible_when", path, CONDITIONS, tr("Condition"),
                                       required=True)
        raw_groups = self._list(raw, "groups", path)
        if not raw_groups:
            self.err(path, tr("groups must not be empty"))
        groups = [self.group(g, "%s.groups[%d]" % (path, i)) for i, g in enumerate(raw_groups)]
        groups = tuple(g for g in groups if g)
        seen = set()
        for g in groups:
            if g.id in seen:
                self.err(path, tr("group ID %r duplicated") % g.id)
            seen.add(g.id)
        activate_on = self._names(raw, "activate_on", path, EVENTS, tr("Event"))
        if tid is None or label is None:
            return None
        return Tab(id=tid, label=label, groups=groups, context=context,
                   visible_when=visible_when, activate_on=activate_on)

    def ribbon(self, data):
        if not isinstance(data, dict):
            raise ConfigError([tr("root must be an object")])
        self._keys(data, _TOP_KEYS, tr("root"))
        if data.get("version") != SCHEMA_VERSION:
            self.err("version", tr("expected %d, found %r") % (SCHEMA_VERSION, data.get("version")))
        raw_cmds = data.get("commands")
        if not isinstance(raw_cmds, dict) or not raw_cmds:
            self.err("commands", tr("missing or empty"))
            raw_cmds = {}
        for cid, raw in raw_cmds.items():
            cmd = self.command(cid, raw)
            if cmd is not None:
                self.commands[cid] = cmd
        self.broken = set(raw_cmds) - set(self.commands)
        # Zweiter Durchgang: Galerien verweisen auf andere Befehle
        for cid, raw in raw_cmds.items():
            cmd = self.commands.get(cid)
            if cmd is not None and cmd.kind == "control" and "gallery" in raw:
                self.commands[cid] = self.gallery_spec(self.commands[cid], raw["gallery"])

        tabs = []
        for key, contextual in (("tabs", False), ("contextual_tabs", True)):
            for i, raw in enumerate(self._list(data, key, key, required=not contextual)):
                t = self.tab(raw, "%s[%d]" % (key, i), contextual)
                if t is not None:
                    tabs.append(t)
        if not any(not t.contextual for t in tabs):
            self.err("tabs", tr("at least one main tab required"))
        seen = set()
        for t in tabs:
            if t.id in seen:
                self.err("tabs", tr("tab ID %r duplicated") % t.id)
            seen.add(t.id)

        qat = []
        for i, cid in enumerate(self._list(data, "quick_access", "quick_access", required=False)):
            cmd = self.ref(cid, "quick_access[%d]" % i)
            if cmd is not None:
                qat.append(cmd)
        hide = self._list(data, "hide_toolbars", "hide_toolbars", required=False)
        for i, name in enumerate(hide):
            if not isinstance(name, str) or not name:
                self.err("hide_toolbars[%d]" % i, tr("objectName (text) expected"))
        extensions = self.extensions(data.get("extensions"))
        if sum(1 for t in tabs if t.dynamic) > 1:
            self.err("tabs", tr("at most one tab with dynamic"))

        if self.errors:
            raise ConfigError(self.errors)
        return Ribbon(tabs=tuple(tabs), commands=dict(self.commands),
                      quick_access=tuple(qat),
                      hide_toolbars=tuple(n for n in hide if isinstance(n, str)),
                      extensions=extensions)

    def extensions(self, raw):
        """Abschnitt ``extensions``: wo Plugins ihre Aktionen ablegen."""
        if raw is None:
            return ExtensionSources()
        if not isinstance(raw, dict):
            self.err("extensions", tr("must be an object"))
            return ExtensionSources()
        self._keys(raw, _EXTENSION_KEYS, "extensions")
        lists = {}
        for key in ("menus", "toolbars", "qgis_toolbars"):
            names = self._list(raw, key, "extensions", required=False)
            for i, name in enumerate(names):
                if not isinstance(name, str) or not name:
                    self.err("extensions.%s[%d]" % (key, i), tr("objectName (text) expected"))
            lists[key] = tuple(n for n in names if isinstance(n, str) and n)
        hide = raw.get("hide", True)
        if not isinstance(hide, bool):
            self.err("extensions.hide", tr("true or false expected"))
            hide = True
        return ExtensionSources(hide=hide, **lists)


def parse(data):
    """Geladenes YAML (dict) -> ``Ribbon``. Löst ``ConfigError`` aus."""
    return _Parser().ribbon(data)


def read_yaml(path):
    """YAML-Datei als Python-Daten. Braucht PyYAML (in QGIS enthalten)."""
    import yaml

    with io.open(path, encoding="utf-8") as fh:
        try:
            return yaml_cache.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError([tr("YAML not readable: %s") % exc])


def load(path=DEFAULT_CONFIG, cache_dir=None):
    """YAML-Datei laden und prüfen (über den Zwischenspeicher, falls eingerichtet)."""
    return parse(yaml_cache.load(path, read_yaml, cache_dir))
