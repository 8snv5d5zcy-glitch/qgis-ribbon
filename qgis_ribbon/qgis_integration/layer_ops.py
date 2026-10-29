"""Operationen der eigenen Befehle auf QGIS-Layern (ohne Widgets).

Jede Änderung setzt genau die QGIS-Eigenschaft, die auch der passende
QGIS-Dialog setzt, und meldet sie wie QGIS: neu zeichnen, ``styleChanged``,
Projekt geändert. So bleiben Layereigenschaften, Layer-Styling und Legende
im Einklang mit dem Ribbon.

Beschriftung: Einfache Beschriftung und regelbasierte Beschriftung werden
unterstützt. Bei regelbasierter Beschriftung wirkt eine Änderung auf alle
Regeln, angezeigt werden die Werte der ersten Regel.
"""

from qgis.core import (Qgis, QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateTransform,
                       QgsExpression, QgsFeatureRenderer, QgsGraduatedSymbolRenderer,
                       QgsHeatmapRenderer, QgsMapLayer, QgsPalLayerSettings, QgsProject,
                       QgsProviderRegistry, QgsRasterLayer, QgsRuleBasedLabeling,
                       QgsRuleBasedRenderer, QgsSettings, QgsSingleSymbolRenderer, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling)
from ..core.i18n import tr

# Schriftgrößen für Vergrößern/Verkleinern und die Größenauswahl (Punkt)
FONT_SIZES = (6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72)

# QGIS-Standardwert für den kleinsten Maßstab eines Layers (bedeutet: keine Grenze)
DEFAULT_MIN_SCALE = 1e8

# Abfragemodus des QGIS-Abfragewerkzeugs (Einstellung Map/identifyMode)
IDENTIFY_KEY = "Map/identifyMode"
IDENTIFY_MODES = ("ActiveLayer", "TopDownStopAtFirst", "TopDownAll", "LayerSelection")


def changed(layer, repaint=True):
    """Änderung an einem Layer melden wie QGIS-Dialoge."""
    if repaint:
        layer.triggerRepaint()
    layer.emitStyleChanged()
    QgsProject.instance().setDirty(True)


def is_vector(layer):
    return isinstance(layer, QgsVectorLayer) and layer.isSpatial()


# -- Bearbeitung ------------------------------------------------------------

def has_unsaved_edits(layer):
    return isinstance(layer, QgsVectorLayer) and layer.isEditable() and layer.isModified()


def discard_edits(layer):
    """Ungespeicherte Änderungen verwerfen; die Bearbeitung bleibt eingeschaltet."""
    ok = layer.rollBack(False)
    layer.triggerRepaint()
    return ok


# -- Sichtbarkeitsbereich ---------------------------------------------------

def scale_range(layer):
    """(an, größter Maßstab, kleinster Maßstab) als Maßstabszahlen, 0 = keine Grenze.

    Größter Maßstab = am weitesten hineingezoomt (kleinste Maßstabszahl,
    QGIS ``maximumScale``). Der QGIS-Standard
    für den kleinsten Maßstab (1:100.000.000) gilt als keine Grenze.
    """
    min_scale = layer.minimumScale()
    if min_scale >= DEFAULT_MIN_SCALE:
        min_scale = 0.0
    return layer.hasScaleBasedVisibility(), layer.maximumScale(), min_scale


def set_scale_range_enabled(layer, on):
    layer.setScaleBasedVisibility(bool(on))
    changed(layer)


def set_layer_scale(layer, which, scale):
    """``which``: ``max`` (hineingezoomt) oder ``min`` (herausgezoomt). Schaltet den Bereich ein."""
    scale = float(scale or 0)
    if which == "max":
        layer.setMaximumScale(scale)
    else:
        layer.setMinimumScale(scale)
    if scale:
        layer.setScaleBasedVisibility(True)
    changed(layer)


# -- Effekte --------------------------------------------------------------

def opacity(layer):
    return layer.opacity()


def set_opacity(layer, value):
    layer.setOpacity(max(0.0, min(1.0, float(value))))
    changed(layer)


def blend_mode(layer):
    return layer.blendMode()


def set_blend_mode(layer, mode):
    layer.setBlendMode(mode)
    changed(layer)


