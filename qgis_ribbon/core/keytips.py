"""KeyTips: Buchstabenkürzel für die Tastaturbedienung (ohne qgis-Imports).

Ablauf wie in Pro: Alt drücken und loslassen zeigt die KeyTips der Tabs, der
Schnellzugriffsleiste und der Suche (Ebene 0). Ein Tab-Kürzel öffnet den Tab
und zeigt die KeyTips seiner Elemente (Ebene 1).

``assign(labels)`` vergibt Kürzel aus den deutschen Beschriftungen,
deterministisch in der gegebenen Reihenfolge:

- zuerst ein Buchstabe, bevorzugt Wortanfänge, dann weitere Buchstaben;
- reichen die Buchstaben nicht, zwei Zeichen mit einem Präfix, das selbst
  kein Kürzel ist. Kein Kürzel ist Anfang eines anderen, damit beim Tippen
  sofort klar ist, wann ein Kürzel vollständig ist.

KeyTips anderer Programme werden nicht übernommen; sie passen zu deren
Beschriftungen und sind teils nicht eindeutig.

Eigene Kürzel (Overrides des Nutzers, Dialog „Kürzel anpassen“) gehen der
automatischen Vergabe vor (``fixed``). Sie hängen an stabilen Schlüsseln:
``tab:<Tab-ID>`` für Tabs, ``<Tab-ID>/<Befehls-ID>`` für Elemente
(``target_keys``), nicht an der Position.
"""

import string
from .i18n import tr

LETTERS = string.ascii_uppercase
MAX_LEN = 2
_UMLAUTS = {"Ä": "A", "Ö": "O", "Ü": "U", "ß": "S"}


def _letters(text):
    """Großbuchstaben A–Z aus dem Text (Umlaute auf den Grundbuchstaben)."""
    out = []
    for ch in text.upper():
        ch = _UMLAUTS.get(ch, ch)
        if ch in LETTERS:
            out.append(ch)
    return out


def _preferences(label):
    """Buchstaben in Vorzugsreihenfolge: Wortanfänge, dann übrige, dann das ganze Alphabet."""
    words = [w for w in label.replace("-", " ").replace("/", " ").split() if _letters(w)]
    order = []
    for w in words:
        first = _letters(w)[0]
        if first not in order:
            order.append(first)
    for ch in _letters(label):
        if ch not in order:
            order.append(ch)
    for ch in LETTERS:
        if ch not in order:
            order.append(ch)
    return order


def normalize(code):
    """Eingabe eines eigenen Kürzels -> Großbuchstaben ohne Leerzeichen (Umlaute auf Grundbuchstaben)."""
    return "".join(_UMLAUTS.get(c, c) for c in (code or "").strip().upper())


def code_error(code):
    """Fehlertext für ein eigenes Kürzel oder None (1–2 Buchstaben A–Z)."""
    if not 1 <= len(code) <= MAX_LEN or any(c not in LETTERS for c in code):
        return tr("KeyTip: 1–%d letters A–Z") % MAX_LEN
    return None


def conflicts(codes):
    """Paare (i, j) mit gleichem Kürzel oder Kürzel i als Anfang von Kürzel j."""
    out = []
    for i, a in enumerate(codes):
        if not a:
            continue
        for j, b in enumerate(codes):
            if i != j and b and (a == b and i < j or (a != b and b.startswith(a))):
                out.append((i, j))
    return out


