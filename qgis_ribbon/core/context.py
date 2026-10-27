"""Kontextlogik des Ribbons (ohne qgis-Imports).

``ContextLogic`` hält den aktuellen ``Snapshot`` und leitet daraus ab,
welche Befehle bedienbar und welche Kontext-Tabs sichtbar sind. Beim Laden
wird ein Index Bedingung → Befehle/Tabs gebaut; bei einer Änderung werden
nur die Bedingungen neu bewertet, deren Snapshot-Felder sich geändert haben,
und nur die davon betroffenen Befehle und Tabs gemeldet.

Tab-Wechsel (wie in ArcGIS Pro):

- Verschwindet der gerade gewählte Kontext-Tab, geht es auf einen neu
  sichtbaren Kontext-Tab mit derselben Beschriftung (z. B. „Daten“ beim
  Wechsel von Vektorlayer zu Tabelle), sonst auf den zuletzt gewählten
  Haupt-Tab.
- Tritt ein Ereignis ein, das ein Tab in ``activate_on`` nennt (z. B.
  ``editing_started``), wird dieser Tab gewählt, sofern er sichtbar ist.
  Ausnahme: Der gewählte Tab ist ein eigener Tab des Nutzers (``stay_on``,
  standardmäßig alle eigenen Tabs). Wer dort einen Arbeitsablauf aufgebaut
  hat und die Bearbeitung startet, bleibt in seinem Tab.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from . import conditions
from .conditions import Snapshot
from .customization import CUSTOM_TAB_PREFIX
from .model import iter_commands


@dataclass
class Changes:
    """Ergebnis von ``ContextLogic.update``: nur, was sich geändert hat."""

    commands: Dict[str, bool] = field(default_factory=dict)  # Befehls-ID -> bedienbar
    tabs: Dict[str, bool] = field(default_factory=dict)      # Tab-ID -> sichtbar
    select: Optional[str] = None                             # Tab, der gewählt werden soll

    def __bool__(self):
        return bool(self.commands or self.tabs or self.select)


def own_tabs(ribbon):
    """IDs der eigenen Tabs des Nutzers (Ereignisse wechseln von dort nicht weg)."""
    return {t.id for t in ribbon.tabs if t.id.startswith(CUSTOM_TAB_PREFIX)}


class ContextLogic(object):
    def __init__(self, ribbon, snapshot=None, stay_on=None):
        self.ribbon = ribbon
        # Tabs, die ein Ereignis (activate_on) nicht verlässt
        self.stay_on = set(own_tabs(ribbon) if stay_on is None else stay_on)
        self.snapshot = snapshot or Snapshot()
        self._commands = {}                 # ID -> Command mit Bedingungen
        self._tabs = {t.id: t for t in ribbon.tabs if t.contextual}
        self._by_condition = {}             # Bedingung -> ({Befehls-IDs}, {Tab-IDs})
        self._by_event = {}                 # Ereignis -> [Tab-IDs] in Ribbon-Reihenfolge
        commands = dict(ribbon.commands)
        for tab in ribbon.tabs:
            for cmd in iter_commands(tab):
                commands.setdefault(cmd.id, cmd)
        for cmd in ribbon.quick_access:
            commands.setdefault(cmd.id, cmd)
        for cmd in commands.values():
            if cmd.enabled_when:
                self._commands[cmd.id] = cmd
                for c in cmd.enabled_when:
                    self._entry(c)[0].add(cmd.id)
        for tab in self._tabs.values():
            for c in tab.visible_when:
                self._entry(c)[1].add(tab.id)
        for tab in ribbon.tabs:
            for e in tab.activate_on:
                self._by_event.setdefault(e, []).append(tab.id)

        self._values = {c: conditions.evaluate(c, self.snapshot) for c in self._by_condition}
        self._enabled = {cid: self._all(cmd.enabled_when) for cid, cmd in self._commands.items()}
        self._visible = {tid: self._all(t.visible_when) for tid, t in self._tabs.items()}
        main = [t.id for t in ribbon.tabs if not t.contextual]
        self.current_tab = main[0] if main else None
        self._last_main = self.current_tab

    def _entry(self, condition):
        return self._by_condition.setdefault(condition, (set(), set()))

    def _all(self, names):
        return all(self._values[n] for n in names)

    # Abfragen
    @property
    def conditions(self):
        """Bedingungen, die in der Ribbon-Definition vorkommen."""
        return sorted(self._by_condition)

    def command_enabled(self, command_id):
        return self._enabled.get(command_id, True)

    def tab_visible(self, tab_id):
        return self._visible.get(tab_id, True)

    def affected(self, condition):
        """(Befehls-IDs, Tab-IDs), die von einer Bedingung abhängen."""
        cmds, tabs = self._by_condition.get(condition, ((), ()))
        return set(cmds), set(tabs)

    # Rückmeldung der Oberfläche
    def tab_selected(self, tab_id):
        """Die Oberfläche meldet den gewählten Tab (Klick oder programmatisch)."""
        self.current_tab = tab_id
        if tab_id not in self._tabs:
            self._last_main = tab_id

    # Aktualisierung
    def update(self, snapshot, events=()):
        changes = Changes()
        changed = conditions.depending_on(conditions.changed_fields(self.snapshot, snapshot))
        self.snapshot = snapshot
        cmds, tabs = set(), set()
        for c in changed:
            if c not in self._values:
                continue
            value = conditions.evaluate(c, snapshot)
            if value == self._values[c]:
                continue
            self._values[c] = value
            cmds.update(self._by_condition[c][0])
            tabs.update(self._by_condition[c][1])
        for cid in cmds:
            value = self._all(self._commands[cid].enabled_when)
            if value != self._enabled[cid]:
                self._enabled[cid] = value
                changes.commands[cid] = value
        for tid in tabs:
            value = self._all(self._tabs[tid].visible_when)
            if value != self._visible[tid]:
                self._visible[tid] = value
                changes.tabs[tid] = value

        target = None
        if self.current_tab in self.stay_on:
            events = ()
        for e in events:
            for tid in self._by_event.get(e, ()):
                if self.tab_visible(tid):
                    target = tid
                    break
        if target is None and changes.tabs.get(self.current_tab) is False:
            target = self._replacement(self.current_tab, changes)
        if target is not None and target != self.current_tab:
            changes.select = target
            self.tab_selected(target)
        return changes

    def _replacement(self, hidden_id, changes):
        label = self._tabs[hidden_id].label
        for tab in self.ribbon.tabs:
            if changes.tabs.get(tab.id) and tab.label == label:
                return tab.id
        return self._last_main
