"""Grafischer Ribbon-Editor „Ribbon anpassen“."""
import copy
import json

import pytest
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QLineEdit, QToolButton

from qgis_ribbon.core import customization as cz
from qgis_ribbon.core.editor import Place
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration.user_settings import KEY_EDITOR_SIZE, KEY_LAYOUT, KEY_QUICK_ACCESS, UserSettings
from qgis_ribbon.ui import ribbon_editor
from qgis_ribbon.ui.ribbon_editor import RibbonEditor

from test_anpassung import DEFINITION, config, plugin, settle, tab_ids  # noqa: F401 (Fixtures)


@pytest.fixture
def shipped(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


@pytest.fixture
def no_confirm(monkeypatch):
    calls = []
    answer = {"value": True}
    monkeypatch.setattr(ribbon_editor, "confirm_discard",
                        lambda parent: calls.append(parent) or answer["value"])
    return calls, answer


def open_editor(widget):
    dlg = widget.customize_dialog()
    dlg.show()
    dlg.activateWindow()
    QApplication.setActiveWindow(dlg)
    settle()
    return dlg


def press(dlg, key, mods=Qt.NoModifier, widget=None):
    target = widget or QApplication.focusWidget() or dlg.focusWidget() or dlg
    QTest.keyClick(target, key, mods)
    settle()


def close(dlg):
    dlg.editor._undo = []   # keine Rückfrage beim Aufräumen
    dlg._initial = None
    dlg.hide()
    dlg.deleteLater()
    settle()
    # außerhalb einer Ereignisschleife löscht nur das ausdrücklich (sonst stauen sich die
    # Editoren und ihr Abbau verzögert in späteren Tests die Zeitgeber)
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def wait_until(condition, ms=1000):
    for _ in range(ms // 20):
        if condition():
            return True
        QTest.qWait(20)
    return condition()


def labels(dlg):
    return [c.group.label for c in dlg.preview.cards]


def items(dlg, gi):
    return [t.label for t in dlg.preview.cards[gi].tiles]


# -- Grundgerüst und Tastatur -------------------------------------------

def test_editor_replaces_customize_dialog(plugin):
    dlg = plugin.widget.customize_dialog()
    try:
        assert isinstance(dlg, RibbonEditor)
        assert dlg.windowTitle() == "Ribbon anpassen"
        assert [c.title for c in dlg.tab_strip.chips] == ["Karte", "Projekt"]
        assert dlg.current_tab == "karte" and labels(dlg) == ["Navigieren"]
        assert items(dlg, 0) == ["Verschieben", "Hineinzoomen"]
        assert dlg.arrangement_label.text() == "Anordnung: Standard"
        assert not dlg.undo_button.isEnabled()
    finally:
        close(dlg)


def test_keyboard_only_editing(plugin):
    dlg = open_editor(plugin.widget)
    try:
        dlg.select(("tab", "karte"), focus=True)
        settle()
        press(dlg, Qt.Key_Right)                      # nächster Tab
        assert dlg.current_tab == "projekt" and labels(dlg) == ["Datei"]
        press(dlg, Qt.Key_Down)                       # in die Vorschau: Gruppenkopf
        assert dlg.selection == ("group", Place("projekt", 0))
        press(dlg, Qt.Key_Down)                       # erster Eintrag
        assert dlg.selection == ("item", Place("projekt", 0, 0))
        assert QApplication.focusWidget() is dlg.widget_for(dlg.selection)
        press(dlg, Qt.Key_Right, Qt.ControlModifier)  # verschieben
        assert items(dlg, 0) == ["Speichern", "Neues Projekt"]
        assert dlg.selection == ("item", Place("projekt", 0, 1))
        press(dlg, Qt.Key_Delete)                     # entfernen
        assert items(dlg, 0) == ["Speichern"]
        press(dlg, Qt.Key_Z, Qt.ControlModifier)      # rückgängig
        assert items(dlg, 0) == ["Speichern", "Neues Projekt"]
        press(dlg, Qt.Key_Y, Qt.ControlModifier)      # wiederholen
        assert items(dlg, 0) == ["Speichern"]
        assert "angepasst" in dlg.card(0).header.accessibleName()
        # Umbenennen mit F2 im Gruppenkopf
        dlg.select(("group", Place("projekt", 0)), focus=True)
        settle()
        press(dlg, Qt.Key_F2)
        edit = QApplication.focusWidget()
        assert isinstance(edit, QLineEdit) and edit.objectName() == "ribbon_editor_label"
        edit.selectAll()
        QTest.keyClicks(edit, "Dateien")
        press(dlg, Qt.Key_Return, widget=edit)
        assert labels(dlg) == ["Dateien"]
        # Leertaste blendet aus und wieder ein
        dlg.select(("group", Place("projekt", 0)), focus=True)
        press(dlg, Qt.Key_Space)
        assert not dlg.editor.arr.tab("projekt").groups[0].visible
        press(dlg, Qt.Key_Space)
        assert dlg.editor.arr.tab("projekt").groups[0].visible
        # Palette: Eingabe fügt in die gewählte Gruppe ein (hinter den gewählten Eintrag)
        dlg.select(("item", Place("projekt", 0, 0)), focus=True)
        dlg.palette_box.list.setFocus()
        dlg.palette_box.select("command", "zoomen")
        press(dlg, Qt.Key_Return, widget=dlg.palette_box.list)
        assert items(dlg, 0) == ["Speichern", "Hineinzoomen"]
        press(dlg, Qt.Key_Return, widget=dlg.palette_box.list)          # zweimal: Hinweis, kein Fehler
        assert "schon in dieser Gruppe" in dlg.status.text()
        assert dlg.isVisible()                                      # Eingabe speichert nicht
        assert dlg.save()
    finally:
        close(dlg)
    settle()
    plugin.widget.select_tab("projekt")
    page = plugin.widget.page("projekt")
    assert [g.group.label for g in page.groups] == ["Dateien"]
    assert [v.element.command.id for v in page.groups[0].views] == ["speichern", "zoomen"]


def test_cut_and_paste_between_tabs(plugin):
    dlg = open_editor(plugin.widget)
    try:
        dlg.select(("item", Place("karte", 0, 1)), focus=True)
        press(dlg, Qt.Key_X, Qt.ControlModifier)
        assert dlg.clip == Place("karte", 0, 1)
        assert dlg.widget_for(("item", Place("karte", 0, 1))).marked
        dlg.select(("tab", "projekt"), focus=True)
        dlg.select(("item", Place("projekt", 0, 0)), focus=True)
        press(dlg, Qt.Key_V, Qt.ControlModifier)
        assert items(dlg, 0) == ["Neues Projekt", "Hineinzoomen", "Speichern"]
        assert dlg.clip is None
        dlg.select(("tab", "karte"))
        assert items(dlg, 0) == ["Verschieben"]
        # Ausschneiden und auf „＋ Gruppe“ einfügen = neue Gruppe
        dlg.select(("item", Place("karte", 0, 0)), focus=True)
        press(dlg, Qt.Key_X, Qt.ControlModifier)
        dlg.select(("newgroup", "karte"), focus=True)
        press(dlg, Qt.Key_V, Qt.ControlModifier)
        assert labels(dlg) == ["Navigieren", "Neue Gruppe"]
        assert items(dlg, 1) == ["Verschieben"]
        assert dlg.card(0).empty is not None   # geleerte Gruppe der Definition: Hinweis zum Hineinziehen
    finally:
        close(dlg)


def test_new_tab_and_group_from_keyboard(plugin):
    dlg = open_editor(plugin.widget)
    try:
        dlg.select(("tab", "karte"), focus=True)
        dlg.add_tab_button.click()
        settle()
        tab_id = dlg.current_tab
        assert tab_id == "eigener_tab_1" and [c.title for c in dlg.tab_strip.chips][1] == "Neuer Tab"
        press(dlg, Qt.Key_F2)
        edit = QApplication.focusWidget()
        edit.selectAll()
        QTest.keyClicks(edit, "Mein Tab")
        press(dlg, Qt.Key_Return, widget=edit)
        assert dlg.editor.arr.tab(tab_id).label == "Mein Tab"
        dlg.select(("newgroup", tab_id), focus=True)
        press(dlg, Qt.Key_Return)
        assert labels(dlg) == ["Neue Gruppe"] and dlg.selection == ("group", Place(tab_id, 0))
        dlg.palette_box.select("command", "deckkraft")
        dlg.palette_box.list.setFocus()
        press(dlg, Qt.Key_Return, widget=dlg.palette_box.list)
        assert dlg.editor.arr.tab(tab_id).groups[0].items[0].size == "medium"   # Steuerelement mittel
        # Größe über die Segmente
        dlg.select(("item", Place(tab_id, 0, 0)))
        small = [b for b in dlg.props.findChildren(QToolButton, "ribbon_editor_size")
                 if b.property("ribbon_size_value") == "small"][0]
        small.click()
        settle()
        assert dlg.editor.arr.tab(tab_id).groups[0].items[0].size == "small"
        # Tab der Definition behält die Beschriftung
        dlg.select(("tab", "karte"), focus=True)
        press(dlg, Qt.Key_F2)
        assert "behalten ihre Beschriftung" in dlg.status.text()
        # Strg+Pfeil verschiebt Tabs
        dlg.select(("tab", tab_id), focus=True)
        press(dlg, Qt.Key_Left, Qt.ControlModifier)
        assert [t.id for t in dlg.editor.arr.tabs][0] == tab_id
        assert dlg.save()
    finally:
        close(dlg)
    settle()
    assert tab_ids(plugin) == ["eigener_tab_1", "karte", "projekt"]


def test_definition_groups_only_hide_and_reset(plugin):
    dlg = open_editor(plugin.widget)
    try:
        dlg.select(("group", Place("karte", 0)), focus=True)
        press(dlg, Qt.Key_Delete)
        assert "nur ausblenden" in dlg.status.text()
        assert not dlg.editor.arr.tab("karte").groups[0].visible
        assert dlg.card(0).header.faded
        dlg.toggle_visible(("group", Place("karte", 0)))
        dlg.remove(("item", Place("karte", 0, 0)))
        menu = dlg.group_menu_actions(("group", Place("karte", 0)))
        reset = [a for a in menu.actions() if a.text() == "Auf Standard zurücksetzen"][0]
        assert reset.isEnabled()
        reset.trigger()
        settle()
        assert items(dlg, 0) == ["Verschieben", "Hineinzoomen"]
        assert cz.to_dict(dlg.editor.arr, plugin.base) is None
        # Tab der Definition: Entf blendet nur aus
        dlg.select(("tab", "projekt"), focus=True)
        press(dlg, Qt.Key_Delete)
        assert not dlg.editor.arr.tab("projekt").visible and "nur ausblenden" in dlg.status.text()
        dlg.select(("tab", "karte"), focus=True)
        press(dlg, Qt.Key_Space)
        assert not dlg.save() and "Haupt-Tab" in dlg.status.text()
        assert not dlg.save_button.isEnabled()
    finally:
        close(dlg)


def test_reset_cancel_and_confirm(plugin, settings, no_confirm):
    calls, answer = no_confirm
    arr = plugin.arrangements.current()
    cz.new_tab(arr, plugin.base)
    plugin.arrangements.set_current(arr)
    settle()
    dlg = open_editor(plugin.widget)
    try:
        assert dlg.arrangement_label.text() == "Anordnung: angepasst"
        dlg.reset_all()
        assert cz.is_standard(dlg.editor.arr, plugin.base)
        answer["value"] = False
        dlg.reject()                       # Rückfrage: nein -> bleibt offen
        assert dlg.isVisible() and len(calls) == 1
        answer["value"] = True
        dlg.reject()
        assert not dlg.isVisible()
    finally:
        dlg.deleteLater()
        settle()
    assert settings.value(KEY_LAYOUT)       # nichts gespeichert
    dlg = open_editor(plugin.widget)
    try:
        dlg.reset_all()
        assert dlg.save()
    finally:
        dlg.deleteLater()
    settle()
    assert settings.value(KEY_LAYOUT) is None
    assert tab_ids(plugin) == ["karte", "projekt"]
    assert settings.value(KEY_EDITOR_SIZE)


def test_empty_custom_groups_are_dropped_on_save(plugin):
    dlg = open_editor(plugin.widget)
    try:
        dlg.select(("newgroup", "karte"))
        dlg.new_group()
        assert "werden beim Speichern verworfen" in dlg.status.text()
        assert dlg.save()
    finally:
        dlg.deleteLater()
    settle()
    assert plugin.user.layout() is None


def test_contents_of_splits_and_menus_only_viewable(shipped):
    dlg = open_editor(shipped.widget)
    try:
        tiles = [t for c in dlg.preview.cards for t in c.tiles if t.menu]
        assert tiles
        menu = dlg.show_contents(tiles[0], popup=False)
        texts = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert texts[0] == "Inhalt (im Editor nur ansehbar)" and len(texts) > 1
    finally:
        close(dlg)


def test_without_plugin_saves_settings(fake_iface, settings):
    """Ribbon ohne Plugin (Tests): der Editor speichert, ein Neuaufbau findet nicht statt."""
    from qgis_ribbon.core import config_loader
    from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
    from qgis_ribbon.qgis_integration.signals import SignalHub
    from qgis_ribbon.ui.ribbon_widget import RibbonWidget
    hub = SignalHub()
    ribbon = config_loader.parse(copy.deepcopy(DEFINITION))
    w = RibbonWidget(ribbon, ActionResolver(fake_iface), hub, fake_iface.mainWindow(),
                     user=UserSettings(settings))
    try:
        dlg = w.customize_dialog()
        dlg.toggle_visible(("tab", "projekt"))
        assert dlg.save()
        dlg.deleteLater()
        assert json.loads(settings.value(KEY_LAYOUT)) == {
            "tabs": [{"tab": "karte"}, {"tab": "projekt", "visible": False}]}
        assert settings.value(KEY_QUICK_ACCESS) is None
    finally:
        hub.disconnect_all()
        w.deleteLater()
        settle()


def test_shipped_definition_in_editor(shipped):
    plugin = shipped
    dlg = open_editor(plugin.widget)
    try:
        chips = dlg.tab_strip.chips
        contextual = [t for t in plugin.base.tabs if t.contextual]
        assert len(chips) == len(plugin.base.tabs)
        assert [c.context for c in chips if c.context] == [t.context for t in contextual]
        # Alle Tabs bauen, Kacheln haben zugängliche Namen
        for t in plugin.base.tabs:
            dlg.select(("tab", t.id))
            for card in dlg.preview.cards:
                assert card.tiles, card.group.label
                for tile in card.tiles:
                    assert tile.accessibleName().startswith(tile.label)
                    assert not tile.missing
        # Rasterbefehl passt nicht in einen Vektor-Kontext-Tab
        vector = next(t for t in contextual if "active_layer_is_vector" in t.visible_when)
        raster_cmd = next(c for c in plugin.base.commands.values()
                          if c.enabled_when == ("active_layer_is_raster",))
        dlg.select(("tab", vector.id))
        dlg.select(("group", Place(vector.id, 0)))
        dlg.insert_from_palette(("command", raster_cmd.id))
        assert "passt nicht" in dlg.status.text()
        # Palette: Suche mit Umlauten, Filter „nicht im Ribbon“, Häkchen im Tab
        dlg.palette_box.search.setText("groesser")
        visible = dlg.palette_box.visible_values()
        assert ("command", "beschriftung_groesser") in visible and len(visible) < 5
        dlg.palette_box.search.setText("")
        dlg.palette_box.filter.setCurrentIndex(1)
        unused = dlg.palette_box.visible_values()
        assert unused and len(unused) < len(plugin.base.commands)
        dlg.palette_box.filter.setCurrentIndex(0)
        assert dlg.palette_box.checked and dlg.palette_box.checked <= set(plugin.base.commands)
        dlg.palette_box.set_mode("groups")
        assert len(dlg.palette_box.visible_values()) == len(cz.standard_groups(plugin.base))
        dlg.palette_box.set_mode("commands")
        assert dlg.save()   # unverändert speichern = keine Anpassung
    finally:
        close(dlg)
    settle()
    assert plugin.user.layout() is None


def test_editor_builds_fast(shipped):
    import time
    t0 = time.perf_counter()
    dlg = shipped.widget.customize_dialog()
    build = (time.perf_counter() - t0) * 1000
    try:
        times = []
        for t in shipped.base.tabs:
            t1 = time.perf_counter()
            dlg.select(("tab", t.id))
            times.append((time.perf_counter() - t1) * 1000)
        print("Editor: Aufbau %.0f ms, Tabwechsel max %.0f ms" % (build, max(times)))
        assert build < 2000 and max(times) < 500
    finally:
        close(dlg)



# -- Ziehen und Ablegen -------------------------------------------------

from qgis.PyQt.QtCore import QPoint, QPointF  # noqa: E402
from qgis.PyQt.QtGui import QDragMoveEvent, QDropEvent  # noqa: E402

from qgis_ribbon.ui.editor_widgets import mime  # noqa: E402

_MIME = []   # QMimeData am Leben halten
ACTIONS = Qt.MoveAction | Qt.CopyAction


def _data():
    _MIME.append(mime("test"))
    return _MIME[-1]


def drag_over(widget, pos):
    ev = QDragMoveEvent(QPoint(pos), ACTIONS, _data(), Qt.LeftButton, Qt.NoModifier)
    widget.dragMoveEvent(ev)
    return ev.isAccepted()


def drop(widget, pos):
    ev = QDropEvent(QPointF(pos), ACTIONS, _data(), Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(ev)
    settle()
    return ev.isAccepted()


def left_of(card, i):
    g = card.tiles[i].geometry().translated(card.body.pos())
    return QPoint(g.left() + 2, g.center().y())


def right_of(card, i):
    g = card.tiles[i].geometry().translated(card.body.pos())
    return QPoint(g.right() - 2, g.center().y())


def test_drag_from_palette_into_group(plugin):
    dlg = open_editor(plugin.widget)
    try:
        card = dlg.card(0)
        dlg.begin_drag(("command", "speichern"))
        assert drag_over(card, right_of(card, 1))
        assert card.drop_index == 2 and card.drop_line()[0] > card.tiles[1].geometry().right()
        assert drop(dlg.card(0), right_of(dlg.card(0), 1))
        assert items(dlg, 0) == ["Verschieben", "Hineinzoomen", "Speichern"]
        assert dlg._drag is None and dlg.editor.can_undo
        assert dlg.selection == ("item", Place("karte", 0, 2))
        # vor die erste Kachel
        card = dlg.card(0)
        dlg.begin_drag(("command", "neu"))
        assert drop(card, left_of(card, 0))
        assert items(dlg, 0)[0] == "Neues Projekt"
        # Doppelt in derselben Gruppe: kein Ziel, keine Marke, Grund in der Statuszeile
        card = dlg.card(0)
        dlg.begin_drag(("command", "zoomen"))
        assert not drag_over(card, right_of(card, 0))
        assert card.drop_index is None and "steht schon" in dlg.status.text()
        assert not drop(card, right_of(card, 0))
        dlg.end_drag()
        assert items(dlg, 0) == ["Neues Projekt", "Verschieben", "Hineinzoomen", "Speichern"]
        # Fremde Zieh-Daten (ohne laufenden Vorgang) werden nicht angenommen
        assert not drag_over(dlg.card(0), right_of(dlg.card(0), 0))
        # Auf „＋ Gruppe“: neue Gruppe mit dem Befehl
        dlg.select(("tab", "projekt"))
        dlg.begin_drag(("command", "zoomen"))
        assert drag_over(dlg.preview.new_card, QPoint(20, 20)) and dlg.preview.new_card.active
        assert drop(dlg.preview.new_card, QPoint(20, 20))
        assert labels(dlg) == ["Datei", "Neue Gruppe"] and items(dlg, 1) == ["Hineinzoomen"]
        # Gruppe der Definition aus der Palette „Gruppen“ in die Lücke ganz vorn
        dlg.begin_drag(("groupref", cz.group_ref("karte", "nav")))
        assert drag_over(dlg.preview, QPoint(2, 40)) and dlg.preview.drop_gap == 0
        assert drop(dlg.preview, QPoint(2, 40))
        assert labels(dlg) == ["Navigieren", "Datei", "Neue Gruppe"]
        # … und kein zweites Mal
        dlg.begin_drag(("groupref", cz.group_ref("karte", "nav")))
        assert not drag_over(dlg.preview, QPoint(2, 40)) and dlg.preview.drop_gap is None
        dlg.end_drag()
    finally:
        close(dlg)


def test_drag_items_within_between_groups_and_tabs(plugin):
    dlg = open_editor(plugin.widget)
    try:
        # innerhalb der Gruppe: zweite Kachel nach vorn
        card = dlg.card(0)
        dlg.begin_drag(("item", Place("karte", 0, 1)))
        assert drag_over(card, left_of(card, 0)) and card.drop_index == 0
        assert drop(card, left_of(card, 0))
        assert items(dlg, 0) == ["Hineinzoomen", "Verschieben"]
        # an den alten Platz: erlaubt, ändert nichts, kein Verlaufseintrag
        n = len(dlg.editor._undo)
        card = dlg.card(0)
        dlg.begin_drag(("item", Place("karte", 0, 0)))
        assert drop(card, left_of(card, 0))
        assert items(dlg, 0) == ["Hineinzoomen", "Verschieben"] and len(dlg.editor._undo) == n
        # in einen anderen Tab: über dem Tab verweilen wechselt die Vorschau
        dlg.begin_drag(("item", Place("karte", 0, 1)))
        chip = dlg.widget_for(("tab", "projekt"))
        assert not drag_over(chip, QPoint(10, 10))        # auf dem Tab selbst kein Ablegen
        assert dlg._hover_tab == "projekt" and dlg._hover_timer.isActive()
        assert wait_until(lambda: dlg.current_tab == "projekt", ribbon_editor.HOVER_SWITCH_MS + 2000)
        assert labels(dlg) == ["Datei"]
        assert dlg._drag == ("item", Place("karte", 0, 1))   # Zieh-Vorgang läuft weiter
        card = dlg.card(0)
        assert drop(card, right_of(card, 1))
        assert items(dlg, 0) == ["Neues Projekt", "Speichern", "Verschieben"]
        dlg.select(("tab", "karte"))
        assert items(dlg, 0) == ["Hineinzoomen"]
        # Tab verlassen, bevor die Zeit um ist: kein Wechsel
        dlg.begin_drag(("item", Place("karte", 0, 0)))
        chip = dlg.widget_for(("tab", "projekt"))
        drag_over(chip, QPoint(10, 10))
        chip.dragLeaveEvent(None)
        assert not dlg._hover_timer.isActive()
        QTest.qWait(ribbon_editor.HOVER_SWITCH_MS + 150)
        assert dlg.current_tab == "karte"
        # in eine neue Gruppe (Eintrag verschieben)
        assert drop(dlg.preview.new_card, QPoint(20, 20))
        assert labels(dlg) == ["Navigieren", "Neue Gruppe"] and items(dlg, 1) == ["Hineinzoomen"]
        assert items(dlg, 0) == []
    finally:
        close(dlg)


def test_drag_back_to_palette_removes(plugin):
    dlg = open_editor(plugin.widget)
    try:
        lst = dlg.palette_box.list
        assert lst.viewport().acceptDrops()   # sonst kommen echte Zieh-Ereignisse nie an
        dlg.begin_drag(("item", Place("karte", 0, 0)))
        assert drag_over(lst, QPoint(20, 20)) and lst.drop_active
        assert drop(lst, QPoint(20, 20))
        assert items(dlg, 0) == ["Hineinzoomen"] and not lst.drop_active
        # Schnellzugriff
        assert dlg.editor.quick_ids() == ["neu"]
        dlg.begin_drag(("quick", 0))
        assert drop(lst, QPoint(20, 20))
        assert dlg.editor.quick_ids() == []
        # eigene Gruppe wird gelöscht, Gruppe der Definition nur ausgeblendet
        dlg.new_group()
        assert labels(dlg) == ["Navigieren", "Neue Gruppe"]
        dlg.begin_drag(("group", Place("karte", 1)))
        assert drop(lst, QPoint(20, 20))
        assert labels(dlg) == ["Navigieren"]
        dlg.begin_drag(("group", Place("karte", 0)))
        assert drop(lst, QPoint(20, 20))
        assert labels(dlg) == ["Navigieren"] and not dlg.editor.arr.tab("karte").groups[0].visible
        # Befehle aus der Palette zurück in die Palette: nichts
        dlg.begin_drag(("command", "neu"))
        assert not drag_over(lst, QPoint(20, 20)) and not lst.drop_active
        dlg.end_drag()
    finally:
        close(dlg)


def test_drag_sorts_groups_and_tabs(plugin):
    dlg = open_editor(plugin.widget)
    try:
        dlg.new_group()
        dlg.editor.rename_group("karte", 1, "Zweite")
        dlg.refresh()
        # Gruppe über eine Karte ziehen: Lücke zwischen den Gruppen
        dlg.begin_drag(("group", Place("karte", 1)))
        card = dlg.card(0)
        assert drag_over(card, QPoint(2, 20)) and dlg.preview.drop_gap == 0 and card.drop_index is None
        assert drop(card, QPoint(2, 20))
        assert labels(dlg) == ["Zweite", "Navigieren"]
        # Gruppe auf einen anderen Tab: ans Ende (Gruppe der Definition wird kopiert)
        dlg.begin_drag(("group", Place("karte", 1)))
        chip = dlg.widget_for(("tab", "projekt"))
        assert drag_over(chip, QPoint(10, 10)) and chip.drop_active
        assert drop(chip, QPoint(10, 10))
        assert dlg.current_tab == "projekt" and labels(dlg) == ["Datei", "Navigieren"]
        dlg.select(("tab", "karte"))
        assert labels(dlg) == ["Zweite", "Navigieren"]
        # die Kopie steht schon in „Projekt“: kein Ziel
        dlg.begin_drag(("group", Place("karte", 1)))
        chip = dlg.widget_for(("tab", "projekt"))
        assert not drag_over(chip, QPoint(10, 10)) and not chip.drop_active
        dlg.end_drag()
        # Tabs sortieren
        dlg.begin_drag(("tab", "projekt"))
        assert drag_over(dlg.tab_strip, QPoint(1, 10)) and dlg.tab_strip.drop_gap == 0
        assert drop(dlg.tab_strip, QPoint(1, 10))
        assert [c.title for c in dlg.tab_strip.chips] == ["Projekt", "Karte"]
        # auch über einem Chip (Lücke je nach Hälfte)
        chip = dlg.widget_for(("tab", "projekt"))
        dlg.begin_drag(("tab", "karte"))
        assert drop(chip, QPoint(2, 10))
        assert [c.title for c in dlg.tab_strip.chips] == ["Karte", "Projekt"]
        dlg.undo()
        assert [c.title for c in dlg.tab_strip.chips] == ["Projekt", "Karte"]
    finally:
        close(dlg)


def test_drag_into_quick_access(plugin):
    dlg = open_editor(plugin.widget)
    try:
        strip = dlg.quick
        dlg.begin_drag(("command", "speichern"))
        assert drag_over(strip, QPoint(strip.width() - 4, 10)) and strip.drop_gap == 1
        assert drop(strip, QPoint(strip.width() - 4, 10))
        assert dlg.editor.quick_ids() == ["neu", "speichern"] and dlg.selection == ("quick", 1)
        # sortieren
        dlg.begin_drag(("quick", 1))
        assert drop(strip, QPoint(1, 10))
        assert dlg.editor.quick_ids() == ["speichern", "neu"]
        # aus einer Gruppe: kopiert, die Gruppe bleibt
        dlg.begin_drag(("item", Place("karte", 0, 0)))
        assert drop(strip, QPoint(strip.width() - 4, 10))
        assert dlg.editor.quick_ids() == ["speichern", "neu", "verschieben"]
        assert items(dlg, 0) == ["Verschieben", "Hineinzoomen"]
        # Steuerelemente nicht
        dlg.begin_drag(("command", "deckkraft"))
        assert not drag_over(strip, QPoint(4, 10)) and strip.drop_gap is None
        assert "nur Buttons" in dlg.status.text()
        dlg.end_drag()
        assert "nur Buttons" not in dlg.status.text()
    finally:
        close(dlg)


def test_drag_rules_in_shipped_definition(shipped):
    plugin = shipped
    dlg = open_editor(plugin.widget)
    try:
        main = [t.id for t in plugin.base.tabs if not t.contextual]
        n = len(plugin.base.tabs)
        # Haupt-Tab nicht hinter die Kontext-Tabs
        dlg.begin_drag(("tab", main[0]))
        last = dlg.tab_strip.chips[-1].geometry()
        assert not drag_over(dlg.tab_strip, QPoint(last.right() - 2, 10))
        assert "Kontext-Tabs" in dlg.status.text()
        dlg.end_drag()
        # Rasterbefehl nicht in einen Vektor-Kontext-Tab
        vector = next(t for t in plugin.base.tabs if t.contextual and "active_layer_is_vector" in t.visible_when)
        raster_cmd = next(c for c in plugin.base.commands.values() if c.enabled_when == ("active_layer_is_raster",))
        dlg.select(("tab", vector.id))
        card = dlg.card(0)
        dlg.begin_drag(("command", raster_cmd.id))
        assert not drag_over(card, right_of(card, 0)) and card.drop_index is None
        assert not drag_over(dlg.preview.new_card, QPoint(10, 10)) and not dlg.preview.new_card.active
        dlg.end_drag()
        assert len(dlg.tab_strip.chips) == n
    finally:
        close(dlg)


def test_auto_scroll_at_preview_edges(shipped):
    dlg = open_editor(shipped.widget)
    try:
        dlg.resize(640, 700)
        settle()
        bar = dlg.preview_area.horizontalScrollBar()
        assert bar.maximum() > 0
        vp = dlg.preview_area.viewport()
        card = dlg.card(0)
        dlg.begin_drag(("command", "neu"))
        drag_over(card, card.mapFromGlobal(vp.mapToGlobal(QPoint(vp.width() - 4, 40))))
        assert dlg._scroll_timer.isActive()
        wait_until(lambda: bar.value() > 0)
        assert bar.value() > 0
        # weg vom Rand: Schluss
        drag_over(card, card.mapFromGlobal(vp.mapToGlobal(QPoint(vp.width() // 2, 40))))
        assert not dlg._scroll_timer.isActive()
        value = bar.value()
        drag_over(card, card.mapFromGlobal(vp.mapToGlobal(QPoint(3, 40))))
        wait_until(lambda: bar.value() < value)
        assert bar.value() < value
        dlg.end_drag()
        assert not dlg._scroll_timer.isActive()
    finally:
        close(dlg)


class FakeDrag(object):
    """Ersatz für QDrag: ``exec_`` spielt ein Skript ab (wie die Ereignisschleife beim Ziehen)."""

    script = None

    def __init__(self, parent):
        self.parent = parent
        self.pixmap = None

    def setMimeData(self, data):  # noqa: N802
        self.data = data

    def setPixmap(self, pixmap):  # noqa: N802
        self.pixmap = pixmap

    def setHotSpot(self, pos):  # noqa: N802
        self.hot = pos

    def exec_(self, *_args):
        FakeDrag.script(self)
        return Qt.MoveAction


def test_drag_exec_keeps_source_until_done(plugin, monkeypatch):
    from qgis.PyQt import sip
    monkeypatch.setattr(ribbon_editor, "QDrag", FakeDrag)
    dlg = open_editor(plugin.widget)
    try:
        source = dlg.widget_for(("item", Place("karte", 0, 0)))
        seen = {}

        def script(drag):
            assert dlg._drag_running and source.marked
            assert drag.data.hasFormat(ribbon_editor.MIME_TYPE) and not drag.pixmap.isNull()
            drag_over(dlg.widget_for(("tab", "projekt")), QPoint(10, 10))
            dlg._hover_switch()
            settle()
            # die Quelle ist abgebaut, aber noch nicht gelöscht (sie steht im Aufrufstapel)
            assert not sip.isdeleted(source) and any(
                w is source or source in w.findChildren(type(source)) for w in dlg._graveyard)
            card = dlg.card(0)
            assert drop(card, right_of(card, 1)) is True
            seen["before"] = items(dlg, 0)   # abgelegt wird erst nach exec
        FakeDrag.script = script
        dlg.start_drag(source)
        assert seen["before"] == ["Neues Projekt", "Speichern"]
        assert items(dlg, 0) == ["Neues Projekt", "Speichern", "Verschieben"]
        assert dlg._drag is None and dlg._graveyard is None
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert sip.isdeleted(source)
        # Palette: Befehl ziehen, nirgends ablegen
        dlg.palette_box.select("command", "zoomen")

        def nowhere(drag):
            assert dlg._drag == ("command", "zoomen") and not drag.pixmap.isNull()
        FakeDrag.script = nowhere
        n = len(dlg.editor._undo)
        assert dlg.start_palette_drag(("command", "zoomen")) is None
        assert len(dlg.editor._undo) == n and dlg._drag is None
        # Neue Gruppe ist keine Zieh-Quelle
        assert dlg.start_drag(dlg.preview.new_card) is None
    finally:
        close(dlg)


# -- Feinschliff --------------------------------------------------------

def test_gallery_dialog_with_icons_and_drag_order(shipped):
    from qgis.PyQt.QtCore import QModelIndex
    from qgis_ribbon.ui.customize_dialog import GalleryDialog
    dlg = GalleryDialog(shipped.arrangements, "editor_galerie")
    try:
        assert dlg.list.count() > 2
        assert all(not dlg.list.item(i).icon().isNull() for i in range(dlg.list.count()))
        tree = dlg.picker.tree
        assert all(not tree.topLevelItem(i).icon(0).isNull() for i in range(tree.topLevelItemCount()))
        dlg.picker.set_mode("groups")
        assert not tree.topLevelItem(0).icon(0).isNull()
        dlg.picker.set_mode("commands")
        # Reihenfolge per Ziehen (InternalMove verschiebt Zeilen im Modell)
        before = dlg.ids()
        assert "(Standard)" in dlg.status.text()
        assert dlg.list.model().moveRow(QModelIndex(), 0, QModelIndex(), 3)
        assert dlg.ids() == before[1:3] + before[:1] + before[3:]
        assert "(Standard)" not in dlg.status.text()
        assert dlg.list.dragDropMode() == dlg.list.InternalMove
    finally:
        dlg.deleteLater()
        settle()


def test_refresh_keeps_preview_scroll(shipped):
    dlg = open_editor(shipped.widget)
    try:
        dlg.resize(640, 700)
        settle()
        bar = dlg.preview_area.horizontalScrollBar()
        last = dlg.card(len(dlg.preview.cards) - 1)
        dlg.select(("item", Place(dlg.current_tab, len(dlg.preview.cards) - 1, len(last.tiles) - 1)), focus=True)
        settle()
        assert bar.value() > 0
        value = bar.value()
        # Neuaufbau (Palette umschalten) mit Fokus in der Vorschau: im echten QGIS rollte Qt sonst zum
        # nächsten Fokus (offscreen ohne aktives Fenster nicht nachstellbar; der Test sichert das Ergebnis)
        dlg.palette_box.set_mode("groups")
        settle()
        assert bar.value() == value
        dlg.palette_box.set_mode("commands")
        settle()
        assert bar.value() == value
    finally:
        close(dlg)
