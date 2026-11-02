"""Bedingungen und Kontext-Zustand (ohne qgis-Imports).

``qgis_integration.context_state`` verdichtet den QGIS-Zustand zu einem
unveränderlichen ``Snapshot``. Bedingungen sind benannte Prädikate darauf.
Jede Bedingung nennt die Snapshot-Felder, von denen sie abhängt; so lässt
sich bei einer Änderung genau bestimmen, welche Bedingungen neu zu
bewerten sind.

Bedingungen werden in der Ribbon-Definition verwendet:

- ``visible_when`` an Tabs: Tab sichtbar, wenn alle gelten (Pflicht bei Kontext-Tabs);
- ``enabled_when`` an Befehlen: Befehl bedienbar, wenn alle gelten
  (zusätzlich zum Zustand der QGIS-Quelle).

Ereignisse (``EVENTS``) sind Übergänge, keine Zustände. Sie lösen den
automatischen Wechsel auf einen Tab aus (``activate_on``).
"""

from dataclasses import dataclass, fields
from typing import FrozenSet, Optional
from .i18n import tr

# Layerarten im Snapshot. QGIS kennt weniger Typen als ArcGIS Pro: WMS, WMTS
# und XYZ sind Rasterlayer, WFS ist ein Vektorlayer. ``group``: in der
# Layerliste ist eine Gruppe gewählt (kein aktiver Layer).
LAYER_KINDS = ("vector", "table", "raster", "vector_tile", "point_cloud", "mesh", "other", "group")
# Was der Datenanbieter eines Vektorlayers mit Feldern kann
FIELD_CAPS = ("add", "delete", "rename")
# Elementarten im Layout-Fenster. ``shape``: Form, Pfeil, Markierung, Knotenelement; ``table``: Rahmen einer
# Attribut- oder festen Tabelle; ``other``: alles ohne eigenen Kontext-Tab (3D-Karte, HTML, Gruppe, Plugins).
ITEM_KINDS = ("map", "label", "legend", "scalebar", "picture", "shape", "table", "other")


@dataclass(frozen=True)
class Snapshot:
    """Verdichteter Zustand des aktiven Layers.

    ``layer_kind``: ``vector`` (Vektorlayer mit Geometrie), ``table``
    (Vektorlayer ohne Geometrie), ``raster``, ``vector_tile``,
    ``point_cloud``, ``mesh``, ``other`` (Annotationen, Plugin-Layer ...),
    ``group`` (Gruppe in der Layerliste gewählt) oder ``None`` (nichts gewählt).
    """

    layer_kind: Optional[str] = None
    editable: bool = False       # Layer im Bearbeitungsmodus
    has_selection: bool = False  # mindestens ein Objekt gewählt
    field_caps: FrozenSet[str] = frozenset()  # Felder anlegen/löschen/umbenennen (``FIELD_CAPS``)
    label_classes: bool = False  # Beschriftung des Layers ist regelbasiert (Klassen an)
    selected_items: int = 0      # Layout-Fenster: Zahl der gewählten Elemente
    item_kind: Optional[str] = None  # Layout-Fenster: Art des einzigen gewählten Elements (``ITEM_KINDS``)
    layout_report: bool = False  # Layout-Fenster: Es zeigt einen Bericht, kein Drucklayout

    def __post_init__(self):
        if self.layer_kind is not None and self.layer_kind not in LAYER_KINDS:
            raise ValueError(tr("Invalid layer kind: %r") % self.layer_kind)
        if self.item_kind is not None and self.item_kind not in ITEM_KINDS:
            raise ValueError(tr("Invalid item kind: %r") % self.item_kind)
        unknown = set(self.field_caps) - set(FIELD_CAPS)
        if unknown:
            raise ValueError(tr("Invalid field capability: %r") % sorted(unknown)[0])


SNAPSHOT_FIELDS = tuple(f.name for f in fields(Snapshot))

