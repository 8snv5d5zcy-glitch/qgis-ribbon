"""Plugin-ZIP für das QGIS-Plugin-Repository bauen und prüfen.

Aufruf: ``python tools/build_zip.py [--out dist]``. Packt ``qgis_ribbon/``
ohne ``__pycache__``, ``*.pyc`` und versteckte Dateien in
``<out>/qgis_ribbon-<version>.zip`` (ein Ordner ``qgis_ribbon/`` im ZIP).

Prüft vorher, was das Repository verlangt: Pflichtfelder in
``metadata.txt``, nur ASCII dort, Lizenzdatei und Icon im Plugin,
Größe unter 25 MB. Nur Standardbibliothek, Python 3.7.
"""

import argparse
import configparser
import io
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN = os.path.join(ROOT, "qgis_ribbon")
NAME = "qgis_ribbon"
REQUIRED = ("name", "qgisMinimumVersion", "description", "about", "version", "author", "email",
            "repository", "tracker")
MAX_BYTES = 25 * 1024 * 1024
SKIP_DIRS = {"__pycache__"}
SKIP_EXT = (".pyc", ".pyo")


class BuildError(Exception):
    pass


def read_metadata(folder=PLUGIN):
    path = os.path.join(folder, "metadata.txt")
    with io.open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BuildError("metadata.txt ist nicht ASCII (Byte %d)" % exc.start)
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    if not parser.has_section("general"):
        raise BuildError("metadata.txt: Abschnitt [general] fehlt")
    return dict(parser.items("general"))


def check(folder=PLUGIN):
    """Fehlerliste (leer = in Ordnung) und Metadaten."""
    errors = []
    try:
        meta = read_metadata(folder)
    except BuildError as exc:
        return [str(exc)], {}
    for key in REQUIRED:
        if not meta.get(key, "").strip():
            errors.append("metadata.txt: %s fehlt" % key)
    for key in ("repository", "tracker", "homepage"):
        if meta.get(key) and not meta[key].startswith("https://"):
            errors.append("metadata.txt: %s ist keine https-Adresse" % key)
    if not os.path.isfile(os.path.join(folder, "LICENSE")):
        errors.append("LICENSE fehlt im Plugin-Ordner")
    icon = meta.get("icon")
    if not icon or not os.path.isfile(os.path.join(folder, icon)):
        errors.append("Icon fehlt: %s" % icon)
    if not os.path.isfile(os.path.join(folder, "__init__.py")):
        errors.append("__init__.py fehlt")
    return errors, meta


def files(folder=PLUGIN):
    """(Pfad, Name im ZIP) aller Dateien, sortiert."""
    out = []
    for current, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or name.endswith(SKIP_EXT):
                continue
            path = os.path.join(current, name)
            rel = os.path.relpath(path, folder).replace(os.sep, "/")
            out.append((path, NAME + "/" + rel))
    return out


def build(out_dir, folder=PLUGIN):
    errors, meta = check(folder)
    if errors:
        raise BuildError("\n".join(errors))
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "%s-%s.zip" % (NAME, meta["version"]))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arc in files(folder):
            zf.write(path, arc)
    size = os.path.getsize(target)
    if size > MAX_BYTES:
        os.remove(target)
        raise BuildError("ZIP zu groß: %.1f MB" % (size / 1048576.0))
    return target, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args(argv)
    try:
        target, size = build(args.out)
    except BuildError as exc:
        print("Fehler:\n%s" % exc)
        return 1
    print("Geschrieben: %s (%.2f MB, %d Dateien)" % (target, size / 1048576.0, len(files())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
