"""Wächter gegen Qt6-Fehler, die erst zur Laufzeit auffallen.

Zwei Prüfungen:

``scan`` (läuft im Python von QGIS, in jeder Version): Liest den Plugin-Code als
Syntaxbaum und prüft gegen die laufende Version, was sich ohne Ausführen prüfen lässt:
Importe aus ``qgis``, Attribute an importierten Klassen (``QFoo.bar.baz``), Methoden an
Variablen mit bekannter Klasse (``x = QFoo()`` und ``self.x = QFoo()``). Stellen mit
Ausweichweg (``try``/``except``, ``hasattr``) zählen nicht.

``compare`` (normales Python): Holt aus QGIS 3 und QGIS 4 die Attributnamen aller Klassen.
Ein Name, den der Plugin-Code benutzt und den es unter QGIS 3 gibt, aber unter QGIS 4 in
keiner Klasse mehr, ist verdächtig (so fielen ``associatedWidgets`` und ``paletteChanged``
auf). Die Klasse einer Variablen kennt der Vergleich nicht, er braucht sie auch nicht.

Aufruf:
    python tools/qt6_api_check.py                beide QGIS-Versionen, Rückgabe 1 bei Funden
    python tools/qt6_api_check.py --review DATEI dazu: was einzelne Klassen verloren haben (zum Durchsehen)
    python-qgis.bat tools/qt6_api_check.py --scan              nur die laufende Version
    python-qgis.bat tools/qt6_api_check.py --dump DATEI        Namen als JSON schreiben
"""
import ast
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = (
    "qgis.PyQt.QtCore", "qgis.PyQt.QtGui", "qgis.PyQt.QtWidgets", "qgis.PyQt.QtXml",
    "qgis.PyQt.QtSvg", "qgis.PyQt.QtNetwork", "qgis.PyQt.QtPrintSupport",
    "qgis.core", "qgis.gui",
)
# Namen, die der Vergleich nennt, die aber geprüft und richtig sind (Name: Begründung)
GEPRUEFT = {
    "associatedWidgets": "ui/qt_compat.action_widgets, Ausweichweg für Qt5",
    "paletteChanged": "ui/theme.py, unter Qt6 Ereignisfilter statt Signal",
}
# Umgebung der aufrufenden QGIS-Version darf nicht in die andere durchschlagen
FREMD = ("PYTHONPATH", "PYTHONHOME", "QGIS_PREFIX_PATH", "OSGEO4W_ROOT", "GDAL_DATA", "GDAL_DRIVER_PATH",
         "PROJ_LIB", "PROJ_DATA", "QT_PLUGIN_PATH", "O4W_QT_BINARIES", "O4W_QT_PLUGINS", "O4W_QT_PREFIX",
         "O4W_QT_TRANSLATIONS", "O4W_QT_HEADERS", "O4W_QT_DOC", "O4W_QT_LIBRARIES", "VSI_CACHE",
         "VSI_CACHE_SIZE", "GS_LIB", "PDAL_DRIVER_PATH", "PYTHONUTF8", "PATH")


def _python_files():
    return sorted(p for p in (ROOT / "qgis_ribbon").rglob("*.py") if "__pycache__" not in p.parts)


def _guarded(node, parents):
    """Steht ``node`` in einem Block mit Ausweichweg (``try``, ``if hasattr``)?"""
    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(parent, ast.Try) and parent.handlers and (current in parent.body or current in parent.handlers):
            return True
        if isinstance(parent, (ast.If, ast.IfExp)) and "hasattr" in ast.dump(parent.test):
            return True
        current = parent
    return False


