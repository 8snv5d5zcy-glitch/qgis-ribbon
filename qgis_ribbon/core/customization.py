"""Nutzeranpassungen des Ribbons und gespeicherte Anordnungen (ohne qgis-Imports).

Eine *Anordnung* (``Arrangement``) beschreibt, wie der Nutzer den Ribbon
gegenüber der Definition (``ribbon_arcgis.yaml``) umgestellt hat:

- Reihenfolge und Sichtbarkeit der Tabs, eigene Tabs;
- je Tab Reihenfolge und Sichtbarkeit der Gruppen, eigene Gruppen mit
  Befehlen (Größe groß/mittel/klein) und Gruppen der Definition aus anderen
  Tabs;
- persönliche Fassungen von Gruppen der Definition: eigene
  Beschriftung, Befehle und Einheiten der Definition in eigener Reihenfolge
  und Größe; einzeln auf den Standard zurücksetzbar;
- Inhalt und Reihenfolge der Galerien (z. B. Editor- und Analysewerkzeuge).

Tabs und Gruppen der Definition werden nie gelöscht, nur ausgeblendet. Eigene
Tabs und Gruppen und Kopien von Gruppen in anderen Tabs lassen sich löschen.
Kontext-Tabs behalten ihren Platz hinter den Haupt-Tabs.

Gespeichert wird nur, was vom Standard abweicht (``to_dict``): ein
unveränderter Tab steht nur mit seiner ID in der Liste und folgt damit
Änderungen der Definition, ebenso eine Gruppe ohne persönliche Fassung. Tabs
und Gruppen, die die Definition später neu bekommt, erscheinen auch bei
angepasster Anordnung (am Ende). Unbekannte IDs (z. B. nach einer Änderung der
Definition oder aus einer fremden Datei) werden übergangen und als Hinweis
gemeldet, nie als Fehler.

Format 2 (JSON, Schlüssel wie in der Ribbon-Definition)::

    {"tabs": [
        {"tab": "karte"},
        {"tab": "einfuegen", "visible": false},
        {"tab": "bearbeiten", "groups": [
            {"group": "bearbeiten/auswahl", "visible": false},
            {"group": "bearbeiten/werkzeuge", "label": "Meine Werkzeuge", "items": [
                {"element": "split:rechteck", "size": "large"},
                {"command": "puffer", "size": "medium"}]},
            {"id": "eigene_gruppe_1", "label": "Häufig", "items": [
                {"command": "puffer", "size": "large"}]},
            {"group": "karte/navigieren"}]},
        {"id": "eigener_tab_1", "label": "Mein Tab", "groups": [...]}],
     "galleries": {"editor_galerie": ["verschieben", "drehen"]}}

Eine Gruppe der Definition mit ``items`` ist die persönliche Fassung, ohne
``items`` folgt sie der Definition. Einträge sind einzelne Befehle
(``command`` mit ``size``) oder ganze Einheiten der Definition (``element``:
Split, Menü, Galerie-Menü, Zeile) mit stabilem Schlüssel (``element_key``);
Splits und Menüs tragen eine Größe, Zeilen nicht. Format 1 (ohne
persönliche Fassungen) wird unverändert gelesen.

Eine Datei zum Teilen (``make_bundle``/``read_bundle``) enthält zusätzlich die
Schnellzugriffsleiste und die eigenen Kürzel.
"""

import copy
import dataclasses
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .model import (SIZES, Command, CommandRef, Group, Menu, Ribbon, Row, Split, SubMenu, Tab)
from .i18n import tr

FORMAT = "qgis_ribbon_anordnung"
VERSION = 2
READ_VERSIONS = (1, 2)
CUSTOM_TAB_PREFIX = "eigener_tab_"
CUSTOM_GROUP_PREFIX = "eigene_gruppe_"
NEW_TAB_LABEL = tr("New Tab")
NEW_GROUP_LABEL = tr("New Group")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SIZE_LABELS = {"large": tr("large"), "medium": tr("medium"), "small": tr("small")}


