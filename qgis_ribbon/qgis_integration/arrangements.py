"""Anordnung des Ribbons: Definition plus Anpassung des Nutzers.

``Arrangements`` verbindet die Ribbon-Definition (``base``) mit den
Einstellungen des Nutzers (``UserSettings``):

- ``effective()``: wirksamer Ribbon (Definition mit Anpassung, ``core.customization``);
- ``set_current``/``set_gallery``/``save_editor``: Anpassung aus dem Editor und den
  Dialogen speichern;
- gespeicherte Anordnungen: unter einem Namen speichern, laden, löschen,
  als Datei exportieren und importieren. Eine Anordnung umfasst Tabs,
  Gruppen, Galerien, Schnellzugriffsleiste und eigene Kürzel. Die zuletzt
  geladene oder gespeicherte ist die aktuelle (``current_name``); „Speichern“
  schreibt in sie zurück.

Nach jeder Änderung sendet ``changed``; das Plugin baut den Ribbon dann neu
auf. Ohne Plugin (Ribbon allein, Tests) hört niemand zu, gespeichert wird
trotzdem.

Erweiterungen: Das Plugin setzt bei jedem Aufbau die um Plugin-Aktionen
und benötigte Werkzeuge erweiterte Definition (``set_base``) und für den
Editor ``full_base`` (alle Werkzeuge des Werkzeugkastens). Laufzeit-IDs, die
eine Datei oder gespeicherte Anordnung nennt, gehen beim Übernehmen nicht
verloren: Sie stehen bis zum nächsten Aufbau als Platzhalter in der Definition.
"""

import io
import json
import os

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core import customization as cz
from ..core import extensions as ext
from ..core import quick_access
from ..core.i18n import tr

LOG_TAG = "QGIS Ribbon"
FILE_SUFFIX = ".json"


