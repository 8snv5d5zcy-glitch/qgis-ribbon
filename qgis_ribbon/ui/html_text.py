"""HTML-Maskierung für Tooltips.

Wie ``html.escape``; das Modul ``html`` lädt beim Import ``html.entities``
(rund 17 ms), die der Ribbon nicht braucht.
"""

_TABLE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;"})


def escape(text):
    return str(text).translate(_TABLE)
