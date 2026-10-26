"""Domänen: Modell, Prüfung und Bearbeitungsstand (ohne QGIS).

Eine Domäne legt die erlaubten Werte eines Felds fest, wie in Pro:

- ``coded``: Werteliste (Code und Beschreibung), in QGIS als Wertzuordnung;
- ``range``: Bereich (Minimum bis Maximum), in QGIS als Bereich;
- ``glob``: Muster (nur Anzeige; kommt in vorhandenen GeoPackages vor).

Gespeichert wird in der Datenquelle (GeoPackage, FileGDB), sonst im Projekt
(``qgis_integration.domains``). ``DomainSession`` hält die Änderungen des
Dialogs, bis gespeichert wird, und prüft sie vorher vollständig.
"""

import copy
from dataclasses import dataclass, field
from .i18n import tr

KINDS = ("coded", "range", "glob")
EDITABLE_KINDS = ("coded", "range")
KIND_LABELS = {"coded": tr("Coded values"), "range": tr("Range"), "glob": tr("Glob")}
FIELD_TYPES = ("string", "integer", "real")
TYPE_LABELS = {"string": tr("Text"), "integer": tr("Integer"), "real": tr("Decimal")}
# Bereich nur für Zahlen
RANGE_TYPES = ("integer", "real")
NONE_LABEL = tr("(none)")


@dataclass
class Domain:
    name: str
    kind: str = "coded"
    field_type: str = "string"
    description: str = ""
    values: list = field(default_factory=list)      # [(Code, Beschreibung)] bei ``coded``
    minimum: object = None                          # bei ``range``; None = offen
    maximum: object = None
    min_inclusive: bool = True
    max_inclusive: bool = True
    glob: str = ""                                  # bei ``glob``

    def copy(self):
        return copy.deepcopy(self)


