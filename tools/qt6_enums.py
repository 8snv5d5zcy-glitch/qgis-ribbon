"""Qt-Enums vollständig qualifizieren (Voraussetzung für Qt6 / QGIS 4).

PyQt6 kennt nur noch die Schreibweise mit Enum-Namen (`Qt.AlignmentFlag.AlignLeft`),
die auch unter PyQt5 funktioniert. Das Skript ermittelt die Zuordnung zur Laufzeit
im Python der QGIS-Installation und schreibt Stellen wie `Qt.AlignLeft` um.

Aufruf (im QGIS-Python, z. B. über `python-qgis-ltr.bat`):
    tools/qt6_enums.py            prüft qgis_ribbon, tests und tools, listet Funde
    tools/qt6_enums.py --fix      schreibt die Funde um
    tools/qt6_enums.py PFAD ...   nur diese Dateien oder Ordner

Rückgabe 1, wenn es unqualifizierte Stellen gibt. Nicht erfasst werden Enums, die
sich unter Qt6 anders verhalten (QVariant.Type, QgsWkbTypes, `exec_`); die
werden von Hand umgestellt.
"""
import importlib
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = ("qgis_ribbon", "tests", "tools")
MODULES = (
    "qgis.PyQt.QtCore", "qgis.PyQt.QtGui", "qgis.PyQt.QtWidgets", "qgis.PyQt.QtXml",
    "qgis.PyQt.QtSvg", "qgis.PyQt.QtNetwork", "qgis.PyQt.QtPrintSupport",
    "qgis.core", "qgis.gui",
)
# Klassen, deren Enums unter QGIS 4 anders heißen oder verschwinden; von Hand umgestellt
SKIP_CLASSES = {"QgsWkbTypes", "QVariant"}


def _namespace():
    names = {}
    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in dir(module):
            if name[:1] == "Q" and name not in names:
                names[name] = getattr(module, name)
    return names


def _qualified(owner, attr, namespace_cache):
    """Gibt den Enum-Namen zurück, unter dem `owner.attr` erreichbar sein muss, sonst None."""
    value = getattr(owner, attr, None)
    if value is None or isinstance(value, (bool, str, float)):
        return None
    enum_type = type(value)
    module = getattr(enum_type, "__module__", "") or ""
    if enum_type is int or not issubclass(enum_type, int):
        return None
    if not module.startswith(("PyQt5", "PyQt6", "qgis")):
        return None
    enum_name = enum_type.__name__
    holder = getattr(owner, enum_name, None)
    if holder is not enum_type:
        return None
    member = getattr(holder, attr, None)
    if member is None or int(member) != int(value):
        return None
    return enum_name


def scan_source(source, namespace):
    """Liefert [(Zeile, Spalte_von, Spalte_bis, Klasse, Name, Enum)] der unqualifizierten Stellen."""
    found = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return found
    for index in range(len(tokens) - 2):
        first, dot, second = tokens[index:index + 3]
        if first.type != tokenize.NAME or dot.string != "." or second.type != tokenize.NAME:
            continue
        if first.string in SKIP_CLASSES or first.string not in namespace:
            continue
        if index and tokens[index - 1].string == ".":
            # Kette wie self.Qt.X oder QtCore.Qt.X: nur Modulpräfixe zulassen
            before = tokens[index - 2].string if index >= 2 else ""
            if not before.startswith("Qt") or before == "Qt":
                continue
        enum_name = _qualified(namespace[first.string], second.string, namespace)
        if enum_name:
            found.append((second.start[0], second.start[1], second.end[1],
                          first.string, second.string, enum_name))
    return found


def iter_files(paths):
    for entry in paths:
        path = Path(entry)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts
                              and p.resolve() != Path(__file__).resolve())
        elif path.suffix == ".py":
            yield path


def apply_fixes(source, found):
    lines = source.splitlines(keepends=True)
    for row, start, _end, _cls, name, enum_name in sorted(found, reverse=True):
        line = lines[row - 1]
        lines[row - 1] = line[:start] + enum_name + "." + name + line[start + len(name):]
    return "".join(lines)


def main(argv):
    fix = "--fix" in argv
    paths = [a for a in argv if not a.startswith("--")] or DEFAULT_PATHS
    namespace = _namespace()
    total = 0
    for path in iter_files(paths):
        source = open(path, encoding="utf-8", newline="").read()
        found = scan_source(source, namespace)
        if not found:
            continue
        total += len(found)
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print("%s: %d" % (rel, len(found)))
        if fix:
            path.write_text(apply_fixes(source, found), encoding="utf-8", newline="")
        else:
            for row, _s, _e, cls, name, enum_name in found[:5]:
                print("  %d: %s.%s -> %s.%s.%s" % (row, cls, name, cls, enum_name, name))
    print("%d Stellen%s" % (total, " umgestellt" if fix else ""))
    return 0 if (fix or not total) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
