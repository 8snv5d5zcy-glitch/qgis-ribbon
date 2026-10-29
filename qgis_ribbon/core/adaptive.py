"""Adaptive Gruppenbreite (ohne qgis-Imports).

Jede Gruppe eines Tabs hat mehrere Fassungen, von der schmalsten
(eingeklappt: ein Button mit Menü) über die definierte Fassung bis zu
erweiterten Fassungen (mehr Galerie-Kacheln). ``choose`` wählt je Gruppe eine Fassung, sodass die
verfügbare Breite möglichst ausgenutzt und nie überschritten wird:

1. Start mit der definierten Fassung jeder Gruppe.
2. Zu breit: Gruppen schrittweise verkleinern, reihum von rechts (die am
   wenigsten verkleinerte Gruppe zuerst, bei Gleichstand die rechte).
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


def choose(widths, ideal, available, spacing=0):
    """Fassung je Gruppe.

    ``widths``: je Gruppe die Breiten ihrer Fassungen, aufsteigend (Index 0 =
    schmalste). ``ideal``: Index der definierten Fassung je Gruppe.
    ``available``: verfügbare Breite. ``spacing``: Abstand zwischen Gruppen.
    Passt selbst die schmalste Fassung aller Gruppen nicht, bleibt es bei ihr
    (der Ribbon scrollt dann).
    """
    choice = [min(max(i, 0), len(w) - 1) for w, i in zip(widths, ideal)]
    base = list(choice)
    n = len(widths)
    if total(widths, choice, spacing) > available:
        shrunk = [0] * n
        while total(widths, choice, spacing) > available:
            candidates = [g for g in range(n) if choice[g] > 0]
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
