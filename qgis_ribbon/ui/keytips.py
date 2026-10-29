"""KeyTips: Ribbon per Tastatur bedienen, wie in Pro.

- Alt drücken und wieder loslassen (ohne andere Taste dazwischen) zeigt
  Ebene 0: Kürzel der Tabs, Schnellzugriff (1–9) und Suche (Q).
  Alt+Buchstabe in einem Zug bleibt bei QGIS (Menüs).
- Ein Tab-Kürzel wählt den Tab und zeigt Ebene 1: Kürzel aller Elemente.
  Ein Element-Kürzel löst es aus (Menüs öffnen sich, Steuerelemente
  bekommen den Fokus) und beendet den Modus.
- Eingeklappte Gruppen (adaptive Breite) bekommen auf Ebene 1 ein eigenes
  Kürzel; es öffnet die Gruppe und zeigt die Kürzel ihrer Elemente
  (Ebene 2). Die Element-Kürzel bleiben dieselben wie bei aufgeklappter
  Gruppe, damit sie unabhängig von der Fensterbreite gelten.
- Esc geht eine Ebene zurück, Rücktaste löscht das letzte Zeichen, Alt,
  ein Mausklick oder ein Fensterwechsel beenden den Modus.

Umsetzung: Ereignisfilter an der QApplication (läuft vor den Filtern der
Menüleiste). Im Modus werden alle Tastenereignisse verbraucht, auch
``ShortcutOverride``, damit keine QGIS-Tastenkürzel mitlaufen. Der Filter
wird beim Entladen entfernt. Die Buchstaben sind kleine Beschriftungen über
den Elementen (Kinder des Ribbons bzw. des aufgeklappten Ribbons oder der
Gruppe); ihr Aussehen kommt aus dem Stylesheet des Ribbons
(``QLabel#ribbon_keytip``, gesperrt über ``setEnabled(False)``).
"""

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication, QLabel

from ..core import keytips
from .controls.buttons import activate_button
from ..core.i18n import tr


def tab_codes(rw, overrides=None):
    """(automatische, wirksame) Kürzel aller Tabs; eigene Kürzel aus ``overrides`` bzw. den Einstellungen."""
    overrides = rw.user.keytips() if overrides is None else overrides
    labels = [t.label for t in rw.ribbon.tabs]
    fixed = {i: overrides[keytips.tab_key(t.id)] for i, t in enumerate(rw.ribbon.tabs)
             if keytips.tab_key(t.id) in overrides}
    auto, _ = keytips.top_level(labels, 0)
    effective, _ = keytips.top_level(labels, 0, fixed)
    return auto, effective


def element_codes(rw, tab_id, overrides=None):
    """Ziele eines Tabs mit Schlüssel, automatischem und wirksamem Kürzel.

    Vergeben wird über alle Ziele des Tabs (nicht nur die sichtbaren), damit
    die Kürzel stabil sind.
    """
    overrides = rw.user.keytips() if overrides is None else overrides
    targets = rw.targets(tab_id)
    keys = keytips.target_keys([(t.command.id if t.command is not None else None, t.label)
                                for t in targets])
    labels = [t.label for t in targets]
    fixed = {i: overrides[keytips.element_key(tab_id, k)] for i, k in enumerate(keys)
             if keytips.element_key(tab_id, k) in overrides}
    return targets, keys, keytips.assign(labels), keytips.assign(labels, fixed=fixed)


class Item(object):
    """Element einer KeyTip-Ebene: Kürzel, Widget (ggf. Rechteck darin), Aktion."""

    __slots__ = ("code", "label", "widget", "rect", "activate", "tab_id", "group")

    def __init__(self, label, widget, activate, rect=None, tab_id=None, group=None):
        self.code = None
        self.group = group
        self.label = label
        self.widget = widget
        self.rect = rect
        self.activate = activate
        self.tab_id = tab_id

    def enabled(self):
        return self.widget.isEnabled()


