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
``extend`` baut daraus die erweiterte Definition: die
Befehle dazu und den Tab mit ``dynamic: erweiterungen`` gefüllt (eine Gruppe
je Plugin bzw. Plugin-Werkzeugleiste). Befehle, die eine gespeicherte
Anordnung nennt, die es aber gerade nicht gibt (Plugin deinstalliert, Skript
gelöscht), bleiben als Platzhalter erhalten und erscheinen ausgegraut, damit
die Anordnung sie nicht verliert.

Schlüssel dürfen kein Komma enthalten (Schnellzugriff wird kommagetrennt
gespeichert) und keinen Schrägstrich in einem Teil; beides wird mit ``%``
maskiert (``key``).
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from .model import CommandRef, Command, Group, Ribbon, Source, Split, Tab
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
    items: Tuple[str, ...] = ()       # Schlüssel der Dropdown-Einträge (Split-Button)
    parent: Optional[str] = None      # Eintrag im Dropdown dieser Aktion, kein eigener Button


@dataclass(frozen=True)
class Algorithm:
    id: str
    label: str
    provider: str                     # Anbieter-ID (script, model, native ...)
    provider_label: str = ""
    group: str = ""
    description: str = ""

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


def plugin_command(found):
    return Command(id=plugin_id(found.key), label=found.label,
                   source=Source("extension", {"key": found.key}),
                   description=found.description or tr("Extension “%s”") % found.group)


def toolbox_command(alg):
    where = " › ".join(p for p in (tr("Toolbox"), alg.provider_label, alg.group) if p)
    text = alg.description.strip() if alg.description else ""
    return Command(id=toolbox_id(alg.id), label=alg.label,
                   source=Source("processing", {"algorithm": alg.id}),
                   description=("%s · %s" % (text, where)) if text else where)


def placeholder(command_id):
    """Befehl für eine ID, die es gerade nicht gibt; None für andere IDs."""
    if is_toolbox(command_id):
        alg = command_id[len(TOOLBOX_PREFIX):]
        label = alg.split(":", 1)[-1] or alg
        return Command(id=command_id, label=label, source=Source("processing", {"algorithm": alg}),
                       description=tr("Tool %s is not available") % alg)
    if is_plugin(command_id):
        k = command_id[len(PLUGIN_PREFIX):]
        label = unescape(k.rsplit("/", 1)[-1]) or k
        return Command(id=command_id, label=label, source=Source("extension", {"key": k}),
                       description=tr("Extension not loaded"))
    return None


def referenced_ids(*data):
    """IDs von Laufzeitbefehlen in gespeicherten Daten (Anordnung, Anordnungen, Schnellzugriff).

    Durchsucht dicts und Listen nach ``"command": ID`` und Listen/kommagetrennten
    Texten unter ``quick_access``.
    """
    out = set()

    def walk(value, quick=False):
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "command" and is_runtime(v):
                    out.add(v)
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
        cid = toolbox_id(f.algorithm) if f.algorithm else plugin_id(f.key)
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


def _group(gid, label, commands, menus=None):
    """Gruppe aus Befehlen; ``menus``: Befehls-ID -> Dropdown-Einträge (Split-Button)."""
    size = "large" if len(commands) <= LARGE_UP_TO else "medium"
    menus = menus or {}
    return Group(id=gid, label=label, elements=tuple(
        Split(c, menus[c.id], size) if menus.get(c.id) else CommandRef(c, size) for c in commands))


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
        if f.items and not f.algorithm:
            items = tuple(commands[plugin_id(k)] for k in f.items if plugin_id(k) in commands)
            if items:
                menus[plugin_id(f.key)] = items
    groups = tuple(_group(gid, label, tuple(commands[c] for c in ids), menus)
                   for gid, label, ids in plugin_groups(found))
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


def visible(ribbon):
    """Wirksamer Ribbon ohne leere dynamische Tabs (keine Plugins geladen)."""
    if all(t.groups or not t.dynamic for t in ribbon.tabs):
        return ribbon
    return Ribbon(tabs=tuple(t for t in ribbon.tabs if t.groups or not t.dynamic),
                  commands=ribbon.commands, quick_access=ribbon.quick_access,
                  hide_toolbars=ribbon.hide_toolbars, extensions=ribbon.extensions)
