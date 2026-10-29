"""Symbol des aktiven Vektorlayers: Klassen, Farbe, Rand, Breite (Gruppe Symbol im Tab Darstellung).

Die Klassen kommen einheitlich aus den Legenden-Einträgen des Renderers
(``legendSymbolItems``, geschrieben über ``setLegendSymbolItem``), wie beim
Farbrad im Kontextmenü der QGIS-Layerliste. So gehen Einzelsymbol,
kategorisiert, abgestuft, regelbasiert und die eingebetteten Renderer von
Cluster und Punktverdrängung gleich. Renderer ohne Symbole (Heatmap) haben
keine Klassen.

Bei mehreren Klassen steht vorn „Alle …“ (``ALL``). Farben gelten dann je
Klasse und sind nicht setzbar; die Breite wirkt auf jede Klasse.

Farbe wie QGIS im Kontextmenü der Layerliste (``QgsSymbol.setColor``); bei
Linien ist das die Linienfarbe. Rand und Breite wirken auf die Symbolebenen,
die sie haben: Punkte Größe, Linien Breite, Flächen Randbreite.

Jede Änderung geht als Schritt auf den Stil-Rückgängig-Stapel des Layers
(``undoStackStyles``, wie im Panel Layer-Styling). Aufeinanderfolgende
Änderungen desselben Werts derselben Klasse werden zu einem Schritt
zusammengefasst (Farbdialog mit Live-Vorschau, Zahlenfeld).
"""

from qgis.core import (Qgis, QgsLayerTreeModelLegendNode, QgsLineSymbol, QgsMapLayerStyle, QgsMarkerSymbol,
                       QgsSymbolLayer, QgsUnitTypes, QgsVectorLayer)
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QUndoCommand

from ..core.i18n import tr

ALL = "__alle__"           # Schlüssel „Alle Klassen“
MERGE_ID = 0x51B0          # Kennung der Schritte, die sich zusammenfassen lassen
HOLDER_NAME = "qgis_ribbon_style_stack"
WIDTH_RANGE = (0.0, 1000.0)

FILL, STROKE, WIDTH = "fill", "stroke", "width"
_DD = {FILL: (QgsSymbolLayer.Property.FillColor,),
       STROKE: (QgsSymbolLayer.Property.StrokeColor,),
       WIDTH: (QgsSymbolLayer.Property.StrokeWidth, QgsSymbolLayer.Property.Width,
               QgsSymbolLayer.Property.Size)}


def _renderer(layer):
    if not isinstance(layer, QgsVectorLayer) or not layer.isSpatial():
        return None
    return layer.renderer()


def _items(layer):
    renderer = _renderer(layer)
    if renderer is None:
        return []
    return [it for it in renderer.legendSymbolItems() if it.symbol() is not None and it.ruleKey()]


def has_classes(layer):
    return bool(_items(layer))


def all_label(layer):
    """Beschriftung von „Alle …“ je nach Renderer."""
    renderer = _renderer(layer)
    kind = renderer.type() if renderer is not None else ""
    if kind == "categorizedSymbol":
        return tr("All categories")
    if kind == "RuleRenderer":
        return tr("All rules")
    return tr("All classes")


def classes(layer):
    """``[(Schlüssel, Beschriftung, Symbol)]``; bei mehreren Klassen vorn ``ALL``.

    Ein Einzelsymbol heißt „Alle Objekte“ und steht allein. Die Symbole sind
    Kopien: die des Legenden-Eintrags gehört ihm und verschwindet mit ihm.
    """
    items = _items(layer)
    if not items:
        return []
    if len(items) == 1:
        return [(items[0].ruleKey(), tr("All features"), items[0].symbol().clone())]
    out = [(ALL, all_label(layer), None)]
    out += [(it.ruleKey(), it.label() or tr("(no label)"), it.symbol().clone()) for it in items]
    return out


def tree_class(iface):
    """``(Layer, Schlüssel)`` der Klasse, die in der Layerliste gewählt ist, sonst ``(None, None)``."""
    view = iface.layerTreeView() if hasattr(iface, "layerTreeView") else None
    node = view.index2legendNode(view.currentIndex()) if view is not None else None
    if node is None or node.layerNode() is None:
        return None, None
    key = node.data(QgsLayerTreeModelLegendNode.CustomRole.RuleKey)
    return node.layerNode().layer(), key or None


def valid_key(layer, key):
    """``key``, wenn es ihn am Layer (noch) gibt, sonst die erste Wahl der Liste."""
    keys = [k for k, _label, _symbol in classes(layer)]
    if not keys:
        return None
    return key if key in keys else keys[0]


def symbols(layer, key):
    """Symbole der Klasse ``key`` (bei ``ALL`` aller Klassen), als Kopien."""
    return [it.symbol().clone() for it in _items(layer) if key == ALL or it.ruleKey() == key]


def symbol(layer, key):
    """Symbol der Klasse (Kopie) oder None (``ALL`` mit mehreren Klassen, unbekannter Schlüssel)."""
    found = symbols(layer, key)
    return found[0] if len(found) == 1 else None


def is_line(sym):
    return isinstance(sym, QgsLineSymbol)


def _stroke_layers(sym):
    return [sl for sl in sym.symbolLayers() if sl.strokeColor().isValid()]


def has(sym, what):
    """Gibt es den Wert an diesem Symbol? (Linien haben keine Füllfarbe.)"""
    if what == FILL:
        return not is_line(sym)
    if what == STROKE:
        return is_line(sym) or bool(_stroke_layers(sym))
    return width(sym) is not None