class KeyTipController(QObject):
    def __init__(self, ribbon_widget, main_window):
        QObject.__init__(self)
        self.rw = ribbon_widget
        self.mw = main_window
        self.active = False
        self.level = None          # 0, 1 oder 2 (eingeklappte Gruppe)
        self.group = None
        self.tab_id = None
        self.typed = ""
        self.items = []
        self.labels = []
        self._armed = False
        self._installed = False
        self._focus_before = None

    # Lebenszyklus
    def install(self):
        if not self._installed:
            QApplication.instance().installEventFilter(self)
            self._installed = True

    def uninstall(self):
        self.exit()
        if self._installed:
            QApplication.instance().removeEventFilter(self)
            self._installed = False

    # Ereignisse
    def eventFilter(self, obj, event):
        t = event.type()
        if self.active:
            if t == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if t == QEvent.Type.KeyPress:
                return self._key(event)
            if t == QEvent.Type.KeyRelease:
                return True
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                     QEvent.Type.NonClientAreaMouseButtonPress):
                self.exit()
                return False
            if t == QEvent.Type.ApplicationDeactivate or (t == QEvent.Type.WindowDeactivate and obj is self.mw):
                self.exit()
            return False
        if t == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Alt and self._alt_alone(event) \
                and self._window_ready():
            # Alt allein gehört dem Ribbon: die Menüleiste merkt sich „Alt gedrückt“
            # hier und holte sich beim Loslassen sonst den Fokus. Alt+Buchstabe
            # (QGIS-Menüs) läuft über den Buchstaben und bleibt unberührt.
            self._focus_before = QApplication.focusWidget()
            return True
        if t == QEvent.Type.ShortcutOverride and event.key() != Qt.Key.Key_Alt:
            # Alt+Buchstabe läuft als Tastenkürzel (Menü), ein KeyPress kommt dann nicht
            self._armed = False
        if t == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Alt:
                if not event.isAutoRepeat():  # gehaltenes Alt wiederholt: Zustand bleibt
                    self._armed = self._alt_alone(event) and self._window_ready()
            else:
                self._armed = False
        elif t == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Alt and not event.isAutoRepeat() and self._armed \
                    and self._window_ready():  # kein inzwischen geöffnetes Menü
                self._armed = False
                self.start()
                return True  # sonst setzt die Menüleiste den Fokus auf sich
        elif t in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self._armed = False
        return False

    @staticmethod
    def _alt_alone(event):
        # Ob Alt selbst im Modifier steht, hängt von der Plattform ab; andere
        # Modifier schließen aus (AltGr kommt unter Windows als Strg+Alt).
        return not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                                        | Qt.KeyboardModifier.MetaModifier)

    def _window_ready(self):
        return (self.mw.isActiveWindow() and QApplication.activePopupWidget() is None
                and self.rw.isVisible())

    def _key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.back()
            return True
        if key in (Qt.Key.Key_Alt, Qt.Key.Key_F10):
            self.exit()
            return True
        if key == Qt.Key.Key_Backspace:
            self.typed = self.typed[:-1]
            self._update_labels()
            return True
        text = event.text().upper()
        if len(text) == 1 and (text.isdigit() or "A" <= text <= "Z"):
            self.type_char(text)
            return True
        # Andere Tasten (Pfeile, Tab ...) beenden den Modus und gehen weiter
        self.exit()
        return False

    # Ebenen
    def start(self):
        self.active = True
        before = self._focus_before
        if before is not None and QApplication.focusWidget() is self.mw.menuBar():
            before.setFocus(Qt.FocusReason.OtherFocusReason)
        self.show_level0()

    def exit(self):
        self._clear_labels()
        self.active = False
        self.level = None
        self.tab_id = None
        self.group = None
        self.typed = ""
        self.items = []

    def back(self):
        if self.level == 2:
            group, self.group = self.group, None
            group.close_popup()
            self.show_level1(self.tab_id)
        elif self.level == 1:
            if self.rw.minimized:
                self.rw.hide_popup()
            self.show_level0()
        else:
            self.exit()

    def level0_items(self):
        rw = self.rw
        tabs = list(rw.ribbon.tabs)
        _auto, codes = tab_codes(rw)
        qat_codes = keytips.QUICK_ACCESS_KEYS[:len(rw.quick.buttons)]
        items = []
        for i, tab in enumerate(tabs):
            if not rw.tabbar.isTabVisible(i):
                continue
            item = Item(tab.label, rw.tabbar, None, rect=rw.tabbar.tabRect(i), tab_id=tab.id)
            item.code = codes[i]
            items.append(item)
        for btn, code in zip(rw.quick.buttons, qat_codes):
            item = Item(btn.defaultAction().text(), btn, lambda b=btn: activate_button(b))
            item.code = code
            items.append(item)
        search = Item(tr("Search"), rw.search, self._focus_search)
        search.code = keytips.SEARCH_KEY
        items.append(search)
        return items

    def level1_items(self, tab_id):
        targets, _keys, _auto, codes = element_codes(self.rw, tab_id)
        items = []
        for t, code in zip(targets, codes):
            if not t.widget.isVisible():
                continue
            item = Item(t.label, t.widget, t.activate)
            item.code = code
            items.append(item)
        groups = [g for g in self.rw.collapsed_groups(tab_id)
                  if g.collapse_button is not None and g.collapse_button.isVisible()]
        if groups:
            # Eigene Kürzel um alle Element-Kürzel herum (auch die der eingeklappten Elemente)
            group_codes = keytips.assign([g.group.label for g in groups], reserved=[c for c in codes if c])
            for g, code in zip(groups, group_codes):
                item = Item(g.group.label, g.collapse_button, None, group=g)
                item.code = code
                items.append(item)
        return items

    def level2_items(self, group):
        """Elemente einer aufgeklappten (eingeklappten) Gruppe mit ihren Ebene-1-Kürzeln."""
        targets, _keys, _auto, codes = element_codes(self.rw, self.tab_id)
        items = []
        for t, code in zip(targets, codes):
            if t.widget.isVisible() and t.widget.window() is group.popup:
                item = Item(t.label, t.widget, t.activate)
                item.code = code
                items.append(item)
        return items

    def show_level0(self):
        self.level = 0
        self.tab_id = None
        self.typed = ""
        self.items = self.level0_items()
        self._show_labels()

    def show_level1(self, tab_id):
        if not self.active:
            return
        self.level = 1
        self.tab_id = tab_id
        self.typed = ""
        self.items = self.level1_items(tab_id)
        self._show_labels()

    def show_level2(self, group):
        if not self.active or not group.popup.isVisible():
            return
        self.level = 2
        self.group = group
        self.typed = ""
        self.items = self.level2_items(group)
        self._show_labels()

    def type_char(self, ch):
        self.typed += ch
        hit, more = keytips.matches([i.code for i in self.items], self.typed)
        if hit is not None:
            self._hit(self.items[hit])
        elif not more:
            self.typed = ""  # unbekanntes Kürzel: verwerfen, Modus bleibt
        self._update_labels()

    def _hit(self, item):
        if self.level == 0 and item.tab_id is not None:
            self._clear_labels()
            self.rw.select_tab(item.tab_id)
            if self.rw.minimized:
                self.rw.show_popup()
            # Erst nach dem Layout des Tabs sind die Positionen gültig
            QTimer.singleShot(0, lambda: self.show_level1(item.tab_id))
            self.items = []
            self.typed = ""
            return
        if item.group is not None:
            self._clear_labels()
            item.group.open_popup()
            QTimer.singleShot(0, lambda: self.show_level2(item.group))
            self.items = []
            self.typed = ""
            return
        if not item.enabled():
            self.typed = ""
            return
        self.exit()
        item.activate()

    def _focus_search(self):
        self.rw.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.rw.search.selectAll()
        return True

    # Beschriftungen
    def _parent_for(self, widget):
        """Ribbon (im Hauptfenster) oder das aufgeklappte Ribbon (eigenes Fenster)."""
        if widget.window() is self.rw.window():
            return self.rw
        return widget.window()

    def _show_labels(self):
        self._clear_labels()
        for item in self.items:
            parent = self._parent_for(item.widget)
            label = QLabel(item.code, parent)
            label.setObjectName("ribbon_keytip")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setEnabled(item.enabled())
            label.adjustSize()
            label.setMinimumWidth(max(label.width(), label.height()))
            label.resize(max(label.width(), label.height()), label.height())
            rect = item.rect if item.rect is not None else item.widget.rect()
            bottom_center = item.widget.mapTo(parent, QPoint(rect.center().x(), rect.bottom()))
            x = bottom_center.x() - label.width() // 2
            y = bottom_center.y() - label.height() // 2
            area = QRect(0, 0, parent.width(), parent.height())
            x = max(area.left(), min(x, area.right() - label.width()))
            y = max(area.top(), min(y, area.bottom() - label.height()))
            label.move(x, y)
            label.show()
            label.raise_()
            label.setProperty("ribbon_code", item.code)
            self.labels.append(label)

    def _update_labels(self):
        for label in self.labels:
            code = label.property("ribbon_code") or ""
            label.setVisible(code.startswith(self.typed))

    def _clear_labels(self):
        for label in self.labels:
            try:
                label.hide()
                label.deleteLater()
            except RuntimeError:
                pass
        self.labels = []
