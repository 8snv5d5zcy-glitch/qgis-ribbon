"""Erweiterungen: Befehle, die erst zur Laufzeit feststehen (ohne qgis-Imports).

Zwei Quellen ergänzen die Ribbon-Definition:

- **Plugin-Aktionen**: Einträge, die andere Plugins in die Plugin-Menüs
  (Erweiterungen, Raster, Vektor, Datenbank, Web) und in Werkzeugleisten
  legen. ID ``plugin:<Schlüssel>``; der Schlüssel ist der Ort der Aktion
  (Menü bzw. Werkzeugleiste und Texte), z. B.
  ``plugin:mPluginMenu/Plugin Reloader/Reload a plugin``.
- **Werkzeugkasten**: Algorithmen der Verarbeitung (eigene Skripte, Modelle,
  QGIS und andere Anbieter). ID ``verarbeitung:<Algorithmus-ID>``, z. B.
  ``verarbeitung:script:mein_werkzeug``.

Was die Integration gefunden hat, kommt als ``FoundAction`` bzw.
``Algorithm`` herein. Eine Aktion mit Dropdown (Button mit Menü in einer
Plugin-Leiste) trägt die Schlüssel ihrer Menüeinträge in ``items``; im Tab
wird sie ein Split-Button, die Einträge (``parent`` gesetzt) bilden das Menü.
Ein Untermenü eines Plugins (``menu`` gesetzt) hat keine eigene
Aktion: Es trägt Beschriftung und die Schlüssel seiner Einträge (``items``,
Befehle oder weitere Untermenüs) und wird im Tab ein Dropdown (``Menu``),
tiefere Ebenen werden Untermenüs darin (``SubMenu``). Jeder Eintrag bleibt ein
eigener Befehl.
``extend`` baut daraus die erweiterte Definition: die
Befehle dazu und den Tab mit ``dynamic: erweiterungen`` gefüllt (eine Gruppe
je Plugin bzw. Plugin-Werkzeugleiste). Befehle, die eine gespeicherte
Anordnung nennt, die es aber gerade nicht gibt (Plugin deinstalliert, Skript
gelöscht), bleiben als Platzhalter erhalten (``is_placeholder``), damit die
Anordnung sie nicht verliert. Der Ribbon zeigt sie nicht (``visible``), der
Editor schon; dort lassen sie sich entfernen (``core.editor.orphan_ids``).
Kommt das Plugin zurück, ist der Eintrag wieder da.

Schlüssel dürfen kein Komma enthalten (Schnellzugriff wird kommagetrennt
gespeichert) und keinen Schrägstrich in einem Teil; beides wird mit ``%``
maskiert (``key``).
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple

import dataclasses

from .model import CommandRef, Command, Gallery, Group, Menu, Ribbon, Row, Source, Split, SubMenu, Tab
from .i18n import tr

PLUGIN_PREFIX = "plugin:"
TOOLBOX_PREFIX = "verarbeitung:"
DYNAMIC_KINDS = ("erweiterungen",)
GROUP_PREFIX = "erw_"
# Anbieter der eigenen Werkzeuge (Skripte, Modelle, Modelle im Projekt)
OWN_PROVIDERS = ("script", "model", "project")
# Gruppen mit höchstens so vielen Einträgen zeigen große Buttons, sonst mittlere
LARGE_UP_TO = 3
OTHER_GROUP = tr("More")

_ESCAPE = (("%", "%25"), (",", "%2C"), ("/", "%2F"))
_SLUG = re.compile(r"[^a-z0-9]+")
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def escape(part):
    for raw, esc in _ESCAPE:
        part = part.replace(raw, esc)
    return part


def unescape(part):
    for raw, esc in reversed(_ESCAPE):
        part = part.replace(esc, raw)
    return part


def key(*parts):
    """Schlüssel einer Plugin-Aktion aus ihrem Ort (Menü/Werkzeugleiste, Texte)."""
    return "/".join(escape(p) for p in parts)


def unique_key(k, taken):
    """``k``, oder ``k#2``, ``k#3`` …, wenn ``k`` schon vergeben ist (gleicher Ort, gleicher Text).

    Der erste Eintrag behält seinen Schlüssel (gespeicherte Anordnungen bleiben gültig),
    spätere zählen in der Reihenfolge von QGIS hoch.
    """
    if k not in taken:
        return k
    n = 2
    while "%s#%d" % (k, n) in taken:
        n += 1
    return "%s#%d" % (k, n)


def slug(text):
    return _SLUG.sub("_", (text or "").lower().translate(_FOLD)).strip("_")


@dataclass(frozen=True)
class FoundAction:
    """Aktion eines anderen Plugins, wie die Integration sie gefunden hat."""

    key: str
    label: str
    group: str                        # Beschriftung der Gruppe (Plugin bzw. Werkzeugleiste)
    description: str = ""
    algorithm: Optional[str] = None   # Button eines Algorithmus (Verarbeitungs-Werkzeugleiste)
    items: Tuple[str, ...] = ()       # Schlüssel der Dropdown-Einträge (Split-Button, Menü)
    parent: Optional[str] = None      # Eintrag im Dropdown dieser Aktion, kein eigener Button
    menu: bool = False                # Untermenü ohne eigene Aktion (Dropdown, kein Befehl)


@dataclass(frozen=True)
class Algorithm:
    id: str
    label: str
    provider: str                     # Anbieter-ID (script, model, native ...)
    provider_label: str = ""
    group: str = ""
    description: str = ""
    keywords: str = ""                # Tags und interner Name (nur für die Suche)

    @property
    def own(self):
        return self.provider in OWN_PROVIDERS


def is_runtime(command_id):
    return isinstance(command_id, str) and command_id.startswith((PLUGIN_PREFIX, TOOLBOX_PREFIX))


def is_plugin(command_id):
    return command_id.startswith(PLUGIN_PREFIX)


def is_toolbox(command_id):
    return command_id.startswith(TOOLBOX_PREFIX)


def own_tool(command_id):
    """Eigenes Werkzeug (Skript, Modell)? Die Algorithmus-ID beginnt mit der Anbieter-ID."""
    return is_toolbox(command_id) and command_id[len(TOOLBOX_PREFIX):].split(":", 1)[0] in OWN_PROVIDERS


def plugin_id(action_key):
    return PLUGIN_PREFIX + action_key


def toolbox_id(algorithm_id):
    return TOOLBOX_PREFIX + algorithm_id


def menu_id(menu_key):
    """Schlüssel eines Dropdowns aus einem Plugin-Untermenü (``Menu.key``, kein Befehl)."""
    return plugin_id(menu_key)


def plugin_command(found):
    return Command(id=plugin_id(found.key), label=found.label,
                   source=Source("extension", {"key": found.key}),
                   description=found.description or tr("Extension “%s”") % found.group)


def toolbox_command(alg, toolbox=None):
    """``toolbox``: übersetztes „Toolbox“, wenn viele Befehle auf einmal entstehen."""
    where = " › ".join(p for p in (toolbox or tr("Toolbox"), alg.provider_label, alg.group) if p)
    text = alg.description.strip() if alg.description else ""
    return Command(id=toolbox_id(alg.id), label=alg.label,
                   source=Source("processing", {"algorithm": alg.id}),
                   description=("%s · %s" % (text, where)) if text else where)


def placeholder(command_id):
    """Befehl für eine ID, die es gerade nicht gibt; None für andere IDs."""
    if is_toolbox(command_id):
        alg = command_id[len(TOOLBOX_PREFIX):]
        label = alg.split(":", 1)[-1] or alg
        return Command(id=command_id, label=label,
                       source=Source("processing", {"algorithm": alg, "placeholder": True}),
                       description=tr("Tool %s is not available") % alg)
    if is_plugin(command_id):
        k = command_id[len(PLUGIN_PREFIX):]
        label = unescape(k.rsplit("/", 1)[-1]) or k
        return Command(id=command_id, label=label, source=Source("extension", {"key": k, "placeholder": True}),
                       description=tr("Extension not loaded"))
    return None


def is_placeholder(command):
    """Platzhalter für einen Laufzeitbefehl, den es gerade nicht gibt?"""
    return bool(command.source.get("placeholder"))


def referenced_ids(*data):
    """IDs von Laufzeitbefehlen in gespeicherten Daten (Anordnung, Anordnungen, Schnellzugriff).

    Durchsucht dicts und Listen nach ``"command": ID``, Listen/kommagetrennten
    Texten unter ``quick_access`` und den Einträgen unter ``galleries`` und
    ``menus`` (Galerie-ID bzw. Elementschlüssel -> Liste der IDs).
    """
    out = set()

    def walk(value, quick=False):
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "command" and is_runtime(v):
                    out.add(v)
                elif k in ("galleries", "menus") and isinstance(v, dict):
                    for ids in v.values():
                        walk(ids, quick=True)
                else:
                    walk(v, quick=(k == "quick_access"))
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v, quick)
        elif quick and isinstance(value, str):
            out.update(c for c in value.split(",") if is_runtime(c))

    for d in data:
        if isinstance(d, str):
            walk(d, quick=True)   # Schnellzugriff als Text
        else:
            walk(d)
    return out


def plugin_groups(found):
    """Gruppen des Tabs „Erweiterungen“: [(Gruppen-ID, Beschriftung, [Befehls-ID])].

    Reihenfolge wie gefunden; Gruppen nach Beschriftung zusammengefasst, eine
    Aktion nur einmal. IDs aus der Beschriftung (stabil, solange das Plugin
    seinen Namen behält).
    """
    order, members, seen_cmd = [], {}, set()
    for f in found:
        if f.parent is not None:
            continue
        cid = toolbox_id(f.algorithm) if f.algorithm else plugin_id(f.key)   # Menü: menu_id
        if cid in seen_cmd:
            continue
        seen_cmd.add(cid)
        label = f.group or OTHER_GROUP
        if label not in members:
            order.append(label)
            members[label] = []
        members[label].append(cid)
    out, taken = [], set()
    for label in order:
        stem = GROUP_PREFIX + (slug(label) or "gruppe")
        gid, n = stem, 2
        while gid in taken:
            gid, n = "%s_%d" % (stem, n), n + 1
        taken.add(gid)
        out.append((gid, label, members[label]))
    return out


def _group(gid, label, members, menus=None, dropdowns=None):
    """Gruppe aus Befehlen und Dropdowns.

    ``members``: Befehle bzw. Schlüssel von Dropdowns (``menu_id``) in ``dropdowns``
    (-> (Beschriftung, Einträge)); ``menus``: Befehls-ID -> Dropdown-Einträge (Split-Button).
    """
    size = "large" if len(members) <= LARGE_UP_TO else "medium"
    menus = menus or {}
    dropdowns = dropdowns or {}
    elements = []
    for m in members:
        if isinstance(m, str):
            title, items = dropdowns[m]
            elements.append(Menu(label=title, items=items, size=size, key=m))
        elif menus.get(m.id):
            elements.append(Split(m, menus[m.id], size))
        else:
            elements.append(CommandRef(m, size))
    return Group(id=gid, label=label, elements=tuple(elements))


def _dropdowns(found, commands):
    """Menü-ID -> (Beschriftung, Einträge) für die Untermenüs der Plugins (``FoundAction.menu``)."""
    by_key = {f.key: f for f in found if f.menu}
    out = {}

    def items(f, seen):
        entries = []
        for k in f.items:
            sub = by_key.get(k)
            if sub is not None:
                if k in seen:
                    continue
                inner = items(sub, seen | {k})
                if inner:
                    entries.append(SubMenu(label=sub.label, items=inner, key=menu_id(k)))
            elif plugin_id(k) in commands:
                entries.append(commands[plugin_id(k)])
        return tuple(entries)

    for f in by_key.values():
        if f.parent is None:
            entries = items(f, {f.key})
            if entries:
                out[menu_id(f.key)] = (f.label, entries)
    return out


def extend(base, found=(), algorithms=(), referenced=()):
    """Definition um Plugin-Aktionen und Werkzeuge erweitern -> neuer ``Ribbon``.

    ``found``: Plugin-Aktionen (füllen den Tab ``dynamic: erweiterungen``);
    ``algorithms``: Werkzeuge, die als Befehl bereitstehen sollen;
    ``referenced``: Laufzeit-IDs aus gespeicherten Anordnungen (fehlende werden Platzhalter).
    Ohne Plugin-Aktionen bleibt der Tab leer (der Ribbon zeigt leere Tabs nicht).
    """
    commands = dict(base.commands)
    algs = {a.id: a for a in algorithms}
    for a in algorithms:
        commands[toolbox_id(a.id)] = toolbox_command(a)
    for f in found:
        if f.menu:
            continue
        if f.algorithm:
            cid = toolbox_id(f.algorithm)
            if cid not in commands:
                alg = algs.get(f.algorithm)
                commands[cid] = toolbox_command(alg) if alg else placeholder(cid)
        else:
            commands.setdefault(plugin_id(f.key), plugin_command(f))
    for cid in referenced:
        if cid not in commands:
            cmd = placeholder(cid)
            if cmd is not None:
                commands[cid] = cmd
    menus = {}
    for f in found:
        if f.items and not f.algorithm and not f.menu:
            items = tuple(commands[plugin_id(k)] for k in f.items if plugin_id(k) in commands)
            if items:
                menus[plugin_id(f.key)] = items
    dropdowns = _dropdowns(found, commands)
    groups = tuple(_group(gid, label, tuple(c if c in dropdowns else commands[c] for c in ids
                                            if c in dropdowns or c in commands), menus, dropdowns)
                   for gid, label, ids in plugin_groups(found))
    groups = tuple(g for g in groups if g.elements)
    tabs = tuple(Tab(id=t.id, label=t.label, groups=groups, dynamic=t.dynamic) if t.dynamic else t
                 for t in base.tabs)
    return Ribbon(tabs=tabs, commands=commands, quick_access=base.quick_access,
                  hide_toolbars=base.hide_toolbars, extensions=base.extensions)


def _replace_commands(base, commands):
    return Ribbon(tabs=base.tabs, commands=commands, quick_access=base.quick_access,
                  hide_toolbars=base.hide_toolbars, extensions=base.extensions)


def with_algorithms(base, algorithms):
    """Definition mit zusätzlichen Werkzeugen als Befehl (Palette des Editors)."""
    commands = dict(base.commands)
    for a in algorithms:
        commands.setdefault(toolbox_id(a.id), toolbox_command(a))
    return _replace_commands(base, commands)


def with_placeholders(base, ids):
    """Definition mit Platzhaltern für unbekannte Laufzeit-IDs (Import, geladene Anordnung)."""
    missing = [c for c in ids if c not in base.commands and is_runtime(c)]
    if not missing:
        return base
    commands = dict(base.commands)
    for cid in missing:
        commands[cid] = placeholder(cid)
    return _replace_commands(base, commands)


def _menu_items(items):
    out = []
    for i in items:
        if isinstance(i, SubMenu):
            sub = _menu_items(i.items)
            if sub or not i.items:
                out.append(dataclasses.replace(i, items=sub) if len(sub) != len(i.items) else i)
        elif not is_placeholder(i):
            out.append(_command(i))
    return tuple(out)


def _command(cmd):
    """Befehl ohne Platzhalter in seiner Galerie (eine Galerie im Ribbon behält mindestens einen Eintrag)."""
    if cmd.gallery is None or not any(is_placeholder(c) for c in cmd.gallery.items):
        return cmd
    items = tuple(c for c in cmd.gallery.items if not is_placeholder(c))
    if not items and cmd.gallery.display == "ribbon":
        return cmd
    return dataclasses.replace(cmd, gallery=Gallery(items, cmd.gallery.display, cmd.gallery.columns))


def _element(e):
    """Element ohne Platzhalter; None, wenn nichts bleibt."""
    if isinstance(e, CommandRef):
        return None if is_placeholder(e.command) else CommandRef(_command(e.command), e.size)
    if isinstance(e, Split):
        if is_placeholder(e.command):
            return None
        items = _menu_items(e.items)
        if not items and e.items:
            return CommandRef(_command(e.command), e.size)
        return dataclasses.replace(e, items=items) if len(items) != len(e.items) else e
    if isinstance(e, Menu):
        items = _menu_items(e.items)
        if not items and e.items and e.gallery is None:
            return None
        return dataclasses.replace(e, items=items) if len(items) != len(e.items) else e
    if isinstance(e, Row):
        cmds = tuple(c for c in e.commands if not is_placeholder(c))
        return Row(cmds) if cmds else None
    return e


def without_placeholders(ribbon):
    """Ribbon ohne Platzhalter; Gruppen und eigene Tabs, die dadurch leer werden, fallen weg.

    Die Befehle (``ribbon.commands``) und der Schnellzugriff bleiben: was der Nutzer
    gespeichert hat, geht nicht verloren.
    """
    if not any(is_placeholder(c) for c in ribbon.commands.values()):
        return ribbon
    tabs = []
    for t in ribbon.tabs:
        groups = []
        for g in t.groups:
            elements = tuple(x for x in (_element(e) for e in g.elements) if x is not None)
            if g.elements and not elements:
                continue
            launcher = g.launcher if g.launcher is None or not is_placeholder(g.launcher) else None
            groups.append(dataclasses.replace(g, elements=elements, launcher=launcher))
        if t.groups and not groups and not t.dynamic:
            continue
        tabs.append(dataclasses.replace(t, groups=tuple(groups)))
    if not any(not t.contextual for t in tabs):
        return ribbon
    return Ribbon(tabs=tuple(tabs), commands=ribbon.commands, quick_access=ribbon.quick_access,
                  hide_toolbars=ribbon.hide_toolbars, extensions=ribbon.extensions)


def visible(ribbon):
    """Wirksamer Ribbon ohne Platzhalter und ohne leere dynamische Tabs (keine Plugins geladen)."""
    ribbon = without_placeholders(ribbon)
    if all(t.groups or not t.dynamic for t in ribbon.tabs):
        return ribbon
    return Ribbon(tabs=tuple(t for t in ribbon.tabs if t.groups or not t.dynamic),
                  commands=ribbon.commands, quick_access=ribbon.quick_access,
                  hide_toolbars=ribbon.hide_toolbars, extensions=ribbon.extensions)
