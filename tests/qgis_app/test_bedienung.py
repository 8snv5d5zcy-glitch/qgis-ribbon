"""Bedienung: KeyTips, Schnellzugriffsleiste, Minimieren, Befehlssuche, Tastatur in Galerien."""
import copy

import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAction, QApplication, QLabel, QMenu, QShortcut, QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.qgis_integration.user_settings import (KEY_MINIMIZED, KEY_QUICK_ACCESS,
                                                         UserSettings)
from qgis_ribbon.ui.controls.gallery import GalleryGrid
from qgis_ribbon.ui.keytips import KeyTipController
from qgis_ribbon.ui.ribbon_widget import TEXT_ADD, TEXT_REMOVE, RibbonWidget


def qa(name):
    return {"type": "qgis_action", "object_name": name}


DEFINITION = {
    "version": 1,
    "quick_access": ["neu"],
    "commands": {
        "neu": {"label": "Neues Projekt", "source": qa("mActionNewProject")},
        "speichern": {"label": "Speichern", "source": qa("mActionSaveProject")},
        "verschieben": {"label": "Verschieben", "source": qa("mActionPan")},
        "zoomen": {"label": "Hineinzoomen", "source": qa("mActionZoomIn")},
        "loeschen": {"label": "Löschen", "source": qa("mActionDeleteSelected")},
        "layer_menue": {"label": "Layer hinzufügen", "source": {"type": "qgis_menu",
                                                                "object_name": "mAddLayerMenu"}},
        "werkzeuge": {"label": "Werkzeuge", "kind": "control",
                      "source": {"type": "custom", "id": "ribbon.galerie"},
                      "gallery": {"display": "ribbon", "columns": 2,
                                  "items": ["verschieben", "zoomen", "speichern"]}},
    },
    "tabs": [
        {"id": "karte", "label": "Karte", "groups": [
            {"id": "nav", "label": "Navigieren", "items": [
                {"split": "verschieben", "items": ["zoomen"], "size": "large"},
                {"command": "speichern", "size": "medium"},
                {"command": "loeschen", "size": "medium"},
                {"command": "layer_menue", "size": "medium"},
            ]}]},
        {"id": "ansicht", "label": "Ansicht", "groups": [
            {"id": "g", "label": "Galerie", "items": [
                {"menu": "Werkzeuge", "gallery": "werkzeuge", "items": ["zoomen"]}]}]},
    ],
}


def settle():
    for _ in range(4):
        QgsApplication.processEvents()


@pytest.fixture
def setup(fake_iface, settings):
    mw = fake_iface.mainWindow()
    hub = SignalHub()
    ribbon = config_loader.parse(copy.deepcopy(DEFINITION))
    w = RibbonWidget(ribbon, ActionResolver(fake_iface), hub, mw, user=UserSettings(settings))
    w.resize(1200, 140)
    w.show()
    mw.activateWindow()
    QApplication.setActiveWindow(mw)
    keys = KeyTipController(w, mw)
    keys.install()
    settle()
    yield w, keys, mw
    keys.uninstall()
    w.hide_popup()
    hub.disconnect_all()
    w.deleteLater()
    settle()


def alt(widget):
    """Alt drücken und loslassen, ohne andere Taste."""
    QTest.keyPress(widget, Qt.Key_Alt, Qt.AltModifier)
    QTest.keyRelease(widget, Qt.Key_Alt, Qt.NoModifier)


def codes(keys):
    return {i.label: i.code for i in keys.items}


def visible_labels(w):
    return sorted(l.text() for l in w.findChildren(QLabel, "ribbon_keytip") if l.isVisible())


# -- KeyTips --------------------------------------------------------------------

def test_alt_alone_shows_level0(setup):
    w, keys, mw = setup
    alt(mw)
    assert keys.active and keys.level == 0
    c = codes(keys)
    assert c["Karte"] == "K" and c["Suchen"] == "Q" and "1" in c.values()
    settle()
    assert "K" in visible_labels(w) and "Q" in visible_labels(w)
    QTest.keyClick(mw, Qt.Key_Escape)
    assert not keys.active
    settle()
    assert visible_labels(w) == []


def test_alt_with_letter_stays_with_qgis(setup):
    _w, keys, mw = setup
    QTest.keyPress(mw, Qt.Key_Alt, Qt.AltModifier)
    QTest.keyClick(mw, Qt.Key_P, Qt.AltModifier)
    QTest.keyRelease(mw, Qt.Key_Alt, Qt.NoModifier)
    assert not keys.active
    # Auch wenn der Buchstabe als Tastenkürzel verbraucht wird (Menü-Mnemonik)
    fired = []
    sc = QShortcut(QKeySequence("Alt+M"), mw)
    sc.activated.connect(lambda: fired.append(1))
    QTest.keyPress(mw, Qt.Key_Alt, Qt.AltModifier)
    QTest.keyClick(mw, Qt.Key_M, Qt.AltModifier)
    QTest.keyRelease(mw, Qt.Key_Alt, Qt.NoModifier)
    assert fired and not keys.active
    sc.setParent(None)