def feature_blend_mode(layer):
    """Mischmodus der Objekte untereinander (nur Vektorlayer)."""
    return layer.featureBlendMode()


def set_feature_blend_mode(layer, mode):
    layer.setFeatureBlendMode(mode)
    changed(layer)


# -- Beschriftung -----------------------------------------------------------

def _rules(labeling):
    root = labeling.rootRule()
    return [r for r in root.descendants() if r.settings() is not None]


def label_settings(layer):
    """Beschriftungseinstellungen des Layers (Kopien), leer ohne Beschriftung."""
    if not is_vector(layer) or layer.labeling() is None:
        return []
    lab = layer.labeling()
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        return [lab.settings()]
    if isinstance(lab, QgsRuleBasedLabeling):
        return [QgsPalLayerSettings(r.settings()) for r in _rules(lab)]
    return []


def update_label_settings(layer, change):
    """``change(settings)`` auf alle Beschriftungseinstellungen anwenden und zurückschreiben.

    Ohne Beschriftung wird eine einfache Beschriftung angelegt (ausgeschaltet
    bleibt sie, bis sie eingeschaltet wird).
    """
    if not is_vector(layer):
        return False
    lab = layer.labeling()
    if lab is None:
        lab = QgsVectorLayerSimpleLabeling(default_label_settings(layer))
        layer.setLabeling(lab)
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        s = lab.settings()
        change(s)
        lab.setSettings(QgsPalLayerSettings(s))
    elif isinstance(lab, QgsRuleBasedLabeling):
        for rule in _rules(lab):
            s = QgsPalLayerSettings(rule.settings())
            change(s)
            rule.setSettings(s)
    else:
        return False
    changed(layer)
    return True


def default_label_settings(layer):
    """Einfache Beschriftung mit dem Anzeigefeld des Layers und dem Standard-Textformat."""
    s = QgsPalLayerSettings()
    s.fieldName = layer.displayField() or (layer.fields()[0].name() if layer.fields().count() else "")
    s.isExpression = False
    fmt = QgsProject.instance().styleSettings().defaultTextFormat()
    if fmt.isValid():
        s.setFormat(fmt)
    suit_placement(layer, s)
    return s


def labels_enabled(layer):
    return is_vector(layer) and layer.labelsEnabled() and layer.labeling() is not None


def set_labels_enabled(layer, on):
    """Beschriftung an/aus. Beim Einschalten bekommt jede Klasse eine Platzierung,
    die zum Geometrietyp passt (sonst beschriftet QGIS z. B. Linien nicht)."""
    if not is_vector(layer):
        return
    if on and layer.labeling() is None:
        layer.setLabeling(QgsVectorLayerSimpleLabeling(default_label_settings(layer)))
    elif on:
        update_label_settings(layer, lambda s: suit_placement(layer, s))
    layer.setLabelsEnabled(bool(on))
    changed(layer)


def label_scale_range(layer):
    """(an, größter, kleinster) Maßstab der Beschriftung (erste Einstellung)."""
    settings = label_settings(layer)
    if not settings:
        return False, 0.0, 0.0
    s = settings[0]
    return s.scaleVisibility, s.maximumScale, s.minimumScale


def set_label_scale(layer, which, scale):
    scale = float(scale or 0)

    def change(s):
        if which == "max":
            s.maximumScale = scale
        else:
            s.minimumScale = scale
        if scale:
            s.scaleVisibility = True

    return update_label_settings(layer, change)


def clear_label_scales(layer):
    def change(s):
        s.scaleVisibility = False
        s.maximumScale = 0
        s.minimumScale = 0

    return update_label_settings(layer, change)


def text_format(layer):
    """Textformat der Beschriftung (erste Einstellung) oder Standardformat des Projekts."""
    settings = label_settings(layer)
    if settings:
        return settings[0].format()
    return QgsProject.instance().styleSettings().defaultTextFormat()


def update_text_format(layer, change):
    def apply(s):
        fmt = s.format()
        change(fmt)
        s.setFormat(fmt)

    return update_label_settings(layer, apply)


def set_text_format(layer, fmt):
    return update_label_settings(layer, lambda s: s.setFormat(fmt))