class Arrangements(QObject):
    changed = pyqtSignal()

    def __init__(self, base, user, parent=None):
        QObject.__init__(self, parent)
        self.base = base
        self.user = user
        self.warnings = []   # Hinweise beim letzten Lesen der Anpassung
        self.full_base = None   # () -> Definition mit allen Werkzeugen (Editor), vom Plugin gesetzt

    def set_base(self, base):
        """Erweiterte Definition (Plugin-Aktionen, Werkzeuge) für den nächsten Aufbau."""
        self.base = base

    def editor_base(self):
        """Definition für den Editor: mit allen Werkzeugen des Werkzeugkastens, wenn verfügbar."""
        return self.full_base() if self.full_base is not None else self.base

    # Aktuelle Anpassung
    def current(self):
        arr, self.warnings = cz.from_dict(self.user.layout(), self.base)
        return arr

    def effective(self):
        """Wirksamer Ribbon; ohne Anpassung die Definition selbst."""
        if not self.user.layout():
            self.warnings = []
            return self.base
        arr = self.current()
        for text in self.warnings:
            QgsMessageLog.logMessage(tr("Arrangement: %s") % text, LOG_TAG, Qgis.MessageLevel.Warning)
        return cz.apply(self.base, arr)

    def set_current(self, arr):
        problems = cz.problems(arr)
        if problems:
            raise ValueError(" ".join(problems))
        self.user.set_layout(cz.to_dict(arr, self.base))
        self.changed.emit()

    def quick_ids(self):
        """Gespeicherte Schnellzugriffsleiste als Liste der IDs; None = Standard der Definition."""
        stored = self.user.quick_access()
        return None if stored is None else quick_access.parse(stored)

    def save_editor(self, arr, qat):
        """Ergebnis des Ribbon-Editors speichern: Anordnung und Schnellzugriff (``None`` = Standard)."""
        problems = cz.problems(arr)
        if problems:
            raise ValueError(" ".join(problems))
        if qat is None:
            self.user.reset_quick_access()
        else:
            self.user.set_quick_access(",".join(qat))
        self.user.set_layout(cz.to_dict(arr, self.base))
        # Eigene Kürzel gelöschter Tabs verfallen
        gone = {r for r in cz.effective_removed(arr) if "/" not in r}
        if gone:
            keytips = self.user.keytips()
            kept = cz.keytips_without_tabs(keytips, gone)
            if kept != keytips:
                self.user.set_keytips(kept)
        self.changed.emit()

    def reset_layout(self):
        """Tabs, Gruppen und Galerien wie in der Definition (Schnellzugriff und Kürzel bleiben)."""
        self.user.set_layout(None)
        self.changed.emit()

    def gallery_items(self, gallery_id):
        """Befehls-IDs der Galerie (Anpassung oder Standard der Definition)."""
        ids = self.current().galleries.get(gallery_id)
        if ids is not None:
            return list(ids)
        return [c.id for c in cz.galleries(self.base)[gallery_id].gallery.items]

    def set_gallery(self, gallery_id, ids):
        """Einträge einer Galerie speichern; ``None`` = Standard der Definition."""
        arr = self.current()
        if ids is None:
            arr.galleries.pop(gallery_id, None)
        else:
            arr.galleries[gallery_id] = list(ids)
        self.set_current(arr)

    # Gespeicherte Anordnungen
    def bundle(self, name=None):
        """Aktuelle Anordnung als dict (Tabs, Gruppen, Galerien, Schnellzugriff, Kürzel)."""
        stored = self.user.quick_access()
        qat = None if stored is None else quick_access.parse(stored)
        return cz.make_bundle(self.user.layout(), qat, self.user.keytips(), name)

    def apply_bundle(self, data):
        """Anordnung übernehmen. Liefert Hinweise auf übergangene Einträge.

        Löst ``customization.BundleError`` aus, wenn ``data`` keine Anordnung ist.
        """
        bundle = cz.read_bundle(data)
        self.base = ext.with_placeholders(self.base, ext.referenced_ids(bundle.layout, bundle.quick_access or []))
        arr, warnings = cz.from_dict(bundle.layout, self.base)
        if cz.problems(arr):
            warnings = warnings + cz.problems(arr) + [tr("Tabs and groups as in the definition")]
            arr = cz.standard(self.base)
            arr.galleries = cz.from_dict(bundle.layout, self.base)[0].galleries
        self.user.set_layout(cz.to_dict(arr, self.base))
        if bundle.quick_access is None:
            self.user.reset_quick_access()
        else:
            unknown = [c for c in bundle.quick_access if c not in self.base.commands]
            warnings += [tr("Command %r of the Quick Access Toolbar no longer exists") % c for c in unknown]
            self.user.set_quick_access(",".join(c for c in bundle.quick_access if c not in unknown))
        self.user.set_keytips(bundle.keytips)
        self.changed.emit()
        return warnings

    def names(self):
        return sorted(self.user.saved(), key=lambda n: n.lower())

    def save_as(self, name):
        name = name.strip()
        if not name:
            raise ValueError(tr("Name missing"))
        saved = self.user.saved()
        saved[name] = self.bundle(name)
        self.user.set_saved(saved)
        self.user.set_current_name(name)
        return name

    def save(self):
        """Stand in die aktuelle Anordnung schreiben. -> Name, None ohne aktuelle Anordnung."""
        name = self.current_name()
        return self.save_as(name) if name else None

    def current_name(self):
        """Gespeicherte Anordnung, in der gerade gearbeitet wird (zuletzt geladen oder gespeichert), sonst None."""
        name = self.user.current_name()
        return name if name in self.user.saved() else None

    def is_modified(self):
        """Die aktuelle Anordnung wurde seit dem Laden oder Speichern geändert."""
        name = self.current_name()
        return name is not None and not cz.same_bundle(self.user.saved()[name], self.bundle())

    def load(self, name):
        warnings = self.apply_bundle(self.user.saved()[name])
        self.user.set_current_name(name)
        return warnings

    def delete(self, name):
        saved = self.user.saved()
        saved.pop(name, None)
        self.user.set_saved(saved)
        if self.user.current_name() == name:
            self.user.set_current_name(None)

    def active_name(self):
        """Name der gespeicherten Anordnung, die dem Stand entspricht, sonst None (die aktuelle zuerst)."""
        current = self.bundle()
        saved = self.user.saved()
        first = self.current_name()
        for name in ([first] if first else []) + self.names():
            if cz.same_bundle(saved[name], current):
                return name
        return None

    def is_standard(self):
        return self.bundle() == cz.make_bundle(None)

    def is_unsaved(self):
        """Angepasst, aber unter keinem Namen gespeichert (Laden würde die Anpassung verwerfen)."""
        return not self.is_standard() and self.active_name() is None

    def reset(self):
        """Standardanordnung: Tabs, Gruppen, Galerien, Schnellzugriff und Kürzel wie geliefert."""
        warnings = self.apply_bundle(cz.make_bundle(None))
        self.user.set_current_name(None)
        return warnings

    # Dateien
    def export(self, path, name=None):
        with io.open(path, "w", encoding="utf-8") as fh:
            json.dump(self.bundle(name), fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

    def unique_name(self, name):
        saved = self.user.saved()
        out, n = name, 2
        while out in saved:
            out, n = "%s (%d)" % (name, n), n + 1
        return out

    def import_file(self, path):
        """Datei als gespeicherte Anordnung übernehmen und laden. -> (Name, Hinweise)."""
        try:
            with io.open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise cz.BundleError(tr("File not readable: %s") % exc)
        bundle = cz.read_bundle(data)
        wanted = bundle.name or os.path.splitext(os.path.basename(path))[0]
        warnings = self.apply_bundle(data)
        # Gleiche Anordnung unter gleichem Namen schon vorhanden: kein „Name (2)“
        name = wanted if self.active_name() == wanted else self.unique_name(wanted)
        # Bereinigt speichern (ohne übergangene Einträge), damit sie als aktiv erkannt wird
        self.save_as(name)
        return name, warnings
