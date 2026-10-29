from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtGui import QCloseEvent
from qgis.PyQt.QtWidgets import QToolBar

from qgis_ribbon.qgis_integration.toolbar_manager import SETTINGS_KEY, STATE_KEY, ToolbarManager

CORE = ["mFileToolBar", "mMapNavToolBar", "mDigitizeToolBar", "mGibtEsNicht"]


def visible(mw):
    return {tb.objectName(): not tb.isHidden() for tb in mw.findChildren(QToolBar)}


def test_hide_only_visible_and_restore_exactly(main_window, settings):
    before = visible(main_window)
    state = main_window.saveState()
    tm = ToolbarManager(main_window, settings)
    tm.hide(CORE)
    assert tm.hidden == ["mFileToolBar", "mMapNavToolBar"]  # Digitalisierung war schon aus
    after = visible(main_window)
    assert not after["mFileToolBar"] and not after["mMapNavToolBar"]
    assert after["mPluginToolBar"]
    assert settings.value(SETTINGS_KEY) == ["mFileToolBar", "mMapNavToolBar"]

    tm.restore()
    assert visible(main_window) == before
    assert main_window.saveState() == state
    assert settings.value(SETTINGS_KEY) is None


def test_ribbon_toolbar_gets_own_first_line_and_is_removed(main_window, settings):
    state = main_window.saveState()
    tm = ToolbarManager(main_window, settings)
    ribbon = QToolBar("Ribbon", main_window)
    ribbon.setObjectName("QgisRibbonToolbar")
    tm.place_ribbon(ribbon)
    QgsApplication.processEvents()
    assert main_window.toolBarBreak(main_window.findChild(QToolBar, "mFileToolBar"))
    assert ribbon.geometry().y() < main_window.findChild(QToolBar, "mFileToolBar").geometry().y()
    tm.remove_ribbon()
    ribbon.setParent(None)
    QgsApplication.processEvents()
    assert main_window.saveState() == state


def test_save_window_state_after_restore_matches_state_without_ribbon(main_window, settings):
    # QGIS speichert beim Beenden am Signal aboutToQuit (mit ausgeblendeten Leisten) und
    # entlädt erst danach die Plugins; das Plugin schreibt den Zustand dann neu
    state = main_window.saveState()
    tm = ToolbarManager(main_window, settings)
    tm.hide(CORE)
    settings.setValue(STATE_KEY, main_window.saveState())   # wie QgisApp::saveWindowState
    assert settings.value(STATE_KEY) != state
    tm.restore()
    tm.save_window_state()
    assert settings.value(STATE_KEY) == state


def test_close_event_does_not_touch_toolbars(main_window, settings):
    # QGIS ignoriert das Schließen-Ereignis; Ein- und Ausblenden dort war wirkungslos
    tm = ToolbarManager(main_window, settings)
    tm.hide(CORE)
    QgsApplication.sendEvent(main_window, QCloseEvent())
    assert not visible(main_window)["mFileToolBar"]
    tm.restore()


def test_leftover_after_crash_counts_as_originally_visible(main_window, settings):
    settings.setValue(SETTINGS_KEY, ["mMapNavToolBar"])
    main_window.findChild(QToolBar, "mMapNavToolBar").hide()  # Zustand nach Absturz
    tm = ToolbarManager(main_window, settings)
    tm.hide(CORE)
    assert "mMapNavToolBar" in tm.hidden
    tm.restore()
    assert visible(main_window)["mMapNavToolBar"]


def test_close_event_type():
    assert QCloseEvent().type() == QEvent.Type.Close
