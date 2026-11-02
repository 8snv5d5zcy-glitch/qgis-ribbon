"""Gemeinsame Logik der Prüfskripte: QGIS-Installation, Name der Profil-INI, Testprofil ohne 3D-Materialien.

``--qgis`` der Skripte nimmt ``3`` (QGIS 3.44 LTR), ``4`` (QGIS 4) oder den Pfad einer
``qgis-bin.exe`` bzw. ``qgis-ltr-bin.exe``. Die Installationsordner lassen sich über
``QGIS3_ROOT`` und ``QGIS4_ROOT`` ändern. Außerhalb von Windows ist je Rechner nur eine
Version installiert: ``3`` und ``4`` nennen dann das INI-Format, gestartet wird ``qgis``
vom Suchpfad.
"""
import os
import re
import subprocess

ROOTS = {"3": os.environ.get("QGIS3_ROOT", r"C:\Program Files\QGIS 3.44.15"),
         "4": os.environ.get("QGIS4_ROOT", r"C:\Program Files\QGIS 4.2.3")}
BINARIES = {"3": "qgis-ltr-bin.exe", "4": "qgis-bin.exe"}
PYTHON = {"3": "python-qgis-ltr.bat", "4": "python-qgis.bat"}
DEFAULT = "3"


def major(qgis):
    """``"3"`` oder ``"4"`` für eine Angabe von ``--qgis``."""
    if qgis in ROOTS:
        return qgis
    found = re.search(r"QGIS\s*(\d+)", qgis)
    if found and found.group(1) in ROOTS:
        return found.group(1)
    return "3" if "ltr" in os.path.basename(qgis).lower() else "4"


def executable(qgis=DEFAULT, windows=os.name == "nt"):
    """Pfad der QGIS-Programmdatei."""
    if qgis not in ROOTS:
        return qgis
    if not windows:
        return "qgis"
    return os.path.join(ROOTS[qgis], "bin", BINARIES[qgis])


def ini_name(qgis=DEFAULT):
    """Name der Einstellungsdatei im Profil: ``QGIS3.ini`` oder ``QGIS4.ini``."""
    return "QGIS%s.ini" % major(qgis)


def kill(proc):
    """Hängendes QGIS beenden, unter Windows samt Kindprozessen."""
    if os.name == "nt":
        subprocess.call(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
    else:
        proc.kill()
    proc.wait()


def drop_3d_materials():
    """Nimmt die 3D-Materialien aus dem Stil des (frischen) Testprofils; nur in QGIS aufrufen.

    QGIS 4.2 rendert im Eigenschaften-Dialog Vorschaubilder der Materialien mit Qt3D und wartet
    ohne Zeitlimit auf das Bild. Ohne Grafikkarte (Linux-Container) kommt es nie, der Dialog
    kehrt dann nicht aus exec() zurück.
    """
    from qgis.core import QgsStyle
    entity = getattr(QgsStyle.StyleEntity, "MaterialSettingsEntity", None)
    if entity is None:
        return []
    style = QgsStyle.defaultStyle()
    names = style.materialSettingsNames()
    for name in names:
        style.removeEntityByName(entity, name)
    return names
