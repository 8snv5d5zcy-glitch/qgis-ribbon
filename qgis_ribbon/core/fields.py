"""Felder anlegen, löschen, umbenennen: Feldtypen und Prüfung (ohne QGIS).

``FieldSpec`` beschreibt ein neues Feld wie der Dialog „Feld hinzufügen“.
Die Typen sind allgemein gehalten; welche ein Layer kann, bestimmt
``qgis_integration.field_ops`` aus den Typen des Datenanbieters. Die Prüfung
hier deckt ab, was sich ohne Datenquelle sagen lässt (Name leer oder doppelt,
Länge und Genauigkeit).
"""

from dataclasses import dataclass
from .i18n import tr

# Schlüssel -> (Beschriftung, hat Länge, hat Genauigkeit, Standardlänge)
TYPES = {
    "string": (tr("Text (string)"), True, False, 80),
    "integer": (tr("Whole number (integer)"), False, False, 0),
    "integer64": (tr("Whole number (integer 64 bit)"), False, False, 0),
    "real": (tr("Decimal number (real)"), True, True, 0),
    "date": (tr("Date"), False, False, 0),
    "datetime": (tr("Date and time"), False, False, 0),
    "time": (tr("Time"), False, False, 0),
    "boolean": (tr("Boolean"), False, False, 0),
    "binary": (tr("Binary object (BLOB)"), False, False, 0),
}
TYPE_ORDER = tuple(TYPES)
MAX_LENGTH = 65535


@dataclass
class FieldSpec:
    name: str = ""
    type: str = "string"
    length: int = 80
    precision: int = 0
    alias: str = ""
    comment: str = ""

    def has_length(self):
        return TYPES[self.type][1]

    def has_precision(self):
        return TYPES[self.type][2]


def type_label(key):
    return TYPES[key][0]


def default_length(key):
    return TYPES[key][3]


def _taken(name, existing):
    folded = name.strip().lower()
    return any(folded == (e or "").strip().lower() for e in existing)


def name_errors(name, existing=()):
    """Fehlertexte zu einem Feldnamen (leer = in Ordnung)."""
    name = (name or "").strip()
    if not name:
        return [tr("Enter a field name.")]
    if _taken(name, existing):
        return [tr("A field named “%s” already exists.") % name]
    return []


def errors(spec, existing=()):
    """Fehlertexte eines neuen Felds (leer = in Ordnung)."""
    out = name_errors(spec.name, existing)
    if spec.type not in TYPES:
        out.append(tr("Unknown field type: %s") % spec.type)
        return out
    if spec.has_length() and not 0 <= spec.length <= MAX_LENGTH:
        out.append(tr("The length must be between 0 and %d.") % MAX_LENGTH)
    if spec.has_precision():
        if spec.precision < 0:
            out.append(tr("The precision must not be negative."))
        elif spec.length and spec.precision >= spec.length:
            out.append(tr("The precision must be smaller than the length."))
    return out


def normalized(spec):
    """Kopie mit getrimmtem Namen; Länge und Genauigkeit 0, wo der Typ keine hat."""
    return FieldSpec(name=spec.name.strip(), type=spec.type,
                     length=spec.length if spec.has_length() else 0,
                     precision=spec.precision if spec.has_precision() else 0,
                     alias=spec.alias.strip(), comment=spec.comment.strip())


def rename_errors(old, new, existing=()):
    """Fehlertexte beim Umbenennen von ``old`` in ``new``."""
    if (new or "").strip() == (old or "").strip():
        return [tr("Enter a new name.")]
    others = [e for e in existing if (e or "").strip().lower() != (old or "").strip().lower()]
    return name_errors(new, others)
