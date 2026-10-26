"""Eingebaute eigene Befehle ohne Widget: Buttons mit Zustand und Galerie-Inhalte.

Die Steuerelemente mit Widget (Regler, Comboboxen, Farbwahl) stehen in
``ui/controls/custom.py``. Beide Module registrieren ihre Befehle beim Aufbau
des Ribbons (``register_all``) und entfernen sie beim Entladen wieder.

Buttons mit Zustand sind ``StateAction``: eine eigene QAction, die ihren
Zustand (aktiv, abgehakt) aus dem aktiven Layer liest und vom Ribbon wie eine
QGIS-Aktion gespiegelt wird.
"""

from qgis.core import (Qgis, QgsExpressionContext, QgsExpressionContextUtils, QgsSettings, QgsStyle,
                       QgsTextFormat)
from qgis.gui import QgsExpressionBuilderDialog
from qgis.PyQt.QtCore import QObject, QSize, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (QAction, QActionGroup, QApplication, QDialog, QDockWidget, QInputDialog,
                                 QMessageBox)

from . import compare, custom_commands, kontext_ops, layer_ops, raster_ops
from .custom_commands import GalleryEntry
from .map_tools import SelectByLineTool
from ..core.i18n import tr

LOG_TAG = "QGIS Ribbon"
PREVIEW_SIZE = QSize(96, 32)


class StateAction(QAction):
    """QAction, deren Zustand aus dem aktiven Layer (oder einer Einstellung) gelesen wird.

    ``read(layer) -> (enabled, checked)``; ``run(layer, checked)`` beim Auslösen.
    """

    def __init__(self, env, text, read, run, checkable=True, parent=None):
        QAction.__init__(self, text, parent)
        self._env = env
        self._read = read
        self._run = run
        self.setCheckable(checkable)
        self.triggered.connect(self._on_triggered)
        if env.layers is not None:
            env.layers.subscribe(self._on_layer)
        self.refresh()

    def layer(self):
        if self._env.layers is not None:
            return self._env.layers.active_layer()
        return self._env.iface.activeLayer()

    def refresh(self):
        enabled, checked = self._read(self.layer())
        self.setEnabled(bool(enabled))
        if self.isCheckable():
            self.setChecked(bool(checked))

    def _on_layer(self, _layer):
        self.refresh()

    def _on_triggered(self, checked=False):
        self._run(self.layer(), checked)
        self.refresh()

    def close_binding(self):
        if self._env.layers is not None:
            self._env.layers.unsubscribe(self._on_layer)


def _args(command):
    return list(command.source.get("args") or [])


def _push(env, text, level=Qgis.Info):
    env.iface.messageBar().pushMessage(LOG_TAG, text, level=level, duration=4)


def _vector_or_warn(env, layer):
    if layer_ops.is_vector(layer):
        return True
    _push(env, tr("Please select a vector layer as the active layer."), Qgis.Warning)
    return False


# -- Buttons ----------------------------------------------------------------

def abfragemodus(env, command):
    """Abfragemodus setzen und das Abfragewerkzeug wählen. Die Modi bilden eine Gruppe."""
    args = _args(command)
    mode = args[0] if args else "ActiveLayer"
    if mode not in layer_ops.IDENTIFY_MODES:
        raise ValueError(tr("Unknown identify mode: %s") % mode)
    group = env.shared("abfragemodus", lambda: QActionGroup(None))
    group.setExclusive(True)

    def read(_layer):
        return True, layer_ops.identify_mode(env.settings) == mode

    def run(_layer, _checked):
        layer_ops.set_identify_mode(mode, env.settings)
        identify = env.iface.mainWindow().findChild(QAction, "mActionIdentify")
        if identify is not None:
            identify.trigger()
        for act in group.actions():
            act.refresh()

    act = env.keep(StateAction(env, command.label, read, run))
    group.addAction(act)
    return act


def locator_fokus(env, command):
    """Locator-Leiste fokussieren, optional mit Präfix (z. B. ``go `` für Gehe zu)."""
    args = _args(command)
    prefix = args[0] if args else ""

    def run():
        env.iface.locatorSearch(prefix)

    return run


