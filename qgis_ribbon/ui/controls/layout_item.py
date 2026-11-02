"""Steuerelemente für die gewählten Elemente im Layout-Fenster (Kontext-Tabs).

Wie ``custom.LayerControl``, nur zeigt das Steuerelement einen Wert der gewählten
Layout-Elemente und schreibt über ``qgis_integration.layout_ops`` (jede Änderung ein
Rückgängig-Schritt, bei mehreren Elementen ein gemeinsamer). Der Beobachter ist
``env.items`` (``layout_state.LayoutSelection``). Haben die gewählten Elemente
verschiedene Werte, bleibt das Feld leer (Zahlen, Farben, Listen) bzw. teilweise
angehakt (Kontrollkästchen); bei der Deckkraft zeigt der Regler den Wert des ersten
Elements.

Kontext-Tabs je Elementart: ``KindControl`` und Unterklassen gelten genau für ein
gewähltes Element dieser Art. ``AtlasFeatureControl`` zeigt das aktuelle Atlas-Objekt.

Registrierung: ``register_all()`` beim Aufbau, ``unregister_all()`` beim Entladen.
"""

from qgis.core import (Qgis, QgsLayoutItemAttributeTable, QgsLayoutItemPicture, QgsLayoutItemRegistry,
                       QgsLayoutItemShape, QgsScaleBarSettings, QgsUnitTypes)
from qgis.gui import (QgsBlendModeComboBox, QgsColorButton, QgsDoubleSpinBox, QgsFontButton, QgsLayoutItemComboBox,
                      QgsMapLayerComboBox, QgsOpacityWidget, QgsScaleWidget, QgsSymbolButton)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFontComboBox, QLineEdit, QSlider, QStyle

from ...core.i18n import tr
from ...qgis_integration import custom_commands, layer_ops, layout_ops, layout_state
from ...qgis_integration.layout_ops import MIXED
from .custom import EDITOR_WIDTHS, OPACITY_SLIDER_MIN, LayerControl, _factory, format_size, parse_size

EDITOR_WIDTHS.update({"refpoint": 110, "frame_width": 84, "item_text": 170, "item_map": 120, "item_choice": 125,
                      "item_scale": 135, "item_length": 110, "item_path": 210, "item_font": 130, "item_button": 70,
                      "atlas_feature": 170})
RANGE = 100000.0
BLANK = " "


def reference_point_labels():
    return {"UpperLeft": tr("Top left"), "UpperMiddle": tr("Top center"), "UpperRight": tr("Top right"),
            "MiddleLeft": tr("Middle left"), "Middle": tr("Center"), "MiddleRight": tr("Middle right"),
            "LowerLeft": tr("Bottom left"), "LowerMiddle": tr("Bottom center"),
            "LowerRight": tr("Bottom right")}


class ItemControl(LayerControl):
    """Grundform für Werte der gewählten Layout-Elemente."""

    def watcher(self):
        return self.env.items

    def layer(self):
        return self.env.items.items() if self.env.items is not None else []

    def suitable(self, items):
        return bool(items)

    def write(self, change):
        """``change(items)`` auf die gewählten Elemente anwenden (nicht während des Lesens)."""
        if self._reading:
            return
        items = self.layer()
        if items:
            self._ctx.resolver.call(self.command, lambda: change(items))


class ItemNumberControl(ItemControl):
    """Zahlenfeld mit Einheit; bei verschiedenen Werten leer."""

    editor_kind = "number"
    low, high, step, decimals = 0.0, RANGE, 1.0, 2
    unit = None   # Einheit des Werts: Funktion Element -> QgsLayout…-Objekt; None: ``suffix``
    suffix = ""

    def create_editor(self):
        w = QgsDoubleSpinBox(self)
        w.setRange(self.low - 1.0, self.high)      # der Wert darunter steht für „verschieden“
        w.setSpecialValueText(BLANK)
        w.setDecimals(self.decimals)
        w.setSingleStep(self.step)
        w.setShowClearButton(False)
        w.setKeyboardTracking(False)               # erst bei Eingabetaste oder Fokuswechsel schreiben
        w.valueChanged.connect(self._changed)
        return w

    def getter(self, item):
        raise NotImplementedError

    def setter(self, items, value):
        raise NotImplementedError

    def read(self, items):
        value = layout_ops.common(items, self.getter)
        self.editor.setSuffix(self.suffix if self.unit is None else layout_ops.unit_suffix(items, self.unit))
        self.editor.setValue(self.low - 1.0 if value is MIXED else value)

    def _changed(self, value):
        if value >= self.low:
            self.write(lambda items: self.setter(items, value))