class BundleError(Exception):
    """Datei ist keine lesbare Anordnung (falsches Format, falsche Version)."""


@dataclass
class ItemEntry:
    """Eintrag einer Gruppe: ein Befehl oder eine Einheit der Definition (``element``)."""

    command: Optional[str] = None
    size: Optional[str] = "large"   # None bei Zeilen (keine Größe)
    element: Optional[str] = None   # Schlüssel (``element_key``) statt eines Befehls

    @property
    def key(self):
        return self.element if self.element is not None else "command:%s" % self.command


@dataclass
class GroupEntry:
    id: str
    label: str
    ref: Optional[str] = None   # Gruppe der Definition ("tab/gruppe"); None = eigene Gruppe
    visible: bool = True
    # Eigene Gruppen: immer eine Liste. Gruppen der Definition: None = wie in der
    # Definition, Liste = persönliche Fassung.
    items: Optional[List[ItemEntry]] = None

    def __post_init__(self):
        if self.ref is None and self.items is None:
            self.items = []

    @property
    def custom(self):
        return self.ref is None

    @property
    def home_tab(self):
        return self.ref.split("/", 1)[0] if self.ref else None


@dataclass
class TabEntry:
    id: str
    label: str
    standard: bool = False      # Tab der Definition
    contextual: bool = False
    visible: bool = True
    groups: List[GroupEntry] = field(default_factory=list)

    def is_home(self, group):
        """Gruppe der Definition an ihrem eigenen Platz (nicht löschbar, nur ausblendbar)."""
        return self.standard and group.ref is not None and group.home_tab == self.id


@dataclass
class Arrangement:
    tabs: List[TabEntry] = field(default_factory=list)
    galleries: Dict[str, List[str]] = field(default_factory=dict)

    def copy(self):
        return copy.deepcopy(self)

    def tab(self, tab_id):
        for t in self.tabs:
            if t.id == tab_id:
                return t
        raise KeyError(tab_id)

    def ids(self):
        out = set()
        for t in self.tabs:
            out.add(t.id)
            out.update(g.id for g in t.groups)
        return out


def group_ref(tab_id, group_id):
    return "%s/%s" % (tab_id, group_id)


_GROUPS_CACHE = {}


def standard_groups(base):
    """Gruppen der Definition: Verweis ("tab/gruppe") -> (Tab, Group).

    Je Definition einmal gebaut (der Editor fragt sehr oft). Nicht verändern.
    """
    cached = _GROUPS_CACHE.get(id(base))
    if cached is not None and cached[0] is base:
        return cached[1]
    groups = {group_ref(t.id, g.id): (t, g) for t in base.tabs for g in t.groups}
    if len(_GROUPS_CACHE) > 8:
        _GROUPS_CACHE.clear()
    _GROUPS_CACHE[id(base)] = (base, groups)
    return groups


def gallery_item_allowed(command):
    """Galerie-Einträge sind Buttons (keine Steuerelemente, keine Galerien)."""
    return command.kind == "button" and command.gallery is None


def galleries(base):
    """Befehle mit festen Galerie-Einträgen, die sich anpassen lassen."""
    return {cid: c for cid, c in base.commands.items() if c.gallery is not None and c.gallery.items}


# Elemente der Definition
def element_key(element, ref):
    """Stabiler Schlüssel eines Gruppenelements aus seinem Inhalt.

    ``ref`` ist die Gruppe der Definition ("tab/gruppe"), in der es steht
    (nur Menüs brauchen sie, weil sie keinen eigenen Befehl haben).
    """
    if isinstance(element, CommandRef):
        return "command:%s" % element.command.id
    if isinstance(element, Split):
        return "split:%s" % element.command.id
    if isinstance(element, Menu):
        return "menu:%s/%s" % (ref, element.key or element.label)
    if isinstance(element, Row):
        return "row:%s" % element.commands[0].id
    raise TypeError(tr("Unknown element: %r") % (element,))


