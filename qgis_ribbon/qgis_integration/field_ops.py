"""Felder eines Vektorlayers anlegen, löschen und umbenennen.

Im Bearbeitungsmodus landet die Änderung im Bearbeitungspuffer (rückgängig
machbar, gespeichert mit den übrigen Änderungen). Sonst schreibt sie direkt in
die Datenquelle, wie der Reiter Felder der Layereigenschaften; die Rückfrage
dazu stellt der Dialog. Freigegeben wird nach den Fähigkeiten des
Datenanbieters (``field_caps``).
"""

from dataclasses import replace

from qgis.core import QgsField, QgsFields, QgsVectorDataProvider, QgsVectorLayer
from qgis.PyQt.QtCore import QMetaType

from ..core import fields as fm
from ..core.i18n import tr

_CAPS = (("add", "AddAttributes"), ("delete", "DeleteAttributes"), ("rename", "RenameAttributes"))

# Feldtyp -> QMetaType (gleiche Zahlen wie QVariant.Type, mit dem nativeTypes() noch arbeitet)
VARIANT = {
    "string": QMetaType.Type.QString,
    "integer": QMetaType.Type.Int,
    "integer64": QMetaType.Type.LongLong,
    "real": QMetaType.Type.Double,
    "date": QMetaType.Type.QDate,
    "datetime": QMetaType.Type.QDateTime,
    "time": QMetaType.Type.QTime,
    "boolean": QMetaType.Type.Bool,
    "binary": QMetaType.Type.QByteArray,
}


def _provider(layer):
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return None
    return layer.dataProvider()


def field_caps(layer):
    """Was der Anbieter des Layers mit Feldern kann: Teilmenge von ``conditions.FIELD_CAPS``."""
    provider = _provider(layer)
    if provider is None or layer.readOnly():
        return frozenset()
    caps = provider.capabilities()
    return frozenset(key for key, flag in _CAPS if caps & getattr(QgsVectorDataProvider, flag))


def supported_types(layer):
    """Feldtypen (Schlüssel aus ``core.fields.TYPES``), die der Anbieter anlegen kann."""
    provider = _provider(layer)
    if provider is None:
        return []
    native = {t.mType for t in provider.nativeTypes()}
    return [key for key in fm.TYPE_ORDER if VARIANT[key] in native]


def sizes(layer, key):
    """(Länge, Genauigkeit) einstellbar? Nach Feldtyp und Anbieter: GeoPackage z. B. speichert
    bei Dezimalzahlen keine Länge, mitgegebene Werte ließen das spätere Speichern scheitern."""
    provider = _provider(layer)
    _label, has_length, has_precision, _default = fm.TYPES[key]
    if provider is None:
        return has_length, has_precision
    native = [t for t in provider.nativeTypes() if t.mType == VARIANT[key]]
    if native:
        has_length = has_length and any(t.mMaxLen > 0 for t in native)
        has_precision = has_precision and any(t.mMaxPrec > 0 for t in native)
    return has_length, has_precision


def _native_type(provider, key, length, precision):
    """Passender Eintrag aus den Typen des Anbieters (Typname, Länge, Genauigkeit)."""
    want = VARIANT[key]
    for t in provider.nativeTypes():
        if t.mType != want:
            continue
        if length and t.mMaxLen > 0 and not t.mMinLen <= length <= t.mMaxLen:
            continue
        return t.mTypeName
    return ""


def names(layer):
    return [f.name() for f in layer.fields()]


def own_fields(layer):
    """Felder aus der Datenquelle (oder dem Puffer): nur diese lassen sich löschen und umbenennen."""
    out = []
    fields = layer.fields()
    for i in range(fields.count()):
        if fields.fieldOrigin(i) in (QgsFields.FieldOrigin.OriginProvider, QgsFields.FieldOrigin.OriginEdit):
            out.append(fields.at(i).name())
    return out


def make_field(layer, spec):
    spec = fm.normalized(spec)
    has_length, has_precision = sizes(layer, spec.type)
    spec = replace(spec, length=spec.length if has_length else 0,
                   precision=spec.precision if has_precision else 0)
    type_name = _native_type(layer.dataProvider(), spec.type, spec.length, spec.precision)
    field = QgsField(spec.name, VARIANT[spec.type], type_name, spec.length, spec.precision, spec.comment)
    if spec.alias:
        field.setAlias(spec.alias)
    return field


