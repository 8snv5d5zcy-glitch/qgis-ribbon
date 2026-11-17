"""Befehlssuche: Leisten vollständig, Funktionen des Ribbons, Skripte und Modelle, Trefferliste."""
import json
import sys
import types

import pytest
from qgis.PyQt.QtWidgets import QAction, QApplication, QMenu, QToolBar, QToolButton

from qgis_ribbon.core import extensions as ext
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration import builtin_commands
from qgis_ribbon.qgis_integration.user_settings import KEY_LAYOUT
from qgis_ribbon.ui import search_box

from test_erweiterungen import native, tool_layout, with_plugins  # noqa: F401 (Fixture)
from test_plugin import settle

SEVEN = ("skript_neu", "skript_aus_vorlage", "skript_oeffnen", "skript_hinzufuegen",
         "modell_neu", "modell_oeffnen", "modell_hinzufuegen")


@pytest.fixture
def make_plugin(fake_iface, settings):
    made = []

    def make(layout=None):
        if layout is not None:
            settings.setValue(KEY_LAYOUT, json.dumps(layout))
        p = RibbonPlugin(fake_iface, settings=settings)
        p.initGui()
        settle()
        made.append(p)
        return p

    make.made = made
    yield make
    for p in made:
        p.unload()
    settle()


def labels(hits):
    return [e.label for e in hits]


def test_toolbar_dropdowns_and_embedded_buttons_are_found(fake_iface, make_plugin):
    """Dropdown einer Leistenaktion und eingebetteter Button (Hauptaktion, Menü) stehen im Index, Unsichtbares nicht."""
    mw = fake_iface.mainWindow()
    tb = mw.findChild(QToolBar, "mFileToolBar")   # Leiste von QGIS
    holder = native(QAction("Leistenmenü", mw))
    menu = native(QMenu("Leistenmenü", mw))
    native(menu.addAction("Dropdown-Eintrag"))
    holder.setMenu(menu)
    tb.addAction(holder)
    button = QToolButton(tb)
    main = native(QAction("Eingebetteter Knopf", mw))
    button.setDefaultAction(main)
    button_menu = native(QMenu(button))
    native(button_menu.addAction("Im Knopfmenü"))
    button.setMenu(button_menu)
    native(tb.addWidget(button))
    hidden = native(QAction("Unsichtbare Probe", mw))
    hidden.setVisible(False)
    tb.addAction(hidden)
    p = make_plugin()
    search = p.widget.search
    hit = search.results("Dropdown-Eintrag")[0]
    assert hit.label == "Dropdown-Eintrag" and "Leistenmenü" in hit.path and not hit.ribbon
    assert labels(search.results("Eingebetteter Knopf"))[0] == "Eingebetteter Knopf"
    assert labels(search.results("Im Knopfmenü"))[0] == "Im Knopfmenü"
    assert search.results("Unsichtbare Probe") == []


def test_plugin_command_of_deleted_group_is_still_found(fake_iface, make_plugin, with_plugins):  # noqa: F811
    """Plugin-Gruppe gelöscht: der Befehl bleibt in der Suche, einmal; mit Gruppe nur als Ribbon-Befehl."""
    p = make_plugin()
    hits = [e for e in p.widget.search.results("Messung starten") if e.label == "Messung starten"]
    assert len(hits) == 1 and hits[0].ribbon
    p.unload()
    make_plugin.made.remove(p)
    p = make_plugin({"tabs": [{"tab": "karte"}], "removed": ["erweiterungen/erw_vermessung"]})
    assert "erw_vermessung" not in [g.id for g in p.ribbon.tab("erweiterungen").groups]
    search = p.widget.search
    hits = [e for e in search.results("Messung starten") if e.label == "Messung starten"]
    assert len(hits) == 1, [(e.path, e.ribbon) for e in hits]
    # findet die Suche die Aktion anderswo nicht, kommt der Befehl selbst in den Index
    entries = search._runtime_entries(set())
    cmd_ids = [e.ref[0].id for e in entries]
    start = next(c for c in cmd_ids if "messung" in c.lower())
    assert ext.is_plugin(start)
    seen = {id(p.widget.ctx.resolver.resolve(p.ribbon.commands[start]).action)}
    assert start not in [e.ref[0].id for e in search._runtime_entries(seen)]


def test_placed_tool_is_found_by_internal_name(make_plugin):
    p = make_plugin(tool_layout("verarbeitung:native:fixgeometries"))
    search = p.widget.search
    for text in ("fixgeometries", "fix"):
        hits = [e for e in search.results(text) if e.ribbon and e.ref[0].id == "verarbeitung:native:fixgeometries"]
        assert len(hits) == 1 and hits[0].ref[1] == "eigener_tab_1", text