def _element_keys(base):
    """(Verweis der Gruppe, Element, Schlüssel) für alle Elemente der Definition.

    Kommt ein Schlüssel mit anderem Inhalt ein zweites Mal vor, bekommt er
    ``#2``, ``#3`` … (gleicher Inhalt = gleicher Schlüssel).
    """
    seen = {}
    out = []
    for t in base.tabs:
        for g in t.groups:
            ref = group_ref(t.id, g.id)
            for e in g.elements:
                stem = key = element_key(e, ref)
                n = 2
                while key in seen and seen[key] != e:
                    key, n = "%s#%d" % (stem, n), n + 1
                seen.setdefault(key, e)
                out.append((ref, e, key))
    return out


_INDEX_CACHE = {}


def element_index(base):
    """Schlüssel -> Element der Definition (Splits, Menüs, Zeilen und einzelne Befehle)."""
    cached = _INDEX_CACHE.get(id(base))
    if cached is not None and cached[0] is base:
        return cached[1]
    index = {}
    by_group = {}
    for ref, e, key in _element_keys(base):
        index.setdefault(key, e)
        by_group.setdefault(ref, []).append(key)
    if len(_INDEX_CACHE) > 8:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[id(base)] = (base, (index, by_group))
    return index, by_group


def element_of(base, key):
    """Element zu einem Schlüssel; None, wenn es das in der Definition nicht (mehr) gibt."""
    return element_index(base)[0].get(key)


def has_size(element):
    return not isinstance(element, Row)


def standard_items(base, ref):
    """Einträge einer Gruppe der Definition, wie sie dort steht."""
    _tab, group = standard_groups(base)[ref]
    keys = element_index(base)[1].get(ref, [])
    out = []
    for e, key in zip(group.elements, keys):
        if isinstance(e, CommandRef):
            out.append(ItemEntry(e.command.id, e.size))
        else:
            out.append(ItemEntry(size=e.size if has_size(e) else None, element=key))
    return out


def group_items(base, group):
    """Wirksame Einträge einer Gruppe (eigene, persönliche Fassung oder Definition)."""
    if group.items is not None:
        return group.items
    return standard_items(base, group.ref)


def standard_label(base, group):
    return standard_groups(base)[group.ref][1].label if group.ref is not None else group.label


def is_modified(base, group):
    """Gruppe der Definition mit persönlicher Fassung oder eigener Beschriftung."""
    if group.ref is None:
        return False
    return group.items is not None or group.label != standard_label(base, group)


def make_personal(base, group):
    """Gruppe der Definition zur persönlichen Fassung machen (Einträge zum Bearbeiten)."""
    if group.items is None:
        group.items = standard_items(base, group.ref)
    return group.items


def reset_group(base, group):
    """Gruppe der Definition wieder wie in der Definition (Beschriftung und Einträge)."""
    if group.ref is None:
        raise ValueError(tr("Only groups of the definition can be reset"))
    group.items = None
    group.label = standard_label(base, group)


def normalize(base, group):
    """Persönliche Fassung, die der Definition entspricht, wieder als „folgt der Definition“."""
    if group.ref is not None and group.items is not None and \
            _items_key(group.items) == _items_key(standard_items(base, group.ref)):
        group.items = None


def item_element(base, item):
    """Element des wirksamen Ribbons für einen Eintrag; None, wenn es fehlt."""
    if item.element is None:
        cmd = base.commands.get(item.command)
        return CommandRef(cmd, item.size if item.size in SIZES else "large") if cmd else None
    element = element_of(base, item.element)
    if element is None:
        return None
    if has_size(element) and item.size in SIZES and item.size != element.size:
        element = dataclasses.replace(element, size=item.size)
    return element


