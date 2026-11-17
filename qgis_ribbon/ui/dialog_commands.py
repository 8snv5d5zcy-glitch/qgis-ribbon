"""Eigene Befehle, die Dialoge öffnen.

Die Dialogmodule (``domain_dialog``, ``customize_dialog``, ``field_dialogs``) ziehen viele
Module nach; sie werden erst beim ersten Öffnen importiert, nicht beim Start
(Budget Startzeit).
"""

from ..qgis_integration import custom_commands

DOMAINS_ID = "ribbon.domaenen_dialog"
GALLERY_ID = "ribbon.galerie_anpassen"
FIELD_IDS = {"ribbon.feld_hinzufuegen": "open_add", "ribbon.feld_loeschen": "open_delete",
             "ribbon.feld_umbenennen": "open_rename"}


def _domains(env, command):
    def run():
        from .domain_dialog import open_dialog
        return open_dialog(env.iface)
    return run


def _gallery(env, command):
    def run():
        from .customize_dialog import open_gallery_dialog
        return open_gallery_dialog(env, command)
    return run


def _fields(name):
    def factory(env, command):
        def run():
            from . import field_dialogs
            return getattr(field_dialogs, name)(env.iface)
        return run
    return factory


def _georef(module, name):
    """Befehle der Sitzung „Georeferenzieren in der Karte“ mit Dialog oder Bedienfeld (Import beim Aufbau)."""
    def factory(env, command):
        from importlib import import_module
        return getattr(import_module("." + module, __package__), name)(env, command)
    return factory


GEOREF_IDS = {"ribbon.georef_entzerren": ("georef_dialog", "georef_entzerren"),
              "ribbon.georef_tabelle": ("georef_panel", "georef_tabelle")}


def register_all():
    custom_commands.register(DOMAINS_ID, _domains, "button")
    for cid, (module, name) in GEOREF_IDS.items():
        custom_commands.register(cid, _georef(module, name), "button")
    custom_commands.register(GALLERY_ID, _gallery, "button")
    for cid, name in FIELD_IDS.items():
        custom_commands.register(cid, _fields(name), "button")


def unregister_all():
    custom_commands.unregister(DOMAINS_ID)
    for cid in GEOREF_IDS:
        custom_commands.unregister(cid)
    custom_commands.unregister(GALLERY_ID)
    for cid in FIELD_IDS:
        custom_commands.unregister(cid)