def _group(env):
    """Gewählte Gruppe der Layerliste (kein Layer aktiv) oder None."""
    return env.layers.group() if env.layers is not None else None


def layer_massstab_schalten(env, command):
    """Sichtbarkeitsbereich an/aus; bei gewählter Gruppe für die Gruppenebene."""
    def read(layer):
        if layer is None:
            group = _group(env)
            target = kontext_ops.group_layer(group)
            return group is not None, target is not None and target.hasScaleBasedVisibility()
        return True, layer.hasScaleBasedVisibility()

    def run(layer, checked):
        if layer is None and _group(env) is not None:
            layer = env.layers.ensure_group_layer()
        if layer is not None:
            layer_ops.set_scale_range_enabled(layer, checked)

    return env.keep(StateAction(env, command.label, read, run))


def beschriftung_schalten(env, command):
    def read(layer):
        return layer_ops.is_vector(layer), layer_ops.labels_enabled(layer)

    def run(layer, checked):
        if _vector_or_warn(env, layer):
            layer_ops.set_labels_enabled(layer, checked)

    return env.keep(StateAction(env, command.label, read, run))


def _on_active_vector(env, change):
    def run():
        layer = env.iface.activeLayer()
        if _vector_or_warn(env, layer):
            change(layer)

    return run


def beschriftung_massstab_aus(env, command):
    return _on_active_vector(env, layer_ops.clear_label_scales)


def beschriftung_groesser(env, command):
    return _on_active_vector(env, lambda layer: layer_ops.change_font_size(layer, +1))


def beschriftung_kleiner(env, command):
    return _on_active_vector(env, lambda layer: layer_ops.change_font_size(layer, -1))


def processing_optionen(env, command):
    """Optionen auf der Processing-Seite öffnen.

    Die Seite stammt aus einer Factory des Processing-Plugins und ist nur über
    ihren übersetzten Titel erreichbar (z. B. „Verarbeitung“); der Titel wird
    deshalb aus der Factory gelesen.
    """
    def run():
        from qgis import utils
        plugin = utils.plugins.get("processing")
        factory = getattr(plugin, "options_factory", None)
        page = factory.title() if factory is not None else ""
        env.iface.showOptionsDialog(env.iface.mainWindow(), page)

    return run


def grundkarte(env, command):
    """Mitgelieferte Grundkarte einfügen. ``args``: [URL, zmin, zmax, Namensnennung]."""
    args = _args(command) + [None] * 4
    url, zmin, zmax, attribution = args[:4]
    if not url:
        raise ValueError(tr("Basemap without URL: %s") % command.id)

    def run():
        layer = layer_ops.add_basemap(command.label, url, zmin or 0, zmax or 19, attribution)
        if layer is None:
            _push(env, tr("Basemap “%s” could not be loaded.") % command.label, Qgis.Warning)

    return run


# -- Galerie-Inhalte ----------------------------------------------------------

def lesezeichen_galerie(env, command):
    def entries():
        canvas = env.iface.mapCanvas()
        out = []
        for section, bookmark in layer_ops.bookmarks():
            out.append(GalleryEntry(
                bookmark.name(), (lambda b=bookmark: layer_ops.zoom_to_bookmark(canvas, b)),
                section=section))
        return out

    return entries


def grundkarten_galerie(env, command):
    """XYZ-Verbindungen des QGIS-Browsers (die mitgelieferten stehen fest in der Galerie)."""
    def entries():
        out = []
        for name, url, zmin, zmax in layer_ops.xyz_connections():
            def add(name=name, url=url, zmin=zmin, zmax=zmax):
                if layer_ops.add_basemap(name, url, zmin, zmax) is None:
                    _push(env, tr("Basemap “%s” could not be loaded.") % name, Qgis.Warning)
            out.append(GalleryEntry(name, add, tooltip=url, section=tr("XYZ connections in QGIS")))
        return out

    return entries