class ItemPositionControl(ItemNumberControl):
    low, high = -RANGE, RANGE

    def __init__(self, env, command, ctx, parent=None, size="medium", axis="x"):
        self.axis = axis
        ItemControl.__init__(self, env, command, ctx, parent, size)

    unit = staticmethod(layout_ops.position_of)

    def getter(self, item):
        point = item.positionWithUnits()
        return point.x() if self.axis == "x" else point.y()

    def setter(self, items, value):
        layout_ops.set_position(items, self.axis, value)


class ItemSizeControl(ItemNumberControl):
    low = 0.1

    def __init__(self, env, command, ctx, parent=None, size="medium", axis="w"):
        self.axis = axis
        ItemControl.__init__(self, env, command, ctx, parent, size)

    unit = staticmethod(layout_ops.size_of)

    def getter(self, item):
        size = item.sizeWithUnits()
        return size.width() if self.axis == "w" else size.height()

    def setter(self, items, value):
        layout_ops.set_size(items, self.axis, value)


class ItemRotationControl(ItemNumberControl):
    low, high, step, decimals = -360.0, 360.0, 1.0, 1
    suffix = " °"

    def getter(self, item):
        return item.itemRotation()

    def setter(self, items, value):
        layout_ops.set_rotation(items, value)


class ItemFrameWidthControl(ItemNumberControl):
    editor_kind = "frame_width"
    high, step = 100.0, 0.1
    unit = staticmethod(layout_ops.frame_width_of)

    def getter(self, item):
        return item.frameStrokeWidth().length()

    def setter(self, items, value):
        layout_ops.set_frame_width(items, value)


class ItemReferencePointControl(ItemControl):
    editor_kind = "refpoint"

    def create_editor(self):
        w = QComboBox(self)
        for name, label in reference_point_labels().items():
            w.addItem(label, name)
        w.setCurrentIndex(-1)
        w.activated.connect(self._chosen)
        return w

    def read(self, items):
        value = layout_ops.common(items, lambda item: item.referencePoint())
        row = -1
        if value is not MIXED:
            for n, name in enumerate(layout_ops.REFERENCE_POINTS):
                if value == layout_ops.reference_point(name):
                    row = n
        self.editor.setCurrentIndex(row)

    def _chosen(self, row):
        name = self.editor.itemData(row)
        self.write(lambda items: layout_ops.set_reference_point(items, name))


class ItemCheckControl(ItemControl):
    """Kontrollkästchen; bei verschiedenen Werten teilweise angehakt."""

    show_label = False

    def create_editor(self):
        w = QCheckBox(self.command.label, self)
        w.clicked.connect(self._clicked)
        return w

    def getter(self, item):
        raise NotImplementedError

    def setter(self, items, on):
        raise NotImplementedError

    def read(self, items):
        value = layout_ops.common(items, self.getter)
        self.editor.setTristate(value is MIXED)
        if value is MIXED:
            self.editor.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.editor.setChecked(bool(value))

    def _clicked(self, _checked):
        on = self.editor.checkState() == Qt.CheckState.Checked
        self.write(lambda items: self.setter(items, on))


class ItemFrameControl(ItemCheckControl):
    def getter(self, item):
        return item.frameEnabled()

    def setter(self, items, on):
        layout_ops.set_frame_enabled(items, on)


class ItemBackgroundControl(ItemCheckControl):
    def getter(self, item):
        return item.hasBackground()

    def setter(self, items, on):
        layout_ops.set_background_enabled(items, on)


