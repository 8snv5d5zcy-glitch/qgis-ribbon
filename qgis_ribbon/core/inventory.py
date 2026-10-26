"""QGIS-Inventar: Format, Index und Prüfung von Befehlsquellen (ohne qgis-Imports).

Das Inventar ist eine Bestandsaufnahme dessen, was eine QGIS-Installation an
Befehlsquellen bietet: QActions, Docks, Shortcuts, Plugin-Aktionen und
Processing-Algorithmen. Es entsteht live in QGIS über
``qgis_ribbon.qgis_integration.inventory``.

``check_source`` prüft eine Befehlsquelle aus der Konfiguration gegen ein
Inventar. Dieselbe Prüfung nutzt später der Action-Resolver und der
Test "alle Quellen gegen die laufende QGIS-Version".
"""

from .i18n import tr

SCHEMA_VERSION = 1

SOURCE_TYPES = ("qgis_action", "qgis_menu", "iface_method", "iface_action", "processing", "dock",
                "plugin_action", "custom", "extension")

# Ergebnis von check_source
OK = "ok"
MISSING = "fehlt"
UNCHECKED = "nicht prüfbar"
INVALID = "ungültig"

REQUIRED_PARAMS = {
    "qgis_action": ("object_name",),
    "qgis_menu": ("object_name",),
    "iface_method": ("method",),
    # QAction, die eine Methode von iface liefert (Aktion ohne eindeutigen objectName)
    "iface_action": ("method",),
    "processing": ("algorithm",),
    "dock": ("object_name",),
    "plugin_action": ("plugin", "object_name"),
    "custom": ("id",),
    # Aktion eines anderen Plugins nach ihrem Ort (entsteht erst zur Laufzeit)
    "extension": ("key",),
}


def build_inventory(raw, quelle, qgis_version=None, locale=None, plugins=None):
    """Rohdaten (Listen von dicts) in das Inventarformat bringen.

    ``raw`` enthält die Schlüssel ``actions``, ``menus``, ``toolbars``,
    ``docks``, ``shortcuts``, ``plugin_actions`` und ``processing`` (jeweils
    optional). Einträge werden sortiert; mehrfach vergebene ``object_name``
    werden mit ``mehrfach: n`` markiert, weil der Resolver dann nicht
    eindeutig auflösen kann.
    """
    out = {
        "schema": SCHEMA_VERSION,
        "quelle": quelle,
        "qgis_version": qgis_version,
        "locale": locale,
        "plugins": sorted(plugins or []),
    }
    for key in ("actions", "docks", "shortcuts", "plugin_actions"):
        items = [dict(i) for i in raw.get(key, [])]
        counts = {}
        for i in items:
            name = i.get("object_name") or ""
            counts[name] = counts.get(name, 0) + 1
        for i in items:
            name = i.get("object_name") or ""
            if name and counts[name] > 1:
                i["mehrfach"] = counts[name]
        items.sort(key=lambda i: (i.get("object_name") or "￿", i.get("text") or ""))
        out[key] = items
    out["menus"] = [dict(m) for m in raw.get("menus", [])]
    out["toolbars"] = sorted((dict(t) for t in raw.get("toolbars", [])),
                             key=lambda t: t.get("object_name") or "")
    out["processing"] = sorted((dict(a) for a in raw.get("processing", [])),
                               key=lambda a: a["id"])
    return out


class InventoryIndex(object):
    """Schneller Zugriff auf ein Inventar nach Quelltyp."""

    def __init__(self, inventory):
        self.quelle = inventory.get("quelle")
        self.actions = {}
        for a in inventory.get("actions", []):
            if a.get("object_name"):
                self.actions.setdefault(a["object_name"], a)
        self.docks = dict((d["object_name"], d) for d in inventory.get("docks", [])
                          if d.get("object_name"))
        self.shortcuts = dict((s["object_name"], s) for s in inventory.get("shortcuts", [])
                              if s.get("object_name"))
        self.plugin_actions = {}
        for a in inventory.get("plugin_actions", []):
            key = (a.get("plugin"), a.get("object_name"))
            self.plugin_actions.setdefault(key, a)
        self.processing = dict((a["id"], a) for a in inventory.get("processing", []))
        self.menus = dict((m["object_name"], m) for m in inventory.get("menus", [])
                          if m.get("object_name"))
        self.plugins = set(inventory.get("plugins") or [])
        # Statisches Inventar kennt nur Kern-Plugins (processing).
        self.static = self.quelle == "static"

    def label(self, source):
        """Kurzer Anzeigetext der Quelle (Text der Aktion, Name des Algorithmus)."""
        t = source.get("type")
        if t == "qgis_action":
            a = self.actions.get(source.get("object_name"))
            return a.get("text") if a else None
        if t == "processing":
            a = self.processing.get(source.get("algorithm"))
            return a.get("name") if a else None
        if t == "dock":
            d = self.docks.get(source.get("object_name"))
            return d.get("title") if d else None
        if t == "qgis_menu":
            m = self.menus.get(source.get("object_name"))
            return " > ".join(m["path"]) if m and m.get("path") else None
        if t == "plugin_action":
            a = self.plugin_actions.get((source.get("plugin"), source.get("object_name")))
            return a.get("text") if a else None
        return None