def set_font_family(layer, family):
    def change(fmt):
        font = fmt.font()
        font.setFamily(family)
        fmt.setFont(font)
        fmt.setNamedStyle("")

    return update_text_format(layer, change)


def set_font_style(layer, style):
    return update_text_format(layer, lambda fmt: fmt.setNamedStyle(style))


def set_font_size(layer, size):
    return update_text_format(layer, lambda fmt: fmt.setSize(float(size)))


def set_font_color(layer, color):
    return update_text_format(layer, lambda fmt: fmt.setColor(color))


def step_font_size(size, step):
    """Nächste Größe aus ``FONT_SIZES`` (``step`` +1 größer, -1 kleiner)."""
    if step > 0:
        bigger = [s for s in FONT_SIZES if s > size + 1e-6]
        return bigger[0] if bigger else size
    smaller = [s for s in FONT_SIZES if s < size - 1e-6]
    return smaller[-1] if smaller else size


def change_font_size(layer, step):
    return update_text_format(layer, lambda fmt: fmt.setSize(step_font_size(fmt.size(), step)))


# -- Beschriftungsklassen ---------------------------------------------------
#
# Eine Beschriftungsklasse in Pro entspricht einer Regel der regelbasierten
# Beschriftung. Einfache Beschriftung ist eine Klasse „Standard“ (Schlüssel
# SIMPLE_KEY); ihr „aktiv“ ist das Ein/Aus der Beschriftung. Braucht sie einen
# Filter, wird sie in eine regelbasierte Beschriftung mit einer Regel umgewandelt.

SIMPLE_KEY = ""
SIMPLE_NAME = tr("Default")


def label_classes(layer):
    """[(Schlüssel, Name, aktiv)] der Beschriftungsklassen; leer ohne Beschriftung."""
    if not is_vector(layer) or layer.labeling() is None:
        return []
    lab = layer.labeling()
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        return [(SIMPLE_KEY, SIMPLE_NAME, layer.labelsEnabled())]
    if isinstance(lab, QgsRuleBasedLabeling):
        out = []
        for i, rule in enumerate(_rules(lab), 1):
            name = rule.description() or rule.filterExpression() or tr("Rule %d") % i
            out.append((rule.ruleKey(), name, rule.active()))
        return out
    return []


def _label_rule(layer, key):
    lab = layer.labeling() if is_vector(layer) else None
    if isinstance(lab, QgsRuleBasedLabeling) and key:
        return lab.rootRule().findRuleByKey(key)
    return None


def label_class_settings(layer, key):
    """Beschriftungseinstellungen (Kopie) der Klasse oder None."""
    lab = layer.labeling() if is_vector(layer) else None
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        return lab.settings()
    rule = _label_rule(layer, key)
    if rule is not None and rule.settings() is not None:
        return QgsPalLayerSettings(rule.settings())
    return None


def update_label_class(layer, key, change):
    """``change(settings)`` nur auf die Klasse ``key`` anwenden."""
    lab = layer.labeling() if is_vector(layer) else None
    if lab is None:
        lab = QgsVectorLayerSimpleLabeling(default_label_settings(layer))
        layer.setLabeling(lab)
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        s = lab.settings()
        change(s)
        lab.setSettings(QgsPalLayerSettings(s))
    else:
        rule = _label_rule(layer, key)
        if rule is None or rule.settings() is None:
            return False
        s = QgsPalLayerSettings(rule.settings())
        change(s)
        rule.setSettings(s)
    changed(layer)
    return True


def add_label_class(layer, key, name):
    """Neue Beschriftungsklasse nach dem Muster der Klasse ``key``; gibt ihren Schlüssel zurück.

    Einfache Beschriftung wird dafür regelbasiert, die bisherigen Einstellungen
    bleiben als erste Klasse („Standard“). Die neue Klasse hat keinen Filter.
    """
    if not is_vector(layer):
        return None
    if layer.labeling() is None:
        layer.setLabeling(QgsVectorLayerSimpleLabeling(default_label_settings(layer)))
    lab = layer.labeling()
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        root = QgsRuleBasedLabeling.Rule(None)
        first = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings(lab.settings()))
        first.setDescription(SIMPLE_NAME)
        root.appendChild(first)
        key = first.ruleKey()
        layer.setLabeling(QgsRuleBasedLabeling(root))
        lab = layer.labeling()
    if not isinstance(lab, QgsRuleBasedLabeling):
        return None
    template = label_class_settings(layer, key) or default_label_settings(layer)
    suit_placement(layer, template)
    rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings(template))
    rule.setDescription(name)
    lab.rootRule().appendChild(rule)
    if not layer.labelsEnabled():
        layer.setLabelsEnabled(True)
    changed(layer)
    return rule.ruleKey()


