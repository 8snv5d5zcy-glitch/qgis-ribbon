"""macOS: Kürzel ohne Systemkonflikte, ihre Schreibweise und die native Menüleiste."""
import pytest

from qgis_ribbon.core import i18n
from qgis_ribbon.qgis_integration import menu_bar
from qgis_ribbon.ui import keys


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(keys, "MAC", True)


def test_key_text_on_mac_uses_symbols(mac):
    assert keys.text("Ctrl+Z") == "⌘Z"
    assert keys.text("Ctrl+Alt+T") == "⌥⌘T"
    assert keys.text("Ctrl+Shift+Z") == "⇧⌘Z"
    assert keys.text("Meta+Q") == "⌃Q"
    assert keys.text("Alt") == "⌥"
    assert keys.text("Del") == "⌫"


def test_key_text_elsewhere_is_translated(monkeypatch):
    monkeypatch.setattr(keys, "MAC", False)
    i18n.set_language("de")
    try:
        assert keys.text("Ctrl+Z") == "Strg+Z"
        assert keys.text("Ctrl+Arrow") == "Strg+Pfeil"
        assert keys.text("Del") == "Entf"
        assert keys.text("Alt") == "Alt"
        i18n.set_language("en")
        assert keys.text("Ctrl+F1") == "Ctrl+F1"
    finally:
        i18n.set_language("de")


def test_mac_shortcuts_avoid_system_keys():
    if not keys.MAC:
        assert (keys.MINIMIZE, keys.QUICK_ACCESS, keys.REDO) == ("Ctrl+F1", "Ctrl+Q", "Ctrl+Y")
    # ⌘Q beendet, ⌘F1/⌃F1 belegt macOS
    assert not keys.MAC or "F1" not in keys.MINIMIZE and keys.QUICK_ACCESS != "Ctrl+Q"


def test_native_menu_bar_is_not_hidden(main_window, monkeypatch):
    bar = main_window.menuBar()
    before = (bar.minimumHeight(), bar.maximumHeight())
    monkeypatch.setattr(bar, "isNativeMenuBar", lambda: True)
    assert not menu_bar.can_hide(main_window)
    hider = menu_bar.MenuBarHider(main_window)
    hider.hide()
    assert not hider.hidden
    assert (bar.minimumHeight(), bar.maximumHeight()) == before
    monkeypatch.undo()
    assert menu_bar.can_hide(main_window)