class ItemColorControl(ItemControl):
    """Rahmen- oder Hintergrundfarbe; bei verschiedenen Farben leer."""

    editor_kind = "color"

    def __init__(self, env, command, ctx, parent=None, size="medium", what="frame"):
        self.what = what
        ItemControl.__init__(self, env, command, ctx, parent, size)

    def create_editor(self):
        w = QgsColorButton(self)
        w.setAllowOpacity(True)
        w.setShowNull(True)
        w.setColorDialogTitle(self.command.label)
        w.colorChanged.connect(self._changed)
        return w

    def color(self, item):
        return item.frameStrokeColor() if self.what == "frame" else item.backgroundColor()

    def read(self, items):
        value = layout_ops.common(items, lambda item: self.color(item).rgba())
        if value is MIXED:
            self.editor.setToNull()
        else:
            self.editor.setColor(self.color(items[0]))

    def _changed(self, color):
        if not color.isValid():
            return
        setter = layout_ops.set_frame_color if self.what == "frame" else layout_ops.set_background_color
        self.write(lambda items: setter(items, color))


class ItemOpacityControl(ItemControl):
    editor_kind = "opacity"
    label_gap = 8

    def create_editor(self):
        w = QgsOpacityWidget(self)
        slider = w.findChild(QSlider)
        if slider is not None:
            slider.setMinimumWidth(OPACITY_SLIDER_MIN)
        if w.layout() is not None:
            w.layout().setSpacing(8)
        w.opacityChanged.connect(lambda value: self.write(lambda items: layout_ops.set_opacity(items, value)))
        return w

    def read(self, items):
        self.editor.setOpacity(items[0].itemOpacity())


class ItemBlendModeControl(ItemControl):
    editor_kind = "blend"

    def create_editor(self):
        w = QgsBlendModeComboBox(self)
        w.currentIndexChanged.connect(
            lambda _i: self.write(lambda items: layout_ops.set_blend_mode(items, w.blendMode())))
        return w

    def read(self, items):
        value = layout_ops.common(items, lambda item: item.blendMode())
        if value is MIXED:
            self.editor.setCurrentIndex(-1)
        else:
            self.editor.setBlendMode(value)


# Kontext-Tabs je Elementart

class KindControl(ItemControl):
    """Wert genau eines gewählten Elements einer Art (``core.conditions.ITEM_KINDS``)."""

    kind = None

    def suitable(self, items):
        return len(items) == 1 and layout_state.kind_of(items[0]) == self.kind

    def write_item(self, change):
        """``change(item)`` auf das gewählte Element anwenden."""
        self.write(lambda items: change(items[0]))


class KindNumberControl(KindControl):
    """Zahlenfeld; ohne Wert unter dem Minimum, da es nur ein Element gibt."""

    editor_kind = "number"
    low, high, step, decimals = 0.0, RANGE, 1.0, 2
    suffix = ""

    def create_editor(self):
        w = QgsDoubleSpinBox(self)
        w.setRange(self.low, self.high)
        w.setDecimals(self.decimals)
        w.setSingleStep(self.step)
        w.setSuffix(self.suffix)
        w.setShowClearButton(False)
        w.setKeyboardTracking(False)
        w.valueChanged.connect(lambda value: self.write_item(lambda item: self.setter(item, value)))
        return w

    def getter(self, item):
        raise NotImplementedError

    def setter(self, item, value):
        raise NotImplementedError

    def read(self, items):
        self.editor.setValue(self.getter(items[0]))


class KindCheckControl(KindControl):
    show_label = False

    def create_editor(self):
        w = QCheckBox(self.command.label, self)
        w.clicked.connect(lambda on: self.write_item(lambda item: self.setter(item, on)))
        return w

    def getter(self, item):
        raise NotImplementedError

    def setter(self, item, on):
        raise NotImplementedError

    def read(self, items):
        self.editor.setChecked(bool(self.getter(items[0])))


class KindChoiceControl(KindControl):
    """Liste fester Werte; ``choices`` liefert (Wert, Beschriftung)."""

    editor_kind = "item_choice"

    def choices(self):
        raise NotImplementedError

    def create_editor(self):
        w = QComboBox(self)
        self.values = []
        for value, label in self.choices():
            self.values.append(value)
            w.addItem(label)
        w.activated.connect(lambda row: self.write_item(lambda item: self.setter(item, self.values[row])))
        return w

    def getter(self, item):
        raise NotImplementedError

    def setter(self, item, value):
        raise NotImplementedError

    def read(self, items):
        value = self.getter(items[0])
        self.editor.setCurrentIndex(self.values.index(value) if value in self.values else -1)


