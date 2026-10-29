"""Nutzeranpassungen des Ribbons in den QGIS-Einstellungen.

Gespeichert werden nur Einstellungen, die der Nutzer selbst ändert: die
Schnellzugriffsleiste (Liste der Befehls-IDs), ob der Ribbon minimiert
ist, eigene KeyTips (JSON: Schlüssel aus ``core.keytips`` -> Kürzel), die
Anordnung der Tabs, Gruppen und Galerien (JSON, ``core.customization``), die
gespeicherten Anordnungen (JSON: Name -> Anordnung), ob die klassische
QGIS-Oberfläche gewählt und die Menüleiste ausgeblendet ist und das Design
(Modus, Akzent, Gesamtbild, Animationen, eigene Icons). Sie bleiben beim Entladen erhalten; das
Hauptfenster stellt ``unload()`` trotzdem exakt wieder her.

Tests übergeben eine eigene Einstellungsdatei (``settings``), nie das echte
Profil.
"""

import json

from qgis.core import QgsSettings

PREFIX = "qgis_ribbon/"
KEY_QUICK_ACCESS = PREFIX + "schnellzugriff"
KEY_MINIMIZED = PREFIX + "minimiert"
KEY_KEYTIPS = PREFIX + "kuerzel"
KEY_LAYOUT = PREFIX + "anordnung"
KEY_SAVED = PREFIX + "anordnungen"
KEY_CURRENT = PREFIX + "anordnung_aktuell"
KEY_CLASSIC = PREFIX + "klassisch"
KEY_MENUBAR_HIDDEN = PREFIX + "menueleiste_aus"
KEY_EDITOR_SIZE = PREFIX + "editor/groesse"
KEY_DESIGN_MODE = PREFIX + "design/modus"
KEY_DESIGN_ACCENT = PREFIX + "design/akzent"
KEY_DESIGN_WHOLE = PREFIX + "design/gesamtbild"
KEY_DESIGN_ANIMATIONS = PREFIX + "design/animationen"
KEY_DESIGN_ICONS = PREFIX + "design/eigene_icons"


def _json(value, kind):
    """Gespeicherten JSON-Text lesen; ``None`` bei fehlendem oder unlesbarem Wert."""
    if not value:
        return None
    try:
        data = json.loads(str(value))
    except ValueError:
        return None
    return data if isinstance(data, kind) else None


def _bool(value):
    return str(value).lower() in ("true", "1")


