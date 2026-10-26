"""Domänen speichern und Feldern zuordnen.

Wo die Domänen liegen:

- **Datenquelle**, wenn sie Domänen kann (GeoPackage, FileGDB; erkannt an
  den Fähigkeiten der QGIS-Datenbankverbindung). Anlegen und Zuordnen über
  die QGIS-Verbindung, Ändern und Löschen über GDAL (QGIS bietet beides
  nicht). Die Domänen gelten dann in jedem Projekt, das die Datei nutzt.
- **Projekt** für alle anderen Formate (Shapefile, PostGIS, Dienste ...):
  Domänen als Liste im Projekt (``qgis_ribbon``/``domaenen``), Zuordnung je
  Layer in einer Layer-Eigenschaft.

In beiden Fällen setzt die Zuordnung das QGIS-Widget des Felds (Wertzuordnung
bzw. Bereich), damit Formulare und Attributtabelle sofort die Werte zeigen.
Eine Domäne, die noch ein Feld nutzt, wird nicht gelöscht.
"""

import json

from qgis.core import (QgsAbstractDatabaseProviderConnection, QgsCodedFieldDomain, QgsCodedValue,
                       QgsEditorWidgetSetup, QgsGlobFieldDomain, QgsProject, QgsProviderRegistry,
                       QgsRangeFieldDomain, QgsVectorLayer)
from qgis.PyQt.QtCore import QMetaType, QVariant

from ..core.domains import Domain, range_config, value_map_config
from ..core.i18n import tr

PROJECT_SCOPE = "qgis_ribbon"
PROJECT_KEY = "domaenen"
LAYER_PROPERTY = "qgis_ribbon/domaenen"

_INTEGER_TYPES = (QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong)
_META_TYPES = {"string": QMetaType.QString, "integer": QMetaType.Int, "real": QMetaType.Double}


class DomainError(Exception):
    pass


def field_type(qgs_field):
    """Feldtyp im Sinne von ``core.domains`` oder None (Datum, Geometrie ...)."""
    t = qgs_field.type()
    if t == QVariant.String:
        return "string"
    if t in _INTEGER_TYPES:
        return "integer"
    if t == QVariant.Double:
        return "real"
    return None


def layer_fields(layer):
    """{Feldname: Feldtyp} der Attributfelder (ohne virtuelle und verknüpfte Felder)."""
    out = {}
    fields = layer.fields()
    for i, f in enumerate(fields):
        if fields.fieldOrigin(i) in (fields.OriginProvider, fields.OriginEdit):
            out[f.name()] = field_type(f)
    return out


# -- Umwandlung QGIS <-> core ------------------------------------------------------

def _value(value, ftype):
    if value is None or (hasattr(value, "isNull") and value.isNull()):
        return None
    if ftype == "integer":
        return int(value)
    if ftype == "real":
        return float(value)
    return str(value)


def from_qgis(dom):
    """``QgsFieldDomain`` -> ``core.domains.Domain``."""
    ftype = {QVariant.String: "string", QVariant.Double: "real"}.get(dom.fieldType())
    if ftype is None:
        ftype = "integer" if dom.fieldType() in _INTEGER_TYPES else "string"
    out = Domain(dom.name(), field_type=ftype, description=dom.description() or "")
    if isinstance(dom, QgsCodedFieldDomain):
        out.kind = "coded"
        out.values = [(_value(v.code(), ftype), v.value()) for v in dom.values()]
    elif isinstance(dom, QgsRangeFieldDomain):
        out.kind = "range"
        out.minimum = _value(dom.minimum(), ftype)
        out.maximum = _value(dom.maximum(), ftype)
        out.min_inclusive = dom.minimumIsInclusive()
        out.max_inclusive = dom.maximumIsInclusive()
    elif isinstance(dom, QgsGlobFieldDomain):
        out.kind = "glob"
        out.glob = dom.glob()
    return out


def to_qgis(domain):
    meta = _META_TYPES[domain.field_type]
    if domain.kind == "coded":
        return QgsCodedFieldDomain(domain.name, domain.description, meta,
                                   [QgsCodedValue(c, l) for c, l in domain.values])
    if domain.kind == "range":
        return QgsRangeFieldDomain(domain.name, domain.description, meta,
                                   domain.minimum, domain.min_inclusive,
                                   domain.maximum, domain.max_inclusive)
    raise DomainError(tr("Domains of kind “%s” cannot be saved.") % domain.kind)


