"""Anleitung: Fenster, Navigation und Zugänge (Hilfe-Menü, Knopf ?, Dialoge)."""
import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtWidgets import QAction, QDialog, QMenu

from qgis_ribbon.plugin import HELP_ACTION_NAME, RibbonPlugin
from qgis_ribbon.ui import guide


def settle():
    for _ in range(3):
        QgsApplication.processEvents()
    QgsApplication.sendPostedEvents(None, 0)
    QgsApplication.processEvents()


def current():
    return guide._window["dialog"]


def test_page_path_follows_language_and_falls_back():
    assert guide.page_path("ribbon").endswith(os.path.join("help", "de", "ribbon.md"))
    assert guide.page_path("ribbon", "xx").endswith(os.path.join("help", "en", "ribbon.md"))
    assert guide.page_path("gibt_es_nicht") is None
    assert guide.topic_of(guide.page_path("keyboard")) == "keyboard"
    assert guide.language_of(guide.page_path("keyboard")) == "de"


def test_navigation_with_links_and_history(main_window):
    dlg = guide.show_help("ribbon", main_window)
    try:
        assert dlg.windowTitle().endswith("Mit dem Ribbon arbeiten")
        assert "Kontext-Tabs" in dlg.view.toPlainText()
        assert not dlg.back.isEnabled()
        dlg._on_link(QUrl("keyboard.md"))
        assert guide.topic_of(dlg.path) == "keyboard"
        dlg.go_back()
        assert guide.topic_of(dlg.path) == "ribbon" and dlg.forward.isEnabled()
        dlg.go_forward()
        assert guide.topic_of(dlg.path) == "keyboard"
        dlg.home.click()
        assert guide.topic_of(dlg.path) == "index" and not dlg.forward.isEnabled()
        # ein zweiter Aufruf nimmt dasselbe Fenster
        assert guide.show_help("tools", main_window) is dlg
        assert guide.topic_of(dlg.path) == "tools"
    finally:
        guide.close_help()
        settle()
    assert current() is None


def test_images_are_scaled_to_the_window(main_window):
    dlg = guide.show_help("ribbon", main_window)
    try:
        dlg.resize(500, 600)
        settle()
        dlg.open_path(dlg.path, record=False)
        widths = []
        block = dlg.view.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fmt = it.fragment().charFormat()
                if fmt.isImageFormat():
                    widths.append(fmt.toImageFormat().width())
                it += 1
            block = block.next()
        assert widths and all(0 < w <= dlg.view.viewport().width() for w in widths)
    finally:
        guide.close_help()
        settle()


def test_guide_belongs_to_an_open_modal_dialog(main_window):
    modal = QDialog(main_window)
    modal.setModal(True)
    modal.show()
    settle()
    try:
        dlg = guide.show_help("customize", main_window)
        assert dlg.parentWidget() is modal
    finally:
        guide.close_help()
        modal.close()
        modal.deleteLater()
        settle()
    dlg = guide.show_help("index", main_window)
    assert dlg.parentWidget() is main_window
    guide.close_help()
    settle()


def test_help_menu_entry_ribbon_button_and_context_menu(fake_iface, settings):
    mw = fake_iface.mainWindow()
    help_menu = mw.findChild(QMenu, "mPluginHelpMenu")
    plugin = RibbonPlugin(fake_iface, settings=settings)
    plugin.initGui()
    settle()
    try:
        act = mw.findChild(QAction, HELP_ACTION_NAME)
        assert act is not None and act in help_menu.actions()
        assert act.text() == "Anleitung QGIS Ribbon"
        act.trigger()
        assert current() is not None and guide.topic_of(current().path) == "index"
        guide.close_help()

        plugin.widget.guide_button.click()
        assert guide.topic_of(current().path) == "index"
        guide.close_help()

        menu = plugin.widget.context_menu(None)
        entry = [a for a in menu.actions() if a.text() == "Ribbon-Anleitung …"]
        assert entry
        entry[0].trigger()
        assert current() is not None
        menu.deleteLater()
    finally:
        plugin.unload()
        settle()
    assert help_menu.actions() == []
    assert current() is None