def add_field(layer, spec):
    """Feld anlegen -> (ok, Meldung)."""
    problems = fm.errors(spec, names(layer))
    if problems:
        return False, problems[0]
    if "add" not in field_caps(layer):
        return False, tr("The data source of this layer cannot add fields.")
    spec = fm.normalized(spec)
    field = make_field(layer, spec)
    if layer.isEditable():
        layer.beginEditCommand(tr("Add field “%s”") % spec.name)
        ok = layer.addAttribute(field)
        if ok:
            layer.endEditCommand()
        else:
            layer.destroyEditCommand()
    else:
        ok = layer.dataProvider().addAttributes([field])
        layer.updateFields()
    if not ok:
        return False, tr("The field “%s” could not be added.") % spec.name
    if spec.alias:
        idx = layer.fields().indexOf(spec.name)
        if idx >= 0:
            layer.setFieldAlias(idx, spec.alias)
    return True, tr("Field “%s” added.") % spec.name


def delete_fields(layer, field_names):
    """Felder löschen -> (ok, Meldung)."""
    field_names = [n for n in field_names if n]
    if not field_names:
        return False, tr("No field selected.")
    if "delete" not in field_caps(layer):
        return False, tr("The data source of this layer cannot delete fields.")
    idx = sorted(layer.fields().indexOf(n) for n in field_names)
    if any(i < 0 for i in idx):
        return False, tr("A selected field no longer exists.")
    if layer.isEditable():
        layer.beginEditCommand(tr("Delete fields"))
        ok = layer.deleteAttributes(idx)
        if ok:
            layer.endEditCommand()
        else:
            layer.destroyEditCommand()
    else:
        ok = layer.dataProvider().deleteAttributes(idx)
        layer.updateFields()
    if not ok:
        return False, tr("The fields could not be deleted.")
    return True, tr("%d field(s) deleted.") % len(idx)


def rename_trap(layer, old, new):
    """Hinweis, wenn QGIS die Umbenennung nicht speichern könnte, sonst "".

    Zurück auf den Namen in der Datenquelle bei offener Umbenennung trägt QGIS als Umbenennung auf
    den vorhandenen Namen ein, und das Speichern scheitert (ebenso nach Rückgängig, das QGIS selbst
    ausführt). Ohne Bearbeitung wird direkt geschrieben, da gibt es das nicht."""
    fields = layer.fields()
    idx = fields.indexOf(old)
    if not layer.isEditable() or idx < 0 or fields.fieldOrigin(idx) != QgsFields.FieldOrigin.OriginProvider:
        return ""
    stored = layer.dataProvider().fields().at(fields.fieldOriginIndex(idx)).name()
    if old != stored and stored.lower() == (new or "").strip().lower():
        return tr("QGIS cannot save a field renamed back to its stored name in the same edit session. "
                  "Save the edits first, then rename the field.")
    return ""


def rename_field(layer, old, new):
    """Feld umbenennen -> (ok, Meldung)."""
    problems = fm.rename_errors(old, new, names(layer))
    if problems:
        return False, problems[0]
    if "rename" not in field_caps(layer):
        return False, tr("The data source of this layer cannot rename fields.")
    idx = layer.fields().indexOf(old)
    if idx < 0:
        return False, tr("The field “%s” no longer exists.") % old
    trap = rename_trap(layer, old, new)
    if trap:
        return False, trap
    new = new.strip()
    if layer.isEditable():
        layer.beginEditCommand(tr("Rename field “%s”") % old)
        ok = layer.renameAttribute(idx, new)
        if ok:
            layer.endEditCommand()
        else:
            layer.destroyEditCommand()
    else:
        ok = layer.dataProvider().renameAttributes({idx: new})
        layer.updateFields()
    if not ok:
        return False, tr("The field “%s” could not be renamed.") % old
    return True, tr("Field “%s” renamed to “%s”.") % (old, new)
