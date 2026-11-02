"""Ribbon im Layout-Fenster: Aufbau und Abbau je Fenster.

``DesignerRibbons`` hört auf das Öffnen und Schließen der Layout-Fenster und
hält je Fenster einen ``DesignerRibbon``. Beim Start übernimmt es auch Fenster,
die schon offen sind. Jeder Ribbon hat einen eigenen ``SignalHub``, sonst würde
``disconnect_all`` beim Schließen eines Fensters auch die anderen trennen.

Fensterzustand (Falle): QGIS speichert beim Schließen ausgeblendete Leisten in
``app/LayoutDesigner/state`` und stellt sie beim nächsten Öffnen so wieder her.
``layoutDesignerWillBeClosed`` kommt vor dem Speichern; dort wird der Ribbon
abgebaut und die Leisten kommen zurück. Das Layout des Fensters muss dabei einmal
laufen, denn eben eingeblendete Leisten haben sonst noch keine Lage.

Berichte teilen sich das Fenster mit den Layouts. Ihr Layout wechselt je Abschnitt
(``view.layoutSet``), zu Beginn gibt es oft keines, und einen Atlas haben sie nicht.
Der Tab Bericht erscheint nur dort; Atlas und Teilen nur bei Layouts. QGIS löscht beim
Wechsel die Aktionen Rückgängig und Wiederholen und legt neue an, ohne Layout gibt es
sie nicht: Der Ribbon wird deshalb je Abschnitt neu aufgebaut.

Anpassen: Alle Fenster teilen sich eine ``LayoutArrangements``. Nach einer Änderung
werden sie neu aufgebaut, aber nie unter einem offenen modalen Dialog. Den Aufbau
trägt die Definition mit den Plugin-Aktionen des jeweiligen Fensters (``DesignerCatalog``);
ändern die sich, wird nur dieses Fenster neu aufgebaut.

Designs, Gesamtbild und Menüleiste gelten für alle Fenster; das Plugin reicht
Änderungen über ``refresh_themes`` und ``set_menubar_hidden`` weiter.
"""

from qgis.core import Qgis, QgsMessageLog, QgsPrintLayout
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QApplication, QToolBar

from .core import config_loader
from .core import extensions as ext
from .core.context import ContextLogic
from .core.i18n import tr
from .qgis_integration.action_resolver import ActionResolver
from .qgis_integration.after_modal import AfterModal
from .qgis_integration.arrangements import LayoutArrangements
from .qgis_integration.custom_commands import CommandEnv
from .qgis_integration.extensions import DesignerCatalog
from .qgis_integration.layout_state import LayoutSelection
from .qgis_integration.menu_bar import MenuBarHider, can_hide
from .qgis_integration.signals import SignalHub
from .qgis_integration.toolbar_manager import ToolbarManager
from .qgis_integration.user_settings import LAYOUT_SCOPE, UserSettings
from .ui import theme
from .ui.keytips import KeyTipController
from .ui.ribbon_widget import RibbonWidget
from .ui.whole_theme import WindowSheet

LOG_TAG = "QGIS Ribbon"
TOOLBAR_NAME = "QgisRibbonToolbar"
# Aktion von QGIS in den Leisten, die nicht ``mAction…`` heißt (Export des Atlas)
QGIS_NAMES = ("AtlasExport",)