class KindTextControl(KindControl):
    """Einzeiliges Textfeld; schreibt bei Eingabetaste oder Fokuswechsel."""

    editor_kind = "item_text"

    def create_editor(self):
        w = QLineEdit(self)
        w.editingFinished.connect(self._finished)
        return w

    def getter(self, item):
        raise NotImplementedError

    def setter(self, item, text):
        raise NotImplementedError

    def writable(self, _item):
        return True

    def _finished(self):
        items = self.layer()
        if not self.suitable(items) or not self.writable(items[0]):
            return
        text = self.editor.text()
        if text != self.getter(items[0]):
            self.write_item(lambda item: self.setter(item, text))

    def read(self, items):
        self.editor.setText(self.getter(items[0]))


class LinkedMapControl(KindControl):
    """Verknüpfte Karte einer Legende, eines Maßstabs oder eines Bilds."""

    editor_kind = "item_map"
    allow_empty = False

    def create_editor(self):
        self._layout = self.env.items.layout
        w = QgsLayoutItemComboBox(self, self._layout)
        w.setItemType(QgsLayoutItemRegistry.ItemType.LayoutMap)
        w.setAllowEmptyItem(self.allow_empty)
        w.activated.connect(self._chosen)      # nicht itemChanged: das meldet auch gelöschte Karten
        return w

    def _chosen(self, _row):
        linked = self.editor.currentItem()
        self.write_item(lambda item: self.setter(item, linked))

    def setter(self, item, linked):
        layout_ops.set_linked_map(item, linked)

    def read(self, items):
        if self.env.items.layout is not self._layout:    # Bericht: anderer Abschnitt
            self._layout = self.env.items.layout
            self.editor.setCurrentLayout(self._layout)
        self.editor.setItem(items[0].linkedMap())


class LabelFontControl(KindControl):
    kind = "label"
    editor_kind = "item_font"

    def create_editor(self):
        w = QFontComboBox(self)
        w.currentFontChanged.connect(
            lambda font: self.write_item(lambda item: layout_ops.set_font_family(item, font.family())))
        return w

    def read(self, items):
        self.editor.setCurrentFont(items[0].textFormat().font())


class LabelSizeControl(KindControl):
    kind = "label"
    editor_kind = "size"

    def create_editor(self):
        w = QComboBox(self)
        w.setEditable(True)
        w.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        w.addItems([format_size(s) for s in layer_ops.FONT_SIZES])
        w.activated.connect(lambda _i: self._apply())
        w.lineEdit().editingFinished.connect(self._apply)
        return w

    def _apply(self):
        items = self.layer()
        if not self.suitable(items):
            return
        size = parse_size(self.editor.currentText())
        if size is None:
            self.refresh()
        elif abs(size - items[0].textFormat().size()) > 1e-9:
            self.write_item(lambda item: layout_ops.set_font_size(item, size))

    def read(self, items):
        self.editor.setEditText(format_size(items[0].textFormat().size()))


class LabelColorControl(KindControl):
    kind = "label"
    editor_kind = "color"

    def create_editor(self):
        w = QgsColorButton(self)
        w.setAllowOpacity(True)
        w.setShowNoColor(False)
        w.setColorDialogTitle(self.command.label)
        w.colorChanged.connect(
            lambda color: self.write_item(lambda item: layout_ops.set_font_color(item, color)))
        return w

    def read(self, items):
        self.editor.setColor(items[0].textFormat().color())


# Karte

class MapScaleControl(KindControl):
    kind = "map"
    editor_kind = "item_scale"

    def create_editor(self):
        w = QgsScaleWidget(self)
        w.setShowCurrentScaleButton(True)
        w.setMapCanvas(self.env.iface.mapCanvas())
        w.scaleChanged.connect(self._changed)
        return w

    def _changed(self, scale):
        if scale > 0:
            self.write_item(lambda item: layout_ops.set_map_scale(item, scale))

    def read(self, items):
        self.editor.setScale(items[0].scale())


class MapRotationControl(KindNumberControl):
    kind = "map"
    low, high, step, decimals = -360.0, 360.0, 1.0, 1
    suffix = " °"

    def getter(self, item):
        return item.mapRotation()

    def setter(self, item, value):
        layout_ops.set_map_rotation(item, value)


class MapKeepLayersControl(KindCheckControl):
    kind = "map"

    def getter(self, item):
        return item.keepLayerSet()

    def setter(self, item, on):
        layout_ops.set_keep_layers(item, on, self.env.iface.mapCanvas())


