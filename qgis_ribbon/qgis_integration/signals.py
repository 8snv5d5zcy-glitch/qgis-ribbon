"""Zentrale Verwaltung von Signalverbindungen.

Jede Verbindung, die der Ribbon zu QGIS-Objekten aufbaut, läuft über einen
``SignalHub``. ``disconnect_all()`` trennt beim Entladen alles in einem
Schritt, auch wenn die Gegenseite (z. B. eine QGIS-Aktion) weiterlebt.

Der Hub merkt sich zu jeder Verbindung den Sender. Ist er schon gelöscht,
wird nicht getrennt: ``disconnect`` auf ein Signal eines Objekts, das C++
gelöscht hat, stürzt ab (Zugriffsverletzung), statt eine Ausnahme zu werfen.
Das passiert beim Beenden von QGIS, wenn vor dem Ribbon ein C++-Plugin
entladen wurde, dessen Aktionen der Ribbon spiegelt.

Fremde Wrapper festhalten (``keep_foreign_wrappers``): Der Ribbon hält
Python-Wrapper von QGIS-Objekten (Aktionen, Menüs, Projekt, Karte) in seinen
Strukturen, und diese hängen in Zyklen (Eintrag, Aufbaukontext, Auflösung).
Räumt die Speicherbereinigung von Python einen solchen Zyklus samt Wrapper ab,
gibt PyQt mit dem Wrapper auch alle Lambda- und ``partial``-Slots frei, die
irgendwer mit Signalen dieses Objekts verbunden hat; die Verbindung bleibt
aber bestehen. Das nächste Signal ruft dann freigegebenen Speicher auf und
QGIS stürzt ab (Zugriffsverletzung ohne Python-Zeile). Betroffen war zuerst
``mActionToggleEditing``: Das Plugin Verarbeitung hängt dort ein ``partial``
an ``triggered``. Vor jedem Abbau hält der Ribbon deshalb alle von C++
erzeugten Wrapper außerhalb des Plugins fest; sie bleiben erreichbar, und die
Speicherbereinigung lässt die fremden Slots in Ruhe.

Der Durchlauf über alle Python-Objekte kostet bei großen Projekten 40 bis
80 ms. Baut sich ein Ribbon im Layout-Fenster neu auf (jeder Abschnittswechsel
im Bericht), genügt ``keep_wrappers_from``: Freigeben kann der Abbau nur, was
von diesem Ribbon aus erreichbar ist (seine Objekte, die Python-Attribute
seiner Widgets und Aktionen, Closures und gebundene Methoden).
"""

import gc
import sys
import types
from functools import partial

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject

# Ablage außerhalb der Module des Plugins: Sie muss Entladen und Neuladen überleben,
# denn die Reste des abgebauten Ribbons räumt Python erst später ab.
KEEP_MODULE = "_qgis_ribbon_kept_wrappers"


def alive(obj):
    """False, wenn ``obj`` None ist oder C++ es schon gelöscht hat (Plugin entladen, Menü neu gebaut).

    Gemerkte Qt-Objekte fremder Herkunft vor jedem Gebrauch so prüfen: ein Aufruf
    auf ein gelöschtes Objekt wirft ``RuntimeError: wrapped C/C++ object … has been deleted``.
    """
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except TypeError:   # kein sip-Objekt
        return True


def kept_wrappers():
    """Festgehaltene Wrapper (id -> Wrapper); die Ablage entsteht beim ersten Zugriff."""
    host = sys.modules.get(KEEP_MODULE)
    if host is None:
        host = sys.modules[KEEP_MODULE] = types.ModuleType(KEEP_MODULE)
        host.kept = {}
    return host.kept


def keep_foreign_wrappers():
    """Alle Wrapper von Qt-Objekten festhalten, die C++ erzeugt hat (vor jedem Abbau aufrufen).

    Eigene Objekte des Ribbons (in Python erzeugt) bleiben draußen, damit der
    abgebaute Ribbon abgeräumt werden kann. Wrapper inzwischen gelöschter
    Objekte fallen dabei wieder heraus. Gibt die Zahl der neu festgehaltenen
    Wrapper zurück.
    """
    kept = kept_wrappers()
    for key in [key for key, obj in kept.items() if sip.isdeleted(obj)]:
        del kept[key]
    before = len(kept)
    qt_types = {}   # je Typ einmal prüfen: der Durchlauf geht über alle Python-Objekte
    for obj in gc.get_objects():
        # type() statt isinstance: isinstance fragt __class__ ab und wirft bei toten Proxys
        kind = type(obj)
        try:
            is_qt = qt_types.get(kind)
        except TypeError:   # Typ ohne Hash (eigene Metaklasse fremder Pakete): kein Qt-Objekt
            continue
        if is_qt is None:
            is_qt = qt_types[kind] = issubclass(kind, QObject)
        if is_qt and not sip.ispycreated(obj) and not sip.isdeleted(obj):
            kept[id(obj)] = obj
    return len(kept) - before


_NO_DESCENT = (types.ModuleType, type, types.FrameType, types.CodeType)


def _referents(obj):
    """Nachfolger im Objektgraphen; bei Funktionen nur Closure und Vorgaben, nicht die Modulglobalen."""
    if isinstance(obj, types.FunctionType):
        out = [c.cell_contents for c in (obj.__closure__ or ()) if _filled(c)]
        out.extend(obj.__defaults__ or ())
        out.extend((obj.__kwdefaults__ or {}).values())
        return out
    if isinstance(obj, partial):
        return [obj.func, obj.args, obj.keywords]
    return gc.get_referents(obj)


def _filled(cell):
    try:
        cell.cell_contents
    except ValueError:      # leere Zelle
        return False
    return True


def keep_wrappers_from(roots):
    """Wie ``keep_foreign_wrappers``, aber nur für Wrapper, die von ``roots`` aus erreichbar sind.

    Läuft durch Attribute, Container, Closures und gebundene Methoden; Module,
    Klassen und die Globalen von Funktionen bleiben draußen. Fremde Qt-Objekte
    werden festgehalten und nicht weiter abgelaufen, eigene (in Python erzeugte)
    weiter über ihre Attribute. Gibt die Zahl der neu festgehaltenen zurück.
    """
    kept = kept_wrappers()
    before = len(kept)
    seen = set()
    stack = list(roots)
    qt_types = {}
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        kind = type(obj)
        if issubclass(kind, _NO_DESCENT):
            continue
        try:
            is_qt = qt_types.get(kind)
            if is_qt is None:
                is_qt = qt_types[kind] = issubclass(kind, QObject)
        except TypeError:   # Typ ohne Hash (eigene Metaklasse fremder Pakete): kein Qt-Objekt
            is_qt = False
        if is_qt:
            if sip.isdeleted(obj):
                continue
            if not sip.ispycreated(obj):
                kept[id(obj)] = obj
                continue
        stack.extend(_referents(obj))
    return len(kept) - before


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