def textformat_galerie(env, command):
    def entries():
        style = QgsStyle.defaultStyle()
        layer = env.iface.activeLayer()
        out = []
        for name in style.textFormatNames():
            fmt = style.textFormat(name)

            def apply(fmt=fmt):
                target = env.iface.activeLayer()
                if not _vector_or_warn(env, target):
                    return
                had_labels = target.labeling() is not None
                layer_ops.set_text_format(target, fmt)
                if not had_labels:
                    layer_ops.set_labels_enabled(target, True)

            icon = QIcon(QgsTextFormat.textFormatPreviewPixmap(fmt, PREVIEW_SIZE, "Abc"))
            out.append(GalleryEntry(name, apply, icon=icon))
        if not layer_ops.is_vector(layer):
            for e in out:
                e.callback = None
        return out

    return entries


def _show_styling_dock(env):
    dock = env.iface.mainWindow().findChild(QDockWidget, "LayerStyling")
    if dock is None:
        return
    if hasattr(dock, "setUserVisible"):
        dock.setUserVisible(True)
    else:
        dock.show()
    dock.raise_()


def renderer_galerie(env, command):
    def entries():
        layer = env.iface.activeLayer()
        current = layer_ops.renderer_type(layer)
        out = []
        for name, label in layer_ops.renderer_choices(layer):
            def apply(name=name):
                target = env.iface.activeLayer()
                if not _vector_or_warn(env, target):
                    return
                layer_ops.set_renderer(target, name)
                _show_styling_dock(env)
            out.append(GalleryEntry(label, apply, icon=layer_ops.renderer_icon(name),
                                    checked=(name == current)))
        return out

    return entries


# -- Lückenfüller --------------------------------------------------------

class LabelClassState(QObject):
    """Gewählte Beschriftungsklasse je Layer (gemeinsam für Klasse, Filter, Feld, Ausdruck).

    Gilt nur in dieser Sitzung; ohne Auswahl die erste Klasse des Layers.
    """

    changed = pyqtSignal()

    def __init__(self):
        QObject.__init__(self)
        self._keys = {}

    def selected(self, layer):
        keys = [k for k, _name, _active in layer_ops.label_classes(layer)]
        if not keys:
            return None
        key = self._keys.get(layer.id())
        return key if key in keys else keys[0]

    def select(self, layer, key):
        self._keys[layer.id()] = key
        self.changed.emit()


def label_class_state(env):
    return env.shared("beschriftungsklasse", LabelClassState)


GALLERY_COMPACT_KEY = "qgis_ribbon/galerie_kompakt"


class GallerySize(QObject):
    """Größe der Galerien im Ribbon: groß (Icon mit Text) oder kompakt (nur Icons).

    Gespeichert pro Nutzer in den QGIS-Einstellungen; Galerien im Ribbon
    melden sich an ``changed`` an.
    """

    changed = pyqtSignal(bool)

    def __init__(self, settings=None):
        QObject.__init__(self)
        self._settings = settings

    def _store(self):
        return self._settings if self._settings is not None else QgsSettings()

    def compact(self):
        return str(self._store().value(GALLERY_COMPACT_KEY, False)).lower() in ("true", "1")

    def set_compact(self, on):
        if bool(on) == self.compact():
            return
        self._store().setValue(GALLERY_COMPACT_KEY, bool(on))
        self.changed.emit(bool(on))


def gallery_size(env):
    return env.shared("galerie_groesse", lambda: GallerySize(env.settings))


def galerie_groesse(env, command):
    size = gallery_size(env)

    def read(_layer):
        return True, size.compact()

    def run(_layer, checked):
        size.set_compact(checked)

    return env.keep(StateAction(env, command.label, read, run))


def layerpfad_kopieren(env, command):
    def run():
        layer = env.iface.activeLayer()
        if layer is None:
            _push(env, tr("Please select an active layer."), Qgis.Warning)
            return
        path = layer_ops.source_path(layer)
        QApplication.clipboard().setText(path)
        _push(env, tr("Path copied: %s") % path)

    return run


def _expression_dialog(env, layer, expression, title):
    """Ausdruckseditor von QGIS; gibt den Ausdruck zurück oder None bei Abbruch."""
    context = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    dlg = QgsExpressionBuilderDialog(layer, expression or "", env.iface.mainWindow(), "labeling",
                                     context)
    dlg.setWindowTitle(title)
    try:
        if dlg.exec_() == QDialog.Accepted:
            return dlg.expressionText()
        return None
    finally:
        dlg.deleteLater()