class MapKeepStylesControl(KindCheckControl):
    """Wie im Bedienfeld nur bei gesperrten Layern bedienbar."""
    kind = "map"

    def suitable(self, items):
        return KindCheckControl.suitable(self, items) and items[0].keepLayerSet()

    def getter(self, item):
        return item.keepLayerStyles()

    def setter(self, item, on):
        layout_ops.set_keep_styles(item, on)


# Text

class LabelTextControl(KindTextControl):
    """Text des Elements. Mehrzeilige Texte bleiben schreibgeschützt, das Feld würde die Umbrüche verlieren."""
    kind = "label"

    def getter(self, item):
        return item.text()

    def setter(self, item, text):
        layout_ops.set_label_text(item, text)

    def writable(self, item):
        return "\n" not in item.text()

    def read(self, items):
        multiline = not self.writable(items[0])
        self.editor.setReadOnly(multiline)
        hint = tr("Text with several lines: edit it in the Item Properties panel.")
        self.editor.setToolTip(hint if multiline else "")
        self.editor.setText(items[0].text().replace("\n", " "))


def horizontal_alignments():
    return ((Qt.AlignmentFlag.AlignLeft, tr("Left")), (Qt.AlignmentFlag.AlignHCenter, tr("Center")),
            (Qt.AlignmentFlag.AlignRight, tr("Right")), (Qt.AlignmentFlag.AlignJustify, tr("Justify")))


def vertical_alignments():
    return ((Qt.AlignmentFlag.AlignTop, tr("Top")), (Qt.AlignmentFlag.AlignVCenter, tr("Middle")),
            (Qt.AlignmentFlag.AlignBottom, tr("Bottom")))


class LabelAlignControl(KindChoiceControl):
    kind = "label"

    def __init__(self, env, command, ctx, parent=None, size="medium", horizontal=True):
        self.horizontal = horizontal
        KindChoiceControl.__init__(self, env, command, ctx, parent, size)

    def choices(self):
        return horizontal_alignments() if self.horizontal else vertical_alignments()

    def getter(self, item):
        return item.hAlign() if self.horizontal else item.vAlign()

    def setter(self, item, value):
        layout_ops.set_label_alignment(item, self.horizontal, value)


# Legende

class LegendMapControl(LinkedMapControl):
    kind = "legend"
    allow_empty = True


class LegendAutoControl(KindCheckControl):
    kind = "legend"

    def getter(self, item):
        return layout_ops.legend_auto_update(item)

    def setter(self, item, on):
        layout_ops.set_legend_auto_update(item, on)


class LegendFilterControl(KindCheckControl):
    kind = "legend"

    def getter(self, item):
        return item.legendFilterByMapEnabled()

    def setter(self, item, on):
        layout_ops.set_legend_filter(item, on)


class LegendTitleControl(KindTextControl):
    kind = "legend"

    def getter(self, item):
        return item.title()

    def setter(self, item, text):
        layout_ops.set_legend_title(item, text)


class LegendColumnsControl(KindNumberControl):
    kind = "legend"
    low, high, decimals = 1.0, 100.0, 0

    def getter(self, item):
        return item.columnCount()

    def setter(self, item, value):
        layout_ops.set_legend_columns(item, value)


class LegendResizeControl(KindCheckControl):
    kind = "legend"

    def getter(self, item):
        return item.resizeToContents()

    def setter(self, item, on):
        layout_ops.set_legend_resize(item, on)


# Maßstab

SCALEBAR_UNITS = (Qgis.DistanceUnit.Meters, Qgis.DistanceUnit.Kilometers, Qgis.DistanceUnit.Feet,
                  Qgis.DistanceUnit.Yards, Qgis.DistanceUnit.Miles, Qgis.DistanceUnit.NauticalMiles,
                  Qgis.DistanceUnit.Centimeters, Qgis.DistanceUnit.Millimeters, Qgis.DistanceUnit.Inches)


class ScaleBarMapControl(LinkedMapControl):
    kind = "scalebar"
    pass


class ScaleBarStyleControl(KindChoiceControl):
    kind = "scalebar"

    def choices(self):
        return layout_ops.scalebar_styles()

    def getter(self, item):
        return item.style()

    def setter(self, item, value):
        layout_ops.set_scalebar_style(item, value)