def assign(labels, reserved=(), fixed=None):
    """Liste von Beschriftungen -> Liste eindeutiger Kürzel (gleiche Reihenfolge).

    ``reserved``: Kürzel, die schon vergeben sind (z. B. ``Q`` für die Suche).
    ``fixed``: eigene Kürzel je Index (Overrides des Nutzers). Sie haben Vorrang;
    die übrigen Kürzel werden darum herum vergeben, ohne Dubletten und ohne
    Präfix-Konflikte. Ein eigenes Kürzel, das mit einem reservierten, einem
    früheren eigenen Kürzel kollidiert oder ungültig ist, wird übergangen.
    """
    reserved = [r.upper() for r in reserved]
    result = [None] * len(labels)
    own = []                                     # angewandte eigene Kürzel
    for i, code in sorted((fixed or {}).items()):
        code = normalize(code)
        if not 0 <= i < len(labels) or code_error(code):
            continue
        if conflicts(reserved + own + [code]):
            continue
        result[i] = code
        own.append(code)
    blocked = set(reserved) | set(own)
    first_letters = {c[0] for c in blocked}      # Einzelbuchstabe wäre Anfang eines Kürzels
    prefs = [_preferences(label) for label in labels]

    # 1. Ein Buchstabe, solange genug frei bleiben
    taken = set(blocked) | first_letters
    for i, order in enumerate(prefs):
        if result[i] is not None:
            continue
        for ch in order:
            if ch not in taken:
                result[i] = ch
                taken.add(ch)
                break

    fixed_idx = {i for i, k in enumerate(result) if k in own and k is not None}
    left = [i for i, k in enumerate(result) if k is None]
    if not left:
        return result

    # 2. Präfixbuchstaben für zweistellige Kürzel: kein Einzelkürzel.
    #    Reichen sie nicht, werden automatisch vergebene Einzelbuchstaben frei gemacht.
    def free_prefixes():
        singles = {k for k in result if k and len(k) == 1} | {r for r in blocked if len(r) == 1}
        return [ch for ch in LETTERS if ch not in singles]

    prefixes = free_prefixes()
    # Jeder Präfix trägt bis zu 26 Kürzel; reichen sie nicht, Einzelbuchstaben freigeben
    while len(prefixes) * len(LETTERS) < len(left):
        autos = [i for i, k in enumerate(result) if k and len(k) == 1 and i not in fixed_idx]
        if not autos:
            raise ValueError(tr("Too many items for KeyTips: %d") % len(labels))
        last = max(autos)
        result[last] = None
        left.append(last)
        prefixes = free_prefixes()
    left.sort()
    taken = {k for k in result if k} | set(blocked)
    for i in left:
        order = prefs[i]
        cand = [p for p in order if p in prefixes] + [p for p in prefixes if p not in order]
        done = False
        for p in cand:
            for ch in order:
                code = p + ch
                if code not in taken:
                    result[i] = code
                    taken.add(code)
                    done = True
                    break
            if done:
                break
        if not done:
            raise ValueError(tr("Too many items for KeyTips: %d") % len(labels))
    return result


def target_keys(targets):
    """Stabile Schlüssel für Overrides: Befehls-ID (oder ``menu:Beschriftung``), Wiederholung mit ``#n``.

    ``targets``: Folge von (Befehls-ID oder None, Beschriftung) in Aufbaureihenfolge.
    """
    seen = {}
    keys = []
    for command_id, label in targets:
        base = command_id or "menu:" + label
        seen[base] = seen.get(base, 0) + 1
        keys.append(base if seen[base] == 1 else "%s#%d" % (base, seen[base]))
    return keys


def tab_key(tab_id):
    return "tab:" + tab_id


def element_key(tab_id, key):
    return "%s/%s" % (tab_id, key)


def matches(codes, typed):
    """Eingetippte Zeichen -> (Treffer-Index oder None, ob weitere Eingabe möglich ist)."""
    typed = typed.upper()
    hit = None
    more = False
    for i, code in enumerate(codes):
        if code is None:
            continue
        if code == typed:
            hit = i
        elif code.startswith(typed):
            more = True
    return hit, more


QUICK_ACCESS_KEYS = tuple("123456789")
SEARCH_KEY = "Q"


def top_level(tab_labels, quick_access_count, fixed=None):
    """Ebene 0: Kürzel für Tabs, Schnellzugriff (1–9) und Suche (Q).

    Liefert (Tab-Kürzel, Schnellzugriff-Kürzel). ``Q`` ist für die Suche
    reserviert, wie in Pro und Office; Schnellzugriff und Suche sind fest.
    ``fixed``: eigene Tab-Kürzel je Index.
    """
    tabs = assign(tab_labels, reserved=(SEARCH_KEY,), fixed=fixed)
    qat = list(QUICK_ACCESS_KEYS[:quick_access_count])
    return tabs, qat
