"""Befehlssuche (ohne qgis-Imports).

Der Index enthält die Befehle des Ribbons (deutsche Beschriftung,
Beschreibung, Ort wie „Karte › Auswahl“), die übrigen QGIS-Aktionen und im
Hauptfenster alle Werkzeuge des Werkzeugkastens samt eigener Skripte und Modelle.
Gesucht wird ohne Groß-/Kleinschreibung und mit gleichgesetzten Umlauten
(„groesse“ findet „Größe“ und umgekehrt). Jedes Suchwort muss vorkommen.

Rangfolge je Treffer (kleiner ist besser):

0. Beschriftung beginnt mit der Eingabe
1. ein Wort der Beschriftung beginnt mit jedem Suchwort
2. jedes Suchwort steht irgendwo in der Beschriftung
3. Suchwörter stehen in Beschriftung, Ort, Beschreibung oder Stichwörtern

Bei gleichem Rang entscheidet die Stufe der Quelle: Ribbon-Befehle, dann
QGIS-Aktionen, dann eigene Skripte und Modelle, dann die übrigen Werkzeuge.
Budget: unter 10 ms je Tastendruck; die Texte werden beim Aufbau einmal
normalisiert.
"""

import re
from .i18n import tr

_SPLIT = re.compile(r"[^0-9a-z]+")


def fold(text):
    """Klein, Umlaute ausgeschrieben, Satzzeichen als Leerzeichen."""
    text = (text or "").lower()
    if not text.isascii():
        # replace statt str.translate: beim Aufbau mit allen Werkzeugen ein Vielfaches schneller
        text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return _SPLIT.sub(" ", text).strip()


# Stufen der Quellen (Rangfolge bei gleichem Rang)
TIER_RIBBON, TIER_ACTION, TIER_OWN_TOOL, TIER_TOOL = range(4)


class Entry(object):
    """Eintrag im Suchindex. ``ref`` ist frei (Befehl, QAction ...)."""

    __slots__ = ("label", "path", "description", "ref", "ribbon", "tier", "_label", "_words", "_all")

    def __init__(self, label, ref, path="", description="", keywords="", ribbon=True, tier=None):
        self.label = label
        self.path = path
        self.description = description
        self.ref = ref
        self.ribbon = ribbon      # ref ist (Command, Tab-ID), sonst eine QAction
        self.tier = (TIER_RIBBON if ribbon else TIER_ACTION) if tier is None else tier
        self._label = fold(label)
        self._words = self._label.split()
        # ein fold über alle übrigen Texte: gleiches Ergebnis, beim Aufbau deutlich schneller
        rest = fold(" ".join(t for t in (path, description, keywords) if t))
        self._all = "%s %s" % (self._label, rest) if rest else self._label

    def add_keywords(self, keywords):
        """Stichwörter nachtragen (z. B. eines Werkzeugs, das als Ribbon-Befehl im Index steht)."""
        extra = fold(keywords)
        if extra and extra not in self._all:
            self._all = "%s %s" % (self._all, extra)


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
            hits.append((rank, e.tier, len(e._label), pos, e))
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


# Quelltypen, die die Suche ohnehin als QGIS-Aktion findet
ACTION_TYPES = ("qgis_action", "plugin_action", "extension")


def pool_entries(ribbon, placed=()):
    """Einträge für Befehle ohne Ort im Ribbon (Befehlsvorrat, gelöschte Gruppen).

    Nur Buttons, die sich ohne ihr Element auslösen lassen, und nur solche, die
    nicht schon als QGIS-Aktion gefunden werden. ``placed``: IDs mit Ort
    (aus ``ribbon_entries``). ``ref`` ist ``(Command, None)``.
    """
    from .extensions import is_runtime

    placed = set(placed)
    out = []
    for cid, cmd in ribbon.commands.items():
        if (cid in placed or cmd.kind != "button" or cmd.gallery is not None or is_runtime(cid)
                or cmd.source.type in ACTION_TYPES):
            continue
        out.append(Entry(cmd.label, (cmd, None), path=tr("Command pool"), description=cmd.description or ""))
    return out


def placed_tools(entries):
    """Werkzeuge, die schon als Ribbon-Befehl im Index stehen: Algorithmus-ID -> Einträge."""
    known = {}
    for e in entries:
        if e.ribbon and e.ref[0].source.type == "processing":
            known.setdefault(e.ref[0].source.get("algorithm"), []).append(e)
    return known


def algorithm_entries(algorithms, placed=(), entries=(), known=None):
    """Einträge für Werkzeuge des Werkzeugkastens ohne Ort im Ribbon.

    ``algorithms``: ``core.extensions.Algorithm``; ``placed``: Befehls-IDs mit Ort.
    Ort „Werkzeugkasten › Anbieter › Gruppe“, Stichwörter (Tags, interner Name)
    finden ein Werkzeug auch in der Sprache des Algorithmus. ``ref`` ist
    ``(Command, None)``, ausgelöst wie jeder Werkzeug-Befehl.

    Ein Werkzeug, das unter ``entries`` schon als Ribbon-Befehl steht (Quelltyp
    ``processing``), kommt nicht noch einmal dazu; sein Eintrag bekommt
    Stichwörter und internen Namen des Werkzeugs. ``known``: dasselbe vorab
    berechnet (``placed_tools``), wenn die Werkzeuge in Schritten kommen.
    """
    from .extensions import toolbox_command, toolbox_id

    placed = set(placed)
    if known is None:
        known = placed_tools(entries)
    toolbox = tr("Toolbox")
    out = []
    for alg in algorithms:
        same = known.get(alg.id)
        if same:
            for e in same:
                e.add_keywords(alg.keywords)
            continue
        if toolbox_id(alg.id) in placed:
            continue
        path = PATH_SEP.join(p for p in (toolbox, alg.provider_label, alg.group) if p)
        out.append(Entry(alg.label, (toolbox_command(alg, toolbox), None), path=path, description=alg.description,
                         keywords=alg.keywords, tier=TIER_OWN_TOOL if alg.own else TIER_TOOL))
    return out