def _to_ogr(domain):
    from osgeo import ogr
    ogr_type = {"string": ogr.OFTString, "integer": ogr.OFTInteger, "real": ogr.OFTReal}
    if domain.kind == "coded":
        values = {str(c): l for c, l in domain.values}
        return ogr.CreateCodedFieldDomain(domain.name, domain.description,
                                          ogr_type[domain.field_type], ogr.OFSTNone, values)
    if domain.kind == "range":
        return ogr.CreateRangeFieldDomain(domain.name, domain.description,
                                          ogr_type[domain.field_type], ogr.OFSTNone,
                                          domain.minimum, domain.min_inclusive,
                                          domain.maximum, domain.max_inclusive)
    raise DomainError(tr("Domains of kind “%s” cannot be saved.") % domain.kind)


def widget_setup(domain):
    """QGIS-Widget für ein Feld mit dieser Domäne."""
    if domain.kind == "coded":
        return QgsEditorWidgetSetup("ValueMap", value_map_config(domain))
    if domain.kind == "range":
        return QgsEditorWidgetSetup("Range", range_config(domain))
    return QgsEditorWidgetSetup()


def _set_widget(layer, field_name, setup):
    idx = layer.fields().indexOf(field_name)
    if idx >= 0:
        layer.setEditorWidgetSetup(idx, setup)


# -- Ablage -------------------------------------------------------------------------

class SourceDomains(object):
    """Domänen in der Datenquelle des Layers (GeoPackage, FileGDB)."""

    where = "source"

    def __init__(self, layer, connection, path, table):
        self.layer = layer
        self.conn = connection
        self.path = path
        self.table = table

    @property
    def title(self):
        return tr("Data source: %s") % self.path

    def domains(self):
        return [from_qgis(self.conn.fieldDomain(n)) for n in self.conn.fieldDomainNames()]

    def assignments(self):
        return {f.name(): f.constraints().domainName() for f in self.layer.fields()
                if f.constraints().domainName()}

    def usage(self, name):
        """[„Tabelle.Feld“] aller Felder der Datenquelle, die die Domäne nutzen."""
        out = []
        for table in self.conn.tables(""):
            tname = table.tableName()
            for f in self.conn.fields("", tname):
                if f.constraints().domainName() == name:
                    out.append("%s.%s" % (tname, f.name()))
        return out

    def apply(self, changes, session):
        for d in changes["added"]:
            self.conn.addFieldDomain(to_qgis(d), "")
        if changes["updated"] or changes["removed"]:
            ds = self._open()
            try:
                for d in changes["updated"]:
                    _gdal_call(ds.UpdateFieldDomain, _to_ogr(d),
                               tr("Domain “%s” could not be changed.") % d.name)
            finally:
                ds = None
        for field_name in changes["unassign"]:
            self.conn.setFieldDomainName(field_name, "", self.table, "")
            _set_widget(self.layer, field_name, QgsEditorWidgetSetup())
        for field_name, name in changes["assign"].items():
            self.conn.setFieldDomainName(field_name, "", self.table, name)
        try:
            if changes["removed"]:
                self._remove(changes["removed"])
        finally:
            # Auch wenn das Löschen abgelehnt wurde: der Rest ist geschrieben, Layer neu lesen
            self.layer.dataProvider().reloadData()
            self.layer.reload()
            # Widgets aller Layer aus dieser Datei, deren Felder eine geänderte Domäne nutzen
            changed = {d.name: d for d in changes["added"] + changes["updated"]}
            for field_name, name in changes["assign"].items():
                changed.setdefault(name, session.get(name))
            refresh_widgets(self.path, changed)

    def _open(self):
        """Datenquelle über GDAL zum Schreiben öffnen (QGIS kann Domänen nicht ändern/löschen)."""
        from osgeo import gdal
        try:
            ds = gdal.OpenEx(self.path, gdal.OF_VECTOR | gdal.OF_UPDATE)
        except RuntimeError:        # GDAL mit eingeschalteten Ausnahmen
            ds = None
        if ds is None:
            raise DomainError(tr("Data source cannot be opened for writing: %s") % self.path)
        return ds

    def _remove(self, names):
        _refuse_busy({n: self.usage(n) for n in names})
        ds = self._open()
        try:
            for n in names:
                _gdal_call(ds.DeleteFieldDomain, n, tr("Domain “%s” could not be deleted.") % n)
        finally:
            ds = None