def remove_label_class(layer, key):
    """Klasse ``key`` löschen; die letzte Klasse bleibt. Gibt den Schlüssel der
    danach gewählten Klasse zurück oder None, wenn nichts gelöscht wurde."""
    rule = _label_rule(layer, key)
    if rule is None or len(label_classes(layer)) < 2:
        return None
    parent = rule.parent()
    parent.removeChildAt(parent.children().index(rule))
    changed(layer)
    return label_classes(layer)[0][0]


def label_class_active(layer, key):
    for k, _name, active in label_classes(layer):
        if k == key:
            return active
    return False


def set_label_class_active(layer, key, on):
    lab = layer.labeling() if is_vector(layer) else None
    if isinstance(lab, QgsVectorLayerSimpleLabeling) or lab is None:
        set_labels_enabled(layer, on)
        return True
    rule = _label_rule(layer, key)
    if rule is None:
        return False
    rule.setActive(bool(on))
    if on and not layer.labelsEnabled():
        layer.setLabelsEnabled(True)
    changed(layer)
    return True


def label_class_filter(layer, key):
    rule = _label_rule(layer, key)
    return rule.filterExpression() if rule is not None else ""


def set_label_class_filter(layer, key, expression):
    """Filter der Klasse setzen. Gibt den (ggf. neuen) Schlüssel der Klasse zurück.

    Einfache Beschriftung wird dafür in eine regelbasierte mit einer Regel
    umgewandelt (wie „Regelbasierte Beschriftung“ in den Layereigenschaften).
    """
    lab = layer.labeling() if is_vector(layer) else None
    if isinstance(lab, QgsVectorLayerSimpleLabeling):
        root = QgsRuleBasedLabeling.Rule(None)
        rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings(lab.settings()))
        rule.setDescription(SIMPLE_NAME)
        rule.setFilterExpression(expression or "")
        root.appendChild(rule)
        layer.setLabeling(QgsRuleBasedLabeling(root))
        changed(layer)
        return rule.ruleKey()
    rule = _label_rule(layer, key)
    if rule is None:
        return None
    rule.setFilterExpression(expression or "")
    changed(layer)
    return key


def label_expression(settings):
    """Ausdruck der Beschriftung: Feldname als Spaltenverweis oder Ausdruck."""
    if settings is None or not settings.fieldName:
        return ""
    if settings.isExpression:
        return settings.fieldName
    return QgsExpression.quotedColumnRef(settings.fieldName)


def set_label_field(layer, key, field, is_expression):
    def change(s):
        s.fieldName = field or ""
        s.isExpression = bool(is_expression)
    return update_label_class(layer, key, change)


# -- Platzierung der Beschriftung --------------------------------------------

# (Platzierung, Beschriftung) je Geometrietyp, wie in den Layereigenschaften
PLACEMENTS = {
    Qgis.GeometryType.Point: (
        ("OrderedPositionsAroundPoint", tr("Cartographic")),
        ("AroundPoint", tr("Around point")),
        ("OverPoint", tr("Offset from point")),
    ),
    Qgis.GeometryType.Line: (
        ("Line", tr("Parallel")),
        ("Curved", tr("Curved")),
        ("Horizontal", "Horizontal"),
    ),
    Qgis.GeometryType.Polygon: (
        ("AroundPoint", tr("Around centroid")),
        ("OverPoint", tr("Offset from centroid")),
        ("Horizontal", "Horizontal"),
        ("Free", tr("Free (angled)")),
        ("Line", tr("Using perimeter")),
        ("PerimeterCurved", tr("Using perimeter (curved)")),
        ("OutsidePolygons", tr("Outside polygons")),
    ),
}


