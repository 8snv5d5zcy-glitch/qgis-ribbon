"""Steuerelemente des Ribbons auf QGIS-API (Regler, Comboboxen, Farbwahl).

Jedes Steuerelement zeigt eine Eigenschaft des aktiven Layers und setzt sie
über ``qgis_integration.layer_ops``. Es meldet sich beim ``LayerWatch`` an
und liest neu, wenn der aktive Layer wechselt oder sich dessen Darstellung
ändert (ereignisgesteuert). Beim Lesen sind die Signale des Widgets
gesperrt, damit Lesen nicht wieder Schreiben auslöst.

Wo möglich werden QGIS-eigene Widgets verwendet (``QgsScaleWidget``,
``QgsOpacityWidget``, ``QgsBlendModeComboBox``, ``QgsColorButton``); sie
verhalten sich wie in den QGIS-Dialogen.

Registrierung: ``register_all()`` beim Aufbau, ``unregister_all()`` beim
Entladen (``custom_commands``, Art ``control``).
"""

from qgis.gui import (QgsBlendModeComboBox, QgsColorButton, QgsDoubleSpinBox,
                      QgsFieldExpressionWidget, QgsOpacityWidget, QgsScaleWidget, QgsSpinBox)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFontDatabase, QIcon, QPainter
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QFontComboBox, QHBoxLayout, QLabel,
                                 QSizePolicy, QSlider, QWidget)

from ...qgis_integration import (builtin_commands, compare, custom_commands, kontext_ops, layer_ops,
                                 raster_ops)
from .. import icons, theme
from ..html_text import escape
from ...core.i18n import tr

EDITOR_WIDTHS = {"scale": 110, "opacity": 200, "blend": 120, "font": 140, "size": 52,
                 "style": 90, "color": 36, "class": 120, "field": 150, "number": 72,
                 "interval": 84, "dataset": 140}


class IconLabel(QWidget):
    """Icon vor der Beschriftung; zeichnet bei jedem Neuzeichnen (folgt Hell/Dunkel)."""

    def __init__(self, icon, parent=None):
        QWidget.__init__(self, parent)
        self.icon = icon
        self.setFixedSize(theme.SMALL_ICON, theme.SMALL_ICON)

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        painter = QPainter(self)
        mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
        self.icon.paint(painter, self.rect(), Qt.AlignCenter, mode)
        painter.end()


