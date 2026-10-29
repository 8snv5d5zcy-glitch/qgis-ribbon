"""Untermenü „Anordnungen“: eigene Anordnungen speichern, laden und teilen.

Eine Anordnung umfasst Tabs, Gruppen, Galerien, Schnellzugriffsleiste und
eigene Kürzel (``qgis_integration.arrangements``). Im Menü stehen die
gespeicherten Anordnungen (die aktuelle abgehakt), Speichern (in die aktuelle
Anordnung), Speichern unter (neue Anordnung, bei vorhandenem Namen nach
Rückfrage), Exportieren und Importieren als Datei (zum Weitergeben), Löschen
und die Standardanordnung. Laden verwirft eine nicht gespeicherte Anpassung
erst nach Rückfrage.

Rückfragen und Meldungen laufen über die Funktionen ``ask_*``, ``confirm``
und ``inform``, damit Tests sie ersetzen können (modale Dialoge blockieren).
"""

import os

from qgis.PyQt.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from ..core.customization import BundleError
from ..core.i18n import tr

TITLE = tr("Arrangements")
TEXT_SAVE = tr("Save Current Arrangement As …")
TEXT_SAVE_CURRENT = tr("Save Arrangement “%s”")
TEXT_SAVE_NEW = tr("Save Arrangement …")
TEXT_EXPORT = tr("Export …")
TEXT_IMPORT = tr("Import …")
TEXT_DELETE = tr("Delete")
TEXT_RESET = tr("Default Arrangement")
TEXT_NONE = tr("No arrangement saved yet")
FILE_FILTER = tr("Ribbon arrangement (*.json)")
DEFAULT_FILE = tr("Ribbon-arrangement.json")
UNSAVED = tr("The current customization is not saved under a name and will be lost. Continue anyway?")
UNSAVED_CHANGES = tr("The changes to arrangement “%s” are not saved and will be lost. Continue anyway?")
MAX_WARNINGS = 8


# Rückfragen (in Tests ersetzbar)
def ask_name(parent, title, label, text=""):
    name, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, text)
    return name.strip() if ok and name.strip() else None


def ask_save_path(parent, suggestion):
    path, _ = QFileDialog.getSaveFileName(parent, tr("Export Arrangement"), suggestion, FILE_FILTER)
    return path or None


def ask_open_path(parent):
    path, _ = QFileDialog.getOpenFileName(parent, tr("Import Arrangement"), os.path.expanduser("~"),
                                          FILE_FILTER)
    return path or None


def confirm(parent, title, text):
    answer = QMessageBox.question(parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def inform(parent, title, text, warning=False):
    (QMessageBox.warning if warning else QMessageBox.information)(parent, title, text)


def _warnings_text(warnings):
    lines = ["– " + w for w in warnings[:MAX_WARNINGS]]
    if len(warnings) > MAX_WARNINGS:
        lines.append(tr("… and %d more") % (len(warnings) - MAX_WARNINGS))
    return tr("Skipped (not present in this ribbon definition):\n") + "\n".join(lines)


def _report(rw, title, warnings):
    if warnings:
        inform(rw.window(), title, _warnings_text(warnings))


# Menü
def add_submenu(menu, rw):
    arr = rw.arrangements
    sub = menu.addMenu(TITLE)
    sub.setObjectName("ribbon_arrangements_menu")
    sub.setToolTipsVisible(True)
    names = arr.names()
    active = arr.active_name() or arr.current_name()
    for name in names:
        act = sub.addAction(name, lambda _c=False, n=name: load(rw, n))
        act.setCheckable(True)
        act.setChecked(name == active)
        act.setToolTip(tr("Load Arrangement"))
    if not names:
        sub.addAction(TEXT_NONE).setEnabled(False)
    sub.addSeparator()
    current = arr.current_name()
    if current:
        act = sub.addAction(TEXT_SAVE_CURRENT % current, lambda: save(rw))
        act.setEnabled(arr.is_modified())
        act.setToolTip(tr("Save the changes to the current arrangement"))
    else:
        sub.addAction(TEXT_SAVE_NEW, lambda: save(rw)).setToolTip(
            tr("Save the current state as a new arrangement"))
    sub.addAction(TEXT_SAVE, lambda: save_as(rw)).setToolTip(
        tr("Save the current state as a new arrangement"))
    sub.addAction(TEXT_EXPORT, lambda: export(rw)).setToolTip(
        tr("Save the current arrangement as a file, e.g. to share it"))
    sub.addAction(TEXT_IMPORT, lambda: import_file(rw)).setToolTip(
        tr("Import an arrangement from a file and load it"))
    if names:
        delete_menu = sub.addMenu(TEXT_DELETE)
        for name in names:
            delete_menu.addAction(name, lambda _c=False, n=name: delete(rw, n))
    sub.addSeparator()
    std = sub.addAction(TEXT_RESET, lambda: reset(rw))
    std.setCheckable(True)
    std.setChecked(arr.is_standard())
    std.setToolTip(tr("Tabs, groups, galleries, Quick Access and KeyTips as shipped"))
    return sub


# Aktionen
def _may_discard(rw, title):
    arr = rw.arrangements
    if not arr.is_unsaved():
        return True
    current = arr.current_name()
    return confirm(rw.window(), title, UNSAVED_CHANGES % current if current else UNSAVED)


def load(rw, name):
    title = tr("Load arrangement “%s”") % name
    if rw.arrangements.active_name() == name or not _may_discard(rw, title):
        return False
    _report(rw, title, rw.arrangements.load(name))
    return True


def reset(rw):
    title = tr("Default Arrangement")
    if rw.arrangements.is_standard() or not _may_discard(rw, title):
        return False
    rw.arrangements.reset()
    return True


def save(rw):
    """In die aktuelle Anordnung speichern; ohne aktuelle wie „Speichern unter“."""
    name = rw.arrangements.save()
    return name if name else save_as(rw)


def save_as(rw):
    """Als neue Anordnung speichern; ein vorhandener Name wird nur nach Rückfrage überschrieben."""
    arr = rw.arrangements
    current = arr.current_name()
    name = ask_name(rw.window(), tr("Save Arrangement"), tr("Name of the arrangement:"),
                    arr.unique_name(current) if current else "")
    if not name:
        return None
    if name in arr.names() and not confirm(rw.window(), tr("Save Arrangement"),
                                           tr("“%s” already exists. Overwrite?") % name):
        return None
    return arr.save_as(name)


def export(rw):
    arr = rw.arrangements
    name = arr.active_name()
    suggestion = os.path.join(os.path.expanduser("~"), (name + ".json") if name else DEFAULT_FILE)
    path = ask_save_path(rw.window(), suggestion)
    if not path:
        return None
    if not path.lower().endswith(".json"):
        path += ".json"
    try:
        arr.export(path, name)
    except OSError as exc:
        inform(rw.window(), tr("Export Arrangement"), tr("File not written: %s") % exc, warning=True)
        return None
    return path


def import_file(rw):
    title = tr("Import Arrangement")
    path = ask_open_path(rw.window())
    if not path or not _may_discard(rw, title):
        return None
    try:
        name, warnings = rw.arrangements.import_file(path)
    except BundleError as exc:
        inform(rw.window(), title, tr("Not a ribbon arrangement: %s") % exc, warning=True)
        return None
    _report(rw, tr("Arrangement “%s” loaded") % name, warnings)
    return name


def delete(rw, name):
    if not confirm(rw.window(), tr("Delete Arrangement"), tr("Delete arrangement “%s”?") % name):
        return False
    rw.arrangements.delete(name)
    return True