def check_source(source, index):
    """Prüft eine Befehlsquelle gegen das Inventar.

    Liefert ``(ergebnis, meldung)`` mit ergebnis in OK, MISSING, UNCHECKED,
    INVALID. ``iface_method``, ``iface_action`` und ``custom`` sind über das
    Inventar nicht prüfbar (Methoden von ``iface`` bzw. eigener Code).
    """
    if not isinstance(source, dict):
        return INVALID, tr("Source is not an object")
    t = source.get("type")
    if t not in SOURCE_TYPES:
        return INVALID, tr("unknown source type %r") % (t,)
    for key in REQUIRED_PARAMS[t]:
        if not source.get(key):
            return INVALID, tr("%s without %s") % (t, key)
    if t == "qgis_action":
        name = source["object_name"]
        if name in index.actions:
            a = index.actions[name]
            if a.get("mehrfach"):
                return OK, tr("objectName %s is used %d times") % (name, a["mehrfach"])
            return OK, ""
        if name in index.shortcuts:
            return OK, tr("QShortcut, not a QAction")
        return MISSING, tr("QAction %s not in inventory") % name
    if t == "qgis_menu":
        if source["object_name"] in index.menus:
            return OK, ""
        return MISSING, tr("Menu %s not in inventory") % source["object_name"]
    if t == "processing":
        alg = source["algorithm"]
        if alg in index.processing:
            return OK, ""
        return MISSING, tr("Algorithm %s not in inventory") % alg
    if t == "dock":
        name = source["object_name"]
        if name in index.docks:
            return OK, ""
        if index.static:
            return UNCHECKED, tr("Dock %s not in static inventory") % name
        return MISSING, tr("Dock %s not in inventory") % name
    if t == "plugin_action":
        # Maßgeblich ist der objectName (QAction als Kind des Hauptfensters).
        # Der Plugin-Schlüssel ist der Ordnername und kann je Installation
        # abweichen; er dient nur der Zuordnung im Inventar.
        key = (source["plugin"], source["object_name"])
        if key in index.plugin_actions:
            return OK, ""
        if any(k[1] == source["object_name"] for k in index.plugin_actions):
            return OK, tr("found under another plugin key")
        if source["object_name"] in index.actions:
            return OK, ""
        if index.static or source["plugin"] not in index.plugins:
            return UNCHECKED, tr("Plugin %s not in inventory") % source["plugin"]
        return MISSING, tr("Action %s not found in plugin %s") % key[::-1]
    return UNCHECKED, ""


def merge_inventories(primary, secondary):
    """Index aus zwei Inventaren: ``primary`` hat Vorrang, ``secondary`` ergänzt.

    Typischer Fall: Live-Inventar (Sprache und Plugins der eigenen
    Installation) vor statischem Inventar (vollständige Kern-Aktionen, auch
    solche, die erst zur Laufzeit entstehen).
    """
    merged = {"quelle": primary.get("quelle"),
              "plugins": sorted(set(primary.get("plugins") or [])
                                | set(secondary.get("plugins") or []))}
    for key, ident in (("actions", "object_name"), ("docks", "object_name"),
                       ("shortcuts", "object_name"), ("menus", "object_name"),
                       ("processing", "id")):
        seen = set()
        items = []
        for inv in (primary, secondary):
            for i in inv.get(key, []):
                k = i.get(ident)
                if k and k not in seen:
                    seen.add(k)
                    items.append(i)
        merged[key] = items
    seen = set()
    merged["plugin_actions"] = []
    for inv in (primary, secondary):
        for a in inv.get("plugin_actions", []):
            k = (a.get("plugin"), a.get("object_name"))
            if k not in seen:
                seen.add(k)
                merged["plugin_actions"].append(a)
    return merged
