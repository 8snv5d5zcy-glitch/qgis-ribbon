"""Zentrale Verwaltung von Signalverbindungen.

Jede Verbindung, die der Ribbon zu QGIS-Objekten aufbaut, läuft über einen
``SignalHub``. ``disconnect_all()`` trennt beim Entladen alles in einem
Schritt, auch wenn die Gegenseite (z. B. eine QGIS-Aktion) weiterlebt.
"""


class SignalHub(object):
    def __init__(self):
        self._connections = []

    def connect(self, signal, slot):
        signal.connect(slot)
        self._connections.append((signal, slot))

    def disconnect_all(self):
        while self._connections:
            signal, slot = self._connections.pop()
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                # Bereits getrennt oder Objekt schon gelöscht
                pass

    def __len__(self):
        return len(self._connections)