class ScaleBarUnitsControl(KindChoiceControl):
    kind = "scalebar"

    def choices(self):
        return ([(Qgis.DistanceUnit.Unknown, tr("Map units"))]
                + [(unit, QgsUnitTypes.toString(unit)) for unit in SCALEBAR_UNITS])

    def getter(self, item):
        return item.units()

    def setter(self, item, value):
        layout_ops.set_scalebar_units(item, value)


class ScaleBarSegmentsControl(KindNumberControl):
    kind = "scalebar"
    low, high, decimals = 1.0, 100.0, 0

    def getter(self, item):
        return item.numberOfSegments()

    def setter(self, item, value):
        layout_ops.set_scalebar_segments(item, value)


class ScaleBarLengthControl(KindNumberControl):
    """Segmentlänge; bei „an Breite anpassen“ berechnet QGIS sie selbst, das Feld ist dann aus."""
    kind = "scalebar"
    editor_kind = "item_length"
    low, high, step, decimals = 0.0001, 1.0e9, 10.0, 4

    def suitable(self, items):
        return (KindNumberControl.suitable(self, items)
                and items[0].segmentSizeMode() == QgsScaleBarSettings.SegmentSizeMode.SegmentSizeFixed)

    def getter(self, item):
        return item.unitsPerSegment()

    def setter(self, item, value):
        layout_ops.set_scalebar_length(item, value)


class ScaleBarFontControl(KindControl):
    kind = "scalebar"
    editor_kind = "item_button"

    def create_editor(self):
        w = QgsFontButton(self)
        w.setMode(QgsFontButton.Mode.ModeTextRenderer)
        w.setMapCanvas(self.env.iface.mapCanvas())
        w.changed.connect(lambda: self.write_item(lambda item: layout_ops.set_text_format(item, w.textFormat())))
        return w

    def read(self, items):
        self.editor.setTextFormat(items[0].textFormat())


# Bild

PICTURE_FILTER = "*.svg *.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp"


class PicturePathControl(KindTextControl):
    """Pfad oder Adresse des Bilds, mit Dateiauswahl am Ende des Felds."""
    kind = "picture"
    editor_kind = "item_path"

    def create_editor(self):
        w = KindTextControl.create_editor(self)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        w.addAction(icon, QLineEdit.ActionPosition.TrailingPosition).triggered.connect(self._browse)
        return w

    def _browse(self):
        path, _filter = QFileDialog.getOpenFileName(self, self.command.label, self.editor.text(),
                                                    tr("Images (%s)") % PICTURE_FILTER)
        if path:
            self.editor.setText(path)
            self._finished()

    def getter(self, item):
        return item.picturePath()

    def setter(self, item, text):
        layout_ops.set_picture_path(item, text)


class PictureModeControl(KindChoiceControl):
    kind = "picture"

    def choices(self):
        modes = QgsLayoutItemPicture.ResizeMode
        return ((modes.Zoom, tr("Fit in Frame")), (modes.Stretch, tr("Stretch")), (modes.Clip, tr("Clip")),
                (modes.ZoomResizeFrame, tr("Zoom and Resize Frame")),
                (modes.FrameToImageSize, tr("Resize Frame to Image Size")))

    def getter(self, item):
        return item.resizeMode()

    def setter(self, item, value):
        layout_ops.set_picture_resize_mode(item, value)


class PictureAnchorControl(KindChoiceControl):
    kind = "picture"

    def choices(self):
        return tuple(reference_point_labels().items())

    def getter(self, item):
        anchor = item.pictureAnchor()
        for name in layout_ops.REFERENCE_POINTS:
            if anchor == layout_ops.reference_point(name):
                return name
        return None

    def setter(self, item, value):
        layout_ops.set_picture_anchor(item, value)


class PictureMapControl(LinkedMapControl):
    kind = "picture"
    allow_empty = True

    def setter(self, item, linked):
        layout_ops.set_picture_map(item, linked)


# Form

class ShapeSymbolControl(KindControl):
    kind = "shape"
    editor_kind = "item_button"

    def create_editor(self):
        w = QgsSymbolButton(self)
        w.setDialogTitle(self.command.label)
        w.setMapCanvas(self.env.iface.mapCanvas())
        w.changed.connect(lambda: self.write_item(lambda item: layout_ops.set_shape_symbol(item, w.symbol())))
        return w

    def read(self, items):
        symbol = items[0].symbol()
        self.editor.setSymbolType(symbol.type())
        self.editor.setSymbol(symbol.clone())


