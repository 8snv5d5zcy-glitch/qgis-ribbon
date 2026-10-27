"""Menüs anderer Plugins unter dem Ribbon-Knopf öffnen.

Manche Plugins öffnen beim Klick auf ihren Werkzeugleisten-Knopf ein Menü
aus eigenem Code, an der Stelle dieses Knopfs (``menu.popup(knopf.mapToGlobal
(...))``). Im Ribbon ist die Werkzeugleiste ausgeblendet; das Menü erschiene
dort, wo die Leiste zuletzt stand, weit weg vom Ribbon-Knopf.

``anchored(ziel)`` umschließt das Auslösen eines solchen Befehls mit einem
einmaligen Ereignisfilter an der Anwendung: Das erste Fenster, das in dieser
Zeit erscheint, wird, wenn es ein Menü ist, unter den Ribbon-Knopf gelegt.
Erscheint zuerst ein anderes Fenster (z. B. ein Dialog), bleibt alles, wie
es ist. Der Filter gilt nur für diesen Klick und ist danach wieder entfernt
(auch wenn das Plugin sein Menü blockierend mit ``exec`` öffnet, gilt er nur
bis zu dessen Rückkehr). Kein Zeitgeber, kein Abfragen.

Menüs, die Qt selbst an einem Knopf öffnet (``QToolButton.setMenu``), zeigt
der Ribbon ohnehin als eigenes Dropdown (Split-Button, siehe Erweiterungen).
"""

from contextlib import contextmanager

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QRect, Qt
from qgis.PyQt.QtGui import QCursor, QGuiApplication
from qgis.PyQt.QtWidgets import QApplication, QMenu, QToolButton

# Quelltypen, hinter denen Code anderer Plugins steckt
FOREIGN_SOURCES = ("extension", "plugin_action")
SPLIT_TOP = "ribbon_split_top"   # oberer Teil eines großen Split-Buttons (buttons.LargeSplitButton)


def anchor_rect(widget):
    """Globales Rechteck, unter dem das Menü erscheinen soll (Knopf oder Mauszeiger)."""
    if widget is not None:
        try:
            return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
        except RuntimeError:
            pass
    return QRect(QCursor.pos(), QPoint(QCursor.pos()))


def place_under(menu, rect):
    """``menu`` unter ``rect`` legen (globale Lage); passt es nicht darunter, darüber."""
    size = menu.sizeHint()
    pos = QPoint(rect.left(), rect.bottom() + 1)
    screen = QGuiApplication.screenAt(rect.center())
    if screen is not None:
        area = screen.availableGeometry()
        if pos.y() + size.height() > area.bottom() and rect.top() - size.height() >= area.top():
            pos.setY(rect.top() - size.height())
        pos.setX(max(area.left(), min(pos.x(), area.right() - size.width() + 1)))
    menu.move(pos)


class _NextMenu(QObject):
    """Ereignisfilter: legt das erste erscheinende Fenster, wenn es ein Menü ist, unter ``rect``."""

    def __init__(self, rect):
        QObject.__init__(self)
        self.rect = rect
        self.done = False
        self.moved = None

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        if self.done or event.type() != QEvent.Show or not obj.isWidgetType():
            return False
        if not obj.isWindow() or obj.windowType() == Qt.ToolTip:
            return False
        self.done = True
        if isinstance(obj, QMenu):
            place_under(obj, self.rect)
            self.moved = obj
        return False


@contextmanager
def anchored(widget):
    """Während des Blocks erscheint ein von fremdem Code geöffnetes Menü unter ``widget``."""
    app = QApplication.instance()
    if app is None:
        yield None
        return
    watcher = _NextMenu(anchor_rect(widget))
    app.installEventFilter(watcher)
    try:
        yield watcher
    finally:
        app.removeEventFilter(watcher)


def trigger_widget(action):
    """Knopf, über den ``action`` gerade ausgelöst wurde (unter dem Mauszeiger, gedrückt, sonst sichtbar)."""
    buttons = [w for w in action.associatedWidgets()
               if isinstance(w, QToolButton) and w.isVisible()]
    pos = QCursor.pos()
    found = None
    for w in buttons:
        if w.rect().contains(w.mapFromGlobal(pos)):
            found = w
            break
    if found is None:
        found = next((w for w in buttons if w.isDown() or w.hasFocus()), None)
    if found is None and buttons:
        found = buttons[0]
    if found is not None and found.objectName() == SPLIT_TOP:
        found = found.parentWidget()   # großer Split-Button: Menü unter den ganzen Knopf
    return found