def item_label(base, item):
    """Beschriftung eines Eintrags für Anzeigen und Meldungen."""
    element = item_element(base, item)
    if isinstance(element, CommandRef):
        return element.command.label
    if isinstance(element, Split):
        return element.display_label
    if isinstance(element, Menu):
        return element.label
    if isinstance(element, Row):
        return ", ".join(c.label for c in element.commands)
    return item.key


# Standard und Lesen
def _std_group(tab, group):
    return GroupEntry(id=group.id, label=group.label, ref=group_ref(tab.id, group.id))


def _std_tab(tab):
    return TabEntry(id=tab.id, label=tab.label, standard=True, contextual=tab.contextual,
                    groups=[_std_group(tab, g) for g in tab.groups])


def standard(base):
    """Anordnung der Definition (keine Anpassung)."""
    return Arrangement(tabs=[_std_tab(t) for t in base.tabs])


class _Reader(object):
    def __init__(self, base):
        self.base = base
        self.warnings = []
        self.std_tabs = {t.id: t for t in base.tabs}
        self.std_groups = standard_groups(base)
        self.custom_ids = set()

    def warn(self, text):
        self.warnings.append(text)

    def _custom_id(self, raw_id, what):
        if not isinstance(raw_id, str) or not ID_PATTERN.match(raw_id):
            self.warn(tr("%s with invalid ID %r skipped") % (what, raw_id))
            return None
        if raw_id in self.std_tabs or raw_id in self.custom_ids:
            self.warn(tr("%s %r duplicated, skipped") % (what, raw_id))
            return None
        self.custom_ids.add(raw_id)
        return raw_id

    @staticmethod
    def _label(raw, default):
        label = raw.get("label")
        return label.strip() if isinstance(label, str) and label.strip() else default

    def items(self, raw_items, where):
        out = []
        for raw in raw_items if isinstance(raw_items, list) else []:
            if isinstance(raw, str):
                raw = {"command": raw}
            if not isinstance(raw, dict):
                continue
            size = raw.get("size", "large")
            if "element" in raw:
                key = raw["element"]
                element = element_of(self.base, key) if isinstance(key, str) else None
                if element is None:
                    self.warn(tr("Element %r in %s no longer exists") % (key, where))
                    continue
                if not has_size(element):
                    size = None
                elif size not in SIZES:
                    size = element.size
                out.append(ItemEntry(size=size, element=key))
                continue
            cid = raw.get("command")
            if cid not in self.base.commands:
                self.warn(tr("Command %r in %s no longer exists") % (cid, where))
                continue
            out.append(ItemEntry(cid, size if size in SIZES else "large"))
        return out

    def groups(self, raw_groups, tab_id):
        out, refs = [], set()
        for raw in raw_groups if isinstance(raw_groups, list) else []:
            if not isinstance(raw, dict):
                continue
            visible = raw.get("visible", True) is not False
            if "group" in raw:
                ref = raw["group"]
                if ref not in self.std_groups:
                    self.warn(tr("Group %r no longer exists in the ribbon definition") % (ref,))
                    continue
                if ref in refs:
                    continue
                refs.add(ref)
                t, g = self.std_groups[ref]
                entry = _std_group(t, g)
                entry.visible = visible
                entry.label = self._label(raw, g.label)
                if "items" in raw:
                    entry.items = self.items(raw["items"], tr("“%s”") % entry.label)
                    normalize(self.base, entry)
                out.append(entry)
                continue
            gid = self._custom_id(raw.get("id"), tr("Custom group"))
            if gid is None:
                continue
            label = self._label(raw, NEW_GROUP_LABEL)
            out.append(GroupEntry(id=gid, label=label, visible=visible,
                                  items=self.items(raw.get("items"), tr("“%s”") % label)))
        return out

    def tab(self, raw, used):
        visible = raw.get("visible", True) is not False
        if "tab" in raw:
            tid = raw["tab"]
            base_tab = self.std_tabs.get(tid)
            if base_tab is None:
                self.warn(tr("Tab %r no longer exists in the ribbon definition") % (tid,))
                return None
            if tid in used:
                return None
            entry = _std_tab(base_tab)
            entry.visible = visible
            if "groups" in raw:
                entry.groups = self.groups(raw["groups"], tid)
                present = {g.ref for g in entry.groups if entry.is_home(g)}
                # Gruppen, die die Definition neu bekommen hat, hinten anfügen
                entry.groups += [_std_group(base_tab, g) for g in base_tab.groups
                                 if group_ref(tid, g.id) not in present]
            return entry
        tid = self._custom_id(raw.get("id"), tr("Custom tab"))
        if tid is None:
            return None
        return TabEntry(id=tid, label=self._label(raw, NEW_TAB_LABEL), visible=visible,
                        groups=self.groups(raw.get("groups"), tid))

    def galleries(self, raw):
        out = {}
        known = galleries(self.base)
        for gid, ids in (raw.items() if isinstance(raw, dict) else ()):
            if gid not in known or not isinstance(ids, list):
                self.warn(tr("Gallery %r no longer exists") % (gid,))
                continue
            items = []
            for cid in ids:
                cmd = self.base.commands.get(cid)
                if cmd is None or not gallery_item_allowed(cmd):
                    self.warn(tr("Gallery item %r no longer exists") % (cid,))
                elif cid not in items:
                    items.append(cid)
            if not items and known[gid].gallery.display == "ribbon":
                self.warn(tr("Gallery %r without items, default applies") % gid)
                continue
            out[gid] = items
        return out

    def read(self, data):
        if not data:
            return standard(self.base)
        if not isinstance(data, dict):
            self.warn(tr("Arrangement unreadable, default applies"))
            return standard(self.base)
        tabs, used = [], set()
        for raw in data.get("tabs") or []:
            if not isinstance(raw, dict):
                continue
            entry = self.tab(raw, used)
            if entry is not None:
                tabs.append(entry)
                used.add(entry.id)
        if not data.get("tabs"):
            tabs = standard(self.base).tabs
            used = {t.id for t in tabs}
        # Tabs, die die Definition neu bekommen hat: Haupt-Tabs hinter den letzten Haupt-Tab
        for base_tab in self.base.tabs:
            if base_tab.id in used:
                continue
            entry = _std_tab(base_tab)
            if base_tab.contextual:
                tabs.append(entry)
            else:
                last = max([i for i, t in enumerate(tabs) if not t.contextual] or [-1])
                tabs.insert(last + 1, entry)
        arr = Arrangement(tabs=_ordered(tabs), galleries=self.galleries(data.get("galleries")))
        return arr


