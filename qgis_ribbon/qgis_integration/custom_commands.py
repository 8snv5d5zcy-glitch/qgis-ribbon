"""Registry der eigenen Befehle (Quelltyp ``custom``).

Drei Arten, je nach ``kind`` beim Registrieren:

- ``button``: ``factory(env, command) -> callable | QAction``. Ein Callable
  wird beim Klick ausgeführt. Eine QAction (z. B. ``StateAction``) wird wie
  eine QGIS-Aktion gespiegelt: der Ribbon übernimmt aktiv/abgehakt über
  deren Signal ``changed``.
- ``control``: ``factory(env, command, ctx, parent, size) -> QWidget``.
  Steuerelement im Ribbon (Regler, Combobox, Farbwahl ...). Gebaut wird es
  in ``ui``; die Fabrik registriert ``ui.controls.custom``.
- ``gallery``: ``factory(env, command) -> callable``, das die Einträge liefert,
  die erst zur Laufzeit feststehen (Liste von ``GalleryEntry``). Aufgerufen
  wird es beim Öffnen der Galerie, nicht dauernd.

Parameter aus der Ribbon-Definition stehen in ``command.source.get("args")``.
``env`` (``CommandEnv``) gibt Zugriff auf ``iface`` und den Beobachter des
aktiven Layers. Nicht registrierte IDs erscheinen im Ribbon ausgegraut.
"""

from ..core.i18n import tr

KINDS = ("button", "control", "gallery")

_REGISTRY = {}


def register(command_id, factory, kind="button"):
    if kind not in KINDS:
        raise ValueError(tr("Unknown kind of built-in command: %r") % kind)
    if command_id in _REGISTRY:
        raise ValueError(tr("Built-in command registered twice: %s") % command_id)
    _REGISTRY[command_id] = (kind, factory)


def unregister(command_id):
    _REGISTRY.pop(command_id, None)


def get(command_id):
    entry = _REGISTRY.get(command_id)
    return entry[1] if entry else None


def kind_of(command_id):
    entry = _REGISTRY.get(command_id)
    return entry[0] if entry else None


def registered():
    return sorted(_REGISTRY)


class GalleryEntry(object):
    """Eintrag einer Galerie, der erst zur Laufzeit feststeht (Lesezeichen, Grundkarten ...)."""

    __slots__ = ("label", "icon", "callback", "checked", "tooltip", "section")

    def __init__(self, label, callback, icon=None, checked=None, tooltip=None, section=None):
        self.label = label
        self.callback = callback
        self.icon = icon
        self.checked = checked      # None: nicht abhakbar
        self.tooltip = tooltip
        self.section = section      # Überschrift, unter der der Eintrag steht


class CommandEnv(object):
    """Umgebung der eigenen Befehle: ``iface``, Layer-Beobachter, eigene Objekte.

    Objekte, die Fabriken anlegen (QActions, Gruppen), werden über ``keep``
    festgehalten und in ``close`` gelöscht. ``shared`` legt ein Objekt je
    Schlüssel nur einmal an (z. B. gemeinsame Gruppe der Abfragemodi).
    Signale von QGIS-Objekten (Karte, Projekt) verbinden Befehle über ``hub``;
    der Hub wird beim Entladen zentral getrennt. ``host`` ist die Anordnung des
    Ribbons (``arrangements.Arrangements``) für Befehle, die den Ribbon selbst
    anpassen (Galerie anpassen); ohne Plugin None.
    """

    def __init__(self, iface, layers=None, settings=None, hub=None, host=None):
        self.iface = iface
        self.layers = layers        # LayerWatch oder None
        self.settings = settings    # QgsSettings (None: QGIS-Einstellungen; Tests: eigene Datei)
        self.hub = hub              # zentraler SignalHub (None: Befehle verbinden nichts)
        self.host = host            # Arrangements oder None
        self._owned = []
        self._shared = {}

    def keep(self, obj):
        self._owned.append(obj)
        return obj

    def shared(self, key, create):
        if key not in self._shared:
            self._shared[key] = self.keep(create())
        return self._shared[key]

    def close(self):
        self._shared.clear()
        while self._owned:
            obj = self._owned.pop()
            close = getattr(obj, "close_binding", None)
            if close is not None:
                close()
            if hasattr(obj, "deleteLater"):
                try:
                    obj.deleteLater()
                except RuntimeError:
                    pass