def beschriftung_ausdruck(env, command):
    def run():
        layer = env.iface.activeLayer()
        if not _vector_or_warn(env, layer):
            return
        state = label_class_state(env)
        key = state.selected(layer)
        settings = layer_ops.label_class_settings(layer, key) if key is not None else None
        expression = _expression_dialog(env, layer, layer_ops.label_expression(settings),
                                        tr("Label expression"))
        if expression is None:
            return
        layer_ops.set_label_field(layer, key, expression, True)
        if not layer_ops.labels_enabled(layer):
            layer_ops.set_labels_enabled(layer, True)
        state.changed.emit()

    return run


def beschriftung_regel_neu(env, command):
    """Neue Beschriftungsklasse nach dem Muster der gewählten; danach gewählt."""
    def run():
        layer = env.iface.activeLayer()
        if not _vector_or_warn(env, layer):
            return
        state = label_class_state(env)
        number = len(layer_ops.label_classes(layer)) + 1
        name, ok = QInputDialog.getText(env.iface.mainWindow(), tr("New Label Class"),
                                        tr("Name of the new label class:"), text=tr("Class %d") % number)
        name = name.strip()
        if not ok or not name:
            return
        key = layer_ops.add_label_class(layer, state.selected(layer), name)
        if key is not None:
            state.select(layer, key)
            _push(env, tr("Label class “%s” added. Use Filter to choose which features it labels.") % name)

    return run


def beschriftung_regel_loeschen(env, command):
    """Gewählte Beschriftungsklasse löschen (nach Rückfrage); die letzte bleibt."""
    def read(layer):
        return len(layer_ops.label_classes(layer)) > 1, False

    def run(layer, _checked):
        if not _vector_or_warn(env, layer):
            return
        state = label_class_state(env)
        key = state.selected(layer)
        names = {k: n for k, n, _active in layer_ops.label_classes(layer)}
        if key not in names or len(names) < 2:
            _push(env, tr("A layer keeps at least one label class."), Qgis.Warning)
            return
        answer = QMessageBox.question(env.iface.mainWindow(), tr("Delete Label Class"),
                                      tr("Delete the label class “%s”?") % names[key])
        if answer != QMessageBox.Yes:
            return
        new_key = layer_ops.remove_label_class(layer, key)
        if new_key is not None:
            state.select(layer, new_key)

    return env.keep(StateAction(env, command.label, read, run, checkable=False))


def layer_aenderungen_verwerfen(env, command):
    """Ungespeicherte Änderungen nur des aktiven Layers verwerfen (nach Rückfrage).

    QGIS hat dafür keine Aktion: „Zurücksetzen“ wirkt auf die in der
    Layerliste gewählten Layer, die Werkzeugleiste kennt nur „Alle“.
    """
    def read(layer):
        return layer_ops.has_unsaved_edits(layer), False

    def run(layer, _checked):
        if not layer_ops.has_unsaved_edits(layer):
            return
        answer = QMessageBox.question(env.iface.mainWindow(), tr("Discard Edits"),
                                      tr("Discard the unsaved edits of layer “%s”?") % layer.name())
        if answer == QMessageBox.Yes:
            layer_ops.discard_edits(layer)

    return env.keep(StateAction(env, command.label, read, run, checkable=False))


def beschriftung_regel_filter(env, command):
    def run():
        layer = env.iface.activeLayer()
        if not _vector_or_warn(env, layer):
            return
        state = label_class_state(env)
        key = state.selected(layer)
        if key is None:
            _push(env, tr("The active layer has no labels."), Qgis.Warning)
            return
        expression = _expression_dialog(env, layer, layer_ops.label_class_filter(layer, key),
                                        tr("Label class filter"))
        if expression is None:
            return
        new_key = layer_ops.set_label_class_filter(layer, key, expression)
        if new_key is not None:
            state.select(layer, new_key)

    return run