def data_defined(sym, what):
    """Wird der Wert über einen Ausdruck oder ein Feld bestimmt?"""
    if what == WIDTH and isinstance(sym, QgsMarkerSymbol) and sym.dataDefinedSize().isActive():
        return True
    if what == WIDTH and is_line(sym) and sym.dataDefinedWidth().isActive():
        return True
    props = _DD[STROKE if what == FILL and is_line(sym) else what]
    return any(sl.dataDefinedProperties().isActive(p) for sl in sym.symbolLayers() for p in props)


def color(sym, what):
    if what == FILL or is_line(sym):
        return sym.color()
    layers = _stroke_layers(sym)
    return layers[0].strokeColor() if layers else None


def set_color(sym, what, value):
    if what == FILL or is_line(sym):
        sym.setColor(value)
        return
    for sl in _stroke_layers(sym):
        sl.setStrokeColor(value)


def _width_layers(sym):
    """Symbolebenen einer Fläche mit Randbreite."""
    return [sl for sl in sym.symbolLayers() if hasattr(sl, "strokeWidth") and hasattr(sl, "setStrokeWidth")]


def width(sym):
    """Punkte: Größe, Linien: Breite, Flächen: Randbreite (erste Ebene mit Rand); None ohne Wert."""
    if isinstance(sym, QgsMarkerSymbol):
        return sym.size()
    if is_line(sym):
        return sym.width()
    layers = _width_layers(sym)
    return layers[0].strokeWidth() if layers else None


def set_width(sym, value):
    if isinstance(sym, QgsMarkerSymbol):
        sym.setSize(value)
    elif is_line(sym):
        sym.setWidth(value)
    else:
        for sl in _width_layers(sym):
            sl.setStrokeWidth(value)


def width_unit(sym):
    """Abkürzung der Einheit der Breite (mm, px, pt …)."""
    if isinstance(sym, QgsMarkerSymbol):
        unit = sym.sizeUnit()
    elif is_line(sym):
        unit = sym.outputUnit()
    else:
        layers = _width_layers(sym)
        unit = layers[0].strokeWidthUnit() if layers and hasattr(layers[0], "strokeWidthUnit") \
            else Qgis.RenderUnit.Millimeters
    return QgsUnitTypes.toAbbreviatedString(unit)


class StyleStep(QUndoCommand):
    """Schritt auf ``undoStackStyles``: Stil vorher und nachher.

    Beim Ablegen ist die Änderung schon gemacht; das erste ``redo`` (Qt ruft
    es beim ``push``) tut darum nichts.
    """

    def __init__(self, layer, before, after, text, merge_key=None):
        QUndoCommand.__init__(self, text)
        self.layer = layer
        self.before = before
        self.after = after
        self.merge_key = merge_key
        self._done = True

    def id(self):
        return MERGE_ID if self.merge_key is not None else -1

    def mergeWith(self, other):  # noqa: N802 (Qt)
        if getattr(other, "merge_key", None) != self.merge_key or other.layer is not self.layer:
            return False
        self.after = other.after
        return True

    def _write(self, style):
        style.writeToLayer(self.layer)
        self.layer.triggerRepaint()

    def redo(self):
        if self._done:
            self._done = False
            return
        self._write(self.after)

    def undo(self):
        self._write(self.before)


def _style(layer):
    style = QgsMapLayerStyle()
    style.readFromLayer(layer)
    return style


def change(layer, key, edit, text, merge_key=None):
    """``edit(symbol)`` auf die Klasse ``key`` (``ALL``: jede Klasse) anwenden, als ein Schritt.

    ``edit`` ändert die Kopie des Symbols oder gibt ein neues zurück.
    ``merge_key``: gleiche Schlüssel nacheinander ergeben einen Schritt. Gibt
    zurück, ob sich etwas geändert hat.
    """
    renderer = _renderer(layer)
    items = [it for it in _items(layer) if key == ALL or it.ruleKey() == key]
    if renderer is None or not items:
        return False
    before = _style(layer)
    for it in items:
        sym = it.symbol().clone()
        new = edit(sym)
        renderer.setLegendSymbolItem(it.ruleKey(), new if new is not None else sym)
    layer.triggerRepaint()
    layer.emitStyleChanged()
    push(layer, StyleStep(layer, before, _style(layer), text, merge_key))
    return True


class _StackHolder(QObject):
    """Hält den Python-Wrapper des Stil-Stapels eines Layers; Kind des Layers, stirbt mit ihm."""

    def __init__(self, layer):
        QObject.__init__(self, layer)
        self.setObjectName(HOLDER_NAME)
        self.stack = layer.undoStackStyles()


def push(layer, step):
    """Schritt auf den Stil-Stapel legen, so dass sein Python-Teil bleibt.

    ``push`` hängt den Schritt an den Python-Wrapper des Stapels. Stirbt der
    Wrapper (``undoStackStyles()`` liefert sonst nur einen vorübergehenden),
    stirbt auch der Python-Teil des Schritts: ``undo`` tut dann nichts mehr
    oder stürzt ab. Darum hält ``_StackHolder`` den Wrapper, solange der Layer
    lebt; auch einen aus einem früheren Laden des Plugins.
    """
    holder = layer.findChild(QObject, HOLDER_NAME)
    if getattr(holder, "stack", None) is None:
        holder = _StackHolder(layer)
    holder.stack.push(step)


def replace(layer, key, sym, text):
    """Klasse ``key`` durch ``sym`` ersetzen (Symboleditor), als ein Schritt."""
    return change(layer, key, lambda _old: sym.clone(), text)