class ShapeTypeControl(KindChoiceControl):
    """Nur für Formen (Rechteck, Ellipse, Dreieck); Pfeil, Markierung und Knotenelement haben keinen Typ."""
    kind = "shape"

    def suitable(self, items):
        return KindChoiceControl.suitable(self, items) and isinstance(items[0], QgsLayoutItemShape)

    def choices(self):
        shapes = QgsLayoutItemShape.Shape
        return ((shapes.Rectangle, tr("Rectangle")), (shapes.Ellipse, tr("Ellipse")), (shapes.Triangle, tr("Triangle")))

    def getter(self, item):
        return item.shapeType()

    def setter(self, item, value):
        layout_ops.set_shape_type(item, value)


class ShapeRadiusControl(KindNumberControl):
    """Eckenradius; gilt wie im Bedienfeld nur für Rechtecke."""
    kind = "shape"
    high, step = 1000.0, 0.5

    def suitable(self, items):
        return (KindNumberControl.suitable(self, items) and isinstance(items[0], QgsLayoutItemShape)
                and items[0].shapeType() == QgsLayoutItemShape.Shape.Rectangle)

    def getter(self, item):
        return item.cornerRadius().length()

    def setter(self, item, value):
        layout_ops.set_corner_radius(item, value)

    def read(self, items):
        self.editor.setSuffix(" " + QgsUnitTypes.toAbbreviatedString(items[0].cornerRadius().units()))
        self.editor.setValue(self.getter(items[0]))


# Tabelle: das gewählte Element ist ein Rahmen, die Werte stehen am Multiframe

class TableControl(object):
    kind = "table"

    def suitable(self, items):
        return (KindControl.suitable(self, items)
                and isinstance(layout_state.multi_frame(items[0]), QgsLayoutItemAttributeTable))

    def table(self, item):
        return layout_state.multi_frame(item)


class TableLayerControl(TableControl, KindControl):
    """Layer der Attributtabelle; bei Atlas oder Beziehung als Quelle aus."""

    editor_kind = "item_map"

    def suitable(self, items):
        return (TableControl.suitable(self, items)
                and self.table(items[0]).source() == QgsLayoutItemAttributeTable.ContentSource.LayerAttributes)

    def create_editor(self):
        w = QgsMapLayerComboBox(self)
        w.setFilters(Qgis.LayerFilter.VectorLayer)
        w.activated.connect(self._chosen)      # nicht layerChanged: das meldet auch Änderungen am Projekt
        return w

    def _chosen(self, _row):
        layer = self.editor.currentLayer()
        if layer is not None:
            self.write_item(lambda item: layout_ops.set_table_layer(self.table(item), layer))

    def read(self, items):
        self.editor.setLayer(self.table(items[0]).vectorLayer())


class TableRowsControl(TableControl, KindNumberControl):
    low, high, decimals = 0.0, RANGE, 0

    def getter(self, item):
        return self.table(item).maximumNumberOfFeatures()

    def setter(self, item, value):
        layout_ops.set_table_rows(self.table(item), value)


class TableFilterControl(TableControl, KindTextControl):
    def getter(self, item):
        table = self.table(item)
        return table.featureFilter() if table.filterFeatures() else ""

    def setter(self, item, text):
        layout_ops.set_table_filter(self.table(item), text)


class TableVisibleControl(TableControl, KindCheckControl):
    def getter(self, item):
        return self.table(item).displayOnlyVisibleFeatures()

    def setter(self, item, on):
        layout_ops.set_table_visible_only(self.table(item), on)


# Atlas

class AtlasFeatureControl(ItemControl):
    """Objekt-Auswahl auf dem Tab Atlas; bedienbar, solange die Atlas-Vorschau läuft."""

    editor_kind = "atlas_feature"

    def create_editor(self):
        self._names = None
        w = QComboBox(self)
        w.setMaxVisibleItems(20)
        w.activated.connect(self._chosen)
        return w

    def atlas(self):
        return layout_ops.atlas_of(self.env.designer)

    def suitable(self, _items):
        return layout_ops.atlas_preview_on(self.env.designer)

    def _chosen(self, row):
        if not self._reading and row >= 0:
            self._ctx.resolver.call(self.command, lambda: self.atlas().seekTo(row))

    def read(self, _items):
        atlas = self.atlas()
        names = layout_ops.atlas_names(atlas)
        if names != self._names:
            self._names = names
            self.editor.clear()
            self.editor.addItems(names)
        self.editor.setCurrentIndex(atlas.currentFeatureNumber())