def _ordered(tabs):
    """Haupt-Tabs vor Kontext-Tabs, sonst in der gegebenen Reihenfolge."""
    return [t for t in tabs if not t.contextual] + [t for t in tabs if t.contextual]


def from_dict(data, base):
    """Gespeicherte Anpassung -> (``Arrangement``, Hinweise). ``None``/leer = Standard.

    Liest Format 1 und Format 2; Format 1 ist eine Teilmenge.
    """
    reader = _Reader(base)
    arr = reader.read(data)
    return arr, reader.warnings


# Schreiben
def _item_dict(item):
    if item.element is not None:
        out = {"element": item.element}
        if item.size is not None:
            out["size"] = item.size
        return out
    return {"command": item.command, "size": item.size}


def _items_key(items):
    return [_item_dict(i) for i in items]


def _group_dict(g, base=None):
    if g.ref is not None:
        out = {"group": g.ref}
        if base is not None:
            if g.label != standard_label(base, g):
                out["label"] = g.label
            if g.items is not None and _items_key(g.items) != _items_key(standard_items(base, g.ref)):
                out["items"] = _items_key(g.items)
    else:
        out = {"id": g.id, "label": g.label, "items": _items_key(g.items)}
    if not g.visible:
        out["visible"] = False
    return out


def _groups_key(groups, base=None):
    return [_group_dict(g, base) for g in groups]