class DesignerRibbon(object):
    """Ribbon in einem Layout-Fenster; ``teardown`` stellt das Fenster wieder her."""

    def __init__(self, designer, iface, store, host, arrangements, definition):
        self.designer = designer
        self.host = host
        self.arrangements = arrangements
        self.definition = definition      # Definition ohne Plugin-Aktionen
        self.window = designer.window()
        self.report = not isinstance(designer.masterLayout(), QgsPrintLayout)
        self.hub = SignalHub()
        self.user = arrangements.user
        self.selection = None
        self.logic = None
        self.keytips = None
        self.catalog = None
        self.env = CommandEnv(iface, None, store, self.hub, host=arrangements, designer=designer)
        self.resolver = ActionResolver(iface, self.env, window=self.window)
        self.toolbars = ToolbarManager(self.window, remember=False)
        self.menubar = MenuBarHider(self.window)
        self.sheet = WindowSheet(self.window)
        self.themes = theme.ThemeManager(self.user)
        self.themes.lightness_override = host.lightness
        self.themes.refresh(emit=False)
        self.toolbar = None
        self.widget = None

    def _effective(self):
        """Wirksamer Ribbon: Definition, Plugin-Aktionen dieses Fensters, Anpassung des Nutzers."""
        self.catalog = DesignerCatalog(self.resolver.iface, self.window, self.definition.hide_toolbars, self.hub,
                                       known=QGIS_NAMES)
        self.catalog.scan()
        self.resolver.extensions = self.catalog
        referenced = ext.referenced_ids(self.user.layout(), self.user.quick_access() or "")
        self.arrangements.set_base(ext.extend(self.definition, self.catalog.found, (), referenced))
        return ext.visible(self.arrangements.effective())

    def build(self):
        host = self.host
        ribbon = self._effective()
        # Auswahl zuerst bestimmen, damit der Ribbon gleich im richtigen Kontext entsteht
        self.logic = ContextLogic(ribbon)
        self.selection = LayoutSelection(self._layout(), self.hub, self._on_context, report=self.report)
        self.env.items = self.selection
        self.selection.start()
        if self.report:
            self.hub.connect(self.designer.view(), "layoutSet", self.selection.set_layout)
        self.toolbar = QToolBar("Ribbon", self.window)
        self.toolbar.setObjectName(TOOLBAR_NAME)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.toggleViewAction().setVisible(False)
        self.toolbar.setStyleSheet(theme.toolbar_qss(theme.current()))
        self.widget = RibbonWidget(ribbon, self.resolver, self.hub, self.toolbar, logic=self.logic,
                                   user=self.user, arrangements=self.arrangements, theme_manager=self.themes)
        self.widget.whole_available = True
        self.widget.menubar_available = can_hide(self.window)
        self.widget.designer_available = True
        self.widget.classicRequested.connect(lambda: host.set_classic(True))
        self.widget.menuBarToggled.connect(host.menubar_toggled)
        self.widget.designerToggled.connect(host.switch_toggled)
        self.hub.connect(self.themes, "changed", host.theme_changed)
        self.toolbar.addWidget(self.widget)
        self.keytips = KeyTipController(self.widget, self.window)
        self.keytips.install()
        # QGIS zeigt das Fenster schon vor dem Signal: Umbau in einem Rutsch zeichnen
        self.window.setUpdatesEnabled(False)
        try:
            self.toolbars.place_ribbon(self.toolbar)
            self.toolbars.hide(ribbon.hide_toolbars)
            if self.user.menubar_hidden():
                self.set_menubar_hidden(True)
            self.apply_whole()
        finally:
            self.window.setUpdatesEnabled(True)
        self.catalog.start()

    def _layout(self):
        """Gezeigtes Layout. masterLayout: layout() liefert bei neu angelegten Layouts nur die Basisklasse
        ohne atlas(). Beim Bericht das Layout des gezeigten Abschnitts, zu Beginn oft keines."""
        return self.designer.view().currentLayout() if self.report else self.designer.masterLayout()

    def _on_context(self, snapshot, events):
        changes = self.logic.update(snapshot, events)
        if changes and self.widget is not None:
            self.widget.apply_context(changes)

    def set_menubar_hidden(self, on):
        self.menubar.set_hidden(on)
        self.widget.set_menubar_hidden(self.menubar.hidden)

    def apply_whole(self):
        self.sheet.update(bool(self.themes.settings()["whole"]), theme.current())

    def teardown(self):
        if self.catalog is not None:
            self.catalog.stop()
        if self.selection is not None:
            self.selection.stop()
            self.selection = None
        self.hub.disconnect_all()
        if self.keytips is not None:
            self.keytips.uninstall()
            self.keytips = None
        self.themes.stop()
        self.themes.lightness_override = None
        alive = not sip.isdeleted(self.window)
        if alive and self.widget is not None:
            self.widget.hide_popup()
        if alive:
            self.menubar.restore()
            self.sheet.restore()
            self.toolbars.restore()
            self.toolbars.remove_ribbon()
            layout = self.window.layout()
            if layout is not None:
                layout.activate()   # Lage der eingeblendeten Leisten, QGIS speichert gleich den Zustand
            if self.toolbar is not None:
                self.toolbar.setParent(None)
                self.toolbar.deleteLater()
        self.toolbars.deleteLater()
        self.themes.deleteLater()
        self.toolbar = None
        self.widget = None
        self.resolver.clear()
        self.resolver.extensions = None
        if self.catalog is not None:
            self.catalog.deleteLater()
            self.catalog = None