def test_alt_with_arrows_of_another_plugin_wins(setup):
    """Ein anderes Plugin belegt Alt+↑/Alt+↓ (QAction am Hauptfenster): sein Kürzel gilt, keine KeyTips."""
    _w, keys, mw = setup
    fired = []
    acts = []
    for seq, name in (("Alt+Up", "hoch"), ("Alt+Down", "runter")):
        act = QAction(name, mw)
        act.setShortcut(QKeySequence(seq))
        act.triggered.connect(lambda _c=False, n=name: fired.append(n))
        mw.addAction(act)
        acts.append(act)
    QTest.keyPress(mw, Qt.Key_Alt, Qt.AltModifier)
    QTest.keyClick(mw, Qt.Key_Up, Qt.AltModifier)
    QTest.keyClick(mw, Qt.Key_Down, Qt.AltModifier)
    QTest.keyClick(mw, Qt.Key_Down, Qt.AltModifier)       # Alt bleibt gedrückt
    QTest.keyRelease(mw, Qt.Key_Alt, Qt.NoModifier)
    assert fired == ["hoch", "runter", "runter"]
    assert not keys.active
    # Danach startet Alt allein die KeyTips wie gewohnt
    alt(mw)
    assert keys.active
    keys.exit()
    for act in acts:
        mw.removeAction(act)
        act.setParent(None)


def test_tab_then_element(setup, fake_iface):
    w, keys, mw = setup
    zoom = mw.findChild(QAction, "mActionZoomIn")
    w.select_tab("karte")
    alt(mw)
    QTest.keyClick(mw, Qt.Key_A)                        # Ansicht
    settle()
    assert w.current_tab() == "ansicht" and keys.level == 1
    QTest.keyClick(mw, Qt.Key_Escape)                   # zurück auf Ebene 0
    assert keys.active and keys.level == 0
    QTest.keyClick(mw, Qt.Key_K)                        # Karte
    settle()
    assert keys.level == 1
    c = codes(keys)
    assert set(c) >= {"Verschieben", "Speichern", "Löschen", "Layer hinzufügen"}
    assert len(set(c.values())) == len(c)
    # Grauer Befehl: Modus bleibt
    for ch in c["Löschen"]:
        QTest.keyClick(mw, getattr(Qt, "Key_" + ch))
    assert keys.active
    # Split per Tastatur: Menü mit Hauptbefehl oben
    for ch in c["Verschieben"]:
        QTest.keyClick(mw, getattr(Qt, "Key_" + ch))
    assert not keys.active
    settle()
    menu = QApplication.activePopupWidget()
    assert isinstance(menu, QMenu) and menu.objectName() == "ribbon_keyboard_menu"
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[:2] == ["Verschieben", "Hineinzoomen"]
    menu.close()
    assert not zoom.isChecked()


def test_shortcuts_do_not_fire_in_keytip_mode(setup):
    _w, keys, mw = setup
    fired = []
    sc = QShortcut(QKeySequence("X"), mw)
    sc.activated.connect(lambda: fired.append(1))
    alt(mw)
    QTest.keyClick(mw, Qt.Key_X)
    assert keys.active and fired == []
    QTest.keyClick(mw, Qt.Key_Escape)
    sc.setParent(None)


def test_quick_access_digit_and_search_key(setup, fake_iface):
    w, keys, mw = setup
    triggered = []
    mw.findChild(QAction, "mActionNewProject").triggered.connect(lambda: triggered.append(1))
    alt(mw)
    QTest.keyClick(mw, Qt.Key_1)
    assert triggered and not keys.active
    alt(mw)
    QTest.keyClick(mw, Qt.Key_Q)
    settle()
    assert QApplication.focusWidget() is w.search


def test_uninstall_removes_filter(setup):
    _w, keys, mw = setup
    keys.uninstall()
    alt(mw)
    assert not keys.active


# -- Schnellzugriffsleiste --------------------------------------------------------

