"""Operationen des grafischen Ribbon-Editors mit Verlauf (ohne qgis-Imports).

Der Editor (``ui/ribbon_editor.py``) bearbeitet eine Anordnung
(``customization.Arrangement``) und die Schnellzugriffsleiste. Alle
Änderungen laufen über die Funktionen dieses Moduls; ``Editor`` hält dazu
den Verlauf für Rückgängig/Wiederholen.

Orte (``Place``) sind Tab-ID, Index der Gruppe im Tab und Index des Eintrags
in der Gruppe. Indizes statt Objekten, weil der Verlauf Kopien der
Anordnung zurückholt. Einfügeindizes beziehen sich auf die Liste *vor* dem
Verschieben (wie die Einfügemarke beim Ziehen).

Regeln:

- Jede Gruppe ist änderbar (E2). Eine Gruppe der Definition wird beim ersten
  Eingriff zur persönlichen Fassung (``customization.make_personal``); sie
  lässt sich einzeln zurücksetzen. Entspricht sie wieder der Definition,
  gilt sie als unverändert.
- Derselbe Befehl darf im selben Tab mehrmals stehen, aber nicht zweimal in
  derselben Gruppe (``EditError`` mit Hinweis statt Fehler).
- Kontext-Tabs nehmen nur Befehle, die dort bedienbar sein können: Es muss
  einen Layer-Zustand geben, in dem der Tab sichtbar *und* der Befehl
  bedienbar ist (``fits``; z. B. kein Rasterbefehl im Tab für Vektorlayer).
- Tabs und Gruppen der Definition lassen sich löschen (``removed`` der
  Anordnung), Kontext-Tabs der Definition nur ausblenden; mindestens ein
  Haupt-Tab bleibt. Eine Gruppe der Definition, die in einen anderen Tab
  gezogen wird, kommt dort als Kopie hinzu.

Fehlgeschlagene Operationen lösen ``EditError`` aus und lassen die Anordnung
unverändert.
"""

import copy
from dataclasses import dataclass
from typing import Optional

from . import customization as cz
from .conditions import FIELD_CAPS, LAYER_KINDS, Snapshot, all_true
from .model import CommandRef, Menu, Row, Split, iter_commands
from .i18n import tr

HISTORY_LIMIT = 200


class EditError(Exception):
    """Operation nicht möglich; der Text ist ein Hinweis für den Nutzer."""


@dataclass(frozen=True)
class Place:
    tab: str
    group: Optional[int] = None
    item: Optional[int] = None


# Abfragen
def group_at(arr, tab_id, gi):
    groups = arr.tab(tab_id).groups
    if not 0 <= gi < len(groups):
        raise EditError(tr("This group does not exist."))
    return groups[gi]


def items_at(arr, base, tab_id, gi):
    """Wirksame Einträge der Gruppe (ohne sie zur persönlichen Fassung zu machen)."""
    return cz.group_items(base, group_at(arr, tab_id, gi))


def top_commands(base, item):
    """Befehle, die ein Eintrag direkt zeigt (Button, Hauptbefehl eines Splits, Zeile)."""
    element = cz.item_element(base, item)
    if isinstance(element, CommandRef):
        return {element.command.id}
    if isinstance(element, Split):
        return {element.command.id}
    if isinstance(element, Row):
        return {c.id for c in element.commands}
    return set()


def item_commands(base, item):
    """Alle Befehle eines Eintrags (mit Menüeinträgen und Galerie)."""
    element = cz.item_element(base, item)
    return [] if element is None else list(iter_commands(element))


def tab_commands(base, arr, tab_id):
    """IDs aller Befehle in einem Tab der Anordnung (Häkchen in der Palette)."""
    out = set()
    for g in arr.tab(tab_id).groups:
        for item in cz.group_items(base, g):
            out.update(c.id for c in item_commands(base, item))
    return out


def ribbon_commands(base, arr):
    """IDs aller Befehle in sichtbaren Gruppen sichtbarer Tabs (Filter „nicht im Ribbon“)."""
    out = set()
    for t in arr.tabs:
        if not t.visible:
            continue
        for g in t.groups:
            if g.visible:
                for item in cz.group_items(base, g):
                    out.update(c.id for c in item_commands(base, item))
    return out