class DesignerRibbons(object):
    """Alle Ribbons der Layout-Fenster. ``host`` ist das Plugin (siehe ``DesignerRibbon.build``)."""

    def __init__(self, iface, store, host, config_path=None):
        self.iface = iface
        self.store = store
        self.host = host
        self.config_path = config_path or config_loader.LAYOUT_CONFIG
        self.hub = SignalHub()
        self.base = None
        self._broken = False
        self.active = False
        self.ribbons = {}      # Fenster -> DesignerRibbon
        self._pending = set()  # Fenster, die neu aufzubauen sind
        self._after_modal = None
        self.arrangements = LayoutArrangements(self._definition, UserSettings(store, LAYOUT_SCOPE), host.arrangements)
        self.arrangements.changed.connect(self.request_rebuild)

    def _definition(self):
        """Definition des Layout-Fensters: geladen beim ersten Gebrauch, nicht beim Start von QGIS."""
        if self.base is None and not self._broken:
            try:
                self.base = config_loader.load(self.config_path, qgis_version=Qgis.QGIS_VERSION_INT)
            except config_loader.ConfigError as exc:
                self._broken = True
                QgsMessageLog.logMessage(str(exc), LOG_TAG, Qgis.MessageLevel.Critical)
        return self.base

    def start(self):
        if self.active:
            return
        self.active = True
        self.hub.connect(self.iface, "layoutDesignerOpened", self.opened)
        self.hub.connect(self.iface, "layoutDesignerWillBeClosed", self.closing)
        for designer in self.iface.openLayoutDesigners():
            self.opened(designer)

    def stop(self):
        self.hub.disconnect_all()
        self.active = False
        self._pending.clear()
        self._cancel_after_modal()
        while self.ribbons:
            _window, ribbon = self.ribbons.popitem()
            ribbon.teardown()

    def close(self):
        """Beim Entladen: alles abbauen und die Anordnung freigeben."""
        self.stop()
        self.arrangements.changed.disconnect(self.request_rebuild)
        self.host.arrangements.partner = None
        self.arrangements.deleteLater()

    def opened(self, designer):
        window = designer.window()
        if window in self.ribbons or self._definition() is None:
            return
        ribbon = DesignerRibbon(designer, self.iface, self.store, self.host, self.arrangements, self.base)
        try:
            ribbon.build()

            def rebuild(*_args):
                self.request_rebuild(window)

            ribbon.catalog.changed.connect(rebuild)
            if ribbon.report:
                # QGIS legt Rückgängig und Wiederholen je Abschnitt neu an: Buttons neu binden
                ribbon.hub.connect(designer.view(), "layoutSet", rebuild)
            self.ribbons[window] = ribbon
        except Exception as exc:  # Das Fenster muss auch ohne Ribbon bedienbar bleiben
            ribbon.teardown()
            QgsMessageLog.logMessage(tr("Ribbon in layout window not built: %s") % exc, LOG_TAG,
                                     Qgis.MessageLevel.Critical)

    def closing(self, designer):
        window = designer.window()
        self._pending.discard(window)
        ribbon = self.ribbons.pop(window, None)
        if ribbon is not None:
            ribbon.teardown()

    # Neuaufbau
    def request_rebuild(self, window=None):
        """Fenster neu aufbauen (nach der Ereignisschleife); ohne Angabe alle."""
        if not self.ribbons:
            return
        pending = bool(self._pending)
        self._pending.update([window] if window is not None else self.ribbons)
        if not pending:
            QTimer.singleShot(0, self._rebuild)

    def _rebuild(self):
        modal = QApplication.activeModalWidget()
        if modal is not None:
            # Nicht unter einem offenen Dialog abbauen (er kann aus dem Ribbon stammen)
            if self._after_modal is None:
                self._after_modal = AfterModal(modal, self._after_modal_closed)
            return
        pending, self._pending = self._pending, set()
        for window in pending:
            ribbon = self.ribbons.pop(window, None)
            if ribbon is None:
                continue
            tab = ribbon.widget.current_tab()
            designer = ribbon.designer
            window.setUpdatesEnabled(False)
            try:
                ribbon.teardown()
                self.opened(designer)
                built = self.ribbons.get(window)
                if built is not None and tab in built.widget.tab_ids():
                    built.widget.select_tab(tab)
            finally:
                window.setUpdatesEnabled(True)

    def _after_modal_closed(self):
        self._after_modal = None
        if self._pending:
            self._rebuild()

    def _cancel_after_modal(self):
        if self._after_modal is not None:
            self._after_modal.cancel()
            self._after_modal = None

    # Für alle Fenster
    def refresh_themes(self):
        for ribbon in list(self.ribbons.values()):
            ribbon.themes.refresh()
            ribbon.apply_whole()

    def set_menubar_hidden(self, on):
        for ribbon in list(self.ribbons.values()):
            ribbon.set_menubar_hidden(on)

    def icon(self, command):
        """QGIS-Icon einer Plugin-Aktion aus einem Layout-Fenster (Palette des Editors)."""
        for ribbon in self.ribbons.values():
            icon = ribbon.catalog.icon(command)
            if not icon.isNull():
                return icon
        return QIcon()
