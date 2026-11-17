"""Befehle für „Georeferenzieren in der Karte“ (Tab Bilddaten und Kontext-Tab Georeferenzieren).

Die Sitzung selbst steht in ``georef_session.py``. Buttons lesen ihren Zustand aus der laufenden
Sitzung und folgen ihr über das Signal ``changed`` der Verwaltung (verbunden über den Hub des
Ribbons, der beim Abbau getrennt wird).
"""

import os

from qgis.core import Qgis, QgsProviderRegistry
from qgis.PyQt.QtWidgets import QAction, QFileDialog

from ..core import georef
from ..core.i18n import tr
from . import custom_commands, georef_ops, georef_session
from .builtin_commands import StateAction, ToolAction

LOG_TAG = "QGIS Ribbon"
LAST_DIR_KEY = "qgis_ribbon/georef_ordner"


def _manager(env):
    return georef_session.install(env.iface)


def _session(env):
    session = _manager(env).session
    return session if session is not None and session.alive() else None


def _follow(env, act):
    if env.hub is not None:
        env.hub.connect(_manager(env), "changed", act.refresh)
    return act


def _push(env, text, level=Qgis.MessageLevel.Info):
    env.iface.messageBar().pushMessage(LOG_TAG, text, level=level, duration=6)


def _settings(env):
    if env.settings is not None:
        return env.settings
    from qgis.core import QgsSettings
    return QgsSettings()


def choose_image(env):
    """Bilddatei über die Dateiauswahl (Filter der Rasterformate von QGIS), sonst None."""
    settings = _settings(env)
    folder = settings.value(LAST_DIR_KEY, os.path.expanduser("~"))
    filters = QgsProviderRegistry.instance().fileRasterFilters()
    path, _filter = QFileDialog.getOpenFileName(env.iface.mainWindow(), tr("Georeference Image"), folder, filters)
    if path:
        settings.setValue(LAST_DIR_KEY, os.path.dirname(path))
    return path or None


def start(env, layer=None, path=None):
    """Sitzung beginnen: für den Rasterlayer ``layer``, eine Bilddatei ``path`` oder per Dateiauswahl."""
    if layer is not None and georef_session.is_work_layer(layer):
        return _session(env)
    if layer is not None:
        path = georef_session.source_path(layer)
        if path is None:
            _push(env, tr("Only raster layers from a file can be georeferenced in the map."),
                  Qgis.MessageLevel.Warning)
            return None
    elif path is None:
        path = choose_image(env)
        if path is None:
            return None
    try:
        return _manager(env).start(path, layer)
    except (ValueError, RuntimeError, OSError) as exc:
        _push(env, tr("Georeferencing cannot start: %s") % exc, Qgis.MessageLevel.Warning)
        return None


def _active_raster(env):
    layer = env.layers.active_layer() if env.layers is not None else env.iface.activeLayer()
    return layer if georef_session.source_path(layer) is not None else None


def georef_starten(env, command):
    act = env.keep(QAction(command.label, None))
    act.triggered.connect(lambda _checked=False: start(env, _active_raster(env)))
    return act


class SessionAction(StateAction):
    """Button, der nur während einer Sitzung bedienbar ist."""

    def __init__(self, env, text, run, enabled=None, checked=None):
        self._enabled = enabled
        self._checked = checked
        StateAction.__init__(self, env, text, self._read_session, self._run_session, checkable=checked is not None)
        self._run = run
        _follow(env, self)

    def _read_session(self, _layer):
        session = _session(self._env)
        if session is None:
            return False, False
        enabled = self._enabled(session) if self._enabled is not None else True
        return enabled, self._checked(session) if self._checked is not None else False

    def _run_session(self, _layer, checked):
        pass

    def _on_triggered(self, checked=False):
        session = _session(self._env)
        if session is not None:
            self._run(session, checked)
        self.refresh()


def _preparing(session):
    """Lage von Hand ändern geht nur ohne Passpunkte (danach bestimmen diese die Lage)."""
    return not session.points


def _gt_command(change):
    """Fabrik für einen Button, der die Lage über ``change(session) -> gt`` ändert."""
    def factory(env, command):
        return env.keep(SessionAction(env, command.label, lambda s, _c: s.apply(change(s)), enabled=_preparing))
    return factory


def _fit(env):
    return lambda s: georef.fit_to_extent(s.width, s.height, georef_session.canvas_extent(env.iface.mapCanvas()))


def georef_anpassen(env, command):
    return env.keep(SessionAction(env, command.label, lambda s, _c: s.apply(_fit(env)(s)), enabled=_preparing))


georef_links = _gt_command(lambda s: georef.rotate90(s.gt, s.width, s.height, clockwise=False))
georef_rechts = _gt_command(lambda s: georef.rotate90(s.gt, s.width, s.height, clockwise=True))
georef_waagerecht = _gt_command(lambda s: georef.flip_horizontal(s.gt, s.width, s.height))
georef_senkrecht = _gt_command(lambda s: georef.flip_vertical(s.gt, s.width, s.height))


def georef_bild(env, command):
    return env.keep(SessionAction(env, command.label, lambda s, c: s.set_image_visible(c),
                                  checked=lambda s: s.image_visible()))


