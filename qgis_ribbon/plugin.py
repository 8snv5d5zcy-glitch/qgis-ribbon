"""Einstieg des Plugins: Ribbon aufbauen (initGui) und spurlos entfernen (unload).

Der Aufbau ist wiederholbar: Nach einer Anpassung (Dialog „Ribbon
anpassen“, Galerie, geladene Anordnung) wird der Ribbon abgebaut und mit der
neuen Anordnung wieder aufgebaut. Die klassische QGIS-Oberfläche baut ihn nur
ab; zurück geht es über „Ansicht › Ribbon-Oberfläche“ (eigene Aktion im
QGIS-Menü, beim Entladen entfernt).

Design: ein ``ThemeManager`` je Aufbau liefert Modus und Akzent;
„Kontur für ganz QGIS“ (``WholeTheme``) legt bei Bedarf ein Stylesheet über
das Hauptfenster und nimmt es beim Abbau exakt zurück.

Erweiterungen: Jeder Aufbau sucht die Aktionen anderer Plugins und die
benötigten Werkzeuge (``ExtensionCatalog``), erweitert damit die Definition
und blendet die Plugin-Werkzeugleisten aus. Ändert sich etwas (Plugin geladen
oder entladen, Skript dazugekommen), wird neu aufgebaut, aber nie, solange ein
modaler Dialog offen ist (z. B. die Erweiterungsverwaltung, die aus dem Ribbon
heraus geöffnet wurde): dann erst nach dessen Schließen.

Anleitung: eigene Aktion im QGIS-Menü Hilfe › Plugins (auch in der
klassischen Oberfläche), beim Entladen entfernt; ein offenes Fenster der
Anleitung schließt ``unload`` ebenfalls.
"""

import os
import time

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsSettings
from qgis.PyQt.QtCore import QEvent, QObject, QTimer
from qgis.PyQt.QtWidgets import QAction, QApplication, QToolBar

from .core import config_loader, yaml_cache
from .core import extensions as ext
from .core.context import ContextLogic
from .qgis_integration import builtin_commands, log
from .qgis_integration.action_resolver import ActionResolver
from .qgis_integration.arrangements import Arrangements
from .qgis_integration.context_state import ContextState
from .qgis_integration.custom_commands import CommandEnv
from .qgis_integration.extensions import ExtensionCatalog
from .qgis_integration.layer_watch import LayerWatch
from .qgis_integration.signals import SignalHub
from .qgis_integration.toolbar_manager import ToolbarManager
from .qgis_integration.user_settings import UserSettings
from .ui import dialog_commands, guide, icons, theme
from .ui.controls import custom as custom_controls
from .ui.keytips import KeyTipController
from .ui.layer_tree_style import LayerTreeRadios, layer_tree_exclusive
from .ui.ribbon_widget import RibbonWidget
from .ui.whole_theme import WholeTheme
from .core.i18n import tr

LOG_TAG = "QGIS Ribbon"
TOOLBAR_NAME = "QgisRibbonToolbar"
VIEW_ACTION_NAME = "mActionQgisRibbonToggle"
HELP_ACTION_NAME = "mActionQgisRibbonGuide"
VIEW_ACTION_TEXT = tr("Ribbon Interface")
VIEW_ACTION_TIP = tr("Off: classic QGIS interface with toolbars")
CLASSIC_MESSAGE = tr("Classic QGIS interface. Back to the ribbon: View › Ribbon Interface.")


class _AfterModal(QObject):
    """Ruft ``callback`` auf, sobald der modale Dialog ``widget`` geschlossen ist."""

    def __init__(self, widget, callback):
        QObject.__init__(self)
        self.widget = widget
        self.callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        if obj is self.widget and event.type() in (QEvent.Hide, QEvent.Close):
            self.cancel()
            QTimer.singleShot(0, self.callback)
        return False

    def cancel(self):
        if self.widget is not None:
            try:
                self.widget.removeEventFilter(self)
            except RuntimeError:
                pass
            self.widget = None