def to_dict(arr, base):
    """Anordnung -> JSON-fähiges dict; ``None``, wenn sie dem Standard entspricht."""
    std = {t.id: t for t in standard(base).tabs}
    tabs = []
    for t in arr.tabs:
        if t.standard:
            out = {"tab": t.id}
            if not t.visible:
                out["visible"] = False
            if t.id in std and _groups_key(t.groups, base) != _groups_key(std[t.id].groups, base):
                out["groups"] = _groups_key(t.groups, base)
        else:
            out = {"id": t.id, "label": t.label, "groups": _groups_key(t.groups, base)}
            if not t.visible:
                out["visible"] = False
        tabs.append(out)
    data = {}
    if tabs != [{"tab": t.id} for t in base.tabs]:
        data["tabs"] = tabs
    known = galleries(base)
    gals = {gid: list(ids) for gid, ids in sorted(arr.galleries.items())
            if gid in known and list(ids) != [c.id for c in known[gid].gallery.items]}
    if gals:
        data["galleries"] = gals
    return data or None


def is_standard(arr, base):
    return to_dict(arr, base) is None


# Anwenden
def _subst(item, m):
    """Befehle in einem Ribbon-Objekt ersetzen (angepasste Galerien)."""
    rep = dataclasses.replace
    if isinstance(item, Command):
        return m.get(item.id, item)
    if isinstance(item, CommandRef):
        return rep(item, command=_subst(item.command, m))
    if isinstance(item, Split):
        return rep(item, command=_subst(item.command, m), items=tuple(_subst(i, m) for i in item.items))
    if isinstance(item, (Menu, SubMenu)):
        return rep(item, items=tuple(_subst(i, m) for i in item.items),
                   gallery=_subst(item.gallery, m) if item.gallery is not None else None)
    if isinstance(item, Row):
        return rep(item, commands=tuple(_subst(c, m) for c in item.commands))
    if isinstance(item, Group):
        return rep(item, elements=tuple(_subst(e, m) for e in item.elements),
                   launcher=_subst(item.launcher, m) if item.launcher is not None else None)
    return item


def _elements(base, items):
    out = []
    for item in items:
        element = item_element(base, item)
        if element is not None:
            out.append(element)
    return tuple(out)


def apply(base, arr):
    """Wirksamer Ribbon: Definition mit Anordnung des Nutzers.

    Ohne sichtbaren Haupt-Tab bleibt es bei der Definition (``problems``
    verhindert das Speichern einer solchen Anordnung). Eine geleerte
    persönliche Fassung einer Gruppe der Definition erscheint nicht.
    """
    if arr is None or is_standard(arr, base):
        return base
    if problems(arr):
        return base
    commands = dict(base.commands)
    known = galleries(base)
    replaced = {}
    for gid, ids in arr.galleries.items():
        cmd = known.get(gid)
        items = tuple(commands[c] for c in ids if c in commands)
        if cmd is None or (not items and cmd.gallery.display == "ribbon"):
            continue
        replaced[gid] = dataclasses.replace(cmd, gallery=dataclasses.replace(cmd.gallery, items=items))
    commands.update(replaced)
    std_groups = standard_groups(base)
    tabs = []
    for t in arr.tabs:
        if not t.visible:
            continue
        groups, seen = [], set()
        for g in t.groups:
            if not g.visible:
                continue
            if g.ref is not None:
                if g.ref not in std_groups:
                    continue
                group = std_groups[g.ref][1]
                if g.items is not None:
                    group = dataclasses.replace(group, elements=_elements(base, g.items))
                if g.label != group.label:
                    group = dataclasses.replace(group, label=g.label)
            else:
                group = Group(id=g.id, label=g.label, elements=_elements(base, g.items))
            if g.ref is not None and g.items is not None and not group.elements:
                continue   # geleerte persönliche Fassung
            if group.id in seen:
                # Gleiche ID wie eine andere Gruppe im Tab (z. B. aus einem anderen Tab): eindeutig machen
                stem = "%s_%s" % (g.home_tab or t.id, group.id)
                gid, n = stem, 2
                while gid in seen:
                    gid, n = "%s_%d" % (stem, n), n + 1
                group = dataclasses.replace(group, id=gid)
            if replaced:
                group = _subst(group, replaced)
            seen.add(group.id)
            groups.append(group)
        if t.standard:
            tabs.append(dataclasses.replace(base.tab(t.id), groups=tuple(groups)))
        else:
            tabs.append(Tab(id=t.id, label=t.label, groups=tuple(groups)))
    tabs = [t for t in tabs if not t.contextual] + [t for t in tabs if t.contextual]
    return Ribbon(tabs=tuple(tabs), commands=commands, quick_access=base.quick_access,
                  hide_toolbars=base.hide_toolbars, extensions=base.extensions)


