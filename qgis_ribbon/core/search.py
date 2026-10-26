"""Befehlssuche (ohne qgis-Imports).

Der Index enthält die Befehle des Ribbons (deutsche Beschriftung,
Beschreibung, Ort wie „Karte › Auswahl“) und die übrigen QGIS-Aktionen.
Gesucht wird ohne Groß-/Kleinschreibung und mit gleichgesetzten Umlauten
(„groesse“ findet „Größe“ und umgekehrt). Jedes Suchwort muss vorkommen.

Rangfolge je Treffer (kleiner ist besser):

0. Beschriftung beginnt mit der Eingabe
1. ein Wort der Beschriftung beginnt mit jedem Suchwort
2. jedes Suchwort steht irgendwo in der Beschriftung
3. Suchwörter stehen in Beschriftung, Ort, Beschreibung oder Stichwörtern

Ribbon-Befehle stehen bei gleichem Rang vor QGIS-Aktionen. Budget: unter
10 ms je Tastendruck; die Texte werden beim Aufbau einmal
normalisiert.
"""

import re
from .i18n import tr

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_SPLIT = re.compile(r"[^0-9a-z]+")


def fold(text):
    """Klein, Umlaute ausgeschrieben, Satzzeichen als Leerzeichen."""
    return " ".join(w for w in _SPLIT.split((text or "").lower().translate(_FOLD)) if w)


class Entry(object):
    """Eintrag im Suchindex. ``ref`` ist frei (Befehl, QAction ...)."""

    __slots__ = ("label", "path", "description", "ref", "ribbon", "_label", "_words", "_all")

    def __init__(self, label, ref, path="", description="", keywords="", ribbon=True):
        self.label = label
        self.path = path
        self.description = description
        self.ref = ref
        self.ribbon = ribbon
        self._label = fold(label)
        self._words = self._label.split()
        self._all = " ".join(fold(t) for t in (label, path, description, keywords) if t)


class SearchIndex(object):
    def __init__(self, entries=()):
        self.entries = list(entries)

    def add(self, entry):
        self.entries.append(entry)

    def __len__(self):
        return len(self.entries)

    def search(self, text, limit=20):
        query = fold(text)
        if not query:
            return []
        terms = query.split()
        hits = []
        for pos, e in enumerate(self.entries):
            if not all(t in e._all for t in terms):
                continue
            if e._label.startswith(query):
                rank = 0
            elif all(any(w.startswith(t) for w in e._words) for t in terms):
                rank = 1
            elif all(t in e._label for t in terms):
                rank = 2
            else:
                rank = 3
            hits.append((rank, 0 if e.ribbon else 1, len(e._label), pos, e))
        hits.sort(key=lambda h: h[:4])
        return [h[4] for h in hits[:limit]]


PATH_SEP = " › "  # ›


def ribbon_entries(ribbon):
    """Einträge für alle Befehle im Ribbon mit dem Ort ihres ersten Vorkommens.

    Befehle der Definition ohne Ort (nur im Editor zur Auswahl) fehlen.

    ``ref`` ist ``(Command, Tab-ID)``; Tab-ID ist None für Befehle, die nur in
    der Schnellzugriffsleiste stehen. Kontext-Tabs tragen die Kontextgruppe im
    Ort („Vektorlayer: Darstellung › Effekte“).
    """
    from .model import iter_commands

    seen = {}
    for tab in ribbon.tabs:
        tab_label = "%s: %s" % (tab.context, tab.label) if tab.contextual else tab.label
        for group in tab.groups:
            for cmd in iter_commands(group):
                if cmd.id not in seen:
                    seen[cmd.id] = (tab.id, tab_label + PATH_SEP + group.label)
    for cmd in ribbon.quick_access:
        seen.setdefault(cmd.id, (None, tr("Quick Access")))
    out = []
    for cid, (tab_id, path) in seen.items():
        cmd = ribbon.commands[cid]
        out.append(Entry(cmd.label, (cmd, tab_id), path=path, description=cmd.description or ""))
    return out