CONTROLS = {
    "ribbon.item_karte_massstab": _factory(MapScaleControl),
    "ribbon.item_karte_drehung": _factory(MapRotationControl),
    "ribbon.item_karte_layer_sperren": _factory(MapKeepLayersControl),
    "ribbon.item_karte_stile_sperren": _factory(MapKeepStylesControl),
    "ribbon.item_text_inhalt": _factory(LabelTextControl),
    "ribbon.item_text_schrift": _factory(LabelFontControl),
    "ribbon.item_text_groesse": _factory(LabelSizeControl),
    "ribbon.item_text_farbe": _factory(LabelColorControl),
    "ribbon.item_text_horizontal": _factory(LabelAlignControl, horizontal=True),
    "ribbon.item_text_vertikal": _factory(LabelAlignControl, horizontal=False),
    "ribbon.item_legende_karte": _factory(LegendMapControl),
    "ribbon.item_legende_auto": _factory(LegendAutoControl),
    "ribbon.item_legende_filter": _factory(LegendFilterControl),
    "ribbon.item_legende_titel": _factory(LegendTitleControl),
    "ribbon.item_legende_spalten": _factory(LegendColumnsControl),
    "ribbon.item_legende_anpassen": _factory(LegendResizeControl),
    "ribbon.item_massstab_karte": _factory(ScaleBarMapControl),
    "ribbon.item_massstab_stil": _factory(ScaleBarStyleControl),
    "ribbon.item_massstab_einheit": _factory(ScaleBarUnitsControl),
    "ribbon.item_massstab_segmente": _factory(ScaleBarSegmentsControl),
    "ribbon.item_massstab_laenge": _factory(ScaleBarLengthControl),
    "ribbon.item_massstab_schrift": _factory(ScaleBarFontControl),
    "ribbon.item_bild_quelle": _factory(PicturePathControl),
    "ribbon.item_bild_modus": _factory(PictureModeControl),
    "ribbon.item_bild_anker": _factory(PictureAnchorControl),
    "ribbon.item_bild_karte": _factory(PictureMapControl),
    "ribbon.item_form_symbol": _factory(ShapeSymbolControl),
    "ribbon.item_form_typ": _factory(ShapeTypeControl),
    "ribbon.item_form_radius": _factory(ShapeRadiusControl),
    "ribbon.item_tabelle_layer": _factory(TableLayerControl),
    "ribbon.item_tabelle_zeilen": _factory(TableRowsControl),
    "ribbon.item_tabelle_filter": _factory(TableFilterControl),
    "ribbon.item_tabelle_nur_karte": _factory(TableVisibleControl),
    "ribbon.atlas_objekt": _factory(AtlasFeatureControl),
    "ribbon.item_x": _factory(ItemPositionControl, axis="x"),
    "ribbon.item_y": _factory(ItemPositionControl, axis="y"),
    "ribbon.item_breite": _factory(ItemSizeControl, axis="w"),
    "ribbon.item_hoehe": _factory(ItemSizeControl, axis="h"),
    "ribbon.item_drehung": _factory(ItemRotationControl),
    "ribbon.item_bezugspunkt": _factory(ItemReferencePointControl),
    "ribbon.item_rahmen": _factory(ItemFrameControl),
    "ribbon.item_rahmenfarbe": _factory(ItemColorControl, what="frame"),
    "ribbon.item_rahmenstaerke": _factory(ItemFrameWidthControl),
    "ribbon.item_hintergrund": _factory(ItemBackgroundControl),
    "ribbon.item_hintergrundfarbe": _factory(ItemColorControl, what="background"),
    "ribbon.item_deckkraft": _factory(ItemOpacityControl),
    "ribbon.item_mischmodus": _factory(ItemBlendModeControl),
}


def register_all():
    for cid, factory in CONTROLS.items():
        custom_commands.register(cid, factory, "control")


def unregister_all():
    for cid in CONTROLS:
        custom_commands.unregister(cid)