def test_quick_access_add_remove_reset(setup, settings):
    w, _keys, _mw = setup
    assert [c.id for c in w.quick.commands] == ["neu"]
    btn = w.findChild(QToolButton, "ribbon_btn_speichern")
    menu = w.context_menu(btn)
    add = [a for a in menu.actions() if a.text() == TEXT_ADD][0]
    add.trigger()
    assert [c.id for c in w.quick.commands] == ["neu", "speichern"]
    assert settings.value(KEY_QUICK_ACCESS) == "neu,speichern"
    assert w.findChild(QToolButton, "ribbon_qat_speichern") is not None
    # Im Kontextmenü des Schnellzugriffs: Entfernen
    menu = w.context_menu(w.findChild(QToolButton, "ribbon_qat_neu"))
    [a for a in menu.actions() if a.text() == TEXT_REMOVE][0].trigger()
    assert [c.id for c in w.quick.commands] == ["speichern"]
    # Galerie/Menü: kein Eintrag für den Schnellzugriff
    w.select_tab("ansicht")
    settle()
    gal = w.findChild(QWidget, "ribbon_gallery_werkzeuge")
    assert TEXT_ADD not in [a.text() for a in w.context_menu(gal.expand).actions()]
    w.reset_quick_access()
    assert [c.id for c in w.quick.commands] == ["neu"] and settings.value(KEY_QUICK_ACCESS) is None


def test_quick_access_survives_restart(fake_iface, settings):
    settings.setValue(KEY_QUICK_ACCESS, "speichern,gibtsnicht")
    w = RibbonWidget(config_loader.parse(copy.deepcopy(DEFINITION)), ActionResolver(fake_iface),
                     SignalHub(), user=UserSettings(settings))
    assert [c.id for c in w.quick.commands] == ["speichern"]
    w.deleteLater()


# -- Minimieren ---------------------------------------------------------------------

def test_minimize_popup_and_restore(setup, settings):
    w, _keys, mw = setup
    full = w.sizeHint().height()
    w.toggle_minimized()
    settle()
    assert w.minimized and settings.value(KEY_MINIMIZED) == "true"
    assert w.stack.parent() is w.popup and w.sizeHint().height() < full
    # Klick auf einen Tab klappt die Seite auf
    w._on_tab_clicked(1)
    settle()
    assert w.popup.isVisible() and w.current_tab() == "ansicht"
    # Ein Befehl im aufgeklappten Ribbon klappt wieder zu
    w.select_tab("karte")
    w.show_popup()
    w.findChild(QToolButton, "ribbon_btn_speichern").click()
    settle()
    assert not w.popup.isVisible()
    w.set_minimized(False)
    settle()
    assert not w.minimized and w.stack.parent() is w.surface and settings.value(KEY_MINIMIZED) == "false"


def test_minimized_state_survives_restart(fake_iface, settings):
    settings.setValue(KEY_MINIMIZED, "true")
    w = RibbonWidget(config_loader.parse(copy.deepcopy(DEFINITION)), ActionResolver(fake_iface),
                     SignalHub(), user=UserSettings(settings))
    assert w.minimized and w.popup is not None
    w.hide_popup()
    w.deleteLater()


def test_ctrl_f1_toggles(setup):
    w, _keys, mw = setup
    QTest.keyClick(mw, Qt.Key_F1, Qt.ControlModifier)
    assert w.minimized
    QTest.keyClick(mw, Qt.Key_F1, Qt.ControlModifier)
    assert not w.minimized


def test_keytips_open_tab_in_minimized_ribbon(setup):
    w, keys, mw = setup
    w.set_minimized(True)
    alt(mw)
    QTest.keyClick(mw, Qt.Key_A)
    settle()
    assert w.popup.isVisible() and keys.level == 1
    labels = [l for l in w.popup.findChildren(QLabel, "ribbon_keytip") if l.isVisible()]
    assert labels                                       # Kürzel im aufgeklappten Ribbon
    QTest.keyClick(mw, Qt.Key_Escape)
    assert keys.level == 0 and not w.popup.isVisible()
    QTest.keyClick(mw, Qt.Key_Escape)


# -- Suche --------------------------------------------------------------------------

def test_search_ribbon_and_qgis_actions(setup, fake_iface):
    w, _keys, mw = setup
    idx = w.search.build_index()
    labels = [e.label for e in idx.entries]
    assert "Hineinzoomen" in labels and "Neues Projekt" in labels
    # QGIS-Aktion aus einem Menü, die nicht im Ribbon steht
    hits = w.search.results("vektorlayer")
    assert hits and not hits[0].ribbon and hits[0].path.startswith("QGIS: Layer hinzufügen")
    zoom = mw.findChild(QAction, "mActionZoomIn")
    hit = w.search.results("hineinzoomen")[0]
    assert hit.ribbon and hit.path == "Karte › Navigieren"
    assert w.search.execute(hit) and zoom.isChecked()
    # Grauer Befehl lässt sich nicht auslösen
    assert not w.search.execute(w.search.results("löschen")[0])
    assert w.search.last_ms is not None and w.search.last_ms < 10


def test_search_navigates_to_gallery(setup):
    w, _keys, _mw = setup
    w.select_tab("karte")
    entry = w.search.results("werkzeuge")[0]
    assert entry.ref[0].id == "werkzeuge"
    assert w.search.execute(entry)
    settle()
    assert w.current_tab() == "ansicht"
    popup = QApplication.activePopupWidget()
    assert isinstance(popup, QMenu)
    popup.close()