class ToolAction(StateAction):
    """Button eines eigenen Kartenwerkzeugs: abgehakt, solange das Werkzeug aktiv ist."""

    def __init__(self, env, text, tool, suitable):
        self.tool = tool
        self._canvas = env.iface.mapCanvas()
        self._suitable = suitable
        StateAction.__init__(self, env, text, self._read_tool, self._run_tool)
        if env.hub is not None:
            env.hub.connect(self._canvas, "mapToolSet", self._on_tool_set)

    def _read_tool(self, layer):
        return self._suitable(layer), self._canvas.mapTool() is self.tool

    def _run_tool(self, _layer, checked):
        if checked:
            self._canvas.setMapTool(self.tool)
        elif self._canvas.mapTool() is self.tool:
            self._canvas.unsetMapTool(self.tool)

    def _on_tool_set(self, *_args):
        self.refresh()

    def close_binding(self):
        StateAction.close_binding(self)
        if self._canvas.mapTool() is self.tool:
            self._canvas.unsetMapTool(self.tool)
        self.tool.close()


def auswahl_linie(env, command):
    canvas = env.iface.mapCanvas()
    tool = env.keep(SelectByLineTool(canvas, env.iface.activeLayer))
    return env.keep(ToolAction(env, command.label, tool, layer_ops.is_vector))


def abfragbare_layer(env, command):
    """Abfragbare Layer (Layer-Eigenschaft) und Abfragemodus „alle abfragbaren Layer“."""
    def identify_all():
        layer_ops.set_identify_mode("TopDownAll", env.settings)
        identify = env.iface.mainWindow().findChild(QAction, "mActionIdentify")
        if identify is not None:
            identify.trigger()
        # Buttons der Abfragemodi zeigen den neuen Modus
        for act in env.shared("abfragemodus", lambda: QActionGroup(None)).actions():
            act.refresh()

    def entries():
        out = [GalleryEntry(
            tr("Identify all identifiable layers"), identify_all,
            checked=layer_ops.identify_mode(env.settings) == "TopDownAll",
            tooltip=tr("Select the identify tool; all visible, identifiable layers are queried."),
            section=tr("Identify mode"))]
        for layer, on in layer_ops.identifiable_layers():
            out.append(GalleryEntry(
                layer.name(), (lambda lyr=layer, o=on: layer_ops.set_identifiable(lyr, not o)),
                checked=on, section=tr("Identifiable Layers")))
        return out

    return entries


def platzierung_galerie(env, command):
    def entries():
        layer = env.iface.activeLayer()
        current = layer_ops.label_placement(layer)
        out = []
        for name, label in layer_ops.placement_choices(layer):
            def apply(name=name):
                target = env.iface.activeLayer()
                if not _vector_or_warn(env, target):
                    return
                had_labels = target.labeling() is not None
                layer_ops.set_label_placement(target, name)
                if not had_labels:
                    layer_ops.set_labels_enabled(target, True)
            out.append(GalleryEntry(label, apply, checked=(name == current)))
        return out

    return entries


def _raster_or_warn(env, layer):
    if raster_ops.is_raster(layer):
        return True
    _push(env, tr("Please select a raster layer as the active layer."), Qgis.Warning)
    return False


def raster_renderer_galerie(env, command):
    def entries():
        layer = env.iface.activeLayer()
        current = raster_ops.renderer_type(layer)
        out = []
        for name, label in raster_ops.renderer_choices(layer):
            def apply(name=name):
                target = env.iface.activeLayer()
                if _raster_or_warn(env, target):
                    raster_ops.set_renderer(target, name)
                    _show_styling_dock(env)
            out.append(GalleryEntry(label, apply, checked=(name == current)))
        return out

    return entries


def raster_resampling(env, command):
    def entries():
        layer = env.iface.activeLayer()
        if not raster_ops.is_raster(layer):
            return []
        current = raster_ops.resampling(layer)
        out = []
        for name, label in raster_ops.RESAMPLING:
            def apply(name=name):
                target = env.iface.activeLayer()
                if _raster_or_warn(env, target):
                    raster_ops.set_resampling(target, name)
            out.append(GalleryEntry(label, apply, checked=(name == current)))
        return out

    return entries