def placement_choices(layer):
    if not is_vector(layer):
        return []
    return list(PLACEMENTS.get(layer.geometryType(), ()))


def _placement_name(value):
    for name in dir(Qgis.LabelPlacement):
        if not name.startswith("_") and getattr(Qgis.LabelPlacement, name) == value:
            return name
    return None


def label_placement(layer):
    settings = label_settings(layer)
    if not settings:
        return None
    return _placement_name(settings[0].placement)


def suit_placement(layer, settings):
    """Platzierung auf die erste passende setzen, wenn sie nicht zum Geometrietyp passt.

    Neue Einstellungen stehen auf „Um Punkt“; Linien werden damit nicht
    beschriftet. Für Linien wird es „Parallel“, wie in den Layereigenschaften.
    """
    names = [n for n, _label in placement_choices(layer)]
    if not names or _placement_name(settings.placement) in names:
        return False
    settings.placement = getattr(Qgis.LabelPlacement, names[0])
    return True


def set_label_placement(layer, name):
    value = getattr(Qgis.LabelPlacement, name)

    def change(s):
        s.placement = value
    return update_label_settings(layer, change)


# -- Abfragbare Layer ------------------------------------------------------------

def identifiable_layers():
    """[(Layer, abfragbar)] in der Reihenfolge des Layerbaums."""
    root = QgsProject.instance().layerTreeRoot()
    return [(layer, bool(layer.flags() & QgsMapLayer.LayerFlag.Identifiable))
            for layer in root.layerOrder() if layer is not None]


def set_identifiable(layer, on):
    flags = layer.flags()
    flags = (flags | QgsMapLayer.LayerFlag.Identifiable) if on else (flags & ~QgsMapLayer.LayerFlag.Identifiable)
    layer.setFlags(flags)
    QgsProject.instance().setDirty(True)


# -- Datenquelle -------------------------------------------------------------------

def source_path(layer):
    """Pfad der Datenquelle (Datei mit Layername) oder die Quelle ohne Passwörter."""
    if layer is None:
        return ""
    parts = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.source())
    path = parts.get("path")
    if path:
        name = parts.get("layerName")
        return "%s|layername=%s" % (path, name) if name else path
    return layer.publicSource()


# -- Darstellungsart (Renderer) --------------------------------------------

# Renderer-Typ (QGIS-Name) -> Umwandlung aus dem bisherigen Renderer, wie im
# Layer-Styling. Punkt-Renderer nur für Punktlayer.
RENDERERS = (
    ("singleSymbol", tr("Single symbol"), None),
    ("categorizedSymbol", tr("Categorized"), None),
    ("graduatedSymbol", tr("Graduated"), None),
    ("RuleRenderer", tr("Rule-based"), None),
    ("heatmapRenderer", tr("Heatmap"), Qgis.GeometryType.Point),
)


def renderer_type(layer):
    if not is_vector(layer) or layer.renderer() is None:
        return None
    return layer.renderer().type()


def renderer_choices(layer):
    """[(Typ, Beschriftung)] für den Layer."""
    if not is_vector(layer):
        return []
    geom = layer.geometryType()
    return [(t, label) for t, label, only in RENDERERS if only is None or only == geom]


def renderer_icon(name):
    meta = QgsApplication.rendererRegistry().rendererMetadata(name)
    return meta.icon() if meta is not None else None


def set_renderer(layer, name):
    old = layer.renderer()
    if old is not None and old.type() == name:
        return False
    if name == "singleSymbol":
        new = QgsSingleSymbolRenderer.convertFromRenderer(old) if old else None
        if new is None:
            new = QgsFeatureRenderer.defaultRenderer(layer.geometryType())
    elif name == "categorizedSymbol":
        new = QgsCategorizedSymbolRenderer.convertFromRenderer(old, layer)
    elif name == "graduatedSymbol":
        new = QgsGraduatedSymbolRenderer.convertFromRenderer(old, layer)
    elif name == "RuleRenderer":
        new = QgsRuleBasedRenderer.convertFromRenderer(old, layer)
    elif name == "heatmapRenderer":
        new = QgsHeatmapRenderer.convertFromRenderer(old)
    else:
        raise ValueError(tr("Unknown renderer: %s") % name)
    if new is None:
        return False
    layer.setRenderer(new)
    changed(layer)
    return True