class ProjectDomains(object):
    """Domänen im Projekt (Formate ohne Domänen in der Datenquelle)."""

    where = "project"
    title = tr("Project (the layer's data format has no domains)")

    def __init__(self, layer, project=None):
        self.layer = layer
        self.project = project or QgsProject.instance()

    def _read(self):
        text, _ok = self.project.readEntry(PROJECT_SCOPE, PROJECT_KEY, "")
        try:
            return json.loads(text) if text else []
        except ValueError:
            return []

    def domains(self):
        out = []
        for item in self._read():
            d = Domain(item.get("name", ""), item.get("kind", "coded"),
                       item.get("field_type", "string"), item.get("description", ""))
            d.values = [tuple(v) for v in item.get("values", [])]
            d.minimum = item.get("minimum")
            d.maximum = item.get("maximum")
            d.min_inclusive = item.get("min_inclusive", True)
            d.max_inclusive = item.get("max_inclusive", True)
            out.append(d)
        return out

    def _write(self, domains):
        data = [{"name": d.name, "kind": d.kind, "field_type": d.field_type,
                 "description": d.description, "values": [list(v) for v in d.values],
                 "minimum": d.minimum, "maximum": d.maximum,
                 "min_inclusive": d.min_inclusive, "max_inclusive": d.max_inclusive}
                for d in domains]
        self.project.writeEntry(PROJECT_SCOPE, PROJECT_KEY, json.dumps(data, ensure_ascii=False))

    @staticmethod
    def layer_assignments(layer):
        try:
            return dict(json.loads(layer.customProperty(LAYER_PROPERTY, "{}") or "{}"))
        except ValueError:
            return {}

    def assignments(self):
        names = {f.name() for f in self.layer.fields()}
        return {f: n for f, n in self.layer_assignments(self.layer).items() if f in names}

    def usage(self, name):
        out = []
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                for f, n in self.layer_assignments(layer).items():
                    if n == name:
                        out.append("%s.%s" % (layer.name(), f))
        return out

    def usage_elsewhere(self, name):
        """Wie ``usage``, ohne den Layer des Dialogs (den prüft ``DomainSession``)."""
        out = []
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer is not self.layer:
                out.extend("%s.%s" % (layer.name(), f)
                           for f, n in self.layer_assignments(layer).items() if n == name)
        return out

    def apply(self, changes, session):
        _refuse_busy({n: self.usage_elsewhere(n) for n in changes["removed"]})
        current = {d.name: d for d in self.domains()}
        for d in changes["added"] + changes["updated"]:
            current[d.name] = d
        for n in changes["removed"]:
            current.pop(n, None)
        self._write(list(current.values()))
        assigned = self.layer_assignments(self.layer)
        for field_name in changes["unassign"]:
            assigned.pop(field_name, None)
            _set_widget(self.layer, field_name, QgsEditorWidgetSetup())
        assigned.update(changes["assign"])
        self.layer.setCustomProperty(LAYER_PROPERTY, json.dumps(assigned, ensure_ascii=False))
        # Widgets aller Layer des Projekts, die eine geänderte oder neu zugeordnete Domäne nutzen
        changed = {d.name for d in changes["updated"]} | set(changes["assign"].values())
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            for f, n in self.layer_assignments(layer).items():
                if n in changed and n in current:
                    _set_widget(layer, f, widget_setup(current[n]))
        self.project.setDirty(True)


def _gdal_call(method, arg, message):
    """GDAL-Aufruf mit Rückgabe False oder Ausnahme (je nach GDAL-Modus) -> DomainError."""
    try:
        ok = method(arg)
    except RuntimeError as exc:
        raise DomainError("%s (%s)" % (message, exc))
    if not ok:
        raise DomainError(message)


def _refuse_busy(usage):
    busy = [tr("“%s” (%s)") % (n, ", ".join(u)) for n, u in sorted(usage.items()) if u]
    if busy:
        raise DomainError(tr("Still in use, not deleted: %s") % "; ".join(busy))


_NEEDED = (QgsAbstractDatabaseProviderConnection.ListFieldDomains
           | QgsAbstractDatabaseProviderConnection.AddFieldDomain
           | QgsAbstractDatabaseProviderConnection.SetFieldDomain)


def store_for(layer):
    """Ablage der Domänen für den Layer: Datenquelle, wenn sie Domänen kann, sonst Projekt."""
    if layer.providerType() != "ogr":
        return ProjectDomains(layer)
    parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
    path = parts.get("path") or ""
    if not path:
        return ProjectDomains(layer)
    try:
        conn = QgsProviderRegistry.instance().providerMetadata("ogr").createConnection(path, {})
    except Exception:  # keine Datenbank (Shapefile, CSV ...): QgsProviderConnectionException
        return ProjectDomains(layer)
    if (conn.capabilities() & _NEEDED) != _NEEDED:
        return ProjectDomains(layer)
    table = parts.get("layerName")
    if not table:
        # Ohne Layername öffnet OGR die erste Tabelle
        tables = conn.tables("")
        table = tables[0].tableName() if tables else ""
    return SourceDomains(layer, conn, path, table)


def refresh_widgets(path, domains):
    """Widgets der Felder aller Layer aus ``path`` neu setzen, die eine der Domänen nutzen."""
    if not domains:
        return
    registry = QgsProviderRegistry.instance()
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
            continue
        if registry.decodeUri("ogr", layer.source()).get("path") != path:
            continue
        for f in layer.fields():
            d = domains.get(f.constraints().domainName())
            if d is not None:
                _set_widget(layer, f.name(), widget_setup(d))
