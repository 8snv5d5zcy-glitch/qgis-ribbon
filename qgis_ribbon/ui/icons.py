"""Icons „Kontur“ in Qt.

``command_icon(command, fallback)`` liefert ein ``QIcon`` mit eigener
``QIconEngine``. Die Engine zeichnet das Motiv aus ``core.icons`` beim
Zeichnen in den aktuellen Farben (``theme.current()``): Kontur in Textfarbe,
Detail in Akzentfarbe, abgehakt in der Textfarbe „aktiv“, gesperrt in
„gesperrt“. Ein Wechsel von Modus oder Akzent braucht deshalb kein neues
Icon, nur ein Neuzeichnen. Sind die eigenen Icons abgeschaltet
(``theme.setting("icons")``), zeichnet die Engine das QGIS-Icon.

Befehle ohne Motiv behalten das QGIS-Icon (Rückfall). Gerenderte Bilder
werden je Motiv, Größe, Zustand und Theme-Generation gecacht: die Renderer
und die fertigen Pixmaps. Qt cacht Pixmaps eigener Engines nicht; ohne den
Cache rendert jeder Tabwechsel alle Icons der Seite neu (128 SVGs,
16 ms).

Laufzeitbefehle (Plugin-Aktionen, Werkzeuge) haben nie ein Motiv. Ohne
übergebenen Rückfall fragt ``command_icon`` die Quelle, die das Plugin mit
``set_runtime_icons`` setzt (QGIS-Icon der Aktion bzw. des Algorithmus).
"""

from qgis.PyQt.QtCore import QByteArray, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer

from ..core import extensions as ext
from ..core import icons as core_icons
from . import theme

_SET = None
_FAILED = False
_CACHE = {}
_CACHE_LIMIT = 4000
_PIXMAPS = {}
_RUNTIME = None   # (Command) -> QIcon für Laufzeitbefehle, vom Plugin gesetzt


def set_runtime_icons(provider):
    """Quelle der QGIS-Icons für Laufzeitbefehle; None beim Abbau."""
    global _RUNTIME
    _RUNTIME = provider


def icon_set():
    """Icon-Set (beim ersten Gebrauch geladen); None, wenn die Datei fehlerhaft ist."""
    global _SET, _FAILED
    if _SET is None and not _FAILED:
        try:
            _SET = core_icons.load()
        except (core_icons.IconError, OSError) as exc:
            _FAILED = True
            try:
                from qgis.core import Qgis, QgsMessageLog
                QgsMessageLog.logMessage(str(exc), "QGIS Ribbon", Qgis.MessageLevel.Warning)
            except ImportError:
                pass
    return _SET


def _renderer(name, size, mode, state):
    t = theme.current()
    key = (name, size, mode, state, theme.generation())
    renderer = _CACHE.get(key)
    if renderer is not None:
        return renderer
    motif = icon_set().motifs[name]
    if mode == QIcon.Mode.Disabled:
        contour = accent = t["faint"][:7]
        fill = None
    elif state == QIcon.State.On:
        contour, accent, fill = t["accT"][:7], t["acc"][:7], t["acc"][:7]
    else:
        contour, accent, fill = t["text"][:7], t["acc"][:7], t["acc"][:7]
    stroke = core_icons.STROKE_SMALL if size <= 20 else core_icons.STROKE_LARGE
    data = core_icons.svg(motif, contour, accent, fill, stroke)
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    if len(_CACHE) > _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = renderer
    return renderer


class KonturIconEngine(QIconEngine):
    def __init__(self, name, fallback=None):
        QIconEngine.__init__(self)
        self.name = name
        self.fallback = QIcon(fallback) if fallback is not None else QIcon()

    def _own(self):
        return theme.setting("icons") or self.fallback.isNull()

    def paint(self, painter, rect, mode, state):
        if not self._own():
            self.fallback.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode, state)
            return
        side = min(rect.width(), rect.height())
        target = QRectF(rect.x() + (rect.width() - side) / 2.0,
                        rect.y() + (rect.height() - side) / 2.0, side, side)
        _renderer(self.name, side, mode, state).render(painter, target)

    def pixmap(self, size, mode, state):
        if not self._own():
            return self.fallback.pixmap(size, mode, state)
        key = (self.name, size.width(), size.height(), mode, state, theme.generation())
        pix = _PIXMAPS.get(key)
        if pix is not None:
            return pix
        pix = QPixmap(size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(painter, pix.rect(), mode, state)
        painter.end()
        if len(_PIXMAPS) > _CACHE_LIMIT:
            _PIXMAPS.clear()
        _PIXMAPS[key] = pix
        return pix

    def actualSize(self, size, mode, state):  # noqa: N802 (Qt)
        side = min(size.width(), size.height())
        return QSize(side, side)

    def clone(self):
        return KonturIconEngine(self.name, self.fallback)

    def key(self):
        return "kontur"


def motif_icon(name, fallback=None):
    """Icon eines Motivs; ``fallback`` (QIcon) ohne Icon-Set oder Motiv."""
    s = icon_set()
    if s is None or name is None or name not in s.motifs:
        return fallback if fallback is not None else QIcon()
    return QIcon(KonturIconEngine(name, fallback))


def command_icon(command, fallback=None):
    if ext.is_runtime(command.id):
        if fallback is None and _RUNTIME is not None:
            fallback = _RUNTIME(command)
        return fallback if fallback is not None else QIcon()
    s = icon_set()
    name = s.for_command(command.id) if s is not None else None
    return motif_icon(name, fallback)


def menu_icon(label, fallback=None):
    s = icon_set()
    return motif_icon(s.for_menu(label) if s is not None else None, fallback)


def ui_icon(name, fallback=None):
    s = icon_set()
    return motif_icon(s.for_ui(name) if s is not None else None, fallback)


def clear_cache():
    _CACHE.clear()
    _PIXMAPS.clear()
