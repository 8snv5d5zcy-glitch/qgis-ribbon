"""Adaptive Gruppenbreite (ohne qgis-Imports).

Jede Gruppe eines Tabs hat mehrere Fassungen, von der schmalsten
(eingeklappt: ein Button mit Menü) über die definierte Fassung bis zu
erweiterten Fassungen (mehr Galerie-Kacheln). ``choose`` wählt je Gruppe eine Fassung, sodass die
verfügbare Breite möglichst ausgenutzt und nie überschritten wird:

1. Start mit der definierten Fassung jeder Gruppe.
2. Zu breit: zuerst geben Galerien Kacheln ab (bis auf ``soft`` je Gruppe,
   in der Regel zwei Kacheln), reihum von rechts; erst dann verkleinern sich
   die Gruppen schrittweise weiter (Buttons kleiner, Beschriftungen weg),
   reihum von rechts (die am wenigsten verkleinerte Gruppe zuerst, bei
   Gleichstand die rechte).
3. Platz übrig (auch nach dem Verkleinern, dessen Schritte grob sein
   können): Gruppen schrittweise vergrößern, reihum von links (die am
   wenigsten vergrößerte Gruppe zuerst), solange der nächste Schritt passt.
   Ein Schritt, der nicht passt, wird übersprungen; kleinere Schritte anderer
   Gruppen können noch passen. Gruppen unter ihrer definierten Fassung
   wachsen zuerst; erst wenn keine von ihnen mehr passt, wachsen andere
   über ihre definierte Fassung hinaus (die Fläche bleibt nie ungenutzt).

So wächst der Ribbon beim Aufziehen des Fensters fließend Gruppe für Gruppe
und schrumpft beim Verkleinern von rechts.
"""


def total(widths, choice, spacing=0):
    if not widths:
        return 0
    return sum(w[i] for w, i in zip(widths, choice)) + spacing * (len(widths) - 1)


def choose(widths, ideal, available, spacing=0, soft=None):
    """Fassung je Gruppe.

    ``widths``: je Gruppe die Breiten ihrer Fassungen, aufsteigend (Index 0 =
    schmalste). ``ideal``: Index der definierten Fassung je Gruppe.
    ``available``: verfügbare Breite. ``spacing``: Abstand zwischen Gruppen.
    ``soft``: je Gruppe die schmalste Fassung, die nur Galerie-Kacheln abgibt
    (sonst ``ideal``); bis dorthin verkleinern sich alle Gruppen zuerst.
    Passt selbst die schmalste Fassung aller Gruppen nicht, bleibt es bei ihr
    (der Ribbon scrollt dann).
    """
    choice = [min(max(i, 0), len(w) - 1) for w, i in zip(widths, ideal)]
    base = list(choice)
    n = len(widths)
    floors = [min(max(f, 0), len(w) - 1) for w, f in zip(widths, soft)] if soft is not None else list(choice)
    if total(widths, choice, spacing) > available:
        shrunk = [0] * n
        for floor in (floors, [0] * n):
            while total(widths, choice, spacing) > available:
                candidates = [g for g in range(n) if choice[g] > floor[g]]
                if not candidates:
                    break
                g = min(candidates, key=lambda g: (shrunk[g], -g))
                choice[g] -= 1
                shrunk[g] += 1
    # Auffüllen: wenig verkleinerte Gruppen zuerst, von links
    grown = [0] * n
    used = total(widths, choice, spacing)
    while True:
        best = None
        for g in range(n):
            nxt = choice[g] + 1
            if nxt >= len(widths[g]):
                continue
            extra = widths[g][nxt] - widths[g][choice[g]]
            if used + extra > available:
                continue
            key = (choice[g] >= base[g], grown[g], g)   # unter der definierten Fassung zuerst
            if best is None or key < best[0]:
                best = (key, g, extra)
        if best is None:
            return choice
        _key, g, extra = best
        choice[g] += 1
        grown[g] += 1
        used += extra


def pack(entries, rows=3, spacing=0):
    """Elemente einer Gruppe in Spalten legen.

    ``entries``: ``(Schlüssel, Art, Breite, nur_icon)`` in der definierten
    Reihenfolge; Art ``"col"`` belegt eine eigene Spalte, sonst wird gestapelt
    (bis ``rows`` Zeilen je Spalte). Ein Element nur mit Icon rückt in eine
    frühere Zeile derselben Spalte, die ebenfalls nur Icons enthält, wenn die
    Spalte dadurch nicht breiter wird. So lassen schmale Icons neben breiten
    Feldern keine Lücken (Gruppe Einrasten ohne Beschriftungen).

    Ergebnis: ``[(Art, [[Schlüssel je Zeile]], Breite)]``.
    """
    cols = []
    stack = []      # [[Schlüssel], Breite der Zeile, nur Icons]

    def flush():
        if stack:
            cols.append(("stack", [r[0] for r in stack], max(r[1] for r in stack)))
            del stack[:]

    for key, how, width, icon in entries:
        if how == "col":
            flush()
            cols.append(("col", [[key]], width))
            continue
        if icon and stack:
            limit = max(r[1] for r in stack)
            row = next((r for r in stack if r[2] and r[1] + spacing + width <= limit), None)
            if row is not None:
                row[0].append(key)
                row[1] += spacing + width
                continue
        stack.append([[key], width, icon])
        if len(stack) == rows:
            flush()
    flush()
    return cols
