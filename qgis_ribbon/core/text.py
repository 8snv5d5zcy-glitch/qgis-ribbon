"""Texte fremder Quellen (Tooltips von Plugins, Beschreibungen von Werkzeugen) als reiner Text.

Viele Plugins setzen ihre Tooltips als Rich Text (``<br>``, ``<b>``, ``<p>``),
Werkzeuge des Werkzeugkastens ihre Kurzbeschreibung ebenso. Der Ribbon
maskiert Beschreibungen in seinen Tooltips; ohne Umwandlung erschienen die
Tags dort als Text. ``plain_text`` macht aus Umbrüchen und Blocktags (auch öffnenden) Zeilenumbrüche, lässt
übrige Tags weg, löst Entitäten auf und kürzt lange Texte.

Ohne das Modul ``html``: Es lädt beim Import ``html.entities`` (rund 17 ms).
"""

import re

LIMIT = 300

# Umbruch an Zeilenumbrüchen und an öffnenden wie schließenden Blocktags; mehrere fallen zusammen
_BREAK = re.compile(r"<\s*/?\s*(?:br|p|div|li|tr|h[1-6]|ul|ol|table)\b[^<>]*>", re.IGNORECASE)
# Tag = „<“ direkt gefolgt von Buchstabe, „/“ oder „!“; „a < b“ bleibt stehen
_TAG = re.compile(r"<!--.*?-->|<[A-Za-z/!][^<>]*>", re.DOTALL)
_ENTITY = re.compile(r"&(#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z]+);")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ", "ndash": "–",
          "mdash": "—", "hellip": "…", "laquo": "«", "raquo": "»", "bdquo": "„", "ldquo": "“",
          "rdquo": "”", "lsquo": "‘", "rsquo": "’", "auml": "ä", "ouml": "ö", "uuml": "ü",
          "Auml": "Ä", "Ouml": "Ö", "Uuml": "Ü", "szlig": "ß", "deg": "°", "copy": "©"}
_SPACES = re.compile(r"[ \t\r\f\v ]+")


def _entity(match):
    name = match.group(1)
    if name[0] != "#":
        return _NAMED.get(name, match.group(0))
    try:
        code = int(name[2:], 16) if name[1] in "xX" else int(name[1:])
        return chr(code)
    except (ValueError, OverflowError):
        return match.group(0)


def plain_text(text, limit=LIMIT):
    """Reiner Text aus einem Text, der HTML enthalten kann; höchstens ``limit`` Zeichen."""
    if not text:
        return ""
    if "<" not in text and "&" not in text and "\n" not in text and "  " not in text and len(text) <= limit:
        return text.strip()   # häufigster Fall, ohne reguläre Ausdrücke (Suchindex mit allen Werkzeugen)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = _ENTITY.sub(_entity, text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    if limit and len(text) > limit:
        cut = text[:limit - 1]
        space = max(cut.rfind(" "), cut.rfind("\n"))
        if space > limit // 2:
            cut = cut[:space]
        text = cut.rstrip(" ,;:.\n") + "…"
    return text
