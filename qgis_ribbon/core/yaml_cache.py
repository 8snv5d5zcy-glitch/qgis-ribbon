"""Zwischenspeicher für mitgelieferte YAML-Dateien (ohne qgis-Imports).

Das Einlesen der Ribbon-Definition und des Icon-Sets kostet trotz libyaml
zusammen gut 35 ms (Python-Konstruktion der Objekte), JSON unter 1 ms.
``load`` legt das gelesene YAML deshalb als JSON im Zwischenspeicher-Ordner
ab und nimmt beim nächsten Start diese Fassung, solange Pfad, Größe und
Änderungszeit der YAML-Datei gleich sind. Die YAML-Datei bleibt die einzige
Quelle; ein fehlender oder kaputter Zwischenspeicher fällt still auf das
YAML zurück, Fehler beim Schreiben werden ignoriert.

Den Ordner setzt das Plugin (``set_dir``, im QGIS-Profil); ohne Ordner
(Tests, Werkzeuge) wird immer das YAML gelesen.
"""

import hashlib
import io
import json
import os

FORMAT = 1
_dir = None


def set_dir(path):
    global _dir
    _dir = path


def get_dir():
    return _dir


def cache_file(path, cache_dir):
    """Datei des Zwischenspeichers für ``path`` (je YAML-Pfad eine Datei)."""
    name = os.path.splitext(os.path.basename(path))[0]
    # nur Dateiname, kein Sicherheitszweck
    digest = hashlib.sha1(os.path.abspath(path).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return os.path.join(cache_dir, "%s_%s.json" % (name, digest))


def safe_load(stream):
    """YAML sicher lesen (nur einfache Typen); mit libyaml, wenn vorhanden.

    libyaml (in QGIS enthalten) ist um ein Vielfaches schneller als der reine
    Python-Loader. Der Loader steht ausdrücklich im Aufruf, damit Prüfwerkzeuge
    (bandit, Plugin-Repository) ihn als sicher erkennen.
    """
    import yaml

    if hasattr(yaml, "CSafeLoader"):
        return yaml.load(stream, Loader=yaml.CSafeLoader)
    return yaml.safe_load(stream)


def _stamp(path):
    st = os.stat(path)
    return [FORMAT, os.path.abspath(path), st.st_size, st.st_mtime_ns]


def read_cached(path, cache_dir):
    """Daten aus dem Zwischenspeicher oder None (fehlt, veraltet, unlesbar)."""
    try:
        with io.open(cache_file(path, cache_dir), encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("stamp") == _stamp(path):
            return cached["data"]
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return None


def write_cache(path, cache_dir, data):
    target = cache_file(path, cache_dir)
    tmp = target + ".tmp"
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with io.open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"stamp": _stamp(path), "data": data}, fh, ensure_ascii=False,
                      separators=(",", ":"))
        os.replace(tmp, target)
    except (OSError, TypeError, ValueError):
        try:
            os.remove(tmp)
        except OSError:
            pass


def load(path, read, cache_dir=None):
    """Daten der YAML-Datei ``path``; ``read(path)`` liest das YAML selbst."""
    cache_dir = cache_dir or _dir
    data = read_cached(path, cache_dir) if cache_dir else None
    if data is None:
        data = read(path)
        if cache_dir:
            write_cache(path, cache_dir, data)
    return data