# -- Abfragemodus -----------------------------------------------------------

def identify_mode(settings=None):
    value = (settings or QgsSettings()).value(IDENTIFY_KEY, "ActiveLayer")
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        value = IDENTIFY_MODES[int(value)] if 0 <= int(value) < len(IDENTIFY_MODES) else "ActiveLayer"
    return value


def set_identify_mode(mode, settings=None):
    if mode not in IDENTIFY_MODES:
        raise ValueError(tr("Unknown identify mode: %s") % mode)
    (settings or QgsSettings()).setValue(IDENTIFY_KEY, mode)


# -- Lesezeichen und Grundkarten ---------------------------------------------

def bookmarks():
    """[(Abschnitt, Lesezeichen)]: erst die des Projekts, dann die eigenen."""
    out = []
    for section, manager in ((tr("Project"), QgsProject.instance().bookmarkManager()),
                             (tr("User"), QgsApplication.bookmarkManager())):
        for b in sorted(manager.bookmarks(), key=lambda b: b.name().lower()):
            out.append((section, b))
    return out


def zoom_to_bookmark(canvas, bookmark):
    extent = bookmark.extent()
    rect = extent
    if extent.crs() != canvas.mapSettings().destinationCrs():
        xform = QgsCoordinateTransform(extent.crs(), canvas.mapSettings().destinationCrs(),
                                       QgsProject.instance())
        rect = xform.transformBoundingBox(extent)
    canvas.setExtent(rect)
    if bookmark.rotation() == bookmark.rotation():  # nicht NaN
        canvas.setRotation(bookmark.rotation())
    canvas.refresh()


XYZ_ROOT = "connections/xyz/items"


def xyz_connections():
    """XYZ-Verbindungen aus dem QGIS-Browser: [(Name, URL, zmin, zmax)].

    Ausgeblendete fehlen, ebenso Höhendaten-Kacheln (gesetzte ``interpretation``,
    z. B. „Mapzen Global Terrain“): das sind keine Grundkarten.
    """
    from qgis.core import QgsSettingsTree
    node = QgsSettingsTree.node("connections").childNode("xyz")
    if node is None:
        return []

    def value(key, name):
        setting = node.childSetting(key)  # key() der Einstellung ist der volle Pfad
        return setting.valueAsVariant([name]) if setting is not None else None

    out = []
    for name in sorted(node.items(), key=str.lower):
        if str(value("hidden", name)).lower() in ("true", "1"):
            continue
        if value("interpretation", name):
            continue
        url = value("url", name)
        if not url:
            continue
        # Nicht gesetzte Zoomstufen liefert QGIS als -1
        zmin = _int(value("zmin", name), 0)
        zmax = _int(value("zmax", name), 19)
        out.append((name, url, max(zmin, 0), zmax if zmax >= 0 else 19))
    return out


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def xyz_uri(url, zmin=0, zmax=19):
    from qgis.core import QgsDataSourceUri
    uri = QgsDataSourceUri()
    uri.setParam("type", "xyz")
    uri.setParam("url", url)
    uri.setParam("zmin", str(zmin))
    uri.setParam("zmax", str(zmax))
    return bytes(uri.encodedUri()).decode()


def add_basemap(name, url, zmin=0, zmax=19, attribution=None):
    """XYZ-Grundkarte unten in den Layerbaum einfügen. Gibt den Layer zurück (oder None)."""
    layer = QgsRasterLayer(xyz_uri(url, zmin, zmax), name, "wms")
    if not layer.isValid():
        return None
    if attribution:
        # Namensnennung (Lizenzpflicht) in den Metadaten; Layouts zeigen sie über die Rechte an
        md = layer.metadata()
        md.setRights(list(md.rights()) + [attribution])
        layer.setMetadata(md)
    project = QgsProject.instance()
    project.addMapLayer(layer, False)
    project.layerTreeRoot().insertLayer(-1, layer)
    return layer


def is_map_layer(obj):
    return isinstance(obj, QgsMapLayer)
