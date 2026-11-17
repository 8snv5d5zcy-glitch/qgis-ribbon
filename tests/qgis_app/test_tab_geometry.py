"""Lage der Tabs nach einem Layerwechsel: alle Tabs des neuen Kontexts im Bild.

Offscreen sind die Schriften breiter als in QGIS (Konventionen, Design); die
Breiten hier sind daher nur „passt“ oder „passt nicht“, keine festen Zahlen.
"""
import pytest
from qgis.core import QgsApplication

from qgis_ribbon.plugin import RibbonPlugin

SWITCHES = [
    ("raster", "raster_darstellung", "vector"),
    ("table", "tabelle_daten", "vector"),
    ("vector", "vektor_daten", "raster"),
    ("raster", "karte", "vector"),
    ("vector", "vektor_beschriftung", "table"),
]


def settle():
    for _ in range(3):
        QgsApplication.processEvents()


@pytest.fixture
def plugin(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


def shown(plugin):
    bar = plugin.widget.tabbar
    return [i for i in range(bar.count()) if bar.isTabVisible(i) and i != bar.end]


def context_group(plugin):
    bar = plugin.widget.tabbar
    current = bar.currentIndex()
    ctx = bar.context_of(current)
    if ctx is None:
        return [current]
    return [i for i in shown(plugin) if bar.context_of(i) == ctx]


def in_view(bar, i):
    r = bar.tabRect(i)
    return not r.isEmpty() and r.left() >= 0 and r.right() < bar.width()


def visible_area(bar):
    """Breite ohne Scrollpfeile (sie liegen rechts über den Tabs)."""
    from qgis.PyQt.QtWidgets import QToolButton
    arrows = [b for b in bar.findChildren(QToolButton) if b.isVisible()]
    return min([b.x() for b in arrows] + [bar.width()])


def switch(fake_iface, plugin, layers, start, tab, target):
    fake_iface.set_active_layer(layers[start])
    settle()
    plugin.widget.select_tab(tab)
    settle()
    fake_iface.set_active_layer(layers[target])
    settle()


def check_layout(plugin):
    bar = plugin.widget.tabbar
    ids = [plugin.ribbon.tabs[i].id for i in shown(plugin)]
    # Reihenfolge wie in der Definition, Kontext-Tabs direkt hinter den Haupt-Tabs
    contextual = [plugin.ribbon.tabs[i].contextual for i in shown(plugin)]
    assert contextual == sorted(contextual), ids
    for i in shown(plugin):
        assert not bar.tabRect(i).isEmpty()
    area = visible_area(bar)
    group = context_group(plugin)
    first, last = bar.tabRect(group[0]), bar.tabRect(group[-1])
    if last.right() - first.left() < area:
        for i in group:
            r = bar.tabRect(i)
            assert r.left() >= 0 and r.right() <= area, (ids, plugin.widget.current_tab())
    else:
        r = bar.tabRect(bar.currentIndex())
        assert r.left() >= 0 and r.left() < area


@pytest.mark.parametrize("width", [900, 1100, 1300])
@pytest.mark.parametrize("start,tab,target", SWITCHES)
def test_new_context_is_in_view_when_tabs_overflow(fake_iface, plugin, layers, width, start, tab, target):
    fake_iface.mainWindow().resize(width, 800)
    settle()
    switch(fake_iface, plugin, layers, start, tab, target)
    check_layout(plugin)


def test_group_and_point_cloud_like_switches(fake_iface, plugin, layers):
    """Von einer Gruppe in der Layerliste auf einen Vektorlayer: alle drei Vektor-Tabs im Bild."""
    from qgis.core import QgsProject
    fake_iface.mainWindow().resize(1000, 800)
    settle()
    group = QgsProject.instance().layerTreeRoot().addGroup("G")
    try:
        fake_iface.select_group(group)
        settle()
        if plugin.widget.is_tab_visible("gruppe_darstellung"):
            plugin.widget.select_tab("gruppe_darstellung")
            settle()
        fake_iface.set_active_layer(layers["vector"])
        settle()
        assert plugin.widget.current_tab() == "vektor_darstellung"
        check_layout(plugin)
    finally:
        QgsProject.instance().layerTreeRoot().removeChildNode(group)


def test_wide_window_starts_at_the_left_without_arrows(fake_iface, plugin, layers):
    fake_iface.mainWindow().resize(4000, 800)
    settle()
    switch(fake_iface, plugin, layers, "raster", "raster_darstellung", "vector")
    bar = plugin.widget.tabbar
    assert bar._level == 0
    assert bar.tabRect(shown(plugin)[0]).left() == 0
    assert all(in_view(bar, i) for i in shown(plugin))


def test_compact_levels_before_arrows(fake_iface, plugin, layers):
    """Bei knapper Breite erst kleiner Innenabstand, dann gekürzter und kein Kontextname."""
    bar = plugin.widget.tabbar
    fake_iface.set_active_layer(layers["vector"])
    fake_iface.mainWindow().resize(4000, 800)   # Suchfeld in voller Breite (es weicht erst nach Stufe 3)
    settle()
    needed = [bar.needed_width(level) for level in range(len(bar.LEVELS))]
    assert needed == sorted(needed, reverse=True) and needed[0] > needed[-1]
    for level in range(1, len(bar.LEVELS)):
        width = needed[level] + 1
        assert bar.fit_level(width) == level
    # Die Breite des Fensters so wählen, dass Stufe 1 gerade passt
    mw = fake_iface.mainWindow()
    mw.resize(mw.width() + needed[1] + 2 - bar.width(), 800)
    settle()
    assert bar._level == 1
    assert all(in_view(bar, i) for i in shown(plugin))
    mw.resize(mw.width() + needed[0] + 2 - bar.width(), 800)
    settle()
    assert bar._level == 0


def test_reveal_does_not_emit_or_build(fake_iface, plugin, layers):
    """Der Bildlauf über gesperrtes Wählen löst kein currentChanged aus und baut keinen Tab."""
    w = plugin.widget
    fake_iface.mainWindow().resize(900, 800)
    settle()
    fake_iface.set_active_layer(layers["raster"])
    settle()
    w.select_tab("raster_darstellung")
    settle()
    seen = []
    w.tabbar.currentChanged.connect(seen.append)
    built = set(w._pages)
    fake_iface.set_active_layer(layers["vector"])
    settle()
    assert seen == [w._index["vektor_darstellung"]]
    assert set(w._pages) - built == {"vektor_darstellung"}
    w.tabbar.reveal()
    assert seen == [w._index["vektor_darstellung"]]


def test_right_arrow_reaches_the_last_tab(fake_iface, plugin, layers):
    """Der letzte Tab der Definition ist ein ausgeblendeter Kontext-Tab; der rechte Pfeil bleibt bedienbar."""
    from qgis.PyQt.QtWidgets import QToolButton
    assert not plugin.widget.is_tab_visible(plugin.ribbon.tabs[-1].id)
    fake_iface.mainWindow().resize(900, 800)
    settle()
    fake_iface.set_active_layer(layers["vector"])
    settle()
    plugin.widget.select_tab("karte")
    settle()
    bar = plugin.widget.tabbar
    last = shown(plugin)[-1]
    assert not in_view(bar, last)
    right = max((b for b in bar.findChildren(QToolButton) if b.isVisible()), key=lambda b: b.x())
    for _ in range(40):
        if bar.tabRect(last).right() <= visible_area(bar):
            break
        assert right.isEnabled()
        right.click()
        settle()
    assert bar.tabRect(last).right() <= visible_area(bar)
    assert plugin.widget.current_tab() == "karte"


@pytest.mark.parametrize("width", [1120, 1366])
@pytest.mark.parametrize("start,tab,target", SWITCHES)
def test_context_in_view_with_german_labels(fake_iface, plugin, layers, width, start, tab, target):
    """Wie oben mit den langen deutschen Beschriftungen bei den Breiten aus der Sichtprüfung."""
    from qgis_ribbon.core import i18n
    assert i18n.language() == "de"
    fake_iface.mainWindow().resize(width, 800)
    settle()
    switch(fake_iface, plugin, layers, start, tab, target)
    check_layout(plugin)


def test_search_field_gives_way_before_arrows(fake_iface, plugin, layers):
    """Zu wenig Platz: Suchfeld 220 px, dann 140 px, dann Lupe; Alt+Q klappt das Feld über den Tabs aus."""
    from qgis_ribbon.ui import search_box
    w = plugin.widget
    bar = w.tabbar
    mw = fake_iface.mainWindow()
    fake_iface.set_active_layer(layers["vector"])
    mw.resize(4000, 800)
    settle()
    assert w.search_stage == 0 and w.search.isVisible() and w.search.width() == search_box.WIDTH
    need = bar.needed_width(len(bar.LEVELS) - 1)
    stages = set()
    for extra in (search_box.WIDTH - 20, search_box.NARROW - 20):
        mw.resize(mw.width() - (bar.width() + w.search.width()) + need + extra, 800)
        settle()
        stages.add(w.search_stage)
        if w.search_stage < 2:
            assert w.search.width() == search_box.NARROW
        assert all(not bar.tabRect(i).isEmpty() for i in shown(plugin))
    assert w.search_stage == 2 and w.search_button.isVisible() and not w.search.isVisible()
    # Alt+Q bzw. Klick auf die Lupe: Feld über den Tabs, rechtsbündig an der Lupe
    w.search_button.click()
    settle()
    assert w.search.isVisible() and w.search.width() == search_box.WIDTH
    assert w.search.geometry().right() == w.search_button.geometry().right()
    w.search._ctx.env.iface.mapCanvas().setFocus()
    w.search.clearFocus()
    settle()
    assert not w.search.isVisible()
    mw.resize(4000, 800)
    settle()
    assert w.search_stage == 0 and w.search.isVisible() and not w.search_button.isVisible()


def test_context_tab_shown_and_selected_gets_a_width(fake_iface, plugin, layers):
    """Ein Kontext-Tab, der eingeblendet und gleich gewählt wird (etwa beim Georeferenzieren), hat eine Breite.

    Qt 5.15 ordnete die Tabs ohne Stufenwechsel nicht neu an: tabRect blieb leer,
    der Strich stand unter dem ersten Tab.
    """
    from qgis_ribbon.core.context import Changes
    w = plugin.widget
    bar = w.tabbar
    fake_iface.mainWindow().resize(1600, 800)
    fake_iface.set_active_layer(layers["raster"])
    settle()
    w.select_tab("karte")
    settle()
    hidden = [t.id for t in plugin.ribbon.tabs if t.contextual and not w.is_tab_visible(t.id)]
    assert hidden
    tid = hidden[-1]
    w.apply_context(Changes(tabs={tid: True}, select=tid))
    settle()
    i = w._index[tid]
    assert bar.currentIndex() == i
    assert not bar.tabRect(i).isEmpty()
    check_layout(plugin)
    w.apply_context(Changes(tabs={tid: False}, select="karte"))
    settle()


def test_end_tab_is_never_shown(fake_iface, plugin, layers):
    """Wählt Qt den Abschluss-Tab (QGIS: Bedienfelder umschalten), springt der Ribbon zurück, ohne Fehler."""
    w = plugin.widget
    w.select_tab("ansicht")
    settle()
    w.tabbar.setCurrentIndex(w.tabbar.end)
    settle()
    assert w.current_tab() == "ansicht"


def test_last_context_tab_comes_out_from_under_the_arrows(fake_iface, plugin, layers):
    """Liegt der letzte Kontext-Tab unter den Scrollpfeilen, holt ihn der rechte Pfeil hervor."""
    from qgis.PyQt.QtWidgets import QTabBar
    fake_iface.set_active_layer(layers["vector"])
    settle()
    plugin.widget.select_tab("vektor_darstellung")
    settle()
    bar = plugin.widget.tabbar
    for width in range(900, 1800, 20):   # Pfeile da, der Kontext passt aber zwischen sie (Breite offscreen anders)
        fake_iface.mainWindow().resize(width, 800)
        settle()
        group = context_group(plugin)
        span = bar.tabRect(group[-1]).right() - bar.tabRect(group[0]).left()
        if bar.visible_right() < bar.width() and span < bar.visible_right() - 40:
            break
    else:
        pytest.skip("keine Breite mit Pfeilen, in die der Kontext passt")
    current = bar.currentIndex()
    assert len(group) > 1
    blocked = bar.blockSignals(True)
    QTabBar.setCurrentIndex(bar, shown(plugin)[0])   # Bildlauf ganz nach links, Kontext rechts außerhalb
    QTabBar.setCurrentIndex(bar, current)
    bar.blockSignals(blocked)
    assert bar.tabRect(group[-1]).right() > bar.visible_right()
    blocked = bar.blockSignals(True)   # nur _under_arrows, nicht reveal über _on_tab_changed
    bar._under_arrows(group, current)
    bar.blockSignals(blocked)
    assert bar.tabRect(group[-1]).right() <= bar.visible_right()
    assert bar.tabRect(group[0]).left() >= 0
    assert bar.currentIndex() == current


def test_choosing_a_context_tab_keeps_its_context_in_view(fake_iface, plugin, layers):
    """Wählen eines Kontext-Tabs von Hand: der ganze Kontext bleibt im Bild (nicht nur der gewählte Tab)."""
    from qgis_ribbon.core import i18n
    assert i18n.language() == "de"
    fake_iface.set_active_layer(layers["vector"])
    settle()
    bar = plugin.widget.tabbar
    for width in (1120, 1000, 1366):
        fake_iface.mainWindow().resize(width, 800)
        settle()
        for tid in ("karte", "bearbeiten", "vektor_beschriftung", "vektor_darstellung", "vektor_daten"):
            plugin.widget.select_tab(tid)
            settle()
            if tid.startswith("vektor_"):
                check_layout(plugin)
                assert bar.currentIndex() == plugin.widget._index[tid]