def _chain(node):
    """``a.b.c`` als Liste ``["a", "b", "c"]``, sonst None."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
        return names[::-1]
    return None


def _qt_object(value):
    module = getattr(value, "__module__", "") or ""
    return module.startswith(("PyQt", "qgis")) or module == "sip"


def scan_source(source, name="<code>"):
    """Liefert ``[(Zeile, Text)]`` für alles, was es in der laufenden Version nicht gibt."""
    tree = ast.parse(source, name)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found, imported = [], {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "qgis" and not node.level:
            guarded = _guarded(node, parents)
            try:
                module = importlib.import_module(node.module)
            except ImportError as error:
                if not guarded:
                    found.append((node.lineno, "Modul fehlt: %s (%s)" % (node.module, error)))
                continue
            for alias in node.names:
                if hasattr(module, alias.name):
                    imported[alias.asname or alias.name] = getattr(module, alias.name)
                    continue
                try:
                    imported[alias.asname or alias.name] = importlib.import_module(
                        "%s.%s" % (node.module, alias.name))
                except ImportError:
                    if not guarded:
                        found.append((node.lineno, "Import fehlt: %s.%s" % (node.module, alias.name)))
    subclass = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and len(node.targets) == 1:
            chain = _chain(node.value.func)
            target = _chain(node.targets[0])
            if not chain or not target or chain[0] not in imported:
                continue
            owner = imported[chain[0]]
            for part in chain[1:]:
                owner = getattr(owner, part, None)
            scope = _scope(node, parents, target) if isinstance(owner, type) and _qt_object(owner) else None
            if scope is not None:
                # Mehrfach mit verschiedenen Klassen belegt: unbekannt
                known = subclass.setdefault(scope, {})
                name = ".".join(target)
                known[name] = owner if known.get(name, owner) is owner else None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or isinstance(parents.get(node), ast.Attribute):
            continue
        chain = _chain(node)
        if not chain or _guarded(node, parents):
            continue
        if chain[0] in imported:
            _check_chain(imported[chain[0]], chain, node, found)
            continue
        for length in range(len(chain) - 1, 0, -1):
            owner = _known_class(subclass, node, parents, ".".join(chain[:length]))
            if owner is not None:
                if not isinstance(node.ctx, ast.Store):
                    _check_chain(owner, [owner.__name__] + chain[length:], node, found)
                break
    return sorted(set(found))


def _scope(node, parents, target):
    """Gültigkeitsbereich einer Zuweisung: die Klasse bei ``self.x``, sonst die Funktion."""
    current = node
    while current in parents:
        current = parents[current]
        if target[0] == "self" and isinstance(current, ast.ClassDef):
            return current
        if target[0] != "self" and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _known_class(known, node, parents, name):
    current = node
    while current in parents:
        current = parents[current]
        if current in known and name in known[current]:
            return known[current][name]
    return None


def _check_chain(owner, chain, node, found):
    label = chain[0]
    for part in chain[1:]:
        label += "." + part
        if not hasattr(owner, part):
            if isinstance(node.ctx, ast.Store) and part == chain[-1]:
                return
            if _qt_object(owner) or isinstance(owner, type):
                found.append((node.lineno, "Attribut fehlt: %s" % label))
            return
        owner = getattr(owner, part)
        if not (isinstance(owner, type) or type(owner).__name__ == "module"):
            return


def scan():
    """Prüft den Plugin-Code gegen die laufende QGIS-Version."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    found = []
    for path in _python_files():
        for row, text in scan_source(path.read_text(encoding="utf-8"), str(path)):
            found.append("%s:%d %s" % (path.relative_to(ROOT).as_posix(), row, text))
    return found


def attribute_names():
    """Attributnamen aller Klassen der Qt- und QGIS-Module, auch geschachtelter."""
    names = {}

    def add(prefix, cls, depth=0):
        # Enum.__members__: dir() nennt bei Flag-Enums weder 0 noch zusammengesetzte Werte (NoFocus, StrongFocus)
        attrs = sorted(set(dir(cls)) | set(getattr(cls, "__members__", ())))
        names[prefix] = attrs
        if depth > 1:
            return
        for attr in attrs:
            if attr.startswith("__"):
                continue
            try:
                value = getattr(cls, attr)
            except Exception:  # nosec B112 - manche Deskriptoren werfen beim Lesen an der Klasse
                continue
            if isinstance(value, type) and _qt_object(value):
                add("%s.%s" % (prefix, attr), value, depth + 1)

    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in dir(module):
            value = getattr(module, name, None)
            if isinstance(value, type) and _qt_object(value) and name not in names:
                add(name, value)
    return names