_SNAPSHOTS = tuple(Snapshot(kind, editable, selection, caps)
                   for kind in (None,) + LAYER_KINDS
                   for editable in (False, True) for selection in (False, True)
                   for caps in (frozenset(), frozenset(FIELD_CAPS)))


def fits(base, tab, commands):
    """Können die Befehle im Tab bedienbar sein? (Kontext-Tab gegen ``enabled_when``)

    ``commands``: Befehle eines Eintrags; es reicht, wenn einer passt.
    """
    if not tab.standard or not tab.contextual:
        return True
    visible_when = base.tab(tab.id).visible_when
    commands = list(commands)
    if not commands:
        return True
    return any(all_true(c.enabled_when, s)
               for s in _SNAPSHOTS if all_true(visible_when, s) for c in commands)


def _check_insert(base, tab, items, item, ignore=None):
    """Hinweis, warum ``item`` nicht in die Gruppe mit ``items`` kann; None = möglich."""
    label = cz.item_label(base, item)
    if cz.item_element(base, item) is None:
        return tr("“%s” no longer exists in the ribbon definition.") % label
    new_top = top_commands(base, item)
    for i, other in enumerate(items):
        if ignore is not None and i == ignore:
            continue
        if other.key == item.key or new_top & top_commands(base, other):
            return tr("“%s” is already in this group.") % label
    if not fits(base, tab, item_commands(base, item)):
        return tr("“%s” does not fit in the contextual tab “%s”.") % (label, tab.label)
    return None


def can_insert(arr, base, tab_id, gi, item, ignore=None):
    """None, wenn ``item`` in die Gruppe darf, sonst der Hinweis (für die Einfügemarke)."""
    tab = arr.tab(tab_id)
    if gi is None:
        if not fits(base, tab, item_commands(base, item)):
            return tr("“%s” does not fit in the contextual tab “%s”.") % (cz.item_label(base, item), tab.label)
        return None
    return _check_insert(base, tab, items_at(arr, base, tab_id, gi), item, ignore)


def command_item(base, command_id, size=None):
    cmd = base.commands.get(command_id)
    if cmd is None:
        raise EditError(tr("Command %r does not exist.") % (command_id,))
    return cz.ItemEntry(command_id, size if size in cz.SIZES else cz.default_size(cmd))


def _clamp(index, length):
    return length if index is None else max(0, min(index, length))


# Einträge
def insert_item(arr, base, tab_id, gi, index, item):
    """Eintrag an ``index`` in die Gruppe einfügen. -> ``Place``."""
    group = group_at(arr, tab_id, gi)
    hint = _check_insert(base, arr.tab(tab_id), cz.group_items(base, group), item)
    if hint:
        raise EditError(hint)
    items = cz.make_personal(base, group)
    index = _clamp(index, len(items))
    items.insert(index, copy.deepcopy(item))
    cz.normalize(base, group)
    return Place(tab_id, gi, index)


def insert_command(arr, base, tab_id, gi, index, command_id, size=None):
    return insert_item(arr, base, tab_id, gi, index, command_item(base, command_id, size))


def remove_item(arr, base, place):
    """Eintrag entfernen. -> entfernter ``ItemEntry``."""
    group = group_at(arr, place.tab, place.group)
    items = cz.make_personal(base, group)
    if not 0 <= place.item < len(items):
        raise EditError(tr("This item does not exist."))
    item = items.pop(place.item)
    cz.normalize(base, group)
    return item


