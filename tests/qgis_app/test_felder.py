"""Felder anlegen, löschen, umbenennen; Seitenbefehle der Eigenschaften; Befehlsvorrat in der Suche."""
import pytest
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransformContext, QgsField,
                       QgsFields, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QMenu, QToolButton

from qgis_ribbon.core import fields as fm
from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.qgis_integration import context_state, field_ops
from qgis_ribbon.ui import field_dialogs


def settle():
    for _ in range(3):
        QgsApplication.processEvents()


def memory():
    layer = QgsVectorLayer("Point?crs=EPSG:25832&field=name:string&field=wert:integer", "Punkte", "memory")
    assert layer.isValid()
    return layer


@pytest.fixture
def gpkg(tmp_path):
    path = str(tmp_path / "felder.gpkg")
    fields = QgsFields()
    fields.append(QgsField("art", QMetaType.QString))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "punkte"
    w = QgsVectorFileWriter.create(path, fields, QgsWkbTypes.Point, QgsCoordinateReferenceSystem("EPSG:25832"),
                                   QgsCoordinateTransformContext(), opts)
    del w
    layer = QgsVectorLayer(path + "|layername=punkte", "Punkte", "ogr")
    assert layer.isValid()
    yield layer, path


def names(layer):
    return [f.name() for f in layer.fields()]


# -- Feldoperationen ----------------------------------------------------------------

def test_caps_types_and_snapshot(layers):
    layer = memory()
    assert field_ops.field_caps(layer) == {"add", "delete", "rename"}
    assert {"string", "integer", "real"} <= set(field_ops.supported_types(layer))
    assert field_ops.field_caps(layers["raster"]) == frozenset()
    assert context_state.snapshot(layer).field_caps == {"add", "delete", "rename"}
    assert context_state.snapshot(layers["raster"]).field_caps == frozenset()


def test_direct_add_rename_delete_on_memory_layer():
    layer = memory()
    ok, msg = field_ops.add_field(layer, fm.FieldSpec("hoehe", "real", 10, 2, alias="Höhe", comment="m"))
    assert ok and msg == "Feld „hoehe“ hinzugefügt."
    assert names(layer) == ["name", "wert", "hoehe"]
    assert layer.attributeAlias(2) == "Höhe"
    assert field_ops.add_field(layer, fm.FieldSpec("HOEHE")) == (False, "Ein Feld „HOEHE“ gibt es schon.")
    assert field_ops.rename_field(layer, "hoehe", "z")[0]
    assert names(layer) == ["name", "wert", "z"]
    ok, msg = field_ops.delete_fields(layer, ["wert", "z"])
    assert ok and msg == "2 Feld(er) gelöscht." and names(layer) == ["name"]
    assert field_ops.delete_fields(layer, []) == (False, "Kein Feld gewählt.")


def test_buffer_changes_can_be_undone():
    layer = memory()
    layer.startEditing()
    assert field_ops.add_field(layer, fm.FieldSpec("neu", "integer"))[0]
    assert names(layer) == ["name", "wert", "neu"]
    assert layer.dataProvider().fields().count() == 2       # noch nicht in der Quelle
    assert field_ops.rename_field(layer, "name", "bezeichnung")[0]
    assert field_ops.delete_fields(layer, ["wert"])[0]
    assert names(layer) == ["bezeichnung", "neu"]
    stack = layer.undoStack()
    while stack.canUndo():
        stack.undo()
    assert names(layer) == ["name", "wert"]
    layer.rollBack()        # nach rückgängig gemachter Umbenennung kann QGIS nicht speichern (Test unten)
    layer.startEditing()
    assert field_ops.add_field(layer, fm.FieldSpec("neu", "string", 20))[0]
    assert layer.commitChanges(), layer.commitErrors()
    assert [f.name() for f in layer.dataProvider().fields()] == ["name", "wert", "neu"]


def test_geopackage_direct(gpkg):
    layer, path = gpkg
    assert field_ops.field_caps(layer) >= {"add", "delete"}
    assert field_ops.add_field(layer, fm.FieldSpec("anzahl", "integer64", alias="Anzahl"))[0]
    assert field_ops.add_field(layer, fm.FieldSpec("datum", "date"))[0]
    again = QgsVectorLayer(path + "|layername=punkte", "Punkte", "ogr")
    assert "anzahl" in names(again) and "datum" in names(again)
    if "rename" in field_ops.field_caps(layer):
        assert field_ops.rename_field(layer, "anzahl", "menge")[0]
    assert field_ops.delete_fields(layer, ["datum"])[0]
    again = QgsVectorLayer(path + "|layername=punkte", "Punkte", "ogr")
    assert "datum" not in names(again)


