"""Zentrale Verwaltung von Signalverbindungen.

Jede Verbindung, die der Ribbon zu QGIS-Objekten aufbaut, läuft über einen
``SignalHub``. ``disconnect_all()`` trennt beim Entladen alles in einem
Schritt, auch wenn die Gegenseite (z. B. eine QGIS-Aktion) weiterlebt.

Der Hub merkt sich zu jeder Verbindung den Sender. Ist er schon gelöscht,
wird nicht getrennt: ``disconnect`` auf ein Signal eines Objekts, das C++
gelöscht hat, stürzt ab (Zugriffsverletzung), statt eine Ausnahme zu werfen.
Das passiert beim Beenden von QGIS, wenn vor dem Ribbon ein C++-Plugin
entladen wurde, dessen Aktionen der Ribbon spiegelt.
"""

from qgis.PyQt import sip


class SignalHub(object):
    def __init__(self):
        self._connections = []

    def connect(self, sender, name, slot):
        """``sender.<name>`` mit ``slot`` verbinden."""
        getattr(sender, name).connect(slot)
        self._connections.append((sender, name, slot))

    def disconnect_all(self):
        while self._connections:
            sender, name, slot = self._connections.pop()
            if sip.isdeleted(sender):
                continue
            try:
                getattr(sender, name).disconnect(slot)
            except (TypeError, RuntimeError):
                # Bereits getrennt
                pass

    def __len__(self):
        return len(self._connections)
