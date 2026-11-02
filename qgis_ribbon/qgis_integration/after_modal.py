"""Neuaufbau des Ribbons aufschieben, solange ein modaler Dialog offen ist.

Der Dialog kann aus dem Ribbon selbst stammen (Editor, Erweiterungsverwaltung); unter
ihm abzubauen löscht, was er gerade braucht.
"""

from qgis.PyQt.QtCore import QEvent, QObject, QTimer


class AfterModal(QObject):
    """Ruft ``callback`` auf, sobald der modale Dialog ``widget`` geschlossen ist."""

    def __init__(self, widget, callback):
        QObject.__init__(self)
        self.widget = widget
        self.callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        if obj is self.widget and event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
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