def move_item(arr, base, src, tab_id, gi, index):
    """Eintrag verschieben, auch in eine andere Gruppe oder einen anderen Tab. -> ``Place``."""
    src_items = items_at(arr, base, src.tab, src.group)
    if not 0 <= src.item < len(src_items):
        raise EditError(tr("This item does not exist."))
    item = src_items[src.item]
    same = src.tab == tab_id and src.group == gi
    if same:
        index = _clamp(index, len(src_items))
        if index in (src.item, src.item + 1):
            return Place(tab_id, gi, src.item)   # bleibt stehen
        hint = None
    else:
        hint = _check_insert(base, arr.tab(tab_id), items_at(arr, base, tab_id, gi), item)
    if hint:
        raise EditError(hint)
    item = remove_item(arr, base, src)
    if same and index > src.item:
        index -= 1
    group = group_at(arr, tab_id, gi)
    items = cz.make_personal(base, group)
    index = _clamp(index, len(items))
    items.insert(index, item)
    cz.normalize(base, group)
    return Place(tab_id, gi, index)


def move_item_by(arr, base, place, delta):
    """Eintrag in seiner Gruppe um ``delta`` verschieben (Strg+Pfeil). None am Rand."""
    n = len(items_at(arr, base, place.tab, place.group))
    target = place.item + delta
    if not 0 <= target < n:
        return None
    return move_item(arr, base, place, place.tab, place.group, target + (1 if delta > 0 else 0))


def set_size(arr, base, place, size):
    if size not in cz.SIZES:
        raise EditError(tr("Invalid size."))
    group = group_at(arr, place.tab, place.group)
    items = cz.make_personal(base, group)
    item = items[place.item]
    if item.size is None:
        raise EditError(tr("A row has no size."))
    item.size = size
    cz.normalize(base, group)
    return place


# Gruppen
def new_group(arr, base, tab_id, index=None, label=cz.NEW_GROUP_LABEL, item=None):
    """Eigene Gruppe an ``index`` anlegen, optional gleich mit einem Eintrag. -> ``Place``."""
    tab = arr.tab(tab_id)
    if item is not None:
        hint = can_insert(arr, base, tab_id, None, item)
        if hint:
            raise EditError(hint)
    index = _clamp(index, len(tab.groups))
    entry = cz.GroupEntry(id=cz.new_id(cz.CUSTOM_GROUP_PREFIX, cz._taken(arr, base)), label=label)
    if item is not None:
        entry.items.append(copy.deepcopy(item))
    tab.groups.insert(index, entry)
    return Place(tab_id, index)


def move_item_to_new_group(arr, base, src, tab_id, index=None, label=cz.NEW_GROUP_LABEL):
    """Eintrag in eine neue eigene Gruppe an ``index`` verschieben (Ablegen auf „＋ Gruppe“)."""
    item = remove_item(arr, base, src)
    return new_group(arr, base, tab_id, index, label, item)


def rename_group(arr, tab_id, gi, label):
    label = label.strip()
    if not label:
        raise EditError(tr("The label must not be empty."))
    group_at(arr, tab_id, gi).label = label
    return Place(tab_id, gi)


def set_group_visible(arr, tab_id, gi, visible):
    group_at(arr, tab_id, gi).visible = bool(visible)
    return Place(tab_id, gi)


def reset_group(arr, base, tab_id, gi):
    group = group_at(arr, tab_id, gi)
    if group.custom:
        raise EditError(tr("Custom groups have no default."))
    cz.reset_group(base, group)
    return Place(tab_id, gi)


def remove_group(arr, tab_id, gi):
    """Gruppe löschen (Gruppen der Definition an ihrem Platz: vermerkt in ``removed``). -> True."""
    tab = arr.tab(tab_id)
    group = group_at(arr, tab_id, gi)
    cz.remove_group(tab, group, arr)
    return True


def can_move_group(arr, base, tab_id, gi, dst_tab):
    """None, wenn die Gruppe nach ``dst_tab`` darf, sonst der Hinweis (für die Einfügemarke)."""
    if dst_tab == tab_id:
        return None
    group = group_at(arr, tab_id, gi)
    target = arr.tab(dst_tab)
    if group.ref is not None and any(g.ref == group.ref for g in target.groups):
        return tr("The group “%s” is already in “%s”.") % (group.label, target.label)
    for item in cz.group_items(base, group):
        if not fits(base, target, item_commands(base, item)):
            return tr("“%s” does not fit in the contextual tab “%s”.") % (cz.item_label(base, item), target.label)
    return None


