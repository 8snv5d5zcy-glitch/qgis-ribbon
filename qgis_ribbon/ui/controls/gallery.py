"""Galerien: feste Einträge als Icon-Raster, Laufzeit-Einträge als Menüeinträge.

Eine Galerie gehört zu einem Steuerelement (``Command.gallery``). Feste
Einträge sind andere Befehle (z. B. QGIS-Bearbeitungswerkzeuge); sie werden
als ``ProxyAction`` gespiegelt, zeigen also aktiv/abgehakt wie QGIS.
Einträge, die erst zur Laufzeit feststehen (Lesezeichen, XYZ-Verbindungen,
Textformate, Darstellungsarten), liefert der eigene Befehl
(``custom_commands``, Art ``gallery``). Sie werden beim Öffnen des Menüs neu
gelesen, nicht dauernd.

Darstellung (``Gallery.display``):

- ``ribbon``: die ersten ``columns`` Einträge direkt im Ribbon, daneben ein
  Pfeil, der alle Einträge und die übrigen Menüeinträge aufklappt;
- ``dropdown``: ein Button, der die Galerie aufklappt.

Galerien im Ribbon gibt es groß (Icon mit Text) und kompakt (nur Icons,
doppelt so viele Einträge sichtbar); umgeschaltet wird über den Befehl
„Galeriegröße“ (``builtin_commands.GallerySize``, pro Nutzer gespeichert).
"""

from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import (QAction, QApplication, QGridLayout, QHBoxLayout, QMenu,
                                 QSizePolicy, QToolButton, QWidget, QWidgetAction)

from ...qgis_integration import builtin_commands, custom_commands
from .. import icons, theme
from ..html_text import escape
from .buttons import (MENU_ARROW, ProxyAction, _base_button, activate_button, apply_size,
                      build_menu, remember, tooltip)
from ...core.i18n import tr

TILE_WIDTH = 92          # Breite einer Kachel (Icon groß, Text darunter, z. B. „Zusammenführen“)
COMPACT_TILE_WIDTH = 40  # kompakte Kachel im Ribbon: nur Icon
EXPAND_WIDTH = 16        # Pfeil neben der Galerie im Ribbon
EMPTY_TEXT = tr("No items available")


def provider(command, ctx):
    """Lieferant der Laufzeit-Einträge oder None."""
    cid = command.source.get("id") if command.source.type == "custom" else None
    if cid and custom_commands.kind_of(cid) == "gallery":
        return custom_commands.get(cid)(ctx.env, command)
    return None


def _tile(action, parent):
    btn = QToolButton(parent)
    btn.setAutoRaise(True)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setIconSize(QSize(theme.LARGE_ICON, theme.LARGE_ICON))
    btn.setFixedSize(TILE_WIDTH, theme.CONTENT_HEIGHT - 4)
    btn.setProperty("ribbon_tile", True)
    action.setIconText(theme.wrap_label(action.text()))
    btn.setDefaultAction(action)
    return btn


