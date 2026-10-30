"""QGIS-Menüleiste ausblenden und exakt wiederherstellen; ihre Menüs als ein Dropdown.

Ausgeblendet wird über die Höhe 0, nicht über ``hide()``: Qt schaltet die
Tastenkürzel einer Aktion ab, wenn alle Widgets, in denen sie steht,
unsichtbar sind. Da der Ribbon die QGIS-Werkzeugleisten ausblendet, hängen
viele Aktionen (Speichern, Rückgängig ...) nur noch an den Menüs der
Menüleiste. Mit Höhe 0 bleibt die Leiste für Qt sichtbar, Kürzel und
Alt+Buchstabe funktionieren weiter. ``restore()`` setzt Mindest- und
Höchsthöhe auf die Werte von vorher zurück.

Eine native Menüleiste (macOS, globale Menüs unter Linux) steht nicht im
Fenster; dort gibt es nichts auszublenden (``can_hide``), die Option fehlt.

``fill_menu`` füllt ein eigenes Menü mit den Menüs der Menüleiste (deren
Menüaktionen, unverändert), damit sie auch bei ausgeblendeter Leiste
erreichbar bleiben. Aufgerufen wird es bei jedem Öffnen, damit Menüs von
Plugins, die später dazukommen, mit drin sind.
"""


def menu_bar(main_window):
    try:
        return main_window.menuBar() if main_window is not None else None
    except (AttributeError, RuntimeError):
        return None


def can_hide(main_window):
    """Lässt sich die Menüleiste ausblenden? Nicht, wenn sie nativ außerhalb des Fensters steht."""
    bar = menu_bar(main_window)
    return bar is not None and not bar.isNativeMenuBar()


class MenuBarHider(object):
    def __init__(self, main_window):
        self.mw = main_window
        self._saved = None   # (Mindesthöhe, Höchsthöhe) vor dem Ausblenden

    @property
    def hidden(self):
        return self._saved is not None

    def hide(self):
        bar = menu_bar(self.mw)
        if bar is None or self._saved is not None or not can_hide(self.mw):
            return
        self._saved = (bar.minimumHeight(), bar.maximumHeight())
        bar.setMinimumHeight(0)
        bar.setMaximumHeight(0)

    def restore(self):
        if self._saved is None:
            return
        low, high = self._saved
        self._saved = None
        bar = menu_bar(self.mw)
        if bar is None:
            return
        try:
            bar.setMinimumHeight(low)
            bar.setMaximumHeight(high)
        except RuntimeError:  # Hauptfenster beim Beenden schon gelöscht
            pass

    def set_hidden(self, on):
        if on:
            self.hide()
        else:
            self.restore()


def fill_menu(menu, main_window):
    """``menu`` neu füllen: je sichtbarem Menü der Menüleiste dessen Menüaktion."""
    menu.clear()
    bar = menu_bar(main_window)
    if bar is None:
        return
    for act in bar.actions():
        if act.menu() is not None and act.isVisible():
            menu.addAction(act)