def georef_rueckgaengig(env, command):
    return env.keep(SessionAction(env, command.label, lambda s, _c: s.undo(),
                                  enabled=lambda s: s.history.can_undo()))


def georef_wiederholen(env, command):
    return env.keep(SessionAction(env, command.label, lambda s, _c: s.redo(),
                                  enabled=lambda s: s.history.can_redo()))


def georef_abbrechen(env, command):
    return env.keep(SessionAction(env, command.label, lambda _s, _c: _manager(env).cancel()))


class GeorefToolAction(ToolAction):
    """Kartenwerkzeug der Sitzung: endet die Sitzung, wird das Werkzeug abgegeben."""

    def refresh(self):
        ToolAction.refresh(self)
        if not self.isEnabled() and self._canvas.mapTool() is self.tool:
            self._canvas.unsetMapTool(self.tool)


def _tool(mode):
    def factory(env, command):
        tool = env.keep(georef_session.GeorefTool(env.iface.mapCanvas(), _manager(env), mode))
        act = env.keep(GeorefToolAction(env, command.label, tool,
                                        lambda _layer: _session(env) is not None and _preparing(_session(env))))
        return _follow(env, act)
    return factory


# -- Passpunkte und Abschließen ------------------------------------------------------

def georef_passpunkt(env, command):
    tool = env.keep(georef_session.GcpTool(env.iface.mapCanvas(), _manager(env)))
    act = env.keep(GeorefToolAction(env, command.label, tool, lambda _layer: _session(env) is not None))
    return _follow(env, act)


def _points_dir(env, session):
    return _settings(env).value(LAST_DIR_KEY, os.path.dirname(session.source))


def load_points(env, path=None):
    session = _session(env)
    if session is None:
        return False
    if path is None:
        path, _f = QFileDialog.getOpenFileName(env.iface.mainWindow(), tr("Load Control Points"),
                                               _points_dir(env, session), tr("Control points (*.points)"))
        if not path:
            return False
    try:
        session.load_points(path)
    except (OSError, ValueError) as exc:
        _push(env, tr("The control points cannot be read: %s") % exc, Qgis.MessageLevel.Warning)
        return False
    return True


def save_points(env, path=None):
    session = _session(env)
    if session is None:
        return False
    if path is None:
        default = os.path.splitext(session.source)[0] + ".points"
        path, _f = QFileDialog.getSaveFileName(env.iface.mainWindow(), tr("Save Control Points"), default,
                                               tr("Control points (*.points)"))
        if not path:
            return False
    try:
        session.save_points(path)
    except OSError as exc:
        _push(env, tr("The control points cannot be saved: %s") % exc, Qgis.MessageLevel.Warning)
        return False
    return True


def georef_punkte_laden(env, command):
    return env.keep(SessionAction(env, command.label, lambda _s, _c: load_points(env)))


def georef_punkte_speichern(env, command):
    return env.keep(SessionAction(env, command.label, lambda _s, _c: save_points(env),
                                  enabled=lambda s: bool(s.points)))


def save_georeference(env):
    """Worldfile und Begleitdatei neben das Bild; Sitzung endet, das Bild zeigt die neue Lage."""
    manager = _manager(env)
    session = _session(env)
    if session is None or not session.linear():
        return None
    try:
        georef_session.release_file(session.source)
        written = georef_ops.save_georeference(session.source, session.gt, session.crs_wkt)
    except (OSError, ValueError, RuntimeError) as exc:
        _push(env, tr("The georeference cannot be saved: %s") % exc, Qgis.MessageLevel.Warning)
        return None
    manager.finish(session.source, replace=False)
    _push(env, tr("Georeference saved next to the image: %s") % ", ".join(os.path.basename(p) for p in written),
          Qgis.MessageLevel.Success)
    return written


def georef_speichern(env, command):
    act = SessionAction(env, command.label, lambda _s, _c: save_georeference(env),
                        enabled=lambda s: s.linear())
    return env.keep(act)


BUTTONS = {
    "ribbon.georef_starten": georef_starten,
    "ribbon.georef_anpassen": georef_anpassen,
    "ribbon.georef_verschieben": _tool(georef_session.MOVE),
    "ribbon.georef_skalieren": _tool(georef_session.SCALE),
    "ribbon.georef_drehen": _tool(georef_session.ROTATE),
    "ribbon.georef_links": georef_links,
    "ribbon.georef_rechts": georef_rechts,
    "ribbon.georef_waagerecht": georef_waagerecht,
    "ribbon.georef_senkrecht": georef_senkrecht,
    "ribbon.georef_bild": georef_bild,
    "ribbon.georef_rueckgaengig": georef_rueckgaengig,
    "ribbon.georef_wiederholen": georef_wiederholen,
    "ribbon.georef_abbrechen": georef_abbrechen,
    "ribbon.georef_passpunkt": georef_passpunkt,
    "ribbon.georef_punkte_laden": georef_punkte_laden,
    "ribbon.georef_punkte_speichern": georef_punkte_speichern,
    "ribbon.georef_speichern": georef_speichern,
}


def register_all():
    for cid, factory in BUTTONS.items():
        custom_commands.register(cid, factory, "button")


def unregister_all():
    for cid in BUTTONS:
        custom_commands.unregister(cid)
