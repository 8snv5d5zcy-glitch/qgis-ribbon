"""Design „Kontur“: Themes, Icons, adaptive Gruppen, KeyTips, Gesamtbild."""
import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap
from qgis.PyQt.QtWidgets import QApplication, QLabel, QMenu, QToolButton

from qgis_ribbon.core import extensions as ext
from qgis_ribbon.core import theme_tokens
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration.user_settings import KEY_DESIGN_MODE, KEY_DESIGN_WHOLE
from qgis_ribbon.ui import icons, theme
from qgis_ribbon.ui.group_widget import COLLAPSED
from qgis_ribbon.ui.keytips import KeyTipController
from qgis_ribbon.ui.ribbon_widget import TEXT_WHOLE
from qgis_ribbon.ui.whole_theme import MARKER

from test_plugin import snapshot


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)
    QgsApplication.processEvents()


@pytest.fixture
def plugin(fake_iface, settings):
    mw = fake_iface.mainWindow()
    mw.resize(1600, 900)
    mw.show()
    settle()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()
    theme._set_current(theme.themes().tokens("hell"), {"mode": "auto", "whole": False, "icons": True})


def design_menu(w):
    menu = QMenu()
    sub = w.add_design_menu(menu)
    return menu, {a.text(): a for a in sub.actions() if not a.isSeparator()}


def pixel(icon, mode=QIcon.Normal):
    img = icon.pixmap(QSize(32, 32), mode).toImage()
    seen = set()
    for x in range(32):
        for y in range(32):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                seen.add(c.name())
    return seen


def test_mode_switch_restyles_without_rebuild(plugin, settings):
    w = plugin.widget
    page = w.page("karte")
    buttons = len(w.findChildren(QToolButton))
    menu, actions = design_menu(w)
    assert set(actions) >= {"Automatisch (wie QGIS)", "Hell", "Dunkel", "Akzent Moos", "Eigene Icons",
                            "Animationen", TEXT_WHOLE}
    actions["Dunkel"].trigger()
    settle()
    assert settings.value(KEY_DESIGN_MODE) == "dunkel"
    assert theme.current()["mode"] == "dunkel"
    assert theme.current()["win"] in w.styleSheet()
    assert theme.css("win") in plugin.toolbar.styleSheet()
    assert w.page("karte") is page and len(w.findChildren(QToolButton)) == buttons
    actions["Akzent Kobalt"].trigger()
    settle()
    assert theme.current()["accent"] == "kobalt"
    menu.deleteLater()


def test_icons_follow_theme_and_switch_off(plugin):
    w = plugin.widget
    act = next(b.defaultAction() for b in w.findChildren(QToolButton)
               if b.defaultAction() is not None and hasattr(b.defaultAction(), "command")
               and b.defaultAction().isEnabled())
    assert isinstance(act.icon(), QIcon) and not act.icon().isNull()
    light = pixel(act.icon())
    assert theme.current()["text"].lower()[:7] in light
    plugin.themes.set("mode", "dunkel")
    dark = pixel(act.icon())
    assert theme.current()["text"].lower()[:7] in dark and dark != light
    faint = QColor(theme.current()["faint"][:7])
    for name in pixel(act.icon(), QIcon.Disabled):   # gesperrt: nur „faint“ (± Kantenglättung)
        c = QColor(name)
        assert max(abs(c.red() - faint.red()), abs(c.green() - faint.green()),
                   abs(c.blue() - faint.blue())) <= 3, name
    # Eigene Icons aus: QGIS-Icon (Rückfall) statt Kontur
    red = QPixmap(32, 32)
    red.fill(QColor("#ff0000"))
    icon = icons.command_icon(act.command, QIcon(red))
    assert "#ff0000" not in pixel(icon)
    plugin.themes.set("icons", False)
    assert pixel(icon) == {"#ff0000"}
    plugin.themes.set("icons", True)
    assert "#ff0000" not in pixel(icon)


def test_every_shown_command_uses_kontur_icon(plugin):
    s = icons.icon_set()
    assert s is not None
    w = plugin.widget
    for tab in w.tab_ids():
        w.ensure_built(w.tab_ids().index(tab))
    for btn in w.findChildren(QToolButton):
        act = btn.defaultAction()
        if act is None or not hasattr(act, "command") or ext.is_runtime(act.command.id):
            continue   # Plugin-Aktionen und Werkzeuge behalten ihr QGIS-Icon
        assert s.for_command(act.command.id) is not None, act.command.id


def used_width(page):
    groups = [g for g in page.groups if not g.isHidden()]
    return sum(g.width() for g in groups) + theme.GROUP_GAP * (len(groups) - 1)


