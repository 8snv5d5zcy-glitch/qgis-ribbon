"""Schnellzugriffsleiste links neben den Tabs.

Kleine Buttons für die Befehle der Leiste (Standard aus der Definition oder
Anpassung des Nutzers, ``core.quick_access``). Sie spiegeln die QGIS-Aktionen
wie alle Ribbon-Buttons. Der Pfeil am Ende öffnet ein Menü zum Anpassen:
Einträge abwählen, Standard wiederherstellen, Kürzel anpassen, Ribbon minimieren,
dazu die Einträge zum Anpassen des Ribbons (``extend_menu``).
Hinzufügen geht per Rechtsklick auf einen Button im Ribbon.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from . import icons
from .controls.buttons import MENU_ARROW, command_button
from ..core.i18n import tr

CUSTOMIZE_TEXT = tr("Customize Quick Access Toolbar")


class QuickAccessBar(QWidget):
    removeRequested = pyqtSignal(object)   # Command
    resetRequested = pyqtSignal()
    minimizeToggled = pyqtSignal()
    keytipsRequested = pyqtSignal()

    def __init__(self, ctx, parent=None):
        QWidget.__init__(self, parent)
        self.setObjectName("ribbon_quick_access")
        self._ctx = ctx
        self.commands = ()
        self.buttons = []
        self.minimized = False
        self.extend_menu = None  # callable(menu): weitere Einträge am Ende des Menüs
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(2, 0, 6, 0)
        self._lay.setSpacing(0)
        self.customize = QToolButton(self)
        self.customize.setAutoRaise(True)
        icon = icons.ui_icon("chevron_down")
        if icon.isNull():
            self.customize.setText(MENU_ARROW)
        else:
            self.customize.setIcon(icon)
        self.customize.setFixedSize(20, 26)
        self.customize.setToolTip(CUSTOMIZE_TEXT)
        self.customize.setObjectName("ribbon_quick_access_customize")
        self.menu = QMenu(self.customize)
        self.menu.aboutToShow.connect(self._fill_menu)
        self.customize.setMenu(self.menu)
        self.customize.setPopupMode(QToolButton.InstantPopup)
        self._lay.addWidget(self.customize)

    def set_commands(self, commands):
        """Buttons neu aufbauen (nach einer Anpassung)."""
        for btn in self.buttons:
            self._ctx.widget_commands.pop(btn, None)
            if btn.defaultAction() is not None:
                self._ctx.unregister(btn.defaultAction())
            btn.setParent(None)
            btn.deleteLater()
        self.buttons = []
        self.commands = tuple(commands)
        for i, cmd in enumerate(self.commands):
            btn = command_button(cmd, "small", self._ctx, self)
            btn.setObjectName("ribbon_qat_" + cmd.id)
            self._lay.insertWidget(i, btn)
            self.buttons.append(btn)

    def _fill_menu(self):
        # Untermenüs vom letzten Öffnen (Anordnungen) löschen; clear() entfernt nur die Aktionen
        for sub in self.menu.findChildren(QMenu, options=Qt.FindDirectChildrenOnly):
            sub.deleteLater()
        self.menu.clear()
        title = self.menu.addAction(CUSTOMIZE_TEXT)
        title.setEnabled(False)
        for cmd in self.commands:
            act = self.menu.addAction(cmd.label)
            act.setCheckable(True)
            act.setChecked(True)
            act.setToolTip(tr("Unchecking removes the command from the toolbar"))
            act.triggered.connect(lambda _c=False, c=cmd: self.removeRequested.emit(c))
        self.menu.addSeparator()
        hint = self.menu.addAction(tr("To add: right-click a command in the ribbon"))
        hint.setEnabled(False)
        self.menu.addAction(tr("Restore Defaults"), self.resetRequested.emit)
        self.menu.addSeparator()
        self.menu.addAction(tr("Customize KeyTips …"), self.keytipsRequested.emit)
        self.menu.addAction(tr("Pin the Ribbon") if self.minimized else tr("Minimize the Ribbon"),
                            self.minimizeToggled.emit)
        if self.extend_menu is not None:
            self.menu.addSeparator()
            self.extend_menu(self.menu)