def move_group(arr, base, tab_id, gi, dst_tab, index):
    """Gruppe verschieben (im Tab oder in einen anderen). -> ``Place``.

    Eine Gruppe der Definition an ihrem eigenen Platz bleibt dort; in einem
    anderen Tab entsteht eine Kopie (mit Beschriftung und Einträgen).
    """
    tab = arr.tab(tab_id)
    group = group_at(arr, tab_id, gi)
    target = arr.tab(dst_tab)
    if dst_tab == tab_id:
        index = _clamp(index, len(tab.groups))
        if index in (gi, gi + 1):
            return Place(tab_id, gi)
        del tab.groups[gi]
        if index > gi:
            index -= 1
        tab.groups.insert(index, group)
        return Place(tab_id, index)
    hint = can_move_group(arr, base, tab_id, gi, dst_tab)
    if hint:
        raise EditError(hint)
    index = _clamp(index, len(target.groups))
    if not tab.is_home(group):
        del tab.groups[gi]
        moved = group
    else:
        moved = copy.deepcopy(group)
        moved.visible = True
    if moved.custom and moved.id in {g.id for g in target.groups}:
        moved.id = cz.new_id(cz.CUSTOM_GROUP_PREFIX, cz._taken(arr, base))
    target.groups.insert(index, moved)
    return Place(dst_tab, index)


def move_group_by(arr, base, tab_id, gi, delta):
    n = len(arr.tab(tab_id).groups)
    target = gi + delta
    if not 0 <= target < n:
        return None
    return move_group(arr, base, tab_id, gi, tab_id, target + (1 if delta > 0 else 0))


def can_copy_group_ref(arr, base, ref, tab_id):
    """None, wenn die Gruppe der Definition in den Tab darf, sonst der Hinweis."""
    tab = arr.tab(tab_id)
    for g in tab.groups:
        if g.ref == ref:
            return None if not g.visible else tr("The group “%s” is already in “%s”.") % (g.label, tab.label)
    _t, std = cz.standard_groups(base)[ref]
    for e in std.elements:
        if not fits(base, tab, iter_commands(e)):
            return tr("The group “%s” does not fit in the contextual tab “%s”.") % (std.label, tab.label)
    return None


def copy_group_ref(arr, base, ref, tab_id, index=None):
    """Gruppe der Definition (Palette „Gruppen“) in einen Tab übernehmen. -> ``Place``."""
    tab = arr.tab(tab_id)
    hint = can_copy_group_ref(arr, base, ref, tab_id)
    if hint:
        raise EditError(hint)
    for i, g in enumerate(tab.groups):
        if g.ref == ref:
            g.visible = True   # ausgeblendet: wieder einblenden
            return Place(tab_id, i)
    index = _clamp(index, len(tab.groups))
    tab.groups.insert(index, cz._std_group(*cz.standard_groups(base)[ref]))
    return Place(tab_id, index)


# Tabs
def _partition(arr, tab):
    """Indizes der Tabs, unter denen ``tab`` stehen darf (Haupt- bzw. Kontext-Tabs)."""
    return [i for i, t in enumerate(arr.tabs) if t.contextual == tab.contextual]


def tab_index(arr, tab_id):
    return next(i for i, t in enumerate(arr.tabs) if t.id == tab_id)


def new_tab(arr, base, index=None, label=cz.NEW_TAB_LABEL):
    """Eigenen Tab an ``index`` anlegen (höchstens hinter dem letzten Haupt-Tab). -> ``Place``."""
    main = [i for i, t in enumerate(arr.tabs) if not t.contextual]
    last = (main[-1] + 1) if main else 0
    index = last if index is None else max(0, min(index, last))
    entry = cz.TabEntry(id=cz.new_id(cz.CUSTOM_TAB_PREFIX, cz._taken(arr, base)), label=label)
    arr.tabs.insert(index, entry)
    return Place(entry.id)


def rename_tab(arr, tab_id, label):
    tab = arr.tab(tab_id)
    if tab.standard:
        raise EditError(tr("Tabs of the definition keep their label."))
    label = label.strip()
    if not label:
        raise EditError(tr("The label must not be empty."))
    tab.label = label
    return Place(tab_id)