# Prüfen
def problems(arr):
    """Gründe, warum sich die Anordnung nicht speichern lässt (leer = in Ordnung)."""
    out = []
    if not any(t.visible and not t.contextual for t in arr.tabs):
        out.append(tr("At least one main tab must stay visible."))
    for t in arr.tabs:
        if not t.standard and not t.label.strip():
            out.append(tr("A custom tab has no label."))
        for g in t.groups:
            if not g.label.strip():
                out.append(tr("A group in “%s” has no label.") % t.label)
    return out


def drop_empty_groups(arr):
    """Leere eigene Gruppen verwerfen (beim Speichern). -> Beschriftungen der verworfenen."""
    dropped = []
    for t in arr.tabs:
        keep = []
        for g in t.groups:
            if g.custom and not g.items:
                dropped.append(g.label)
            else:
                keep.append(g)
        t.groups[:] = keep
    return dropped


# Bearbeiten
def new_id(prefix, taken):
    n = 1
    while "%s%d" % (prefix, n) in taken:
        n += 1
    return "%s%d" % (prefix, n)


def _taken(arr, base):
    return arr.ids() | {t.id for t in base.tabs}


def new_tab(arr, base, after=None, label=NEW_TAB_LABEL):
    """Eigenen Tab anlegen, hinter dem Tab ``after`` (Index) bzw. hinter dem letzten Haupt-Tab."""
    entry = TabEntry(id=new_id(CUSTOM_TAB_PREFIX, _taken(arr, base)), label=label)
    main = [i for i, t in enumerate(arr.tabs) if not t.contextual]
    if after is None or after >= len(arr.tabs) or arr.tabs[after].contextual:
        after = main[-1] if main else -1
    arr.tabs.insert(after + 1, entry)
    return entry


def new_group(arr, base, tab, after=None, label=NEW_GROUP_LABEL):
    """Eigene Gruppe im Tab anlegen, hinter der Gruppe ``after`` (Index) bzw. am Ende."""
    entry = GroupEntry(id=new_id(CUSTOM_GROUP_PREFIX, _taken(arr, base)), label=label)
    index = len(tab.groups) if after is None else after + 1
    tab.groups.insert(index, entry)
    return entry


def add_group_ref(tab, base, ref, after=None):
    """Gruppe der Definition in den Tab einfügen. None, wenn sie schon dort steht.

    Steht sie ausgeblendet an ihrem eigenen Platz, wird sie wieder eingeblendet.
    """
    std = standard_groups(base)
    if ref not in std:
        raise KeyError(ref)
    for g in tab.groups:
        if g.ref == ref:
            if not g.visible:
                g.visible = True
                return g
            return None
    entry = _std_group(*std[ref])
    tab.groups.insert(len(tab.groups) if after is None else after + 1, entry)
    return entry