@pytest.mark.parametrize("tab", ["karte", "bearbeiten", "einfuegen"])
def test_groups_use_available_width(plugin, fake_iface, tab):
    mw = fake_iface.mainWindow()
    w = plugin.widget
    w.select_tab(tab)
    settle()
    page = w.page(tab)
    targets = len(w.targets(tab))
    history = []
    for width in (700, 1000, 1400, 1900, 2600):
        mw.resize(width, 900)
        settle()
        avail = page.available_width()
        used = used_width(page)
        choice = [g.variant for g in page.groups]
        history.append(sum(choice))
        assert used <= avail or all(v == 0 for v in choice), (width, used, avail)
        # Kein Schritt nach oben hätte noch gepasst (Fläche ausgenutzt)
        for g in page.groups:
            if g.variant + 1 < len(g.variants()):
                grow = g.variants()[g.variant + 1][1] - g.width()
                assert used + grow > avail, (width, g.group.id)
        assert len(w.targets(tab)) == targets   # KeyTip-Ziele stabil
    assert history == sorted(history)
    assert history[0] < history[-1]


def test_narrow_collapses_and_keytips_reach_group(plugin, fake_iface):
    mw = fake_iface.mainWindow()
    w = plugin.widget
    # Tab mit einer Gruppe, die eingeklappt schmaler ist als ihre kleinste Fassung
    tab = next(t for i, t in enumerate(w.tab_ids()) if w.is_tab_visible(t)
               and any(g.variants()[0][0] == COLLAPSED for g in w.ensure_built(i).groups))
    w.select_tab(tab)
    settle()
    page = w.page(tab)
    # Schmaler als das Hauptfenster werden kann (Mindestgröße der Docks)
    page.available_width = lambda: 40
    page.relayout(force=True)
    settle()
    collapsed = w.collapsed_groups(tab)
    expected = [g for g in page.groups if g.variants()[0][0] == COLLAPSED]
    assert expected and collapsed == expected
    assert all(g.variant == 0 for g in page.groups)
    mw.activateWindow()
    QApplication.setActiveWindow(mw)
    keys = KeyTipController(w, mw)
    keys.install()
    try:
        keys.start()
        hit = next(i for i in keys.items if i.tab_id == tab)
        for ch in hit.code:
            keys.type_char(ch)
        settle()
        assert keys.level == 1
        group_items = [i for i in keys.items if i.group is not None]
        assert {i.group for i in group_items} == set(g for g in collapsed if g.collapse_button.isVisible())
        item = group_items[0]
        codes = [i.code for i in keys.items]
        assert len(set(codes)) == len(codes)
        for ch in item.code:
            keys.type_char(ch)
        settle()
        assert keys.level == 2 and item.group.popup.isVisible()
        assert keys.items and all(i.widget.window() is item.group.popup for i in keys.items)
        labels = [l for l in item.group.popup.findChildren(QLabel, "ribbon_keytip") if l.isVisible()]
        assert len(labels) == len(keys.items)
        keys.back()
        settle()
        assert keys.level == 1 and not item.group.popup.isVisible()
    finally:
        keys.uninstall()
        del page.available_width
        page.relayout(force=True)


def test_whole_theme_applies_and_unload_restores(fake_iface, settings):
    mw = fake_iface.mainWindow()
    mw.setStyleSheet("QStatusBar { margin: 0px; }")
    settle()
    before = snapshot(mw)
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    assert MARKER not in mw.styleSheet()
    p.themes.set("whole", True)
    assert settings.value(KEY_DESIGN_WHOLE) == "true"
    assert mw.styleSheet().startswith("QStatusBar { margin: 0px; }") and MARKER in mw.styleSheet()
    p.themes.set("mode", "dunkel")
    assert theme.css("win") in mw.styleSheet()
    p.themes.set("whole", False)
    assert mw.styleSheet() == "QStatusBar { margin: 0px; }"
    p.themes.set("whole", True)
    p.unload()
    settle()
    after = snapshot(mw)
    for key in before:
        assert after[key] == before[key], key
    mw.setStyleSheet("")
    theme._set_current(theme.themes().tokens("hell"), {"mode": "auto", "whole": False})


def test_whole_theme_starts_on_when_saved(fake_iface, settings):
    settings.setValue(KEY_DESIGN_WHOLE, "true")
    mw = fake_iface.mainWindow()
    before = mw.styleSheet()
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    assert MARKER in mw.styleSheet()
    p.unload()
    settle()
    assert mw.styleSheet() == before


def test_auto_mode_follows_qgis_palette(plugin):
    app = QApplication.instance()
    old = app.palette()
    try:
        pal = app.palette()
        from qgis.PyQt.QtGui import QPalette
        pal.setColor(QPalette.Window, QColor("#202124"))
        app.setPalette(pal)
        settle()
        assert theme.current()["mode"] == "dunkel"
    finally:
        app.setPalette(old)
        settle()
    assert theme.current()["mode"] == "hell"


def test_shipped_tokens_pass_contrast():
    themes = theme_tokens.load()
    assert theme_tokens.check(themes) == []


# Keine Dopplungen, Menüpfeile, Palette im Gesamtbild

