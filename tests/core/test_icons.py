import io
import os
import re
import sys

import pytest

from qgis_ribbon.core import config_loader
from qgis_ribbon.core import icons

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def ribbon():
    return config_loader.load()


@pytest.fixture(scope="module")
def shipped(ribbon):
    return icons.load(command_ids=set(ribbon.commands))


def test_every_command_has_a_motif(ribbon, shipped):
    assert set(ribbon.commands) - set(shipped.commands) == set()


def test_menus_without_command_have_a_motif(ribbon, shipped):
    from qgis_ribbon.core.model import Menu, SubMenu

    labels = set()

    def walk(items):
        for it in items:
            if isinstance(it, SubMenu):
                labels.add(it.label)
                walk(it.items)

    for tab in ribbon.tabs:
        for group in tab.groups:
            for el in group.elements:
                if isinstance(el, Menu):
                    labels.add(el.label)
                    walk(el.items)
    assert labels - set(shipped.menus) == set()


def test_ui_symbols(shipped):
    for name in ("launcher", "suchen", "minimieren", "anheften"):
        assert shipped.for_ui(name) in shipped.motifs


def test_svg_has_colors_only_from_arguments(shipped):
    motif = shipped.motifs[shipped.for_command("puffer")]
    text = icons.svg(motif, "#111111", "#222222", "#333333")
    colors = set(re.findall(r"#[0-9A-Fa-f]{6}", text))
    assert colors == {"#111111", "#222222", "#333333"}
    assert "fill-opacity" in text
    # gesperrt: keine Fläche
    assert "#333333" not in icons.svg(motif, "#111111", "#222222", None)


def test_check_finds_errors():
    data = {
        "motive": {
            "gut": {"k": ['<path d="M0 0h1"/>']},
            "Farbe": {"k": ['<path d="M0 0" stroke="#ff0000"/>']},
            "leer": {"f": ['<rect x="1" y="1" width="2" height="2"/>']},
            "skript": {"k": ["<script>alert(1)</script>"]},
        },
        "befehle": {"x": "fehlt", "unbekannt": "gut"},
    }
    errors = icons.check(data, command_ids={"x"})
    text = "\n".join(errors)
    assert "Motivname ungültig: 'Farbe'" in text
    assert "Farbe oder Stil" in text
    assert "Motiv leer: keine Kontur" in text
    assert "Element ungültig" in text
    assert "unbekanntes Motiv 'fehlt'" in text
    assert "unbekannter Befehl 'unbekannt'" in text
    with pytest.raises(icons.IconError):
        icons.parse(data)


def test_shipped_file_matches_generator(tmp_path):
    """Die eingecheckte YAML-Datei ist das Ergebnis von tools/kontur_icons.py."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import kontur_icons
    finally:
        sys.path.pop(0)
    out = tmp_path / "kontur.yaml"
    kontur_icons.write(str(out))
    with io.open(icons.DEFAULT_ICONS, encoding="utf-8") as fh:
        assert out.read_text(encoding="utf-8") == fh.read()

