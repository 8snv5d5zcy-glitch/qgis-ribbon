"""QGIS-Toolbars ausblenden und exakt wiederherstellen, Ribbon-Toolbar einsetzen.

Regeln:

- Nur die in der Ribbon-Definition genannten QGIS-Kern-Toolbars werden
  ausgeblendet, und nur, wenn sie sichtbar waren. ``restore()`` blendet genau
  diese wieder ein.
- QGIS speichert beim Beenden den Fensterzustand (``UI/state``) am Signal
  ``aboutToQuit`` und entlädt erst danach die Plugins; das Schließen-Ereignis
  des Hauptfensters ignoriert QGIS (``closeEvent`` → ``fileExit``). Im
  gespeicherten Zustand fehlen also die ausgeblendeten Toolbars. Das Plugin
  schreibt ihn deshalb beim Entladen nach ``restore()`` und ``remove_ribbon()``
  neu (``save_window_state``), so wie QGIS ihn ohne Ribbon gespeichert hätte.
  (Ein Event-Filter auf ``Close`` wäre im echten QGIS wirkungslos.)
- Die Liste der ausgeblendeten Toolbars steht zusätzlich in den QGIS-Einstellungen.
  Bleibt sie nach einem Absturz stehen, gelten diese Toolbars beim nächsten
  Laden weiter als ursprünglich sichtbar.
- Leisten anderer Plugins (``hide_bars``) werden ebenso behandelt;
  Leisten ohne objectName nur über ihr Objekt (QGIS speichert ihren Zustand
  ohnehin nicht).
"""

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtWidgets import QToolBar

SETTINGS_KEY = "qgis_ribbon/ausgeblendete_toolbars"
STATE_KEY = "UI/state"   # Fensterzustand, den QGIS beim Start wiederherstellt


def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


class ToolbarManager(QObject):
    def __init__(self, main_window, settings=None):
        QObject.__init__(self)
        self.mw = main_window
        self.settings = settings or QgsSettings()
        self._hidden = []          # von uns ausgeblendete Toolbars (objectName)
        self._hidden_bars = []     # ausgeblendete Leisten ohne objectName (Objekt)
        self._ribbon = None
        self._break_before = None  # Toolbar, vor der wir einen Umbruch eingefügt haben

    def _toolbars(self):
        """Toolbars des Hauptfensters (direkte Kinder; rekursive Suche ist teuer)."""
        return self.mw.findChildren(QToolBar, options=Qt.FindDirectChildrenOnly)

    def _toolbar(self, name):
        return self.mw.findChild(QToolBar, name, options=Qt.FindDirectChildrenOnly)

    # Ribbon-Toolbar
    def _top_toolbars(self):
        bars = [tb for tb in self._toolbars()
                if tb is not self._ribbon
                and self.mw.toolBarArea(tb) == Qt.TopToolBarArea]
        visible = [tb for tb in bars if not tb.isHidden()]
        return sorted(visible or bars, key=lambda tb: (tb.geometry().y(), tb.geometry().x()))

    def place_ribbon(self, toolbar):
        """Ribbon-Toolbar als eigene erste Zeile oben einsetzen."""
        self._ribbon = toolbar
        top = self._top_toolbars()
        if top:
            first = top[0]
            self.mw.insertToolBar(first, toolbar)
            self.mw.insertToolBarBreak(first)
            self._break_before = first
        else:
            self.mw.addToolBar(Qt.TopToolBarArea, toolbar)
        toolbar.show()

    def remove_ribbon(self):
        if self._ribbon is None:
            return
        if self._break_before is not None:
            self.mw.removeToolBarBreak(self._break_before)
            self._break_before = None
        self.mw.removeToolBar(self._ribbon)
        self._ribbon = None

    # Kern-Toolbars
    def hide(self, names):
        """Sichtbare Toolbars aus ``names`` ausblenden und merken."""
        leftover = set(_as_list(self.settings.value(SETTINGS_KEY, [])))
        wanted = set(names)
        for tb in self._toolbars():
            name = tb.objectName()
            if name not in wanted or name in self._hidden:
                continue
            if not tb.isHidden():
                tb.hide()
                self._hidden.append(name)
            elif name in leftover:  # nach Absturz noch versteckt
                self._hidden.append(name)
        self.settings.setValue(SETTINGS_KEY, list(self._hidden))

    def hide_bars(self, bars):
        """Leisten (Objekte, z. B. von Plugins) ausblenden, sofern sichtbar."""
        named = [tb.objectName() for tb in bars if tb.objectName()]
        if named:
            self.hide(named)
        for tb in bars:
            if not tb.objectName() and not tb.isHidden() and tb not in self._hidden_bars:
                tb.hide()
                self._hidden_bars.append(tb)

    def _unnamed(self):
        out = []
        for tb in self._hidden_bars:
            try:
                tb.objectName()
            except RuntimeError:   # Plugin entladen, Leiste gelöscht
                continue
            out.append(tb)
        return out

    def _show_hidden(self):
        for name in self._hidden:
            tb = self._toolbar(name)
            if tb is not None:
                tb.show()
        for tb in self._unnamed():
            tb.show()

    def restore(self):
        """Ausgeblendete Toolbars wieder einblenden und Merkliste löschen."""
        self._show_hidden()
        self._hidden = []
        self._hidden_bars = []
        self.settings.remove(SETTINGS_KEY)

    @property
    def hidden(self):
        return list(self._hidden)

    def save_window_state(self):
        """Fensterzustand für den nächsten QGIS-Start speichern (nach ``restore``/``remove_ribbon``).

        Erst das Layout des Hauptfensters anwenden: Der Zustand enthält Lage und
        Größe der Leisten, und eben eingeblendete Leisten haben noch keine.
        """
        layout = self.mw.layout()
        if layout is not None:
            layout.activate()
        self.settings.setValue(STATE_KEY, self.mw.saveState())