class LayerControl(QWidget):
    """Grundform: [Icon] [Beschriftung] [Editor] (mittel) bzw. nur [Editor] (klein)."""

    editor_kind = None
    show_label = True       # False: der Editor trägt die Beschriftung selbst (Kontrollkästchen)
    group_aware = False     # True: bei gewählter Gruppe wirkt es auf deren Gruppenebene
    label_gap = 4           # Abstand zwischen Icon, Beschriftung und Editor

    def __init__(self, env, command, ctx, parent=None, size="medium"):
        QWidget.__init__(self, parent)
        self.env = env
        self.command = command
        self._ctx = ctx
        self._reading = False
        self.stale = False      # Änderung verpasst, weil nicht sichtbar
        self.setObjectName("ribbon_control_" + command.id)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(self.label_gap)
        if size != "small" and self.show_label:
            fallback = ctx.resolver.theme_icon(command.icon) if command.icon else None
            icon = icons.command_icon(command, fallback)
            if icon is not None and not icon.isNull():
                lay.addWidget(IconLabel(icon, self))
            text = QLabel(command.label, self)
            lay.addWidget(text)
        self.editor = self.create_editor()
        self.editor.setFixedHeight(theme.ROW_HEIGHT - 2)
        width = EDITOR_WIDTHS.get(self.editor_kind)
        if width:
            self.editor.setFixedWidth(width)
        lay.addWidget(self.editor)
        self.setFixedHeight(theme.ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip(self._tooltip())
        if env.layers is not None:
            env.layers.subscribe(self.refresh)
        ctx.register(self)
        ctx.add_target(self, command.label, self.focus_editor, command)
        self.refresh(self.layer())

    def focus_editor(self):
        """Per Tastatur (KeyTip, Suche): Fokus in den Editor. False, wenn nicht bedienbar."""
        if not self.isEnabled():
            return False
        self.editor.setFocus(Qt.ShortcutFocusReason)
        return True

    def _tooltip(self):
        parts = ["<b>%s</b>" % escape(self.command.label)]
        if self.command.description:
            parts.append(escape(self.command.description))
        return "<br>".join(parts)

    # Schnittstelle der Unterklassen
    def create_editor(self):
        raise NotImplementedError

    def suitable(self, layer):
        return layer is not None

    def read(self, layer):
        """Editor aus dem Layer füllen (Signale sind gesperrt)."""

    def read_default(self):
        """Gruppe ohne Gruppenebene: Editor auf den QGIS-Standardwert setzen."""

    # Ablauf
    def layer(self):
        if self.env.layers is not None:
            return self.env.layers.active_layer()
        return self.env.iface.activeLayer()

    def group(self):
        """Gewählte Gruppe, wenn das Steuerelement für Gruppen gilt und kein Layer aktiv ist."""
        if not self.group_aware or self.env.layers is None or self.layer() is not None:
            return None
        return self.env.layers.group()

    def refresh(self, layer=None):
        # Nicht sichtbar (anderer Tab, Seite noch im Aufbau): erst beim Zeigen lesen.
        # Sonst liest jeder Layerwechsel alle gebauten Steuerelemente.
        if not self.isVisibleTo(self.window()):
            self.stale = True
            return
        self.stale = False
        layer = self.layer() if layer is None else layer
        self.sync()
        group = self.group() if layer is None else None
        if group is not None:
            layer = kontext_ops.group_layer(group)
        elif not self.suitable(layer):
            return
        self._reading = True
        self.editor.blockSignals(True)
        try:
            if group is not None and layer is None:
                self.read_default()
            else:
                self.read(layer)
        finally:
            self.editor.blockSignals(False)
            self._reading = False

    def sync(self):
        usable = self.suitable(self.layer()) or self.group() is not None
        self.setEnabled(usable and self._ctx.allowed(self.command))

    def refresh_if_stale(self):
        if self.stale:
            self.refresh()

    def showEvent(self, event):  # noqa: N802 (Qt)
        QWidget.showEvent(self, event)
        self.refresh_if_stale()

    def write(self, change):
        """``change(layer)`` auf den aktiven Layer anwenden (nicht während des Lesens).

        Bei gewählter Gruppe auf deren Gruppenebene; die Gruppe wird dazu als
        Gruppe dargestellt, falls sie es noch nicht ist.
        """
        if self._reading:
            return
        layer = self.layer()
        if self.suitable(layer):
            self._ctx.resolver.call(self.command, lambda: change(layer))
        elif self.group() is not None:
            self._ctx.resolver.call(self.command, lambda: change(self.env.layers.ensure_group_layer()))


class ScaleControl(LayerControl):
    """Größter/kleinster Maßstab des Layers oder seiner Beschriftung. Leer = keine Grenze."""

    editor_kind = "scale"

    def __init__(self, env, command, ctx, parent=None, size="medium", which="max", labels=False):
        self.which = which
        self.labels = labels
        self.group_aware = not labels
        LayerControl.__init__(self, env, command, ctx, parent, size)

    def create_editor(self):
        w = QgsScaleWidget(self)
        w.setAllowNull(True)
        w.setShowCurrentScaleButton(True)
        w.setMapCanvas(self.env.iface.mapCanvas())
        w.scaleChanged.connect(self._changed)
        return w

    def suitable(self, layer):
        return layer_ops.is_vector(layer) if self.labels else layer is not None

    def read(self, layer):
        if self.labels:
            _on, max_scale, min_scale = layer_ops.label_scale_range(layer)
        else:
            _on, max_scale, min_scale = layer_ops.scale_range(layer)
        value = max_scale if self.which == "max" else min_scale
        if value:
            self.editor.setScale(value)
        else:
            self.editor.setNull()

    def read_default(self):
        self.editor.setNull()

    def value(self):
        return 0.0 if self.editor.isNull() else self.editor.scale()

    def _changed(self, *_args):
        value = self.value()
        if self.labels:
            self.write(lambda layer: layer_ops.set_label_scale(layer, self.which, value))
        else:
            self.write(lambda layer: layer_ops.set_layer_scale(layer, self.which, value))


OPACITY_SLIDER_MIN = 120   # Schiebereglerteil der Deckkraft, damit er sich gut greifen lässt


class OpacityControl(LayerControl):
    editor_kind = "opacity"
    group_aware = True
    label_gap = 8

    def create_editor(self):
        w = QgsOpacityWidget(self)
        slider = w.findChild(QSlider)
        if slider is not None:
            slider.setMinimumWidth(OPACITY_SLIDER_MIN)
        if w.layout() is not None:
            w.layout().setSpacing(8)
        w.opacityChanged.connect(
            lambda value: self.write(lambda layer: layer_ops.set_opacity(layer, value)))
        return w

    def read(self, layer):
        self.editor.setOpacity(layer_ops.opacity(layer))

    def read_default(self):
        self.editor.setOpacity(1.0)


class BlendModeControl(LayerControl):
    editor_kind = "blend"
    group_aware = True

    def create_editor(self):
        w = QgsBlendModeComboBox(self)
        w.currentIndexChanged.connect(
            lambda _i: self.write(lambda layer: layer_ops.set_blend_mode(layer, w.blendMode())))
        return w

    def read(self, layer):
        self.editor.setBlendMode(layer_ops.blend_mode(layer))

    def read_default(self):
        self.editor.setBlendMode(QPainter.CompositionMode_SourceOver)


class FeatureBlendModeControl(LayerControl):
    """Mischmodus der Objekte eines Vektorlayers untereinander."""

    editor_kind = "blend"

    def create_editor(self):
        w = QgsBlendModeComboBox(self)
        w.currentIndexChanged.connect(lambda _i: self.write(
            lambda layer: layer_ops.set_feature_blend_mode(layer, w.blendMode())))
        return w

    def suitable(self, layer):
        return layer_ops.is_vector(layer)

    def read(self, layer):
        self.editor.setBlendMode(layer_ops.feature_blend_mode(layer))


class LabelControl(LayerControl):
    """Steuerelemente der Beschriftung: nur für Vektorlayer."""

    def suitable(self, layer):
        return layer_ops.is_vector(layer)


class FontControl(LabelControl):
    editor_kind = "font"

    def create_editor(self):
        w = QFontComboBox(self)
        w.currentFontChanged.connect(
            lambda font: self.write(lambda layer: layer_ops.set_font_family(layer, font.family())))
        return w

    def read(self, layer):
        self.editor.setCurrentFont(layer_ops.text_format(layer).font())


def parse_size(text):
    try:
        value = float(str(text).replace(",", ".").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def format_size(value):
    return ("%g" % value).replace(".", ",")


class FontSizeControl(LabelControl):
    editor_kind = "size"

    def create_editor(self):
        w = QComboBox(self)
        w.setEditable(True)
        w.setInsertPolicy(QComboBox.NoInsert)
        w.addItems([format_size(s) for s in layer_ops.FONT_SIZES])
        w.activated.connect(lambda _i: self._apply())
        w.lineEdit().editingFinished.connect(self._apply)
        return w

    def _apply(self):
        size = parse_size(self.editor.currentText())
        if size is None:
            self.refresh()
            return
        if abs(size - layer_ops.text_format(self.layer()).size()) < 1e-9:
            return
        self.write(lambda layer: layer_ops.set_font_size(layer, size))

    def read(self, layer):
        self.editor.setEditText(format_size(layer_ops.text_format(layer).size()))


class FontStyleControl(LabelControl):
    editor_kind = "style"

    def create_editor(self):
        w = QComboBox(self)
        w.activated.connect(lambda _i: self.write(
            lambda layer: layer_ops.set_font_style(layer, w.currentText())))
        return w

    def read(self, layer):
        fmt = layer_ops.text_format(layer)
        family = fmt.font().family()
        styles = QFontDatabase().styles(family) or ["Regular"]
        current = fmt.namedStyle() or QFontDatabase().styleString(fmt.font())
        self.editor.clear()
        self.editor.addItems(styles)
        index = self.editor.findText(current)
        self.editor.setCurrentIndex(index if index >= 0 else 0)


class FontColorControl(LabelControl):
    editor_kind = "color"

    def create_editor(self):
        w = QgsColorButton(self)
        w.setAllowOpacity(True)
        w.setShowNoColor(False)
        w.setColorDialogTitle(self.command.label)
        w.colorChanged.connect(
            lambda color: self.write(lambda layer: layer_ops.set_font_color(layer, color)))
        return w

    def read(self, layer):
        self.editor.setColor(layer_ops.text_format(layer).color())


# -- Lückenfüller --------------------------------------------------------------

class LabelClassControl(LabelControl):
    """Beschriftungsklasse (Regel) des aktiven Layers wählen.

    Die Auswahl gilt für Filter, „Klasse beschriften“, Feld und Ausdruck
    (``builtin_commands.LabelClassState``).
    """

    editor_kind = "class"

    def __init__(self, env, command, ctx, parent=None, size="medium"):
        self.state = builtin_commands.label_class_state(env)
        LabelControl.__init__(self, env, command, ctx, parent, size)
        ctx.hub.connect(self.state, "changed", self.refresh)

    def create_editor(self):
        w = QComboBox(self)
        w.activated.connect(self._chosen)
        return w

    def read(self, layer):
        self.editor.clear()
        selected = self.state.selected(layer)
        for key, name, _active in layer_ops.label_classes(layer):
            self.editor.addItem(name, key)
            if key == selected:
                self.editor.setCurrentIndex(self.editor.count() - 1)
        if not self.editor.count():
            self.editor.addItem(tr("(no labels)"), None)

    def _chosen(self, index):
        key = self.editor.itemData(index)
        layer = self.layer()
        if key is not None and not self._reading and self.suitable(layer):
            self.state.select(layer, key)


class LabelClassActiveControl(LabelControl):
    """Gewählte Beschriftungsklasse an oder aus (einfache Beschriftung: Beschriftung an/aus)."""

    show_label = False

    def __init__(self, env, command, ctx, parent=None, size="medium"):
        self.state = builtin_commands.label_class_state(env)
        LabelControl.__init__(self, env, command, ctx, parent, size)
        ctx.hub.connect(self.state, "changed", self.refresh)

    def create_editor(self):
        w = QCheckBox(self.command.label, self)
        w.toggled.connect(self._toggled)
        return w

    def read(self, layer):
        key = self.state.selected(layer)
        self.editor.setChecked(key is not None and layer_ops.label_class_active(layer, key))

    def _toggled(self, on):
        self.write(lambda layer: layer_ops.set_label_class_active(
            layer, self.state.selected(layer), on))


class LabelFieldControl(LabelControl):
    """Feld oder Ausdruck der gewählten Beschriftungsklasse (QGIS-Feldauswahl mit Ausdruck)."""

    editor_kind = "field"

    def __init__(self, env, command, ctx, parent=None, size="medium"):
        self.state = builtin_commands.label_class_state(env)
        LabelControl.__init__(self, env, command, ctx, parent, size)
        ctx.hub.connect(self.state, "changed", self.refresh)

    def create_editor(self):
        w = QgsFieldExpressionWidget(self)
        w.fieldChanged[str, bool].connect(self._changed)
        return w

    def read(self, layer):
        self.editor.setLayer(layer)
        key = self.state.selected(layer)
        settings = layer_ops.label_class_settings(layer, key) if key is not None else None
        self.editor.setExpression(layer_ops.label_expression(settings))

    def _changed(self, _name, valid):
        if not valid:
            return
        field, is_expression, _valid = self.editor.currentField()
        if not field:
            return

        def change(layer):
            layer_ops.set_label_field(layer, self.state.selected(layer), field, is_expression)
            if not layer_ops.labels_enabled(layer):
                layer_ops.set_labels_enabled(layer, True)
        self.write(change)


class CanvasControl(LayerControl):
    """Steuerelement für eine Eigenschaft der Karte statt des aktiven Layers."""

    editor_kind = "number"
    canvas_signal = None

    def __init__(self, env, command, ctx, parent=None, size="medium"):
        self.canvas = env.iface.mapCanvas()
        LayerControl.__init__(self, env, command, ctx, parent, size)
        ctx.hub.connect(self.canvas, self.canvas_signal, self._on_canvas)

    def _on_canvas(self, *_args):
        self.refresh()

    def suitable(self, layer):
        return True

    def write_canvas(self, change):
        if not self._reading:
            self._ctx.resolver.call(self.command, change)


class MapRotationControl(CanvasControl):
    canvas_signal = "rotationChanged"

    def create_editor(self):
        w = QgsDoubleSpinBox(self)
        w.setRange(-180.0, 180.0)
        w.setWrapping(True)
        w.setDecimals(1)
        w.setSuffix(" °")
        w.setClearValue(0.0)
        w.valueChanged.connect(lambda value: self.write_canvas(lambda: self._rotate(value)))
        return w

    def _rotate(self, value):
        self.canvas.setRotation(value)
        self.canvas.refresh()

    def read(self, _layer):
        rotation = self.canvas.rotation()
        self.editor.setValue(rotation - 360.0 if rotation > 180.0 else rotation)


class MagnifierControl(CanvasControl):
    """Lupe wie in der QGIS-Statusleiste: 10 % bis 1000 %."""

    canvas_signal = "magnificationChanged"

    def create_editor(self):
        w = QgsDoubleSpinBox(self)
        w.setRange(10.0, 1000.0)
        w.setSingleStep(10.0)
        w.setDecimals(0)
        w.setSuffix(" %")
        w.setClearValue(100.0)
        w.valueChanged.connect(lambda value: self.write_canvas(
            lambda: self.canvas.setMagnificationFactor(value / 100.0)))
        return w

    def read(self, _layer):
        self.editor.setValue(self.canvas.magnificationFactor() * 100.0)


class RasterEnhanceControl(LayerControl):
    """Helligkeit, Kontrast oder Gamma des aktiven Rasterlayers."""

    editor_kind = "number"
    SETTERS = {"brightness": raster_ops.set_brightness, "contrast": raster_ops.set_contrast,
               "gamma": raster_ops.set_gamma}

    def __init__(self, env, command, ctx, parent=None, size="medium", which="brightness"):
        self.which = which
        LayerControl.__init__(self, env, command, ctx, parent, size)

    def suitable(self, layer):
        return raster_ops.is_raster(layer)

    def create_editor(self):
        if self.which == "gamma":
            w = QgsDoubleSpinBox(self)
            w.setRange(*raster_ops.GAMMA_RANGE)
            w.setDecimals(2)
            w.setSingleStep(0.1)
            w.setClearValue(1.0)
        else:
            w = QgsSpinBox(self)
            bounds = (raster_ops.BRIGHTNESS_RANGE if self.which == "brightness"
                      else raster_ops.CONTRAST_RANGE)
            w.setRange(*bounds)
            w.setClearValue(0)
        setter = self.SETTERS[self.which]
        w.valueChanged.connect(lambda value: self.write(lambda layer: setter(layer, value)))
        return w

    def read(self, layer):
        brightness, contrast, gamma = raster_ops.enhancement(layer)
        self.editor.setValue({"brightness": brightness, "contrast": contrast,
                              "gamma": gamma}[self.which])


class FlickerIntervalControl(LayerControl):
    """Takt des Flimmerns in Millisekunden (Einstellung, gilt für alle Layer)."""

    editor_kind = "interval"

    def __init__(self, env, command, ctx, parent=None, size="medium"):
        self.comparison = builtin_commands.comparison(env)
        LayerControl.__init__(self, env, command, ctx, parent, size)

    def create_editor(self):
        w = QgsSpinBox(self)
        w.setRange(*compare.FLICKER_RANGE)
        w.setSingleStep(100)
        w.setSuffix(" ms")
        w.setClearValue(compare.FLICKER_DEFAULT)
        w.valueChanged.connect(self._changed)
        return w

    def suitable(self, layer):
        return True

    def read(self, _layer):
        self.editor.setValue(self.comparison.interval())

    def _changed(self, value):
        if not self._reading:
            self._ctx.resolver.call(self.command, lambda: self.comparison.set_interval(value))


class PointCloudControl(LayerControl):
    """Punktgröße oder maximaler Bildschirmfehler der aktiven Punktwolke."""

    editor_kind = "number"

    def __init__(self, env, command, ctx, parent=None, size="medium", which="size"):
        self.which = which
        LayerControl.__init__(self, env, command, ctx, parent, size)

    def suitable(self, layer):
        return kontext_ops.is_point_cloud(layer) and layer.renderer() is not None

    def create_editor(self):
        w = QgsDoubleSpinBox(self)
        if self.which == "size":
            w.setRange(*kontext_ops.POINT_SIZE_RANGE)
            setter = kontext_ops.set_point_size
        else:
            w.setRange(*kontext_ops.SCREEN_ERROR_RANGE)
            setter = kontext_ops.set_max_screen_error
        w.setDecimals(1)
        w.setSingleStep(0.5)
        w.valueChanged.connect(lambda value: self.write(lambda layer: setter(layer, value)))
        return w

    def read(self, layer):
        if self.which == "size":
            self.editor.setValue(kontext_ops.point_size(layer))
        else:
            self.editor.setValue(kontext_ops.max_screen_error(layer))


class MeshGroupControl(LayerControl):
    """Dargestellte Datensatzgruppe des aktiven Netzes (Skalar oder Vektor)."""

    editor_kind = "dataset"

    def __init__(self, env, command, ctx, parent=None, size="medium", vector=False):
        self.vector = vector
        LayerControl.__init__(self, env, command, ctx, parent, size)

    def suitable(self, layer):
        return kontext_ops.is_mesh(layer)

    def create_editor(self):
        w = QComboBox(self)
        w.activated.connect(self._chosen)
        return w

    def read(self, layer):
        self.editor.clear()
        self.editor.addItem(tr("(none)"), -1)
        active = kontext_ops.mesh_active_group(layer, self.vector)
        for index, name in kontext_ops.mesh_groups(layer, self.vector):
            self.editor.addItem(name, index)
            if index == active:
                self.editor.setCurrentIndex(self.editor.count() - 1)

    def _chosen(self, row):
        index = self.editor.itemData(row)
        self.write(lambda layer: kontext_ops.set_mesh_active_group(layer, index, self.vector))


def _factory(cls, **kwargs):
    def create(env, command, ctx, parent, size="medium"):
        return cls(env, command, ctx, parent, size, **kwargs)
    return create


CONTROLS = {
    "ribbon.layer_massstab_max": _factory(ScaleControl, which="max"),
    "ribbon.layer_massstab_min": _factory(ScaleControl, which="min"),
    "ribbon.beschriftung_massstab_max": _factory(ScaleControl, which="max", labels=True),
    "ribbon.beschriftung_massstab_min": _factory(ScaleControl, which="min", labels=True),
    "ribbon.layer_deckkraft": _factory(OpacityControl),
    "ribbon.layer_mischmodus": _factory(BlendModeControl),
    "ribbon.objekt_mischmodus": _factory(FeatureBlendModeControl),
    "ribbon.flimmer_intervall": _factory(FlickerIntervalControl),
    "ribbon.punktwolke_punktgroesse": _factory(PointCloudControl, which="size"),
    "ribbon.punktwolke_fehler": _factory(PointCloudControl, which="error"),
    "ribbon.netz_skalar": _factory(MeshGroupControl, vector=False),
    "ribbon.netz_vektor": _factory(MeshGroupControl, vector=True),
    "ribbon.beschriftung_schrift": _factory(FontControl),
    "ribbon.beschriftung_groesse": _factory(FontSizeControl),
    "ribbon.beschriftung_schriftschnitt": _factory(FontStyleControl),
    "ribbon.beschriftung_farbe": _factory(FontColorControl),
    "ribbon.beschriftung_regel": _factory(LabelClassControl),
    "ribbon.beschriftung_regel_aktiv": _factory(LabelClassActiveControl),
    "ribbon.beschriftung_feld": _factory(LabelFieldControl),
    "ribbon.kartendrehung": _factory(MapRotationControl),
    "ribbon.lupe": _factory(MagnifierControl),
    "ribbon.raster_helligkeit": _factory(RasterEnhanceControl, which="brightness"),
    "ribbon.raster_kontrast": _factory(RasterEnhanceControl, which="contrast"),
    "ribbon.raster_gamma": _factory(RasterEnhanceControl, which="gamma"),
}


def control_widget(command, size, ctx, parent):
    """Widget eines Steuerelements oder None, wenn es nicht registriert ist."""
    cid = command.source.get("id") if command.source.type == "custom" else None
    if not cid or custom_commands.kind_of(cid) != "control":
        return None
    return custom_commands.get(cid)(ctx.env, command, ctx, parent, size)


def register_all():
    for cid, factory in CONTROLS.items():
        custom_commands.register(cid, factory, "control")


def unregister_all():
    for cid in CONTROLS:
        custom_commands.unregister(cid)
