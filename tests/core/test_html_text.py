"""HTML-Maskierung der Tooltips: wie ``html.escape`` (ohne dessen teuren Import)."""
import html
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _module():
    # ui/ importiert sonst qgis; das Modul selbst ist reines Python
    spec = importlib.util.spec_from_file_location(
        "html_text", os.path.join(ROOT, "qgis_ribbon", "ui", "html_text.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_escape_matches_html_escape():
    escape = _module().escape
    for text in ("", "Puffer", "a < b & c > d", 'Feld "Name"', "it's", "Größe <b>fett</b>", 42):
        assert escape(text) == html.escape(str(text))
