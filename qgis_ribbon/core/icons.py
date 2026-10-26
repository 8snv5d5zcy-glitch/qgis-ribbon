"""Eigenes Icon-Set „Kontur“ (ohne qgis-Imports).

Die Motive stehen als Daten in ``config/icons/kontur.yaml``: je Motiv drei
Listen von SVG-Elementen im 24er-Raster, getrennt nach Rolle:

- ``f``: Akzentfläche (leicht getönt, liegt unten),
- ``k``: Kontur in Textfarbe,
- ``a``: Akzentdetail in Akzentfarbe.

Die Elemente tragen keine Farben; ``svg()`` setzt Farben und Strichstärke je
Modus und Zustand ein. Dazu die Zuordnung Befehls-ID -> Motiv (``befehle``),
Menü-Elemente ohne eigenen Befehl nach Beschriftung (``menues``) und Symbole
der Oberfläche (``oberflaeche``: Launcher, Pfeile, Suche …).

``check(data, command_ids)`` prüft Form und Zuordnung (bekannte Befehle,
vorhandene Motive, erlaubte Elemente).
"""

import io
import os
import re

from . import yaml_cache
from .i18n import tr

DEFAULT_ICONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "icons",
                             "kontur.yaml")
ROLES = ("f", "k", "a")
GRID = 24
STROKE_LARGE = 1.6       # Strich im 24er-Raster bei 32 px (≈ 2,1 px)
STROKE_SMALL = 2.0       # bei 16 px (≈ 1,3 px), sonst zu dünn
FILL_OPACITY = 0.22

_ELEMENT = re.compile(r'^<(path|rect|circle|ellipse|line|polyline|polygon)\s[^<>]*/>$')
_FORBIDDEN = re.compile(r'(#[0-9A-Fa-f]{3}|style\s*=|stroke\s*=|fill\s*=\s*"(?!none)|url\()')
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class IconError(ValueError):
    def __init__(self, errors):
        self.errors = list(errors)
        ValueError.__init__(self, tr("Icon set has errors:\n- ") + "\n- ".join(self.errors))


class IconSet(object):
    def __init__(self, motifs, commands, menus, ui):
        self.motifs = motifs        # Name -> {Rolle: [Element]}
        self.commands = commands    # Befehls-ID -> Motiv
        self.menus = menus          # Menü-Beschriftung -> Motiv
        self.ui = ui                # Oberflächen-Symbol -> Motiv

    def for_command(self, command_id):
        return self.commands.get(command_id)

    def for_menu(self, label):
        return self.menus.get(label)

    def for_ui(self, name):
        return self.ui.get(name)


def svg(motif, contour, accent, fill=None, stroke=STROKE_LARGE):
    """SVG-Text eines Motivs. ``fill`` None: keine Akzentfläche (z. B. gesperrt)."""
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">'
             % (GRID, GRID, GRID, GRID)]
    if fill and motif.get("f"):
        parts.append('<g fill="%s" fill-opacity="%.2f" stroke="none">%s</g>'
                     % (fill, FILL_OPACITY, "".join(motif["f"])))
    common = 'fill="none" stroke-width="%.2f" stroke-linecap="round" stroke-linejoin="round"' % stroke
    if motif.get("k"):
        parts.append('<g stroke="%s" %s>%s</g>' % (contour, common, "".join(motif["k"])))
    if motif.get("a"):
        parts.append('<g stroke="%s" %s>%s</g>' % (accent, common, "".join(motif["a"])))
    parts.append("</svg>")
    return "".join(parts)


def parse(data, command_ids=None):
    """Geladenes YAML -> ``IconSet``; Fehler gesammelt in ``IconError``."""
    errors = check(data, command_ids)
    if errors:
        raise IconError(errors)
    motifs = {name: {r: list(m.get(r) or ()) for r in ROLES} for name, m in data["motive"].items()}
    return IconSet(motifs, dict(data.get("befehle") or {}), dict(data.get("menues") or {}),
                   dict(data.get("oberflaeche") or {}))


def check(data, command_ids=None):
    errors = []
    if not isinstance(data, dict) or not isinstance(data.get("motive"), dict):
        return [tr("Section 'motive' missing")]
    motifs = data["motive"]
    for name, motif in motifs.items():
        if not _ID.match(str(name)):
            errors.append(tr("Invalid motif name: %r") % (name,))
        if not isinstance(motif, dict) or not motif:
            errors.append(tr("Motif %s: empty or not an object") % name)
            continue
        for role in set(motif) - set(ROLES):
            errors.append(tr("Motif %s: unknown role %r") % (name, role))
        if not motif.get("k") and not motif.get("a"):
            errors.append(tr("Motif %s: no outline") % name)
        for role in ROLES:
            for el in motif.get(role) or ():
                if not isinstance(el, str) or not _ELEMENT.match(el.strip()):
                    errors.append(tr("Motif %s/%s: invalid element: %r") % (name, role, el))
                elif _FORBIDDEN.search(el):
                    errors.append(tr("Motif %s/%s: color or style in element: %r") % (name, role, el))
    for section in ("befehle", "menues", "oberflaeche"):
        mapping = data.get(section) or {}
        if not isinstance(mapping, dict):
            errors.append(tr("Section %s: not an object") % section)
            continue
        for key, motif in mapping.items():
            if motif not in motifs:
                errors.append(tr("%s: %s -> unknown motif %r") % (section, key, motif))
            if section == "befehle" and command_ids is not None and key not in command_ids:
                errors.append(tr("befehle: unknown command %r") % (key,))
    return errors


def read_yaml(path):
    import yaml

    with io.open(path, encoding="utf-8") as fh:
        try:
            return yaml_cache.safe_load(fh)
        except yaml.YAMLError as exc:
            raise IconError([tr("YAML not readable: %s") % exc])


def load(path=DEFAULT_ICONS, command_ids=None):
    """Icon-Set laden (über den Zwischenspeicher, falls eingerichtet)."""
    return parse(yaml_cache.load(path, read_yaml), command_ids)
