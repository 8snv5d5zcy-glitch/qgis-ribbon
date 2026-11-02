"""Befehle aus QGIS 4 im laufenden Plugin: im Editor nur, wo QGIS sie kennt."""
import pytest
from qgis.core import Qgis

from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.ui.ribbon_editor import RibbonEditor

from test_plugin import settle  # noqa: E402 (gleicher Ordner, ohne Paket)

NEW = {"digitalisieren_bezier", "digitalisieren_nurbs", "fasen_runden", "objekte_als_array",
       "hoehenprofile_verwalten", "annotationen_waehlen", "netz_digitalisieren", "netz_erzwingen",
       "netz_reindizieren", "netz_alle_stuetzpunkte", "netz_isolierte_stuetzpunkte", "netz_transformieren"}
IN_QGIS4 = Qgis.QGIS_VERSION_INT >= 40000


@pytest.fixture
def plugin(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


def test_definition_of_the_running_version(plugin):
    assert (NEW <= set(plugin.base.commands)) == IN_QGIS4
    assert bool(NEW & set(plugin.base.commands)) == IN_QGIS4
    assert "digitalisieren_segment" in plugin.base.commands


def test_editor_palette_of_the_running_version(plugin):
    dlg = RibbonEditor(plugin.arrangements, plugin.widget.window())
    try:
        palette = dlg.palette_box
        shown = {value for _kind, value in palette.visible_values()}
        assert (NEW <= shown) == IN_QGIS4
        assert bool(NEW & shown) == IN_QGIS4
        assert "digitalisieren_segment" in shown
    finally:
        dlg.editor._undo = []
        dlg.deleteLater()
        settle()


def test_new_commands_stay_out_of_the_ribbon(plugin):
    placed = {c.id for t in plugin.ribbon.tabs for g in t.groups for c in _commands(g)}
    assert not NEW & placed


def test_missing_action_is_greyed_with_a_reason(plugin):
    """Fehlt eine Aktion trotz passender Version (ältere 4.x), bleibt der Knopf grau statt abzustürzen."""
    from qgis_ribbon.core.model import Command, Source
    command = Command(id="fehlt", label="Fehlt", source=Source("qgis_action", {"object_name": "mActionGibtEsNicht"}))
    res = plugin.resolver.resolve(command)
    assert not res.available and "mActionGibtEsNicht" in res.reason


def _commands(group):
    from qgis_ribbon.core.model import iter_commands
    return iter_commands(group)