# Name -> (abhängige Felder, Prädikat, Beschreibung)
CONDITIONS = {
    "active_layer": (
        ("layer_kind",), lambda s: s.layer_kind not in (None, "group"),
        tr("A layer is active.")),
    "active_layer_or_group": (
        ("layer_kind",), lambda s: s.layer_kind is not None,
        tr("A layer or a group is active.")),
    "active_layer_is_vector": (
        ("layer_kind",), lambda s: s.layer_kind == "vector",
        tr("The active layer is a vector layer with geometry.")),
    "active_layer_is_table": (
        ("layer_kind",), lambda s: s.layer_kind == "table",
        tr("The active layer is a table (vector layer without geometry).")),
    "active_layer_has_fields": (
        ("layer_kind",), lambda s: s.layer_kind in ("vector", "table"),
        tr("The active layer has attributes (vector layer or table).")),
    "active_layer_is_raster": (
        ("layer_kind",), lambda s: s.layer_kind == "raster",
        tr("The active layer is a raster layer.")),
    "active_layer_is_vector_tile": (
        ("layer_kind",), lambda s: s.layer_kind == "vector_tile",
        tr("The active layer is a vector tile layer.")),
    "active_layer_is_point_cloud": (
        ("layer_kind",), lambda s: s.layer_kind == "point_cloud",
        tr("The active layer is a point cloud layer.")),
    "active_layer_is_mesh": (
        ("layer_kind",), lambda s: s.layer_kind == "mesh",
        tr("The active layer is a mesh layer.")),
    "active_node_is_group": (
        ("layer_kind",), lambda s: s.layer_kind == "group",
        tr("A group is selected in the Layers panel.")),
    "active_layer_is_editable": (
        ("editable",), lambda s: s.editable,
        tr("The active layer is in edit mode.")),
    "active_layer_has_selection": (
        ("has_selection",), lambda s: s.has_selection,
        tr("At least one feature is selected in the active layer.")),
    "active_layer_can_add_fields": (
        ("field_caps",), lambda s: "add" in s.field_caps,
        tr("Fields can be added to the active layer.")),
    "active_layer_can_delete_fields": (
        ("field_caps",), lambda s: "delete" in s.field_caps,
        tr("Fields of the active layer can be deleted.")),
    "active_layer_can_rename_fields": (
        ("field_caps",), lambda s: "rename" in s.field_caps,
        tr("Fields of the active layer can be renamed.")),
    "label_classes_on": (
        ("label_classes",), lambda s: s.label_classes,
        tr("The active layer labels by class (rule-based labeling).")),
    "layout_items_selected": (
        ("selected_items",), lambda s: s.selected_items >= 1,
        tr("At least one item is selected in the layout.")),
    "layout_item_is_map": (
        ("item_kind",), lambda s: s.item_kind == "map",
        tr("Exactly one map is selected in the layout.")),
    "layout_item_is_label": (
        ("item_kind",), lambda s: s.item_kind == "label",
        tr("Exactly one text label is selected in the layout.")),
    "layout_item_is_legend": (
        ("item_kind",), lambda s: s.item_kind == "legend",
        tr("Exactly one legend is selected in the layout.")),
    "layout_item_is_scalebar": (
        ("item_kind",), lambda s: s.item_kind == "scalebar",
        tr("Exactly one scale bar is selected in the layout.")),
    "layout_item_is_picture": (
        ("item_kind",), lambda s: s.item_kind == "picture",
        tr("Exactly one picture or north arrow is selected in the layout.")),
    "layout_item_is_shape": (
        ("item_kind",), lambda s: s.item_kind == "shape",
        tr("Exactly one shape, arrow, marker or node item is selected in the layout.")),
    "layout_item_is_table": (
        ("item_kind",), lambda s: s.item_kind == "table",
        tr("Exactly one attribute table or fixed table is selected in the layout.")),
    "layout_is_report": (
        ("layout_report",), lambda s: s.layout_report,
        tr("The layout window shows a report.")),
    "layout_is_print": (
        ("layout_report",), lambda s: not s.layout_report,
        tr("The layout window shows a print layout.")),
}

EVENTS = {
    "editing_started": tr("Editing of the active layer has started."),
}


def evaluate(name, snapshot):
    return bool(CONDITIONS[name][1](snapshot))


def all_true(names, snapshot):
    return all(evaluate(n, snapshot) for n in names)


def changed_fields(old, new):
    return {f for f in SNAPSHOT_FIELDS if getattr(old, f) != getattr(new, f)}


def depending_on(changed):
    """Bedingungen, die von mindestens einem der geänderten Felder abhängen."""
    return {name for name, (deps, _, _) in CONDITIONS.items() if changed.intersection(deps)}
