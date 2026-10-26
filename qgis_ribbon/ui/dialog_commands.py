"""Eigene Befehle, die Dialoge öffnen.

Die Dialogmodule (``domain_dialog``, ``customize_dialog``) ziehen viele
Module nach; sie werden erst beim ersten Öffnen importiert, nicht beim Start
(Budget Startzeit).
"""

from ..qgis_integration import custom_commands

DOMAINS_ID = "ribbon.domaenen_dialog"
GALLERY_ID = "ribbon.galerie_anpassen"


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


def register_all():
    custom_commands.register(DOMAINS_ID, _domains, "button")
    custom_commands.register(GALLERY_ID, _gallery, "button")


def unregister_all():
    custom_commands.unregister(DOMAINS_ID)
    custom_commands.unregister(GALLERY_ID)
