import copy

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction, QToolButton, QWidget

from qgis_ribbon.core import config_loader
from qgis_ribbon.qgis_integration.action_resolver import ActionResolver
from qgis_ribbon.qgis_integration.signals import SignalHub
from qgis_ribbon.ui import theme
from qgis_ribbon.ui.ribbon_widget import RibbonWidget


def qa(name):
    return {"type": "qgis_action", "object_name": name}


DEFINITION = {
    "version": 1,
    "commands": {
        "neu": {"label": "Neues Projekt", "source": qa("mActionNewProject")},
        "verschieben": {"label": "Verschieben", "source": qa("mActionPan")},
        "zoomen": {"label": "Hineinzoomen", "source": qa("mActionZoomIn")},
        "loeschen": {"label": "Löschen", "source": qa("mActionDeleteSelected")},
        "fehlt": {"label": "Fehlt", "source": qa("mActionGibtEsNicht")},
        "suchen": {"label": "Suchen", "source": {"type": "custom", "id": "ribbon.nicht_da"}},
        "layer_menue": {"label": "Layer hinzufügen", "source": {"type": "qgis_menu", "object_name": "mAddLayerMenu"}},
        "inhalt": {"label": "Inhalt", "source": {"type": "dock", "object_name": "Layers"}},
        "galerie": {"label": "Galerie", "kind": "control", "source": {"type": "custom", "id": "ribbon.g"}},
    },
    "tabs": [
        {"id": "karte", "label": "Karte", "groups": [
            {"id": "nav", "label": "Navigieren", "items": [
                {"split": "verschieben", "items": ["zoomen"], "size": "large"},
                {"command": "loeschen", "size": "medium"},
                {"command": "fehlt", "size": "medium"},
                {"row": ["neu", "zoomen"]},
                {"split": "suchen", "items": ["neu"]},
                {"menu": "Lesezeichen", "gallery": "galerie", "items": ["layer_menue", "inhalt"]},
            ]},
        ]},
        {"id": "ansicht", "label": "Ansicht", "groups": [
            {"id": "fenster", "label": "Fenster", "items": [{"command": "inhalt"}]}]},
    ],
    "contextual_tabs": [
        {"id": "daten", "label": "Daten", "context": "Vektorlayer", "visible_when": ["active_layer_is_vector"],
         "groups": [{"id": "g", "label": "G", "items": [{"command": "loeschen"}]}]},
    ],
}


def make_widget(fake_iface):
    ribbon = config_loader.parse(copy.deepcopy(DEFINITION))
    hub = SignalHub()
    w = RibbonWidget(ribbon, ActionResolver(fake_iface), hub)
    w.resize(1400, 140)
    w.show()
    QgsApplication.processEvents()
    return w, hub


def button(w, name):
    return w.findChild(QToolButton, name)


def test_lazy_building(fake_iface):
    w, hub = make_widget(fake_iface)
    assert w.is_built("karte") and not w.is_built("ansicht") and not w.is_built("daten")
    w.select_tab("ansicht")
    assert w.is_built("ansicht") and not w.is_built("daten")
    assert set(w.build_times) == {"karte", "ansicht"}
    hub.disconnect_all()


def test_buttons_mirror_and_trigger_qgis_actions(fake_iface):
    w, hub = make_widget(fake_iface)
    mw = fake_iface.mainWindow()
    pan, zoom = mw.findChild(QAction, "mActionPan"), mw.findChild(QAction, "mActionZoomIn")

    split = w.findChild(QWidget, "ribbon_split_verschieben")
    # Großer Split wie in Pro: oben Hauptbefehl, unten Beschriftung mit Pfeil (Menü)
    assert split.bottom.popupMode() == QToolButton.InstantPopup
    assert split.bottom.text().startswith("Verschieben")
    assert split.top.defaultAction().isChecked()       # Verschieben ist aktiv
    zoom_btn = w.findChild(QToolButton, "ribbon_btn_zoomen")  # in der Zeile
    zoom_btn.click()
    assert zoom.isChecked() and not pan.isChecked()
    assert zoom_btn.defaultAction().isChecked() and not split.top.defaultAction().isChecked()
    zoom_btn.click()                                    # aktives Werkzeug erneut: bleibt an
    assert zoom.isChecked() and zoom_btn.defaultAction().isChecked()

    delete = mw.findChild(QAction, "mActionDeleteSelected")
    btn = button(w, "ribbon_btn_loeschen")
    assert not btn.isEnabled()
    delete.setEnabled(True)
    assert btn.isEnabled()
    delete.setEnabled(False)
    hub.disconnect_all()


def test_qgis_text_is_not_shown_on_button(fake_iface):
    w, hub = make_widget(fake_iface)
    btn = button(w, "ribbon_btn_loeschen")
    assert btn.text() == "Löschen"
    assert "QGIS: Ausgewähltes löschen" in btn.toolTip()
    hub.disconnect_all()


def test_unavailable_commands_are_disabled_with_reason(fake_iface):
    w, hub = make_widget(fake_iface)
    btn = button(w, "ribbon_btn_fehlt")
    assert not btn.isEnabled() and "mActionGibtEsNicht" in btn.toolTip()
    # Split mit fehlendem Hauptbefehl: Klick öffnet das Menü, Menüeinträge bleiben nutzbar
    split = button(w, "ribbon_split_suchen")
    assert split.isEnabled() and split.popupMode() == QToolButton.InstantPopup
    hub.disconnect_all()


def test_menu_with_gallery_placeholder_and_qgis_menu(fake_iface):
    w, hub = make_widget(fake_iface)
    menu_btn = [b for b in w.findChildren(QToolButton) if b.property("ribbon_text") == "Lesezeichen"][0]
    texts = [a.text() for a in menu_btn.menu().actions() if not a.isSeparator()]
    assert texts[0].startswith("Steuerelement folgt")   # Galerie nicht registriert
    assert "Layer hinzufügen" in texts and "Inhalt" in texts
    assert menu_btn.isEnabled()
    hub.disconnect_all()


def test_contextual_tab_is_marked(fake_iface):
    w, hub = make_widget(fake_iface)
    idx = [t.id for t in w.ribbon.tabs].index("daten")
    assert w.tabbar.contextual == {idx}
    tab = w.ribbon.tabs[idx]
    w.tabbar.setTabVisible(idx, True)
    assert w.tabbar.context_label(idx) == tab.context
    # Kontext-Tabs stehen in einer Kapsel (Token ctxS), der Name des Kontexts davor
    img = w.tabbar.grab().toImage()
    rect = w.tabbar.tabRect(idx)
    assert img.pixelColor(rect.x() + 4, rect.center().y()) == theme.color("ctxS")
    assert w.tabbar.tabToolTip(idx) == "Vektorlayer: Daten"
    hub.disconnect_all()


def test_disconnect_releases_qgis_actions(fake_iface):
    w, hub = make_widget(fake_iface)
    assert len(hub) > 0
    hub.disconnect_all()
    assert len(hub) == 0
    # QGIS-Aktion ändert sich weiter, ohne Fehler durch tote Verbindungen
    w.deleteLater()
    QgsApplication.processEvents()
    fake_iface.mainWindow().findChild(QAction, "mActionDeleteSelected").setEnabled(True)


def test_large_labels_wrap():
    assert theme.wrap_label("Änderungen speichern") == "Änderungen\nspeichern"
    assert theme.wrap_label("Karte") == "Karte"