class UserSettings(object):
    def __init__(self, settings=None):
        self._settings = settings

    @property
    def settings(self):
        # Eine Instanz wiederverwenden: QSettings-Objekte desselben Prozesses
        # sehen gegenseitig ihre Änderungen, ein neues kostet je ~1,5 ms
        if self._settings is None:
            self._settings = QgsSettings()
        return self._settings

    def quick_access(self):
        """Gespeicherte Liste (Text) oder None, wenn nichts angepasst wurde."""
        value = self.settings.value(KEY_QUICK_ACCESS, None)
        return None if value is None else str(value)

    def set_quick_access(self, text):
        self.settings.setValue(KEY_QUICK_ACCESS, text)

    def reset_quick_access(self):
        self.settings.remove(KEY_QUICK_ACCESS)

    def minimized(self):
        return _bool(self.settings.value(KEY_MINIMIZED, "false"))

    def set_minimized(self, on):
        self.settings.setValue(KEY_MINIMIZED, "true" if on else "false")

    def keytips(self):
        """Eigene Kürzel {Schlüssel: Kürzel}; leer, wenn nichts angepasst (oder unlesbar)."""
        data = _json(self.settings.value(KEY_KEYTIPS, None), dict) or {}
        return {str(k): str(v) for k, v in data.items()}

    def set_keytips(self, overrides):
        if overrides:
            self.settings.setValue(KEY_KEYTIPS, json.dumps(dict(sorted(overrides.items()))))
        else:
            self.settings.remove(KEY_KEYTIPS)

    # Anordnung
    def layout(self):
        """Angepasste Anordnung (dict) oder None (Standard der Definition)."""
        return _json(self.settings.value(KEY_LAYOUT, None), dict)

    def set_layout(self, data):
        if data:
            self.settings.setValue(KEY_LAYOUT, json.dumps(data, ensure_ascii=False, sort_keys=True))
        else:
            self.settings.remove(KEY_LAYOUT)

    def saved(self):
        """Gespeicherte Anordnungen {Name: Anordnung (dict, ``core.customization.make_bundle``)}."""
        return _json(self.settings.value(KEY_SAVED, None), dict) or {}

    def set_saved(self, saved):
        if saved:
            self.settings.setValue(KEY_SAVED, json.dumps(saved, ensure_ascii=False, sort_keys=True))
        else:
            self.settings.remove(KEY_SAVED)

    def current_name(self):
        """Name der gespeicherten Anordnung, in der gerade gearbeitet wird (zuletzt geladen oder gespeichert)."""
        value = self.settings.value(KEY_CURRENT, None)
        return str(value) if value else None

    def set_current_name(self, name):
        if name:
            self.settings.setValue(KEY_CURRENT, name)
        else:
            self.settings.remove(KEY_CURRENT)

    def classic(self):
        """Klassische QGIS-Oberfläche statt Ribbon."""
        return _bool(self.settings.value(KEY_CLASSIC, "false"))

    def set_classic(self, on):
        if on:
            self.settings.setValue(KEY_CLASSIC, "true")
        else:
            self.settings.remove(KEY_CLASSIC)

    def menubar_hidden(self):
        """QGIS-Menüleiste ausgeblendet (nur, solange der Ribbon steht)."""
        return _bool(self.settings.value(KEY_MENUBAR_HIDDEN, "false"))

    def set_menubar_hidden(self, on):
        if on:
            self.settings.setValue(KEY_MENUBAR_HIDDEN, "true")
        else:
            self.settings.remove(KEY_MENUBAR_HIDDEN)

    # Design „Kontur“
    def editor_size(self):
        """Letzte Größe des Ribbon-Editors (Breite, Höhe) oder None."""
        value = str(self.settings.value(KEY_EDITOR_SIZE, "") or "")
        try:
            w, h = (int(v) for v in value.split(","))
        except ValueError:
            return None
        return (w, h) if w > 0 and h > 0 else None

    def set_editor_size(self, width, height):
        self.settings.setValue(KEY_EDITOR_SIZE, "%d,%d" % (width, height))

    def design(self):
        """Design-Einstellungen: Modus, Akzent, Gesamtbild, Animationen, eigene Icons."""
        return {
            "mode": str(self.settings.value(KEY_DESIGN_MODE, "auto") or "auto"),
            "accent": str(self.settings.value(KEY_DESIGN_ACCENT, "") or ""),
            "whole": _bool(self.settings.value(KEY_DESIGN_WHOLE, "false")),
            "animations": _bool(self.settings.value(KEY_DESIGN_ANIMATIONS, "true")),
            "icons": _bool(self.settings.value(KEY_DESIGN_ICONS, "true")),
        }

    def set_design(self, key, value):
        name = {"mode": KEY_DESIGN_MODE, "accent": KEY_DESIGN_ACCENT, "whole": KEY_DESIGN_WHOLE,
                "animations": KEY_DESIGN_ANIMATIONS, "icons": KEY_DESIGN_ICONS}[key]
        if isinstance(value, bool):
            value = "true" if value else "false"
        self.settings.setValue(name, value)


class MemoryStore(object):
    """Einstellungen nur im Arbeitsspeicher (Ribbon ohne Plugin, z. B. in Tests)."""

    def __init__(self):
        self._values = {}

    def value(self, key, default=None):
        return self._values.get(key, default)

    def setValue(self, key, value):  # noqa: N802 (QSettings-Schnittstelle)
        self._values[key] = value

    def remove(self, key):
        self._values.pop(key, None)
