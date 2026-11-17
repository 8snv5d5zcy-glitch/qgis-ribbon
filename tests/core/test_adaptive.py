from qgis_ribbon.core.adaptive import choose, pack, total

# drei Gruppen: [eingeklappt, klein, ideal, größer, am größten]
W = [[40, 100, 150, 180, 210], [40, 80, 120], [40, 90, 140, 160]]
IDEAL = [2, 2, 2]


def test_fits_exactly_keeps_ideal():
    assert choose(W, IDEAL, 410) == [2, 2, 2]


def test_shrinks_from_the_right_first():
    # Gruppe 2 wird kleiner; der Rest des Platzes geht an Gruppe 0 (Fläche ausnutzen)
    assert choose(W, IDEAL, 409) == [3, 2, 1]
    assert choose(W, IDEAL, 359) == [3, 1, 1]
    assert choose(W, IDEAL, 319) == [1, 2, 1]   # 270 px wären möglich, 310 nutzen den Platz
    # zweite Runde wieder von rechts; frei gewordener Platz geht an Gruppe 1 zurück
    assert choose(W, IDEAL, 269) == [1, 2, 0]


def test_never_exceeds_available_while_reducible():
    for avail in range(120, 700, 7):
        c = choose(W, IDEAL, avail)
        if total(W, c) > avail:
            assert c == [0, 0, 0]


def test_grows_round_robin_from_left():
    assert choose(W, IDEAL, 440) == [3, 2, 2]
    assert choose(W, IDEAL, 460) == [3, 2, 3]
    assert choose(W, IDEAL, 490) == [4, 2, 3]


def test_skips_steps_that_do_not_fit():
    # Gruppe 0 braucht +30, Gruppe 2 nur +20: bei 25 frei wächst Gruppe 2
    assert choose(W, IDEAL, 435) == [2, 2, 3]


def test_uses_maximum_of_space():
    assert choose(W, IDEAL, 10000) == [4, 2, 3]


def test_spacing_counts_between_groups():
    assert choose(W, IDEAL, 410 + 2 * 8, spacing=8) == [2, 2, 2]
    assert choose(W, IDEAL, 410 + 2 * 8 - 1, spacing=8) == [3, 2, 1]


def test_too_narrow_stays_at_smallest():
    assert choose(W, IDEAL, 10) == [0, 0, 0]


def test_empty():
    assert choose([], [], 100) == []


def test_refills_after_coarse_shrink_step():
    # Gruppe 1 springt beim Verkleinern von 300 auf 40; der Platz geht an Gruppe 0
    widths = [[40, 100, 200, 260], [40, 300], [50, 60]]
    choice = choose(widths, [2, 1, 1], 420)
    assert choice == [3, 0, 1]
    choice = choose(widths, [2, 1, 1], 330)
    assert choice == [2, 0, 1] and sum(w[i] for w, i in zip(widths, choice)) <= 330
    choice = choose(widths, [3, 1, 1], 300)
    assert choice == [2, 0, 1]


def test_below_ideal_grows_first_then_others():
    # Gruppe 0 unter ihrer Fassung, aber deren nächster Schritt passt nicht: Gruppe 1 wächst
    widths = [[40, 400], [100, 130]]
    assert choose(widths, [1, 0], 200) == [0, 1]
    # Platz für einen Schritt: Gruppe 1 (unter ihrer Fassung) vor Gruppe 0 (links)
    widths = [[20, 30], [20, 30], [10, 60, 100]]
    assert choose(widths, [0, 1, 2], 65) == [0, 1, 0]


def test_gallery_gives_up_tiles_before_neighbours_lose_labels():
    """Gruppe 0: Galerie (Fassung 3 = drei Kacheln, 2 = zwei Kacheln); Gruppe 1: Buttons (1 = mit Beschriftung)."""
    widths = [[60, 150, 200, 250], [80, 200]]
    ideal = [3, 1]
    # ohne Vorrang verliert die rechte Gruppe zuerst ihre Beschriftung
    assert choose(widths, ideal, 410) == [3, 0]
    # mit Vorrang gibt die Galerie zuerst eine Kachel ab
    assert choose(widths, ideal, 410, soft=[2, 1]) == [2, 1]
    # reicht das nicht, geht es wie gewohnt weiter (von rechts)
    assert choose(widths, ideal, 300, soft=[2, 1]) == [2, 0]


def test_pack_moves_icons_into_an_icon_row_without_widening():
    """Einrasten ohne Beschriftungen: Icon, Feld, Icon, Feld, Leiste -> Icons in einer Zeile."""
    entries = [("magnet", "stack", 40, True), ("modus", "stack", 190, False), ("typ", "stack", 40, True),
               ("toleranz", "stack", 170, False), ("leiste", "stack", 90, False)]
    cols = pack(entries, rows=3, spacing=2)
    assert cols == [("stack", [["magnet", "typ"], ["modus"], ["toleranz"]], 190), ("stack", [["leiste"]], 90)]


def test_pack_keeps_equal_icons_and_labelled_rows():
    icons = [("a", "stack", 30, True), ("b", "stack", 30, True), ("c", "stack", 30, True), ("d", "stack", 30, True)]
    assert pack(icons, rows=3) == [("stack", [["a"], ["b"], ["c"]], 30), ("stack", [["d"]], 30)]
    mixed = [("feld", "stack", 150, False), ("i", "stack", 30, True), ("gross", "col", 60, False),
             ("j", "stack", 30, True)]
    assert pack(mixed, rows=3, spacing=2) == [("stack", [["feld"], ["i"]], 150), ("col", [["gross"]], 60),
                                              ("stack", [["j"]], 30)]
