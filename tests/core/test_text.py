"""Texte fremder Quellen als reiner Text (Tooltips von Plugins, Beschreibungen von Werkzeugen)."""
import pytest

from qgis_ribbon.core.text import LIMIT, plain_text


@pytest.mark.parametrize("raw,expected", [
    ("Erste Zeile<br>Zweite", "Erste Zeile\nZweite"),
    ("Eins<BR/>Zwei<br />Drei", "Eins\nZwei\nDrei"),
    ("<b>Fett</b> und <i>kursiv</i>", "Fett und kursiv"),
    ("<p>Absatz eins</p><p>Absatz zwei</p>", "Absatz eins\nAbsatz zwei"),
    ("<html><body><p style='margin:0'><span style=\"color:#f00\">Rot</span></p></body></html>", "Rot"),
    ("<ul><li>a</li><li>b</li></ul>", "a\nb"),
    ("Text&nbsp;mit&nbsp;Abstand", "Text mit Abstand"),
    ("Punkte &amp; Linien", "Punkte & Linien"),
    ("&lt;Layer&gt; &quot;x&quot; &#39;y&#39;", "<Layer> \"x\" 'y'"),
    ("&#228;&#xFC;", "äü"),
    ("&unbekannt; bleibt", "&unbekannt; bleibt"),
    ("a < b und c > d", "a < b und c > d"),
    ("x<3", "x<3"),
    ("  viel   \t Leerraum \n\n\n hier ", "viel Leerraum\nhier"),
    ("<!-- Kommentar -->sichtbar", "sichtbar"),
    ("Nur Text", "Nur Text"),
    ("", ""),
    (None, ""),
])
def test_plain_text(raw, expected):
    assert plain_text(raw) == expected


def test_long_text_is_cut_at_a_word():
    raw = "<p>" + " ".join(["Wort%d" % i for i in range(200)]) + "</p>"
    out = plain_text(raw)
    assert len(out) <= LIMIT and out.endswith("…")
    assert out[:-1].split(" ")[-1].startswith("Wort")     # kein halbes Wort
    assert plain_text("x" * 1000, limit=50) == "x" * 49 + "…"
    assert plain_text("kurz", limit=50) == "kurz"