def parse_value(text, field_type):
    """Text -> Wert des Feldtyps. ``ValueError`` mit deutschem Text, wenn er nicht passt."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        value = text
    else:
        value = str(text).strip()
    if field_type == "string":
        return str(value)
    if value == "":
        raise ValueError(tr("Value missing"))
    if field_type == "integer":
        try:
            return int(str(value))
        except ValueError:
            raise ValueError(tr("“%s” is not an integer") % value)
    if field_type == "real":
        try:
            return float(str(value).replace(",", "."))
        except ValueError:
            raise ValueError(tr("“%s” is not a number") % value)
    raise ValueError(tr("Unknown field type: %s") % field_type)


def format_value(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return ("%g" % value).replace(".", ",")
    return str(value)


def errors(domain, other_names=()):
    """Fehlertexte einer Domäne (leer = in Ordnung)."""
    out = []
    name = (domain.name or "").strip()
    if not name:
        out.append(tr("Name missing"))
    elif name.lower() in {n.lower() for n in other_names}:
        out.append(tr("Name “%s” already exists") % name)
    if domain.kind not in KINDS:
        out.append(tr("Unknown kind: %s") % domain.kind)
    if domain.field_type not in FIELD_TYPES:
        out.append(tr("Unknown field type: %s") % domain.field_type)
        return out
    if domain.kind == "coded":
        if not domain.values:
            out.append(tr("Coded value list is empty"))
        seen = set()
        for i, (code, label) in enumerate(domain.values, 1):
            try:
                value = parse_value(code, domain.field_type)
            except ValueError as exc:
                out.append(tr("Row %d: %s") % (i, exc))
                continue
            if domain.field_type == "string" and value == "":
                out.append(tr("Row %d: code missing") % i)
            if value in seen:
                out.append(tr("Row %d: code “%s” duplicated") % (i, format_value(value)))
            seen.add(value)
            if not str(label or "").strip():
                out.append(tr("Row %d: description missing") % i)
    elif domain.kind == "range":
        if domain.field_type not in RANGE_TYPES:
            out.append(tr("Range only for integer or decimal"))
        bounds = []
        for label, value in ((tr("Minimum"), domain.minimum), (tr("Maximum"), domain.maximum)):
            if value in (None, ""):
                bounds.append(None)
                continue
            try:
                bounds.append(parse_value(value, domain.field_type))
            except ValueError as exc:
                out.append("%s: %s" % (label, exc))
                bounds.append(None)
        if bounds[0] is None and bounds[1] is None and not out:
            out.append(tr("Enter a minimum or maximum"))
        if None not in bounds and bounds[0] > bounds[1]:
            out.append(tr("Minimum is greater than maximum"))
    return out


def normalized(domain):
    """Kopie mit Werten im Feldtyp (nach ``errors`` ohne Fehler aufrufen)."""
    d = domain.copy()
    d.name = d.name.strip()
    if d.kind == "coded":
        d.values = [(parse_value(c, d.field_type), str(l).strip()) for c, l in d.values]
    elif d.kind == "range":
        d.minimum = None if d.minimum in (None, "") else parse_value(d.minimum, d.field_type)
        d.maximum = None if d.maximum in (None, "") else parse_value(d.maximum, d.field_type)
    return d


def compatible(domain, field_type):
    """Passt die Domäne zu einem Feld dieses Typs? Ganzzahl-Domänen passen auch zu Dezimalfeldern."""
    if field_type is None:
        return False
    if domain.field_type == field_type:
        return True
    return domain.field_type == "integer" and field_type == "real"


def value_map_config(domain):
    """Konfiguration des QGIS-Widgets Wertzuordnung (Beschreibung -> Code)."""
    return {"map": [{str(label): code} for code, label in domain.values]}


def range_config(domain):
    """Konfiguration des QGIS-Widgets Bereich."""
    integer = domain.field_type == "integer"
    cfg = {"AllowNull": True, "Precision": 0 if integer else 2, "Step": 1 if integer else 0.1,
           "Style": "SpinBox"}
    if domain.minimum is not None:
        cfg["Min"] = domain.minimum
    if domain.maximum is not None:
        cfg["Max"] = domain.maximum
    return cfg


class DomainSession(object):
    """Bearbeitungsstand des Dialogs: Domänen und Zuordnung der Felder eines Layers.

    ``domains``: gespeicherte Domänen; ``fields``: {Feld: Feldtyp oder None};
    ``assignments``: {Feld: Domänenname}. Änderungen werden erst mit
    ``changes()`` abgeholt; vorher ``problems()`` prüfen.
    """

    def __init__(self, domains, fields, assignments):
        self.original = {d.name: d.copy() for d in domains}
        self.domains = [d.copy() for d in domains]
        self.fields = dict(fields)
        self.original_assignments = {f: n for f, n in assignments.items() if n}
        self.assignments = dict(self.original_assignments)

    # Domänen
    def names(self):
        return [d.name for d in self.domains]

    def get(self, name):
        for d in self.domains:
            if d.name == name:
                return d
        return None

    def is_new(self, name):
        return name not in self.original

    def unique_name(self, base=tr("New domain")):
        names = {n.lower() for n in self.names()}
        if base.lower() not in names:
            return base
        i = 2
        while ("%s %d" % (base, i)).lower() in names:
            i += 1
        return "%s %d" % (base, i)

    def add(self, domain):
        self.domains.append(domain)
        return domain

    def replace(self, name, domain):
        """Domäne ``name`` durch ``domain`` ersetzen. Gespeicherte Domänen behalten ihren Namen."""
        for i, d in enumerate(self.domains):
            if d.name == name:
                if not self.is_new(name):
                    domain.name = name
                elif domain.name != name:
                    for f, n in self.assignments.items():
                        if n == name:
                            self.assignments[f] = domain.name
                self.domains[i] = domain
                return domain
        raise KeyError(name)

    def remove(self, name):
        self.domains = [d for d in self.domains if d.name != name]

    def users(self, name):
        return sorted(f for f, n in self.assignments.items() if n == name)

    # Felder
    def assign(self, field_name, domain_name):
        if domain_name:
            self.assignments[field_name] = domain_name
        else:
            self.assignments.pop(field_name, None)

    def choices(self, field_name):
        """Domänen, die zum Feld passen (Namen)."""
        ftype = self.fields.get(field_name)
        return [d.name for d in self.domains if compatible(d, ftype)]

    # Prüfung und Ergebnis
    def problems(self):
        """[(Domäne oder Feld, Fehlertext)] über alles, was gespeichert würde."""
        out = []
        names = self.names()
        for i, d in enumerate(self.domains):
            if d.kind == "glob" or (not self.is_new(d.name) and d == self.original.get(d.name)):
                continue
            others = names[:i] + names[i + 1:]
            for text in errors(d, others):
                out.append((d.name or tr("(unnamed)"), text))
        for f, n in sorted(self.assignments.items()):
            d = self.get(n)
            if d is None:
                out.append((f, tr("Domain “%s” no longer exists") % n))
            elif not compatible(d, self.fields.get(f)):
                out.append((f, tr("Domain “%s” does not match the field type") % n))
        return out

    def changes(self):
        """Dict mit ``added``, ``updated`` (normalisierte Domänen), ``removed`` (Namen),
        ``assign`` ({Feld: Name}) und ``unassign`` ([Felder])."""
        added = [normalized(d) for d in self.domains if self.is_new(d.name)]
        updated = [normalized(d) for d in self.domains
                   if not self.is_new(d.name) and d.kind != "glob"
                   and normalized(d) != normalized(self.original[d.name])]
        current = set(self.names())
        removed = sorted(n for n in self.original if n not in current)
        assign = {f: n for f, n in self.assignments.items()
                  if self.original_assignments.get(f) != n}
        unassign = sorted(f for f in self.original_assignments if f not in self.assignments)
        return {"added": added, "updated": updated, "removed": removed,
                "assign": assign, "unassign": unassign}

    def dirty(self):
        try:
            c = self.changes()
        except ValueError:      # ungültige Eingabe ist auch eine Änderung
            return True
        return any(c[k] for k in c)