def test_tools_come_in_steps(make_plugin):
    p = make_plugin()
    search = p.widget.search
    search.tools = lambda: [ext.Algorithm("native:alg%d" % i, "Werkzeug %d" % i, "native")
                            for i in range(search_box.TOOL_CHUNK * 2 + 5)]
    search.invalidate()
    search.build_index(tools=False)
    count = len(search.index)
    search._add_tools()
    assert not search._with_tools and len(search.index) == count   # erster Schritt: nur die Liste
    for _ in range(10):
        QApplication.processEvents()
    assert search._with_tools and len(search.index) == count + search_box.TOOL_CHUNK * 2 + 5
    assert search.results("werkzeug 7")


@pytest.fixture
def fake_processing(monkeypatch):
    """Verarbeitung als geladenes Plugin mit Aktionen, die nur ihren Aufruf melden."""
    from qgis import utils
    calls = []
    monkeypatch.setitem(utils.plugins, "processing", object())
    for module, name in builtin_commands.PROCESSING_ACTIONS.values():

        class Action(object):
            def setData(self, toolbox):  # noqa: N802
                self.toolbox = toolbox

            def execute(self, _name=name):
                calls.append((_name, self.toolbox))

        monkeypatch.setitem(sys.modules, module, types.SimpleNamespace(**{name: Action}))
    return calls


def test_script_and_model_commands_run_processing_actions(fake_iface, make_plugin, fake_processing):
    p = make_plugin()
    resolver = p.widget.ctx.resolver
    for cid in SEVEN:
        cmd = p.ribbon.commands[cid]
        assert resolver.resolve(cmd).available, cid
        resolver.trigger(cmd)
    assert [c[0] for c in fake_processing] == [name for _m, name in builtin_commands.PROCESSING_ACTIONS.values()]
    assert all(c[1] is fake_iface.mainWindow() for c in fake_processing)
    # im Ribbon: Dropdown „Skripte und Modelle“ im Tab Analyse, Gruppe Werkzeuge; in der Suche
    group = next(g for g in p.ribbon.tab("analyse").groups if g.id == "werkzeuge")
    menu = next(e for e in group.elements if getattr(e, "key", None) == "Skripte und Modelle")
    assert [c.id for c in menu.items] == list(SEVEN)
    hit = p.widget.search.results("neues modell")[0]
    assert hit.ribbon and hit.ref[0].id == "modell_neu" and hit.path.endswith("Werkzeuge")


def test_script_commands_unavailable_without_processing(make_plugin, monkeypatch):
    from qgis import utils
    monkeypatch.delitem(utils.plugins, "processing", raising=False)
    p = make_plugin()
    res = p.widget.ctx.resolver.resolve(p.ribbon.commands["skript_neu"])
    assert not res.available and res.reason == "Das Plugin Verarbeitung ist nicht aktiv"


def test_ribbon_functions_are_searchable(make_plugin, monkeypatch):
    p = make_plugin()
    w = p.widget
    opened = []
    monkeypatch.setattr(type(w), "open_customize_dialog", lambda self: opened.append(1))
    hit = next(e for e in w.search.results("anpassen") if e.label == "Ribbon anpassen")
    assert hit.path == search_box.RIBBON_PLACE and not hit.ribbon
    assert w.search.execute(hit) and opened == [1]
    assert "Klassische QGIS-Oberfläche" in labels(w.search.results("klassische"))
    design = [e for e in w.search.results("dunkel") if e.path.startswith(search_box.RIBBON_PLACE)]
    assert design and search_box.PATH_SEP in design[0].path
    # neu gelesen bei jedem Fokus: alte Aktionen verschwinden, keine doppelten Treffer
    w.search._refresh_functions()
    w.search._refresh_functions()
    assert len([e for e in w.search.results("anpassen") if e.label == "Ribbon anpassen"]) == 1


def test_result_list_is_wide_and_right_aligned(make_plugin):
    p = make_plugin()
    search = p.widget.search
    window = search.window()
    window.resize(1400, 800)
    settle()
    rect = search.popup_rect()
    assert rect.width() >= search_box.POPUP_WIDTH and rect.right() == search.width() - 1
    search.update_results("zoom")
    try:
        popup = search.completer.popup()
        item = search.model.item(0)
        assert item.text() == item.data(search_box.ROLE_ENTRY).label
        assert item.data(search_box.ROLE_PATH)
        assert popup.width() >= search_box.POPUP_WIDTH
    finally:
        search.completer.popup().hide()


def test_columns_shorten_the_place_first():
    assert search_box.columns(100, 300, 250, 10) == (100, 140)
    assert search_box.columns(100, 50, 250, 10) == (100, 50)
    assert search_box.columns(300, 50, 250, 10) == (250, 0)
    assert search_box.columns(100, 0, 250, 10) == (100, 0)
