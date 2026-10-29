"""Qt6-Vorbereitung: keine unqualifizierten Enums und kein ``exec_`` im Code."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "qt6_enums.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("qt6_enums", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not TOOL.exists(), reason="tools/qt6_enums.py fehlt")
def test_no_unqualified_enums():
    tool = _load_tool()
    namespace = tool._namespace()
    found = []
    for path in tool.iter_files(["qgis_ribbon", "tests"]):
        source = path.read_text(encoding="utf-8")
        for row, _s, _e, cls, name, enum_name in tool.scan_source(source, namespace):
            found.append("%s:%d %s.%s -> %s.%s.%s" % (path.relative_to(ROOT), row, cls, name, cls, enum_name, name))
    assert not found, "\n".join(found)


def test_no_exec_underscore():
    pattern = re.compile(r"\.exec_\(")
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "qgis_ribbon").rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_removed_qt5_names_absent():
    # Unter Qt6 entfernt: QVariant.<Typ> und QgsWkbTypes.<...>Geometry (QGIS 4: Qgis.GeometryType)
    pattern = re.compile(r"\bQVariant\.[A-Z]\w+|\bQgsWkbTypes\.\w+Geometry\b")
    hits = []
    for path in (ROOT / "qgis_ribbon").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                hits.append("%s:%d" % (path.relative_to(ROOT), number))
    assert not hits, hits
