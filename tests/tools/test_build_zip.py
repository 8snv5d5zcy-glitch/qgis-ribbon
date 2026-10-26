"""Plugin-ZIP: Prüfungen und Inhalt."""
import os
import sys
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_zip  # noqa: E402


def test_shipped_plugin_passes_checks():
    errors, meta = build_zip.check()
    assert not errors, errors
    assert meta["name"] == "QGIS Ribbon"


def test_zip_content(tmp_path):
    target, size = build_zip.build(str(tmp_path))
    assert size < build_zip.MAX_BYTES
    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
    assert all(n.startswith("qgis_ribbon/") for n in names)
    for needed in ("__init__.py", "metadata.txt", "LICENSE", "icon.png", "config/ribbon_arcgis.yaml",
                   "i18n/de.json", "help/en/index.md", "help/de/index.md"):
        assert "qgis_ribbon/" + needed in names, needed
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc") or "/." in n]


def test_metadata_must_be_ascii(tmp_path):
    (tmp_path / "metadata.txt").write_bytes("[general]\nname=Rübe\n".encode("utf-8"))
    errors, _meta = build_zip.check(str(tmp_path))
    assert errors and "ASCII" in errors[0]


def test_missing_fields_are_reported(tmp_path):
    (tmp_path / "metadata.txt").write_text("[general]\nname=X\nrepository=http://x\n", encoding="ascii")
    errors, _meta = build_zip.check(str(tmp_path))
    text = "\n".join(errors)
    for key in ("version", "tracker", "about", "LICENSE", "Icon", "repository ist keine https"):
        assert key in text, key