def test_search_results_in_model(setup):
    w, _keys, _mw = setup
    w.search.setFocus()
    w.search.update_results("zoom")
    assert w.search.model.rowCount() >= 1
    w.search.completer.popup().hide()


# -- Galerie per Tastatur -------------------------------------------------------------

def test_gallery_grid_keyboard(setup, fake_iface):
    w, _keys, mw = setup
    gal = w.ribbon.commands["werkzeuge"].gallery
    top = QWidget()
    grid = GalleryGrid(gal.items, w.ctx, gal.columns, top)
    top.show()
    QApplication.setActiveWindow(top)
    settle()
    assert [t.objectName() for t in grid.tiles] == ["ribbon_tile_verschieben", "ribbon_tile_zoomen",
                                                    "ribbon_tile_speichern"]
    grid.setFocus()                                     # Fokus-Proxy: erste Kachel
    assert grid.tiles[0].hasFocus()
    QTest.keyClick(grid.tiles[0], Qt.Key_Right)
    assert grid.tiles[1].hasFocus()
    QTest.keyClick(grid.tiles[1], Qt.Key_Down)          # Rand (keine Kachel darunter): bleibt
    assert grid.tiles[1].hasFocus()
    QTest.keyClick(grid.tiles[1], Qt.Key_Left)
    QTest.keyClick(grid.tiles[0], Qt.Key_Down)
    assert grid.tiles[2].hasFocus()
    QTest.keyClick(grid.tiles[2], Qt.Key_Up)
    QTest.keyClick(grid.tiles[0], Qt.Key_Right)
    QTest.keyClick(grid.tiles[1], Qt.Key_Return)
    assert mw.findChild(QAction, "mActionZoomIn").isChecked()
    top.deleteLater()


# -- Eigene Kürzel ----------------------------------------------------------------------

def test_keytip_dialog_lists_and_saves_overrides(setup, settings):
    from qgis_ribbon.core import keytips
    from qgis_ribbon.qgis_integration.user_settings import KEY_KEYTIPS
    from qgis_ribbon.ui.keytip_dialog import COL_AUTO, COL_EFFECTIVE, COL_OWN
    w, keys, mw = setup
    dlg = w.keytip_dialog()
    tab_karte = keytips.tab_key("karte")
    assert dlg._items[tab_karte].text(COL_AUTO) == "K"
    speichern = keytips.element_key("karte", "speichern")
    assert speichern in dlg._items
    # Eigenes Kürzel; andere Kürzel passen sich an
    dlg.set_override(tab_karte, "m")
    assert dlg._items[tab_karte].text(COL_OWN) == "M"
    assert dlg._items[tab_karte].text(COL_EFFECTIVE) == "M"
    # Konflikt: gleiches Kürzel wie ein anderes eigenes -> rot, nicht speicherbar
    dlg.set_override(keytips.tab_key("ansicht"), "M")
    assert dlg.problems() and not dlg.buttons.button(dlg.buttons.Save).isEnabled()
    dlg.set_override(keytips.tab_key("ansicht"), "Q")       # reserviert für die Suche
    assert any("Suche" in p[1] for p in dlg.problems())
    dlg.set_override(keytips.tab_key("ansicht"), "")
    dlg.set_override(speichern, "XY")
    assert not dlg.problems()
    dlg.save()
    assert '"tab:karte": "M"' in settings.value(KEY_KEYTIPS)
    dlg.deleteLater()
    # Wirkt sofort im Ribbon
    alt(mw)
    assert codes(keys)["Karte"] == "M"
    QTest.keyClick(mw, Qt.Key_M)
    settle()
    assert keys.level == 1 and codes(keys)["Speichern"] == "XY"
    QTest.keyClick(mw, Qt.Key_X)
    assert keys.active
    QTest.keyClick(mw, Qt.Key_Y)
    assert not keys.active                               # Speichern ausgelöst
    # Zurücksetzen
    dlg = w.keytip_dialog()
    dlg.reset_all()
    dlg.save()
    assert settings.value(KEY_KEYTIPS) is None
    dlg.deleteLater()


def test_keytip_dialog_filter_and_menu_entries(setup):
    w, _keys, _mw = setup
    dlg = w.keytip_dialog()
    dlg.filter.setText("lösch")
    visible = [dlg.tree.topLevelItem(i).text(0) for i in range(dlg.tree.topLevelItemCount())
               if not dlg.tree.topLevelItem(i).isHidden()]
    assert visible == ["Tab „Karte“"]
    dlg.deleteLater()
    assert "Kürzel anpassen …" in [a.text() for a in w.context_menu(None).actions()]
    w.quick.menu.aboutToShow.emit()
    assert "Kürzel anpassen …" in [a.text() for a in w.quick.menu.actions()]