def raster_kanaele(env, command):
    def entries():
        layer = env.iface.activeLayer()
        current = raster_ops.current_bands(layer)
        out = []
        for label, bands, section in raster_ops.band_combinations(layer):
            def apply(bands=bands):
                target = env.iface.activeLayer()
                if _raster_or_warn(env, target):
                    raster_ops.set_bands(target, bands)
            tip = tr("Red: %s, Green: %s, Blue: %s") % tuple(raster_ops.band_name(layer, b) for b in bands)
            out.append(GalleryEntry(label, apply, checked=(bands == current), tooltip=tip,
                                    section=section))
        return out

    return entries


# -- Kontext-Tabs ----------------------------------------------------------

def _compare_targets(env):
    """Layer, die Wischen und Flimmern ausblenden: aktiver Layer oder Layer der Gruppe."""
    layer = env.layers.active_layer() if env.layers is not None else env.iface.activeLayer()
    if layer is not None:
        return [layer]
    group = _group(env)
    if group is None:
        return []
    out = kontext_ops.group_layers(group)
    if group.groupLayer() is not None:
        out.append(group.groupLayer())
    return out


def comparison(env):
    """Gemeinsamer Zustand von Wischen, Flimmern und Takt."""
    return env.shared("vergleich", lambda: compare.Comparison(
        env.iface.mapCanvas(), lambda: _compare_targets(env), env.settings, env.layers))


def _comparable(env):
    return lambda layer: layer is not None or _group(env) is not None


def wischen(env, command):
    state = comparison(env)
    tool = env.keep(compare.SwipeTool(env.iface.mapCanvas(), state))
    return env.keep(ToolAction(env, command.label, tool, _comparable(env)))


def flimmern(env, command):
    state = comparison(env)
    comparable = _comparable(env)

    def read(layer):
        return comparable(layer), state.flickering

    def run(_layer, checked):
        if checked:
            state.start_flicker()
        else:
            state.stop_flicker()

    act = env.keep(StateAction(env, command.label, read, run))
    if env.hub is not None:
        env.hub.connect(state, "changed", act.refresh)
    return act


def aggregation_galerie(env, command):
    saved = env.shared("aggregation_vorher", dict)

    def entries():
        layer = env.iface.activeLayer()
        usable = kontext_ops.can_aggregate(layer)
        current = kontext_ops.aggregation(layer)
        out = []
        for name, label in kontext_ops.AGGREGATIONS:
            def apply(name=name):
                target = env.iface.activeLayer()
                if not kontext_ops.can_aggregate(target):
                    _push(env, tr("Aggregation is only available for point layers."), Qgis.Warning)
                    return
                kontext_ops.set_aggregation(target, name, saved)
                if name != "none":
                    _show_styling_dock(env)
            out.append(GalleryEntry(label, apply if usable else None,
                                    icon=layer_ops.renderer_icon(name) if name != "none" else None,
                                    checked=(name == current)))
        return out

    return entries


def punktwolke_renderer_galerie(env, command):
    def entries():
        layer = env.iface.activeLayer()
        current = kontext_ops.point_cloud_renderer_type(layer)
        out = []
        for name, label in kontext_ops.point_cloud_choices(layer):
            def apply(name=name):
                target = env.iface.activeLayer()
                if kontext_ops.is_point_cloud(target):
                    kontext_ops.set_point_cloud_renderer(target, name)
                    _show_styling_dock(env)
            out.append(GalleryEntry(label, apply, checked=(name == current)))
        return out

    return entries


def vektorkacheln_beschriftung(env, command):
    def read(layer):
        return kontext_ops.vector_tile_labels(layer)

    def run(layer, checked):
        if kontext_ops.is_vector_tile(layer):
            kontext_ops.set_vector_tile_labels(layer, checked)

    return env.keep(StateAction(env, command.label, read, run))


def netz_gitter(env, command):
    def read(layer):
        mesh = kontext_ops.is_mesh(layer)
        return mesh, mesh and kontext_ops.mesh_frame(layer)

    def run(layer, checked):
        if kontext_ops.is_mesh(layer):
            kontext_ops.set_mesh_frame(layer, checked)

    return env.keep(StateAction(env, command.label, read, run))


