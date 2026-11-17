"""Einrast-Einstellungen des Projekts über die QGIS-API (``QgsSnappingConfig``).

Das Einrast-Widget von QGIS (Leiste ``mSnappingToolBar``) besteht aus
eingebetteten Widgets, die der Ribbon nicht spiegeln kann. Die Steuerelemente
und Schalter des Ribbons lesen und schreiben deshalb die Konfiguration des
Projekts: ``snappingConfig()`` lesen, eine geänderte Kopie mit
``setSnappingConfig`` schreiben. QGIS meldet jede Änderung mit
``snappingConfigChanged`` (auch beim Laden eines Projekts); das Widget von
QGIS und der Ribbon folgen beide diesem Signal und zeigen denselben Stand.

Ausnahme Versatz der Spurverfolgung: QGIS speichert ihn nicht im Projekt,
sondern hält ihn im Tracer der Karte; das Zahlenfeld dazu sitzt im Menü
``tracingMenu`` des Widgets. Der Ribbon setzt den Wert dort (QGIS gibt ihn an
den Tracer weiter) und liest ihn vom Tracer.
"""

from qgis.core import Qgis, QgsProject, QgsSnappingConfig
from qgis.gui import QgsDoubleSpinBox, QgsMapCanvasTracer
from qgis.PyQt.QtWidgets import QMenu

from ..core.i18n import tr

# Signale des Projekts, auf die Einrast-Elemente hören (über den Hub)
PROJECT_SIGNALS = ("snappingConfigChanged", "avoidIntersectionsModeChanged", "topologicalEditingChanged")

MODES = (
    (Qgis.SnappingMode.ActiveLayer, tr("Active Layer")),
    (Qgis.SnappingMode.AllLayers, tr("All Layers")),
    (Qgis.SnappingMode.AdvancedConfiguration, tr("Advanced Configuration")),
)
TYPES = {
    "vertex": (Qgis.SnappingType.Vertex, tr("Vertex")),
    "segment": (Qgis.SnappingType.Segment, tr("Segment")),
    "area": (Qgis.SnappingType.Area, tr("Area")),
    "centroid": (Qgis.SnappingType.Centroid, tr("Centroid")),
    "middle": (Qgis.SnappingType.MiddleOfSegment, tr("Middle of Segments")),
    "endpoint": (Qgis.SnappingType.LineEndpoint, tr("Line Endpoints")),
}
UNITS = (
    (Qgis.MapToolUnit.Pixels, tr("px")),
    (Qgis.MapToolUnit.Layer, tr("layer units")),
    (Qgis.MapToolUnit.Project, tr("project units")),
)
# Kurz für die Einheit direkt neben der Toleranz
UNITS_SHORT = (
    (Qgis.MapToolUnit.Pixels, tr("px")),
    (Qgis.MapToolUnit.Layer, tr("layer")),
    (Qgis.MapToolUnit.Project, tr("project")),
)
SCALE_MODES = (
    (QgsSnappingConfig.ScaleDependencyMode.Disabled, tr("No scale limit")),
    (QgsSnappingConfig.ScaleDependencyMode.Global, tr("Scale limit for all layers")),
    (QgsSnappingConfig.ScaleDependencyMode.PerLayer, tr("Scale limit per layer")),
)
AVOID_MODES = (
    (Qgis.AvoidIntersectionsMode.AllowIntersections, tr("Allow Overlap")),
    (Qgis.AvoidIntersectionsMode.AvoidIntersectionsCurrentLayer, tr("Avoid Overlap on Active Layer")),
    (Qgis.AvoidIntersectionsMode.AvoidIntersectionsLayers, tr("Follow Advanced Configuration")),
)
PER_LAYER = tr("Set per layer in the snapping options")


def project():
    return QgsProject.instance()


def config():
    return project().snappingConfig()


def change(fn):
    """``fn(config)`` auf eine Kopie anwenden und schreiben, wenn sich etwas ändert."""
    cfg = config()
    before = QgsSnappingConfig(cfg)
    fn(cfg)
    if cfg != before:
        project().setSnappingConfig(cfg)


def advanced(cfg=None):
    return (cfg or config()).mode() == Qgis.SnappingMode.AdvancedConfiguration


def type_on(name, cfg=None):
    flag = TYPES[name][0]
    return bool((cfg or config()).typeFlag() & flag)


def set_type(name, on):
    flag = TYPES[name][0]

    def apply(cfg):
        flags = cfg.typeFlag()
        flags = (flags | flag) if on else (flags & ~flag)
        cfg.setTypeFlag(Qgis.SnappingTypes(flags))
    change(apply)


def set_mode(mode):
    change(lambda cfg: cfg.setMode(mode))


def set_tolerance(value):
    change(lambda cfg: cfg.setTolerance(value))


def set_units(units):
    change(lambda cfg: cfg.setUnits(units))


def set_scale_mode(mode):
    change(lambda cfg: cfg.setScaleDependencyMode(mode))


def set_scale(which, value):
    if which == "min":
        change(lambda cfg: cfg.setMinimumScale(value))
    else:
        change(lambda cfg: cfg.setMaximumScale(value))


def avoid_mode():
    return project().avoidIntersectionsMode()


def set_avoid_mode(mode):
    if project().avoidIntersectionsMode() != mode:
        project().setAvoidIntersectionsMode(mode)


def tracer(canvas):
    return QgsMapCanvasTracer.tracerForCanvas(canvas) if canvas is not None else None


def tracing_spin_boxes(window):
    """Zahlenfelder „Versatz“ in den Spurverfolgungs-Menüs des Einrast-Widgets (Leiste und Dialog).

    QGIS 4 nennt das Menü ``tracingMenu``; in 3.44 hat es keinen Namen. Dort ist
    es das einzige Menü des Widgets (``QgsSnappingWidget``, nicht in den
    Python-Bindings) mit einem Zahlenfeld.
    """
    out = []
    for menu in window.findChildren(QMenu):
        owner = menu.parent()
        if owner is not None and owner.metaObject().className() == "QgsSnappingWidget":
            out.extend(menu.findChildren(QgsDoubleSpinBox))
    return out


def tracing_offset(canvas):
    t = tracer(canvas)
    return t.offset() if t is not None else 0.0


def set_tracing_offset(window, canvas, value):
    """Versatz setzen: über die Zahlenfelder von QGIS (die ihn an den Tracer geben), sonst direkt."""
    boxes = tracing_spin_boxes(window)
    for box in boxes:
        if box.value() != value:
            box.setValue(value)
    t = tracer(canvas)
    if t is not None and t.offset() != value:
        t.setOffset(value)