def test_geopackage_real_without_length_saves_later(gpkg):
    # GeoPackage speichert bei Dezimalzahlen keine Länge; mitgegeben scheiterte das nächste Speichern
    layer, path = gpkg
    assert field_ops.sizes(layer, "real") == (False, False)
    assert field_ops.sizes(layer, "string") == (True, False)
    assert field_ops.sizes(memory(), "real") == (True, True)
    assert field_ops.add_field(layer, fm.FieldSpec("flaeche", "real", 12, 2))[0]
    layer.startEditing()
    assert field_ops.add_field(layer, fm.FieldSpec("anzahl", "integer"))[0]
    assert field_ops.rename_field(layer, "art", "kategorie")[0]
    assert layer.commitChanges(), layer.commitErrors()
    again = QgsVectorLayer(path + "|layername=punkte", "Punkte", "ogr")
    assert names(again) == ["fid", "kategorie", "flaeche", "anzahl"]


@pytest.mark.xfail(strict=True, reason="QGIS: Rückgängig beim Umbenennen trägt den alten Namen als Umbenennung ein")
def test_qgis_cannot_save_after_undoing_a_rename():
    # Schlägt dieser Test nicht mehr fehl, hat QGIS den Fehler behoben: Sperre in rename_field überprüfen.
    layer = memory()
    layer.startEditing()
    layer.renameAttribute(0, "bezeichnung")
    layer.undoStack().undo()
    assert layer.commitChanges(), layer.commitErrors()


def test_rename_back_in_one_edit_session_is_refused(gpkg):
    layer, path = gpkg
    layer.startEditing()
    assert field_ops.rename_field(layer, "art", "kategorie")[0]
    ok, msg = field_ops.rename_field(layer, "kategorie", "Art")
    assert not ok and msg.startswith("QGIS kann ein Feld")
    dlg = field_dialogs.RenameFieldDialog(layer)
    dlg.field.setCurrentText("kategorie")
    dlg.new_name.setText("art")
    assert not dlg.check() and dlg.hint.text() == msg
    assert field_ops.rename_field(layer, "kategorie", "typ")[0]       # anderer Name geht
    assert layer.commitChanges(), layer.commitErrors()
    assert field_ops.rename_field(layer, "typ", "art")[0]             # direkt, ohne Bearbeitung
    layer.startEditing()
    assert field_ops.rename_field(layer, "art", "kategorie")[0]
    layer.rollBack()


def test_only_own_fields_can_be_deleted():
    layer = memory()
    layer.addExpressionField("1 + 1", QgsField("virtuell", QMetaType.Int))
    assert names(layer)[-1] == "virtuell"
    assert field_ops.own_fields(layer) == ["name", "wert"]


# -- Dialoge ------------------------------------------------------------------------

@pytest.fixture
def no_dialogs(monkeypatch):
    """exec ersetzt: ``fill(dlg)`` füllt den Dialog aus; Rückfrage antwortet ``answer``."""
    state = {"fill": None, "answer": True, "asked": 0}

    def exec_dialog(dlg):
        state["fill"](dlg)
        return QDialog.Accepted if dlg.buttons.button(QDialogButtonBox.Ok).isEnabled() else QDialog.Rejected

    def confirm(parent, layer):
        state["asked"] += 1
        return state["answer"]

    monkeypatch.setattr(field_dialogs, "exec_dialog", exec_dialog)
    monkeypatch.setattr(field_dialogs, "confirm_direct", confirm)
    return state


def test_add_dialog_checks_and_writes(fake_iface, no_dialogs):
    layer = memory()
    fake_iface.active_layer = layer
    seen = {}

    def fill(dlg):
        assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
        assert dlg.hint.text() == "Einen Feldnamen eingeben."
        dlg.name.setText("WERT")
        seen["dup"] = dlg.hint.text()
        dlg.name.setText("flaeche")
        dlg.type.setCurrentIndex(dlg.type.findData("real"))
        assert dlg.length.isEnabled() and dlg.precision.isEnabled()
        dlg.length.setValue(12)
        dlg.precision.setValue(3)
        dlg.alias.setText("Fläche")
    no_dialogs["fill"] = fill
    assert field_dialogs.open_add(fake_iface) is True
    assert seen["dup"] == "Ein Feld „WERT“ gibt es schon."
    assert no_dialogs["asked"] == 1                     # direkt: Rückfrage
    assert names(layer)[-1] == "flaeche" and layer.attributeAlias(2) == "Fläche"
    # Rückfrage verneint: nichts passiert
    no_dialogs["answer"] = False
    no_dialogs["fill"] = lambda dlg: dlg.name.setText("noch_eins")
    assert field_dialogs.open_add(fake_iface) is False and "noch_eins" not in names(layer)
    # im Bearbeitungsmodus ohne Rückfrage
    layer.startEditing()
    assert field_dialogs.open_add(fake_iface) is True and no_dialogs["asked"] == 2
    assert "noch_eins" in names(layer)
    layer.rollBack()