def gruppe_als_ebene(env, command):
    """Gruppe als Gruppe darstellen (Gruppenebene mit eigener Deckkraft, Mischmodus ...)."""
    def read(_layer):
        group = _group(env)
        return group is not None, group is not None and group.groupLayer() is not None

    def run(_layer, checked):
        group = _group(env)
        if group is None:
            return
        if checked:
            env.layers.ensure_group_layer()
        else:
            kontext_ops.remove_group_layer(group)
            env.layers.rewatch()

    return env.keep(StateAction(env, command.label, read, run))


def gruppe_exklusiv(env, command):
    """Gruppe exklusiv: Es ist immer nur ein Layer der Gruppe sichtbar."""
    def read(_layer):
        group = _group(env)
        return group is not None, group is not None and group.isMutuallyExclusive()

    def run(_layer, checked):
        group = _group(env)
        if group is not None:
            group.setIsMutuallyExclusive(bool(checked))

    return env.keep(StateAction(env, command.label, read, run))


def gruppe_zoomen(env, command):
    def read(_layer):
        return _group(env) is not None, False

    def run(_layer, _checked):
        group = _group(env)
        if group is None:
            return
        canvas = env.iface.mapCanvas()
        extent = kontext_ops.group_extent(group, canvas.mapSettings().destinationCrs())
        if extent.isNull():
            _push(env, tr("The group contains no layers with an extent."), Qgis.Warning)
            return
        canvas.zoomToFeatureExtent(extent)
        canvas.refresh()

    return env.keep(StateAction(env, command.label, read, run, checkable=False))


BUTTONS = {
    "ribbon.abfragemodus": abfragemodus,
    "ribbon.locator_fokus": locator_fokus,
    "ribbon.layer_massstab_schalten": layer_massstab_schalten,
    "ribbon.beschriftung_schalten": beschriftung_schalten,
    "ribbon.beschriftung_massstab_aus": beschriftung_massstab_aus,
    "ribbon.beschriftung_groesser": beschriftung_groesser,
    "ribbon.beschriftung_kleiner": beschriftung_kleiner,
    "ribbon.grundkarte": grundkarte,
    "ribbon.processing_optionen": processing_optionen,
    "ribbon.galerie_groesse": galerie_groesse,
    "ribbon.layerpfad_kopieren": layerpfad_kopieren,
    "ribbon.beschriftung_ausdruck": beschriftung_ausdruck,
    "ribbon.beschriftung_regel_filter": beschriftung_regel_filter,
    "ribbon.beschriftung_regel_neu": beschriftung_regel_neu,
    "ribbon.beschriftung_regel_loeschen": beschriftung_regel_loeschen,
    "ribbon.layer_aenderungen_verwerfen": layer_aenderungen_verwerfen,
    "ribbon.auswahl_linie": auswahl_linie,
    "ribbon.swipe": wischen,
    "ribbon.flimmern": flimmern,
    "ribbon.vektorkacheln_beschriftung": vektorkacheln_beschriftung,
    "ribbon.netz_gitter": netz_gitter,
    "ribbon.gruppe_als_ebene": gruppe_als_ebene,
    "ribbon.gruppe_exklusiv": gruppe_exklusiv,
    "ribbon.gruppe_zoomen": gruppe_zoomen,
}

GALLERIES = {
    "ribbon.lesezeichen_galerie": lesezeichen_galerie,
    "ribbon.grundkarten_galerie": grundkarten_galerie,
    "ribbon.textformat_galerie": textformat_galerie,
    "ribbon.renderer_galerie": renderer_galerie,
    "ribbon.abfragbare_layer": abfragbare_layer,
    "ribbon.platzierung_galerie": platzierung_galerie,
    "ribbon.raster_renderer_galerie": raster_renderer_galerie,
    "ribbon.raster_resampling": raster_resampling,
    "ribbon.raster_kanaele": raster_kanaele,
    "ribbon.aggregation_galerie": aggregation_galerie,
    "ribbon.punktwolke_renderer_galerie": punktwolke_renderer_galerie,
}


def register_all():
    for cid, factory in BUTTONS.items():
        custom_commands.register(cid, factory, "button")
    for cid, factory in GALLERIES.items():
        custom_commands.register(cid, factory, "gallery")


def unregister_all():
    for cid in list(BUTTONS) + list(GALLERIES):
        custom_commands.unregister(cid)