class GalleryGrid(QWidget):
    """Raster aus Kacheln für feste Galerie-Einträge.

    Tastatur: Pfeiltasten wandern durch die Kacheln, Eingabe/Leertaste löst
    aus. Am Rand geht die Taste an das umgebende Menü weiter (nächster
    Menüeintrag).
    """

    def __init__(self, commands, ctx, columns, parent=None, on_click=None):
        QWidget.__init__(self, parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setSpacing(1)
        self.columns = columns
        self.actions_ = []
        self.tiles = []
        for i, cmd in enumerate(commands):
            act = ProxyAction(cmd, ctx, self)
            btn = _tile(act, self)
            btn.setObjectName("ribbon_tile_" + cmd.id)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if on_click is not None:
                act.triggered.connect(on_click)
            self.actions_.append(act)
            self.tiles.append(btn)
            grid.addWidget(btn, i // columns, i % columns)
        if self.tiles:
            self.setFocusProxy(self.tiles[0])
        for tile in self.tiles:
            # Vor dem Button abfangen: QToolButton verschiebt den Fokus sonst selbst nach Lage
            tile.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and obj in self.tiles:
            return self.handle_key(self.tiles.index(obj), event)
        return False

    def handle_key(self, current, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.tiles[current].isEnabled():
                self.tiles[current].defaultAction().trigger()
            return True
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -self.columns,
                Qt.Key.Key_Down: self.columns}.get(key)
        if step is None:
            return False
        target = current + step
        if 0 <= target < len(self.tiles) and not self.tiles[target].isHidden():
            self.tiles[target].setFocus(Qt.FocusReason.TabFocusReason)
            return True
        # Rand: an das umgebende Menü weiterreichen (nächster Menüeintrag)
        parent = self.parentWidget()
        if isinstance(parent, QMenu):
            QApplication.sendEvent(parent, QKeyEvent(event.type(), key, event.modifiers()))
        return True


def add_gallery(menu, command, ctx, section=False):
    """Galerie an der aktuellen Stelle des Menüs einfügen.

    ``section``: Galerie ist ein Menüeintrag; ihre Beschriftung wird zur Überschrift.
    """
    gallery = command.gallery
    if section:
        menu.addSection(command.label)
    if gallery is not None and gallery.items:
        # Raster erst beim ersten Öffnen bauen (Aufbauzeit des Tabs)
        slot = QAction(menu)
        slot.setVisible(False)
        menu.addAction(slot)
        built = []

        def build_grid():
            if built:
                return
            grid = GalleryGrid(gallery.items, ctx, gallery.columns, menu, on_click=menu.close)
            grid.setObjectName("ribbon_gallery_" + command.id)
            wa = QWidgetAction(menu)
            wa.setDefaultWidget(grid)
            menu.insertAction(slot, wa)
            built.append(wa)

        menu.aboutToShow.connect(build_grid)
    entries = provider(command, ctx)
    if entries is None:
        if gallery is None or not gallery.items:
            # Galerie ohne Inhalt (nicht registriert): Grund anzeigen statt leer
            res = ctx.resolver.resolve(command)
            hint = menu.addAction(res.reason or EMPTY_TEXT)
            hint.setEnabled(False)
        return
    anchor = QAction(menu)          # Einfügestelle für die Laufzeit-Einträge
    anchor.setVisible(False)
    anchor.setObjectName("ribbon_gallery_anchor_" + command.id)
    anchor.setProperty("ribbon_dynamic", True)
    menu.addAction(anchor)
    dynamic = []
    allowed = lambda: ctx.allowed(command)  # noqa: E731

    def refill():
        for act in dynamic:
            menu.removeAction(act)
            act.deleteLater()
        del dynamic[:]
        try:
            items = entries()
        except Exception as exc:  # Galerie darf das Menü nie verhindern
            items = []
            ctx.resolver.report(command, exc)
        if not items and not (gallery and gallery.items):
            empty = QAction(EMPTY_TEXT, menu)
            empty.setEnabled(False)
            menu.insertAction(anchor, empty)
            dynamic.append(empty)
        last_section = None
        for entry in items:
            if entry.section and entry.section != last_section:
                sec = menu.insertSection(anchor, entry.section)
                dynamic.append(sec)
                last_section = entry.section
            act = QAction(entry.label, menu)
            if entry.icon is not None:
                act.setIcon(entry.icon)
            if entry.tooltip:
                act.setToolTip(entry.tooltip)
            if entry.checked is not None:
                act.setCheckable(True)
                act.setChecked(entry.checked)
            act.setEnabled(entry.callback is not None and allowed())
            if entry.callback is not None:
                act.triggered.connect(lambda _c=False, e=entry: _run_entry(ctx, command, e))
            menu.insertAction(anchor, act)
            dynamic.append(act)

    menu.aboutToShow.connect(refill)


def _run_entry(ctx, command, entry):
    ctx.resolver.call(command, entry.callback)
    ctx.after_trigger()


class _CommandState(object):
    """Hält einen Button bedienbar nach den Bedingungen seines Befehls (für ``ctx.register``)."""

    def __init__(self, command, widget, ctx, available=True):
        self.command = command
        self.widget = widget
        self._ctx = ctx
        self._available = available
        ctx.register(self)
        self.sync()

    def sync(self):
        self.widget.setEnabled(self._available and self._ctx.allowed(self.command))


def _icon(command, ctx):
    res = ctx.resolver.resolve(command)
    if not res.icon.isNull():
        return res.icon
    return ctx.resolver.theme_icon(command.icon) if command.icon else res.icon


def gallery_button(command, size, ctx, parent, items=()):
    """Dropdown-Galerie als Button (``display: dropdown``), optional mit Menüeinträgen darunter."""
    btn = _base_button(parent, size)
    menu = build_menu(items, ctx, btn, gallery=command)
    btn.setIcon(icons.command_icon(command, _icon(command, ctx)))
    res = ctx.resolver.resolve(command)
    btn.setToolTip(tooltip(command.label, res, command.description))
    btn.setMenu(menu)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn.setObjectName("ribbon_gallery_btn_" + command.id)
    btn._state = _CommandState(command, btn, ctx, res.available)
    remember(btn, command.label, True)
    apply_size(btn, size, command.label, True)
    ctx.add_target(btn, command.label, lambda: activate_button(btn), command)
    return btn


class RibbonGallery(QWidget):
    """Galerie direkt im Ribbon (``display: ribbon``): Kacheln plus Pfeil zum Aufklappen.

    Wie viele Kacheln sichtbar sind, bestimmt die adaptive Breite
    (``set_visible``): definiert sind ``columns`` (kompakt doppelt so viele),
    bei mehr Platz zeigt die Galerie weitere Einträge, bei weniger Platz
    weniger. KeyTips gibt es für die ersten ``2 × columns`` Kacheln (stabil).
    """

    def __init__(self, command, ctx, parent=None, items=()):
        QWidget.__init__(self, parent)
        self.setObjectName("ribbon_gallery_" + command.id)
        self.command = command
        self.items = items
        gallery = command.gallery
        self.columns = gallery.columns
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        all_items = gallery.items
        self.grid = GalleryGrid(all_items, ctx, max(1, len(all_items)), self)
        lay.addWidget(self.grid)
        wide = gallery.columns * 2
        for tile in self.grid.tiles[:wide]:
            ctx.add_target(tile, tile.defaultAction().text(), lambda t=tile: activate_button(t),
                           tile.defaultAction().command)
        self.expand = QToolButton(self)
        self.expand.setAutoRaise(True)
        self.expand.setText(MENU_ARROW)
        self.expand.setFixedSize(EXPAND_WIDTH, theme.CONTENT_HEIGHT)
        self.expand.setToolTip(tr("<b>%s</b>%s<br>Show all items") % (
            escape(command.label),
            "<br>" + escape(command.description) if command.description else ""))
        self.menu = build_menu(items, ctx, self.expand, gallery=command)
        self.expand.setMenu(self.menu)
        self.expand.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.expand.setObjectName("ribbon_gallery_expand_" + command.id)
        lay.addWidget(self.expand)
        self.expand_target = ctx.add_target(self.expand, command.label + tr(" (all)"),
                                            lambda: activate_button(self.expand), command)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(theme.CONTENT_HEIGHT)
        self.setProperty("ribbon_size", "large")
        self._state = _CommandState(command, self, ctx)
        self.visible = None
        size = builtin_commands.gallery_size(ctx.env)
        ctx.hub.connect(size, "changed", self.set_compact)
        self.set_compact(size.compact())

    def tile_width(self):
        return (COMPACT_TILE_WIDTH if self.compact else TILE_WIDTH) + 1

    def ideal_count(self):
        return min(len(self.grid.tiles), self.columns * (2 if self.compact else 1))

    def width_for(self, count):
        return count * self.tile_width() + EXPAND_WIDTH + 4

    def set_compact(self, on):
        self.compact = bool(on)
        for tile in self.grid.tiles:
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly
                                    if on else Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setFixedWidth(COMPACT_TILE_WIDTH if on else TILE_WIDTH)
        self.set_visible(self.ideal_count())

    def set_visible(self, count):
        """Anzahl sichtbarer Kacheln (adaptive Breite)."""
        count = max(0, min(count, len(self.grid.tiles)))
        self.visible = count
        for i, tile in enumerate(self.grid.tiles):
            tile.setHidden(i >= count)
        self.setFixedWidth(self.width_for(count))
        self.grid.adjustSize()
        self.updateGeometry()