def default_size(command):
    """Größe beim Hinzufügen: Steuerelemente mittel (Feld mit Beschriftung), sonst groß."""
    return "medium" if command.kind == "control" and command.gallery is None else "large"


def add_command(group, command_id, size="large", after=None, base=None):
    """Befehl in die Gruppe einfügen. Gruppen der Definition brauchen ``base`` (persönliche Fassung)."""
    if not group.custom:
        if base is None:
            raise ValueError(tr("Commands in groups of the definition need the definition"))
        make_personal(base, group)
    item = ItemEntry(command_id, size if size in SIZES else "large")
    group.items.insert(len(group.items) if after is None else after + 1, item)
    return item


def can_remove_tab(tab):
    return not tab.standard


def can_remove_group(tab, group):
    return not tab.is_home(group)


def remove_tab(arr, tab):
    if not can_remove_tab(tab):
        raise ValueError(tr("Tabs of the definition can only be hidden"))
    arr.tabs.remove(tab)


def remove_group(tab, group):
    if not can_remove_group(tab, group):
        raise ValueError(tr("Groups of the definition can only be hidden"))
    tab.groups.remove(group)


def move_tab(arr, index, delta):
    """Tab verschieben (Haupt-Tabs nur unter Haupt-Tabs, Kontext-Tabs unter Kontext-Tabs).

    Neuer Index oder None, wenn es nicht weiter geht.
    """
    target = index + delta
    if not 0 <= target < len(arr.tabs) or arr.tabs[target].contextual != arr.tabs[index].contextual:
        return None
    arr.tabs[index], arr.tabs[target] = arr.tabs[target], arr.tabs[index]
    return target


def move_in_list(items, index, delta):
    target = index + delta
    if not 0 <= target < len(items):
        return None
    items[index], items[target] = items[target], items[index]
    return target


# Dateien zum Teilen
def make_bundle(layout, quick_access=None, keytips=None, name=None):
    """Anordnung zum Speichern oder Teilen: Anpassung, Schnellzugriff, eigene Kürzel.

    ``quick_access``: Liste der Befehls-IDs oder None (Standard der Definition).
    """
    data = {"format": FORMAT, "version": VERSION}
    if name:
        data["name"] = name
    data["layout"] = layout or {}
    data["quick_access"] = list(quick_access) if quick_access is not None else None
    data["keytips"] = dict(sorted((keytips or {}).items()))
    return data


def same_bundle(a, b):
    """Gleiche Anordnung (ohne Name und Formatversion; Format 1 = Format 2 ohne Neuerungen)."""
    def strip(data):
        out = dict(data)
        out.pop("name", None)
        out.pop("version", None)
        return out
    return strip(a) == strip(b)


@dataclass
class Bundle:
    layout: Optional[dict]
    quick_access: Optional[List[str]]
    keytips: Dict[str, str]
    name: Optional[str] = None


def read_bundle(data):
    """Datei-Inhalt (dict) -> ``Bundle``. Löst ``BundleError`` aus, wenn es keine Anordnung ist."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BundleError(tr("Not a ribbon arrangement"))
    if data.get("version") not in READ_VERSIONS:
        raise BundleError(tr("Version %r is not supported (expected %s)")
                          % (data.get("version"), tr(" or ").join(str(v) for v in READ_VERSIONS)))
    layout = data.get("layout")
    qat = data.get("quick_access")
    if qat is not None:
        qat = [str(c) for c in qat] if isinstance(qat, list) else None
    keytips = data.get("keytips")
    keytips = ({str(k): str(v) for k, v in keytips.items()} if isinstance(keytips, dict) else {})
    name = data.get("name") if isinstance(data.get("name"), str) else None
    return Bundle(layout=layout if isinstance(layout, dict) and layout else None,
                  quick_access=qat, keytips=keytips, name=name)