def test_delete_and_rename_dialogs(fake_iface, no_dialogs):
    layer = memory()
    layer.startEditing()
    fake_iface.active_layer = layer

    def tick(dlg):
        assert [dlg.list.item(i).text() for i in range(dlg.list.count())] == ["name", "wert"]
        assert dlg.hint.text() == "Die zu löschenden Felder abhaken."
        from qgis.PyQt.QtCore import Qt
        dlg.list.item(1).setCheckState(Qt.Checked)
    no_dialogs["fill"] = tick
    assert field_dialogs.open_delete(fake_iface) is True and names(layer) == ["name"]

    def rename(dlg):
        assert dlg.new_name.text() == "name" and dlg.hint.text() == "Einen neuen Namen eingeben."
        dlg.new_name.setText("titel")
    no_dialogs["fill"] = rename
    assert field_dialogs.open_rename(fake_iface) is True and names(layer) == ["titel"]
    assert no_dialogs["asked"] == 0
    layer.rollBack()


def test_dialogs_need_a_vector_layer(fake_iface, layers, no_dialogs):
    fake_iface.active_layer = layers["raster"]
    assert field_dialogs.open_add(fake_iface) is None


# -- Ribbon: Gruppe Felder, Seitenbefehle, Befehlsvorrat ------------------------------

@pytest.fixture
def plugin(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


def buttons(plugin, cid):
    return plugin.widget.findChildren(QToolButton, "ribbon_btn_" + cid)


def test_field_group_in_data_tabs(plugin, fake_iface, layers):
    w = plugin.widget
    for tab in ("vektor_daten", "tabelle_daten"):
        groups = [g.id for g in plugin.ribbon.tab(tab).groups]
        assert groups.index("felder") == groups.index("tabelle") + 1
    fake_iface.set_active_layer(memory())
    settle()
    w.select_tab("vektor_daten")
    settle()
    for cid in ("feld_hinzufuegen", "feld_loeschen", "feld_umbenennen"):
        assert buttons(plugin, cid) and all(b.isEnabled() for b in buttons(plugin, cid)), cid
    # Anbieter ohne Feldänderungen: gesperrt
    read_only = memory()
    read_only.setReadOnly(True)
    fake_iface.set_active_layer(read_only)
    settle()
    assert not any(b.isEnabled() for b in buttons(plugin, "feld_hinzufuegen"))


def test_property_page_commands_pick_the_page(plugin, fake_iface, layers):
    resolver = plugin.widget.ctx.resolver
    fake_iface.set_active_layer(layers["raster"])
    settle()
    resolver.trigger(plugin.ribbon.commands["eigenschaften_beschriftungen"])
    fake_iface.set_active_layer(layers["vector"])
    settle()
    resolver.trigger(plugin.ribbon.commands["eigenschaften_beschriftungen"])
    resolver.trigger(plugin.ribbon.commands["eigenschaften_metadaten"])
    resolver.trigger(plugin.ribbon.commands["projekt_kbs"])
    calls = [c for c in fake_iface.calls if c[0] in ("showLayerProperties", "showProjectPropertiesDialog")]
    assert calls == [("showLayerProperties", layers["raster"], "mOptsPage_Labeling"),
                     ("showLayerProperties", layers["vector"], "mOptsPage_Labels"),
                     ("showLayerProperties", layers["vector"], "mOptsPage_Metadata"),
                     ("showProjectPropertiesDialog", "mProjOptsCRS")]


def test_search_finds_and_runs_the_command_pool(plugin, fake_iface, layers):
    search = plugin.widget.search
    fake_iface.set_active_layer(layers["vector"])
    settle()
    hits = search.results("eigenschaften metadaten")
    entry = next(e for e in hits if e.ribbon and e.ref[0].id == "eigenschaften_metadaten")
    assert entry.path == "Befehlsvorrat"
    assert search.execute(entry)
    assert fake_iface.calls[-1] == ("showLayerProperties", layers["vector"], "mOptsPage_Metadata")
    # QGIS-Menü ohne Ort: öffnet unter dem Suchfeld
    menu = QMenu("Zuletzt verwendet", fake_iface.mainWindow())
    menu.setObjectName("mRecentProjectsMenu")
    menu.addAction("Projekt A")
    fake_iface.mainWindow().menuBar().addMenu(menu)
    search.index = None
    hits = search.results("zuletzt verwendet")
    entry = next(e for e in hits if e.ribbon and e.ref[0].id == "zuletzt_verwendet")
    assert search._enabled(entry)
    assert search.execute(entry)
    settle()
    assert menu.isVisible()
    below = search.mapToGlobal(search.rect().bottomLeft())
    assert abs(menu.pos().y() - below.y()) <= 2
    menu.hide()
