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


def _load_api_check():
    spec = importlib.util.spec_from_file_location("qt6_api_check", ROOT / "tools" / "qt6_api_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_uses_only_existing_api():
    # Läuft in der QGIS-Version des Testlaufs, also je einmal unter 3.44 und unter 4
    found = _load_api_check().scan()
    assert not found, "\n".join(found)


def test_api_check_finds_missing_names():
    scan_source = _load_api_check().scan_source
    source = (
        "from qgis.PyQt.QtCore import Qt, QTimer\n"
        "from qgis.PyQt.QtWidgets import QNichtDa\n"
        "def f():\n"
        "    t = QTimer()\n"
        "    t.gibtsnicht()\n"
        "    t.timeout.connect(f)\n"
        "    return Qt.AlignmentFlag.GibtsNicht\n"
    )
    texts = [text for _row, text in scan_source(source)]
    assert "Import fehlt: qgis.PyQt.QtWidgets.QNichtDa" in texts
    assert "Attribut fehlt: QTimer.gibtsnicht" in texts
    assert "Attribut fehlt: Qt.AlignmentFlag.GibtsNicht" in texts
    assert len(texts) == 3     # Signal mit connect ist in Ordnung


def test_api_check_respects_fallbacks():
    source = (
        "from qgis.PyQt.QtCore import QTimer\n"
        "try:\n"
        "    from qgis.PyQt.QtWidgets import QNichtDa\n"
        "except ImportError:\n"
        "    from qgis.PyQt.QtGui import QNichtDa\n"
        "def f(t=QTimer):\n"
        "    if hasattr(t, 'gibtsnicht'):\n"
        "        return QTimer.gibtsnicht\n"
        "    try:\n"
        "        return QTimer.auchnicht\n"
        "    except AttributeError:\n"
        "        return None\n"
    )
    assert _load_api_check().scan_source(source) == []


def test_api_check_compare():
    tool = _load_api_check()
    names3 = {"QAction": ["text", "associatedWidgets", "weg"], "QWidget": ["pos"]}
    names4 = {"QAction": ["text"], "QWidget": ["pos"], "QPoint": ["x"]}
    used = {"weg": "a.py:1", "associatedWidgets": "b.py:2", "text": "c.py:3", "eigenes": "d.py:4"}
    assert tool.compare(names3, names4, used) == [("weg", "a.py:1")]
    assert tool.lost_on_class(names3, names4, used) == {"associatedWidgets": ["QAction"], "weg": ["QAction"]}


# Regeln des Migrationsskripts von QGIS (scripts/pyqt5_to_pyqt6), die tools/qt6_enums.py nicht abdeckt:
# Das Skript selbst läuft hier nicht, das Plugin-Repository wendet es beim Hochladen an.
MIGRATION_RULES = {
    "PyQt-Import statt qgis.PyQt": r"^\s*(from|import)\s+PyQt[56]\b",
    "qgis.PyQt.Qt": r"from\s+qgis\.PyQt\.Qt\s+import",
    "qApp": r"\bqApp\b",
    "QDesktopWidget": r"\bQDesktopWidget\b|\.desktop\(\)",
    "QRegExp": r"\bQRegExp\b",
    "resources_rc": r"\bresources_rc\b",
    "Signal mit Index [str]": r"\.\w+\[str\]\.connect",
    "QFontMetrics.width": r"(fontMetrics\(\)|[mM]etrics|\bfm)\.width\(",
    "Umbenannte Enums": r"\bQt\.MidButton\b|\bTextColorRole\b|\bBackgroundColorRole\b|\bHighQualityAntialiasing\b",
    "QVariant als Wert": r"\bQVariant\(\s*(QVariant\.)?",
    "QDateTime aus Zahlen": r"\bQDateTime\(\s*(\d|QDate\()",
}


@pytest.mark.parametrize("rule", sorted(MIGRATION_RULES))
def test_migration_rules(rule):
    pattern = re.compile(MIGRATION_RULES[rule])
    hits = []
    for path in (ROOT / "qgis_ribbon").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                hits.append("%s:%d" % (path.relative_to(ROOT), number))
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