def set_tab_visible(arr, tab_id, visible):
    arr.tab(tab_id).visible = bool(visible)
    return Place(tab_id)


def remove_tab(arr, tab_id):
    """Tab löschen; Kontext-Tabs der Definition nur ausblenden. -> True, wenn gelöscht."""
    tab = arr.tab(tab_id)
    if cz.is_last_main_tab(arr, tab):
        raise EditError(tr("At least one main tab must remain."))
    if not cz.can_remove_tab(tab, arr):
        tab.visible = False
        return False
    cz.remove_tab(arr, tab)
    return True


def restore_tab(arr, base, tab_id):
    """Gelöschten Tab der Definition zurückholen. -> ``Place``."""
    if tab_id not in {t.id for t in cz.removed_tabs(arr, base)}:
        raise EditError(tr("This tab is not deleted."))
    cz.restore_tab(arr, base, tab_id)
    return Place(tab_id)


def tab_gaps(arr, tab_id):
    """Einfügeindizes in der Tabliste, an die ``tab_id`` darf (Haupt-Tabs vor Kontext-Tabs)."""
    allowed = _partition(arr, arr.tabs[tab_index(arr, tab_id)])
    return range(allowed[0], allowed[-1] + 2)


def move_tab(arr, tab_id, index):
    """Tab an ``index`` (Einfügeindex in der Tabliste) verschieben. -> ``Place``.

    Haupt-Tabs bleiben vor den Kontext-Tabs; der Index wird dorthin begrenzt.
    """
    src = tab_index(arr, tab_id)
    tab = arr.tabs[src]
    allowed = _partition(arr, tab)
    index = max(allowed[0], min(index, allowed[-1] + 1))
    if index in (src, src + 1):
        return Place(tab_id)
    del arr.tabs[src]
    if index > src:
        index -= 1
    arr.tabs.insert(index, tab)
    return Place(tab_id)


def move_tab_by(arr, tab_id, delta):
    src = tab_index(arr, tab_id)
    target = src + delta
    allowed = _partition(arr, arr.tabs[src])
    if target not in allowed:
        return None
    return move_tab(arr, tab_id, target + (1 if delta > 0 else 0))


# Schnellzugriff
def quick_ids(base, qat):
    """Liste der Schnellzugriffsleiste; ``None`` = Standard der Definition."""
    return [c.id for c in base.quick_access] if qat is None else list(qat)


def quick_allowed(command):
    return command.kind == "button" and command.gallery is None


def quick_insert(base, qat, index, command_id):
    """-> neue Liste. Nur Buttons; jeder Befehl höchstens einmal."""
    cmd = base.commands.get(command_id)
    if cmd is None or not quick_allowed(cmd):
        raise EditError(tr("Only buttons can go into the Quick Access Toolbar (no controls or galleries)."))
    ids = quick_ids(base, qat)
    if command_id in ids:
        src = ids.index(command_id)
        index = _clamp(index, len(ids))
        if index in (src, src + 1):
            return ids
        del ids[src]
        if index > src:
            index -= 1
    ids.insert(_clamp(index, len(ids)), command_id)
    return ids


def quick_command(base, item):
    """ID des Befehls, wenn der Eintrag einer Gruppe in den Schnellzugriff darf, sonst None."""
    if item.element is not None or item.command not in base.commands:
        return None
    return item.command if quick_allowed(base.commands[item.command]) else None


def quick_remove(base, qat, index):
    ids = quick_ids(base, qat)
    if not 0 <= index < len(ids):
        raise EditError(tr("This item does not exist."))
    del ids[index]
    return ids