def used_names():
    """Alle Attributnamen im Plugin-Code, mit erster Fundstelle."""
    used = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used.setdefault(node.attr, "%s:%d" % (path.relative_to(ROOT).as_posix(), node.lineno))
    return used


def compare(names3, names4, used, known=GEPRUEFT):
    """Benutzte Namen, die es unter QGIS 3 in einer Klasse gibt, unter QGIS 4 in keiner."""
    all3 = {attr for attrs in names3.values() for attr in attrs}
    all4 = {attr for attrs in names4.values() for attr in attrs}
    return sorted((name, where) for name, where in used.items()
                  if name in all3 and name not in all4 and name not in known)


def lost_on_class(names3, names4, used):
    """Benutzte Namen, die einzelne Klassen verloren haben, andere aber noch tragen: zum Durchsehen."""
    lost = {}
    for cls, attrs in names3.items():
        if cls in names4:
            for name in set(attrs) - set(names4[cls]):
                if name in used:
                    lost.setdefault(name, []).append(cls)
    return {name: sorted(classes) for name, classes in sorted(lost.items())}


def _clean_env():
    env = {k: v for k, v in os.environ.items() if k.upper() not in FREMD}
    env["PATH"] = os.pathsep.join((os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
                                   os.environ.get("SystemRoot", r"C:\Windows")))
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def _in_qgis(qgis, *args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import qgis_install
    python = os.path.join(qgis_install.ROOTS[qgis], "bin", qgis_install.PYTHON[qgis])
    return subprocess.run(["cmd", "/c", python, str(Path(__file__).resolve()), *args], env=_clean_env(),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)


def run_both(review=None):
    """Beide Prüfungen in beiden Versionen; liefert die Fundstellen als Text.

    ``review`` (Dateipfad): schreibt zusätzlich ``lost_on_class`` als JSON.
    """
    problems, dumps = [], {}
    with tempfile.TemporaryDirectory() as folder:
        for qgis in ("3", "4"):
            result = _in_qgis(qgis, "--scan")
            if result.returncode:
                problems += ["QGIS %s: %s" % (qgis, line) for line in result.stdout.splitlines() if line.strip()]
                if not result.stdout.strip():
                    problems.append("QGIS %s: Prüfung lief nicht: %s" % (qgis, result.stderr[-500:]))
            dump = os.path.join(folder, "namen%s.json" % qgis)
            result = _in_qgis(qgis, "--dump", dump)
            if result.returncode or not os.path.exists(dump):
                problems.append("QGIS %s: Namen nicht lesbar: %s" % (qgis, result.stderr[-500:]))
                continue
            with open(dump, encoding="utf-8") as fh:
                dumps[qgis] = json.load(fh)
    if len(dumps) == 2:
        for name, where in compare(dumps["3"], dumps["4"], used_names()):
            problems.append("%s %s: gibt es unter QGIS 4 in keiner Klasse" % (where, name))
        if review:
            with open(review, "w", encoding="utf-8") as fh:
                json.dump(lost_on_class(dumps["3"], dumps["4"], used_names()), fh, indent=1)
    return problems


def main(argv):
    if "--scan" in argv:
        found = scan()
        print("\n".join(found))
        return 1 if found else 0
    if "--dump" in argv:
        with open(argv[argv.index("--dump") + 1], "w", encoding="utf-8") as fh:
            json.dump(attribute_names(), fh)
        return 0
    problems = run_both(argv[argv.index("--review") + 1] if "--review" in argv else None)
    for line in problems:
        print(line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))
    print("%d Funde" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