def visible_commands(group):
    out = []
    for btn in group.findChildren(QToolButton):
        act = btn.defaultAction()
        if btn.isVisibleTo(group) and act is not None and hasattr(act, "command"):
            out.append(act.command.id)
    return out


def test_open_groups_show_no_command_twice(plugin, fake_iface):
    from qgis_ribbon.ui.controls.buttons import LargeSplitButton
    from qgis_ribbon.ui.group_widget import OPEN

    w = plugin.widget
    fake_iface.mainWindow().resize(3000, 900)
    opened = 0
    for i, tab in enumerate(w.tab_ids()):
        page = w.ensure_built(i)
        page.available_width = lambda: 5000
        page.relayout(force=True)
        settle()
        for g in page.groups:
            modes = g.mode_names()
            ids = visible_commands(g)
            assert len(ids) == len(set(ids)), (tab, g.group.id, ids)
            for v, mode in zip(g.views, modes):
                if mode != OPEN:
                    continue
                opened += 1
                # Aufgeklappt: kein Dropdown mehr, die Einträge stehen daneben
                assert not v.widget.isVisibleTo(g)
                if v.has_main():
                    assert isinstance(v.widget, LargeSplitButton)
                    assert v._main.isVisibleTo(g) and v._main.menu() is None
                    assert v._main.text().replace("\n", " ") == v.element.command.label
        del page.available_width
        page.relayout(force=True)
    assert opened > 0


def test_neuer_layer_open_shows_main_once(plugin):
    w = plugin.widget
    w.select_tab("einfuegen")
    settle()
    page = w.page("einfuegen")
    group = next(g for g in page.groups if g.group.id == "neue_layer")
    group.apply(len(group.variants()) - 1)
    settle()
    ids = visible_commands(group)
    assert ids[0] == "neuer_geopackage_layer" and "neuer_shapefile_layer" in ids
    assert len(ids) == len(set(ids))
    group.apply(group.ideal_index())
    settle()
    split = group.views[0].widget
    menu = split.menu if hasattr(split, "bottom") else split.menu()
    assert split.isVisibleTo(group)
    labels = [a.text() for a in menu.actions()]
    assert labels[0] == "GeoPackage-Layer" and "Shapefile-Layer" in labels


def test_split_with_single_qgis_menu_uses_it_directly(plugin, fake_iface):
    from qgis_ribbon.core.model import Split

    w = plugin.widget
    page = w.page("karte")
    for g in page.groups:
        for v in g.views:
            el = v.element
            if isinstance(el, Split) and len(el.items) == 1:
                res = plugin.resolver.resolve(el.items[0])
                if res.menu is not None:
                    menu = v.widget.menu if hasattr(v.widget, "bottom") else v.widget.menu()
                    assert menu is res.menu
                    assert not v.inline_items()   # nicht aufklappbar


def test_whole_theme_styles_menu_buttons_of_other_toolbars(plugin, fake_iface):
    from qgis.PyQt.QtWidgets import QToolBar

    mw = fake_iface.mainWindow()
    tb = mw.findChild(QToolBar, "mPluginToolBar")
    btn = QToolButton(tb)
    btn.setText("Plugin")
    btn.setMenu(QMenu(btn))
    btn.setPopupMode(QToolButton.MenuButtonPopup)
    tb.addWidget(btn)
    tb.show()
    plugin.themes.set("mode", "dunkel")
    plugin.themes.set("whole", True)
    settle()
    try:
        img = btn.grab().toImage()
        surf = QColor(theme.current()["win"][:7])
        dark = 0
        for x in range(img.width() - 12, img.width()):
            for y in range(img.height()):
                c = img.pixelColor(x, y)
                if c.lightness() < surf.lightness() - 12:
                    dark += 1
        assert dark == 0   # kein schwarzes Feld im Menüteil
    finally:
        plugin.themes.set("whole", False)


def test_whole_theme_sets_palette_for_layer_tree_and_restores(plugin):
    from qgis.PyQt.QtGui import QPalette

    app = QApplication.instance()
    before = QPalette(app.palette())
    plugin.themes.set("mode", "dunkel")
    plugin.themes.set("whole", True)
    settle()
    pal = app.palette()
    assert pal.color(QPalette.Text).name() == theme.current()["text"].lower()[:7]
    assert pal.color(QPalette.Base).name() == theme.current()["surf"].lower()[:7]
    assert pal.color(QPalette.Text).lightness() > 180   # helle Schrift im dunklen Modus
    # „Automatisch“ richtet sich weiter nach QGIS (hell), nicht nach der eigenen Palette
    plugin.themes.set("mode", "auto")
    settle()
    assert theme.current()["mode"] == "hell"
    assert app.palette().color(QPalette.Window).name() == theme.current()["win"].lower()[:7]
    plugin.themes.set("whole", False)
    settle()
    assert app.palette() == before