# Verlauf
class Editor(object):
    """Anordnung und Schnellzugriff im Editor, mit Rückgängig/Wiederholen.

    ``quick_access``: Liste der Befehls-IDs oder None (Standard der Definition).
    Jede Methode, die etwas ändert, legt vorher einen Stand in den Verlauf;
    ändert sie nichts, bleibt der Verlauf, wie er ist.
    """

    def __init__(self, base, arr, quick_access=None):
        self.base = base
        self.arr = arr
        self.qat = None if quick_access is None else list(quick_access)
        self._undo = []   # (Beschreibung, Stand)
        self._redo = []
        self._initial = self._state()

    def _state(self):
        return copy.deepcopy((self.arr, self.qat))

    def _restore(self, state):
        arr, qat = copy.deepcopy(state)
        self.arr, self.qat = arr, qat

    def run(self, label, fn, *args, **kwargs):
        """``fn(*args)`` als ein Schritt im Verlauf. Bei ``EditError`` bleibt alles, wie es war."""
        before = self._state()
        try:
            result = fn(*args, **kwargs)
        except EditError:
            self._restore(before)
            raise
        cz.prune_removed(self.arr)   # z. B. gelöschte Gruppe wieder in ihrem Tab
        if (self.arr, self.qat) != before:
            self._undo.append((label, before))
            del self._undo[:-HISTORY_LIMIT]
            self._redo = []
        return result

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def undo_label(self):
        return self._undo[-1][0] if self._undo else None

    def redo_label(self):
        return self._redo[-1][0] if self._redo else None

    def undo(self):
        if not self._undo:
            return None
        label, state = self._undo.pop()
        self._redo.append((label, self._state()))
        self._restore(state)
        return label

    def redo(self):
        if not self._redo:
            return None
        label, state = self._redo.pop()
        self._undo.append((label, self._state()))
        self._restore(state)
        return label

    @property
    def dirty(self):
        return (self.arr, self.qat) != self._initial

    # Einträge
    def insert_command(self, tab_id, gi, index, command_id, size=None):
        label = self.base.commands[command_id].label if command_id in self.base.commands else command_id
        return self.run(tr("Insert “%s”") % label, insert_command, self.arr, self.base, tab_id, gi,
                        index, command_id, size)

    def insert_item(self, tab_id, gi, index, item):
        return self.run(tr("Insert “%s”") % cz.item_label(self.base, item), insert_item, self.arr,
                        self.base, tab_id, gi, index, item)

    def remove_item(self, place):
        item = self.item(place)
        return self.run(tr("Remove “%s”") % cz.item_label(self.base, item), remove_item, self.arr,
                        self.base, place)

    def move_item(self, src, tab_id, gi, index):
        item = self.item(src)
        return self.run(tr("Move “%s”") % cz.item_label(self.base, item), move_item, self.arr,
                        self.base, src, tab_id, gi, index)

    def move_item_by(self, place, delta):
        item = self.item(place)
        return self.run(tr("Move “%s”") % cz.item_label(self.base, item), move_item_by, self.arr,
                        self.base, place, delta)

    def set_size(self, place, size):
        item = self.item(place)
        return self.run(tr("Size of “%s”: %s") % (cz.item_label(self.base, item), cz.SIZE_LABELS.get(size, size)),
                        set_size, self.arr, self.base, place, size)

    # Gruppen
    def new_group(self, tab_id, index=None, label=cz.NEW_GROUP_LABEL, item=None):
        return self.run(tr("New group"), new_group, self.arr, self.base, tab_id, index, label, item)

    def move_item_to_new_group(self, src, tab_id, index=None, label=cz.NEW_GROUP_LABEL):
        item = self.item(src)
        return self.run(tr("“%s” into a new group") % cz.item_label(self.base, item), move_item_to_new_group,
                        self.arr, self.base, src, tab_id, index, label)

    def rename_group(self, tab_id, gi, label):
        return self.run(tr("Rename group"), rename_group, self.arr, tab_id, gi, label)

    def set_group_visible(self, tab_id, gi, visible):
        text = tr("Show group") if visible else tr("Hide group")
        return self.run(text, set_group_visible, self.arr, tab_id, gi, visible)

    def reset_group(self, tab_id, gi):
        return self.run(tr("Reset group"), reset_group, self.arr, self.base, tab_id, gi)

    def remove_group(self, tab_id, gi):
        return self.run(tr("Remove group"), remove_group, self.arr, tab_id, gi)

    def move_group(self, tab_id, gi, dst_tab, index):
        return self.run(tr("Move group"), move_group, self.arr, self.base, tab_id, gi, dst_tab, index)

    def move_group_by(self, tab_id, gi, delta):
        return self.run(tr("Move group"), move_group_by, self.arr, self.base, tab_id, gi, delta)

    def copy_group_ref(self, ref, tab_id, index=None):
        return self.run(tr("Copy group"), copy_group_ref, self.arr, self.base, ref, tab_id, index)

    # Tabs
    def new_tab(self, index=None, label=cz.NEW_TAB_LABEL):
        return self.run(tr("New tab"), new_tab, self.arr, self.base, index, label)

    def rename_tab(self, tab_id, label):
        return self.run(tr("Rename tab"), rename_tab, self.arr, tab_id, label)

    def set_tab_visible(self, tab_id, visible):
        text = tr("Show tab") if visible else tr("Hide tab")
        return self.run(text, set_tab_visible, self.arr, tab_id, visible)

    def remove_tab(self, tab_id):
        return self.run(tr("Remove tab"), remove_tab, self.arr, tab_id)

    def restore_tab(self, tab_id):
        return self.run(tr("Restore tab"), restore_tab, self.arr, self.base, tab_id)

    def removed_tabs(self):
        return cz.removed_tabs(self.arr, self.base)

    def move_tab(self, tab_id, index):
        return self.run(tr("Move tab"), move_tab, self.arr, tab_id, index)

    def move_tab_by(self, tab_id, delta):
        return self.run(tr("Move tab"), move_tab_by, self.arr, tab_id, delta)

    # Schnellzugriff
    def quick_ids(self):
        return quick_ids(self.base, self.qat)

    def _set_qat(self, ids):
        std = [c.id for c in self.base.quick_access]
        self.qat = None if ids == std else ids

    def quick_insert(self, index, command_id):
        def op():
            self._set_qat(quick_insert(self.base, self.qat, index, command_id))
        label = self.base.commands[command_id].label if command_id in self.base.commands else command_id
        return self.run(tr("“%s” to Quick Access") % label, op)

    def quick_remove(self, index):
        def op():
            self._set_qat(quick_remove(self.base, self.qat, index))
        return self.run(tr("Remove from Quick Access"), op)

    # Galerien
    def gallery_ids(self, gallery_id):
        return cz.gallery_ids(self.arr, self.base, gallery_id)

    def set_gallery(self, gallery_id, ids):
        """Einträge einer Galerie setzen (``None`` = Standard der Definition)."""
        if gallery_id not in cz.galleries(self.base):
            raise EditError(tr("This gallery cannot be customized."))
        ids = None if ids is None else list(ids)
        if ids is not None:
            bad = [c for c in ids if c not in self.base.commands
                   or not cz.gallery_item_allowed(self.base.commands[c])]
            if bad:
                raise EditError(tr("Only buttons can go into a gallery (no controls, galleries or menus)."))
            if not ids and cz.gallery_needs_items(self.base, gallery_id):
                raise EditError(tr("The gallery needs at least one item."))
        label = self.base.commands[gallery_id].label
        return self.run(tr("Customize gallery “%s”") % label, cz.set_gallery_ids, self.arr, self.base,
                        gallery_id, ids)

    # Dropdowns von Splits und Menüs; Ziel ("gallery", ID) oder ("menu", Schlüssel)
    def dropdown_ids(self, target):
        return cz.dropdown_ids(self.arr, self.base, target)

    def set_menu(self, key, ids):
        """Einträge des Dropdowns eines Splits/Menüs setzen (``None`` = Standard der Definition)."""
        if key not in cz.menus(self.base):
            raise EditError(tr("The content of this dropdown cannot be changed."))
        ids = None if ids is None else list(ids)
        if ids is not None:
            if not ids:
                raise EditError(tr("A dropdown needs at least one item."))
            if any(c not in self.base.commands or not cz.menu_item_allowed(self.base, key, self.base.commands[c])
                   for c in ids):
                raise EditError(tr("Only buttons can go into a dropdown (no controls, galleries or menus)."))
        label = dropdown_label(self.base, ("menu", key))
        return self.run(tr("Customize dropdown “%s”") % label, cz.set_menu_ids, self.arr, self.base, key, ids)

    def set_dropdown(self, target, ids):
        kind, key = target
        return self.set_gallery(key, ids) if kind == "gallery" else self.set_menu(key, ids)

    def can_add_to_dropdown(self, target, command_id):
        """Grund, warum der Befehl nicht ins Dropdown kann; None = geht."""
        if target is None:
            return tr("The content of this dropdown cannot be changed.")
        cmd = self.base.commands.get(command_id)
        if cmd is None or not cz.dropdown_allowed(self.base, target, cmd):
            return tr("Only buttons can go into a dropdown (no controls, galleries or menus).")
        if command_id in self.dropdown_ids(target):
            return tr("“%s” is already in this dropdown.") % cmd.label
        return None

    def add_to_dropdown(self, target, command_id):
        """Befehl ans Ende eines Dropdowns (Galerie oder Split/Menü) hängen."""
        hint = self.can_add_to_dropdown(target, command_id)
        if hint:
            raise EditError(hint)
        ids = self.dropdown_ids(target) + [command_id]
        label = self.base.commands[command_id].label
        return self.run(tr("“%s” into “%s”") % (label, dropdown_label(self.base, target)),
                        cz.set_gallery_ids if target[0] == "gallery" else cz.set_menu_ids,
                        self.arr, self.base, target[1], ids)

    def move_into_dropdown(self, place, target):
        """Einzelnen Befehl einer Gruppe ins Dropdown verschieben (ein Schritt)."""
        item = self.item(place)
        if item.element is not None:
            raise EditError(tr("Only single commands can go into a dropdown."))
        hint = self.can_add_to_dropdown(target, item.command)
        if hint:
            raise EditError(hint)
        ids = self.dropdown_ids(target) + [item.command]
        setter = cz.set_gallery_ids if target[0] == "gallery" else cz.set_menu_ids

        def op():
            remove_item(self.arr, self.base, place)
            setter(self.arr, self.base, target[1], ids)
        label = self.base.commands[item.command].label
        return self.run(tr("“%s” into “%s”") % (label, dropdown_label(self.base, target)), op)

    # Ganzes
    def reset_all(self):
        """Tabs, Gruppen und Schnellzugriff wie in der Definition (Galerien und Dropdowns bleiben)."""
        def op():
            gals, drops = self.arr.galleries, self.arr.menus
            self.arr = cz.standard(self.base)
            self.arr.galleries, self.arr.menus = gals, drops
            self.qat = None
        return self.run(tr("Restore defaults"), op)

    def item(self, place):
        items = items_at(self.arr, self.base, place.tab, place.group)
        if place.item is None or not 0 <= place.item < len(items):
            raise EditError(tr("This item does not exist."))
        return items[place.item]

    def result(self):
        """Ergebnis zum Speichern: (Anordnung ohne leere eigene Gruppen, verworfene, Schnellzugriff)."""
        arr = copy.deepcopy(self.arr)
        dropped = cz.drop_empty_groups(arr)
        return arr, dropped, (None if self.qat is None else list(self.qat))

    def problems(self):
        return cz.problems(self.arr)


def dropdown_label(base, target):
    """Beschriftung des Elements zu einem Dropdown-Ziel."""
    kind, key = target
    if kind == "gallery":
        return base.commands[key].label
    element = cz.menus(base)[key]
    return element.display_label if isinstance(element, Split) else element.label


def describe(base, item, place_text=None):
    """Zugänglicher Name einer Kachel: „Puffer, groß, Gruppe Geoverarbeitung“."""
    parts = [cz.item_label(base, item)]
    element = cz.item_element(base, item)
    if isinstance(element, Split):
        parts.append(tr("split button"))
    elif isinstance(element, Menu):
        parts.append(tr("menu"))
    elif isinstance(element, Row):
        parts.append(tr("row"))
    if item.size is not None:
        parts.append(cz.SIZE_LABELS.get(item.size, item.size))
    if place_text:
        parts.append(place_text)
    return ", ".join(parts)