class RibbonPlugin:
    def __init__(self, iface, config_path=None, settings=None, cache_dir=None):
        self.iface = iface
        self.config_path = config_path or config_loader.DEFAULT_CONFIG
        self.settings = settings  # None: QGIS-Einstellungen (Tests übergeben eine eigene Datei)
        # Zwischenspeicher der YAML-Dateien: im QGIS-Profil, in Tests nur auf Wunsch
        if cache_dir is None and settings is None:
            cache_dir = os.path.join(QgsApplication.qgisSettingsDirPath(), "cache", "qgis_ribbon")
        self.cache_dir = cache_dir
        self.store = None         # eine Einstellungs-Instanz für alle Teile (QgsSettings() kostet je ~1,5 ms)
        self.hub = SignalHub()
        self.base = None          # Ribbon-Definition
        self.user = None
        self.arrangements = None
        self.view_action = None
        self.help_action = None
        self.resolver = None
        self.toolbars = None
        self.toolbar = None
        self.widget = None
        self.ribbon = None        # wirksamer Ribbon (Definition mit Anordnung des Nutzers)
        self.logic = None
        self.state = None
        self.layers = None
        self.keytips = None
        self.themes = None
        self.whole = None
        self.catalog = None       # Aktionen anderer Plugins, Werkzeuge
        self.radios = None        # Kreise statt Haken in exklusiven Gruppen der Layerliste
        self._after_modal = None
        self.registered = False
        self.startup_ms = None
        self.rebuild_ms = None    # Messpunkt: Neuaufbau nach einer Anpassung
        self.timings = {}         # Messpunkte: Teilschritte von Laden und Aufbau (ms)
        self._pending = False

    def initGui(self):
        start = time.perf_counter()
        yaml_cache.set_dir(self.cache_dir)
        try:
            self.base = config_loader.load(self.config_path)
        except config_loader.ConfigError as exc:
            QgsMessageLog.logMessage(str(exc), LOG_TAG, Qgis.Critical)
            self.iface.messageBar().pushMessage(
                LOG_TAG, tr("Ribbon definition has errors, ribbon not loaded. Details in the log."),
                level=Qgis.Critical, duration=10)
            return
        self.timings["definition"] = (time.perf_counter() - start) * 1000.0
        self.store = self.settings if self.settings is not None else QgsSettings()
        self.user = UserSettings(self.store)
        self.arrangements = Arrangements(self.base, self.user)
        self.arrangements.changed.connect(self.request_rebuild)
        self._add_view_action()
        self._add_help_action()
        if self.user.classic():
            return
        if self.iface.mainWindow().isVisible():
            self._build()  # nachträglich geladen (Erweiterungsverwaltung, Plugin Reloader)
        else:
            # Beim QGIS-Start erst bauen, wenn alle Plugins geladen und der
            # Fensterzustand wiederhergestellt ist.
            self.hub.connect(self.iface, "initializationCompleted", self._build)

    # Umschalter im QGIS-Menü „Ansicht“
    def _view_menu(self):
        try:
            return self.iface.viewMenu()
        except AttributeError:
            return None

    def _add_view_action(self):
        menu = self._view_menu()
        if menu is None:
            return
        act = QAction(VIEW_ACTION_TEXT, self.iface.mainWindow())
        act.setObjectName(VIEW_ACTION_NAME)
        act.setCheckable(True)
        act.setChecked(not self.user.classic())
        act.setToolTip(VIEW_ACTION_TIP)
        act.setStatusTip(VIEW_ACTION_TIP)
        act.triggered.connect(lambda on: self.set_classic(not on))
        menu.addAction(act)
        self.view_action = act

    # Anleitung im QGIS-Menü „Hilfe › Plugins“
    def _help_menu(self):
        try:
            return self.iface.pluginHelpMenu()
        except AttributeError:
            return None

    def _add_help_action(self):
        menu = self._help_menu()
        if menu is None:
            return
        act = QAction(icons.ui_icon("hilfe"), guide.TITLE, self.iface.mainWindow())
        act.setObjectName(HELP_ACTION_NAME)
        act.setToolTip(guide.TIP)
        act.setStatusTip(guide.TIP)
        act.triggered.connect(lambda: guide.show_help("index", self.iface.mainWindow()))
        menu.addAction(act)
        self.help_action = act

    def _remove_help_action(self):
        if self.help_action is None:
            return
        menu = self._help_menu()
        if menu is not None:
            menu.removeAction(self.help_action)
        self.help_action.setParent(None)
        self.help_action.deleteLater()
        self.help_action = None

    def _remove_view_action(self):
        if self.view_action is None:
            return
        menu = self._view_menu()
        if menu is not None:
            menu.removeAction(self.view_action)
        self.view_action.setParent(None)  # sofort aus dem Hauptfenster, nicht erst beim Löschen
        self.view_action.deleteLater()
        self.view_action = None

    def set_classic(self, on):
        """Klassische QGIS-Oberfläche (Ribbon abgebaut, Werkzeugleisten zurück) oder Ribbon."""
        on = bool(on)
        if self.user is None:
            return
        self.user.set_classic(on)
        if self.view_action is not None:
            self.view_action.setChecked(not on)
        if on:
            # Abbauen erst nach dem auslösenden Menü (es kann im Ribbon selbst sitzen)
            QTimer.singleShot(0, self._enter_classic)
        else:
            self._build()

    def _enter_classic(self):
        if not self.user or not self.user.classic() or self.widget is None:
            return
        self._teardown()
        self.iface.messageBar().pushMessage(LOG_TAG, CLASSIC_MESSAGE, level=Qgis.Info, duration=8)

    # Aufbau und Abbau
    def _build(self):
        if self.widget is not None or self.base is None:
            return
        start = time.perf_counter()
        mw = self.iface.mainWindow()
        known = [c.source.get("object_name") for c in self.base.commands.values()]
        self.catalog = ExtensionCatalog(self.iface, self.base.extensions, self.hub,
                                        exclude=TOOLBAR_NAME, known=known)
        self._extend()
        self.ribbon = ext.visible(self.arrangements.effective())
        lap = self._lap(start, "erweiterungen")
        # Eigene Befehle (Steuerelemente, Galerien) und ihr Layer-Beobachter
        builtin_commands.register_all()
        custom_controls.register_all()
        dialog_commands.register_all()
        self.registered = True
        self.layers = LayerWatch(self.iface, self.hub)
        self.layers.start()
        self.resolver = ActionResolver(
            self.iface, CommandEnv(self.iface, self.layers, self.store, self.hub,
                                   host=self.arrangements))
        self.resolver.extensions = self.catalog
        icons.set_runtime_icons(self.catalog.icon)
        self.toolbars = ToolbarManager(mw, self.store)

        self.toolbar = QToolBar("Ribbon", mw)
        self.toolbar.setObjectName(TOOLBAR_NAME)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.toggleViewAction().setVisible(False)
        self.themes = theme.ThemeManager(self.user)
        self.whole = WholeTheme(mw)
        # Gesamtbild setzt eine eigene Palette: „Automatisch“ folgt weiter der von QGIS
        self.themes.lightness_override = self.whole.base_lightness
        self.themes.changed.connect(self._apply_whole)
        self.toolbar.setStyleSheet(theme.toolbar_qss(theme.current()))
        lap = self._lap(lap, "vorbereitung")
        # Kontext zuerst bestimmen, damit der Ribbon gleich im richtigen Zustand entsteht.
        self.logic = ContextLogic(self.ribbon)
        self.state = ContextState(self.iface, self.hub, self._on_context)
        self.state.start()
        self.widget = RibbonWidget(self.ribbon, self.resolver, self.hub, self.toolbar,
                                   logic=self.logic, user=self.user,
                                   arrangements=self.arrangements, theme_manager=self.themes)
        self.widget.whole_available = True
        self.widget.classicRequested.connect(lambda: self.set_classic(True))
        self.toolbar.addWidget(self.widget)
        self.keytips = KeyTipController(self.widget, mw)
        self.keytips.install()
        lap = self._lap(lap, "ribbon")

        self.toolbars.place_ribbon(self.toolbar)
        self.toolbars.hide(self.ribbon.hide_toolbars)
        if self.base.extensions.hide:
            self.toolbars.hide_bars(self.catalog.toolbars)
        self.catalog.changed.connect(self.request_rebuild)
        self.catalog.start()
        self._apply_whole()
        self._install_radios()
        self._lap(lap, "einsetzen")
        self.startup_ms = (time.perf_counter() - start) * 1000.0
        log.info_later(tr("Ribbon built in %.1f ms") % self.startup_ms)

    def _install_radios(self):
        try:
            view = self.iface.layerTreeView()
        except AttributeError:
            view = None
        if view is None:
            return
        self.radios = LayerTreeRadios(view, layer_tree_exclusive(view), self.hub)
        self.radios.install()

    def _lap(self, since, name):
        now = time.perf_counter()
        self.timings[name] = (now - since) * 1000.0
        return now

    def _extend(self):
        """Definition um Plugin-Aktionen und benötigte Werkzeuge erweitern (Anordnungen)."""
        self.catalog.scan()
        referenced = ext.referenced_ids(self.user.layout(), self.user.quick_access() or "",
                                        self.user.saved())
        needed = {c for c in referenced if ext.is_toolbox(c)}
        needed.update(ext.toolbox_id(f.algorithm) for f in self.catalog.found if f.algorithm)
        self.catalog.needed = needed
        base = ext.extend(self.base, self.catalog.found, self.catalog.algorithms(needed), referenced)
        self.arrangements.set_base(base)
        catalog = self.catalog
        self.arrangements.full_base = lambda: ext.with_algorithms(self.arrangements.base,
                                                                  catalog.algorithms())

    def _apply_whole(self):
        if self.whole is not None and self.themes is not None:
            self.whole.update(bool(self.themes.settings()["whole"]), theme.current())

    def _on_context(self, snapshot, events):
        changes = self.logic.update(snapshot, events)
        if changes and self.widget is not None:
            self.widget.apply_context(changes)

    def request_rebuild(self):
        """Ribbon mit der neuen Anordnung neu aufbauen (nach der Ereignisschleife)."""
        if self.widget is None or self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._rebuild)

    def _rebuild(self):
        self._pending = False
        if self.widget is None:
            return
        modal = QApplication.activeModalWidget()
        if modal is not None:
            # Nicht unter einem offenen Dialog abbauen (er kann aus dem Ribbon stammen)
            if self._after_modal is None:
                self._after_modal = _AfterModal(modal, self._after_modal_closed)
            return
        start = time.perf_counter()
        tab = self.widget.current_tab()
        self._teardown()
        self._build()
        if self.widget is not None and tab in self.widget.tab_ids():
            self.widget.select_tab(tab)
        self.rebuild_ms = (time.perf_counter() - start) * 1000.0
        log.info_later(tr("Ribbon rebuilt in %.1f ms") % self.rebuild_ms)

    def _after_modal_closed(self):
        self._after_modal = None
        self.request_rebuild()

    def _teardown(self, save_state=False):
        if self._after_modal is not None:
            self._after_modal.cancel()
            self._after_modal = None
        if self.catalog is not None:
            self.catalog.changed.disconnect(self.request_rebuild)
            self.catalog.stop()
        if self.keytips is not None:
            self.keytips.uninstall()
            self.keytips = None
        if self.widget is not None:
            self.widget.hide_popup()
        if self.radios is not None:
            self.radios.restore()
            self.radios = None
        if self.themes is not None:
            # Zuerst trennen: das Zurücksetzen der Palette soll nichts mehr auslösen
            self.themes.changed.disconnect(self._apply_whole)
            self.themes.stop()
            self.themes.lightness_override = None
        if self.whole is not None:
            self.whole.restore()
            self.whole = None
        if self.themes is not None:
            self.themes.deleteLater()
            self.themes = None
        if self.state is not None:
            self.state.stop()
            self.state = None
        if self.layers is not None:
            self.layers.stop()
            self.layers = None
        self.hub.disconnect_all()
        if self.toolbars is not None:
            self.toolbars.restore()
            self.toolbars.remove_ribbon()
            if save_state:
                # Beim Beenden hat QGIS den Zustand schon gespeichert (aboutToQuit, vor dem
                # Entladen), mit ausgeblendeten Leisten: so schreiben, wie ohne Ribbon
                self.toolbars.save_window_state()
            self.toolbars.deleteLater()
            self.toolbars = None
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None
        self.widget = None
        self.logic = None
        if self.resolver is not None:
            self.resolver.clear()
            self.resolver.extensions = None
            self.resolver = None
        if self.catalog is not None:
            icons.set_runtime_icons(None)
            self.catalog.deleteLater()
            self.catalog = None
        if self.arrangements is not None:
            self.arrangements.full_base = None
        if self.registered:
            builtin_commands.unregister_all()
            custom_controls.unregister_all()
            dialog_commands.unregister_all()
            self.registered = False

    def unload(self):
        self._teardown(save_state=True)
        yaml_cache.set_dir(None)
        self._remove_view_action()
        self._remove_help_action()
        guide.close_help()
        if self.arrangements is not None:
            self.arrangements.changed.disconnect(self.request_rebuild)
            self.arrangements.deleteLater()
            self.arrangements = None
