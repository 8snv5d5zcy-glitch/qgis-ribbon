"""Tests mit echtem QGIS (headless, ohne QGIS-Hauptfenster).

Laufen nur im Python der QGIS-Installation, z. B. über ``tools/qgis_pytest.cmd``.
In anderen Umgebungen (``.venv``) werden sie übersprungen.

Statt ``QgisApp`` stellt ``fake_iface`` ein Hauptfenster mit QGIS-ähnlichen
Toolbars, Aktionen, Docks und Menüs bereit.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _real_qgis():
    try:
        from qgis.core import QgsApplication
    except ImportError:
        return False
    return hasattr(QgsApplication, "processingRegistry")


if not _real_qgis():
    collect_ignore_glob = ["test_*.py"]
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication, QgsSettings
    from qgis.gui import QgsMapCanvas, QgsMessageBar
    from qgis.PyQt.QtCore import QObject, QSettings, Qt, pyqtSignal
    from qgis.PyQt.QtWidgets import (QAction, QActionGroup, QDockWidget, QMainWindow, QMenu,
                                     QToolBar, QWidget)

    _APP = None

    @pytest.fixture(scope="session", autouse=True)
    def qgis_app():
        global _APP
        if QgsApplication.instance() is None:
            _APP = QgsApplication([], True)
            _APP.initQgis()
            from qgis.analysis import QgsNativeAlgorithms
            QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
        yield QgsApplication.instance()

    class FakeIface(QObject):
        initializationCompleted = pyqtSignal()
        currentLayerChanged = pyqtSignal(object)

        def __init__(self, mw):
            QObject.__init__(self)
            self._mw = mw
            self._bar = QgsMessageBar(mw)
            self._canvas = QgsMapCanvas(mw)
            self.active_layer = None
            self.calls = []
            # Layerliste wie in QGIS von Anfang an vorhanden (zählt zum Ausgangszustand)
            from qgis.core import QgsLayerTreeModel, QgsProject
            from qgis.gui import QgsLayerTreeView
            self._view = QgsLayerTreeView(mw)
            self._view.setModel(QgsLayerTreeModel(QgsProject.instance().layerTreeRoot(), self._view))

        def mainWindow(self):
            return self._mw

        def messageBar(self):
            return self._bar

        def mapCanvas(self):
            return self._canvas

        def activeLayer(self):
            return self.active_layer

        def set_active_layer(self, layer):
            """Wie QGIS: aktiven Layer setzen und ``currentLayerChanged`` senden."""
            self.active_layer = layer
            self.currentLayerChanged.emit(layer)

        def layerTreeView(self):
            return self._view

        def select_group(self, group):
            """Wie ein Klick auf eine Gruppe der Layerliste: kein aktiver Layer, Gruppe aktuell."""
            view = self.layerTreeView()
            self.active_layer = None
            view.setCurrentIndex(view.node2index(group))
            self.currentLayerChanged.emit(None)

        def showLayerProperties(self, layer, page=""):
            self.calls.append(("showLayerProperties", layer, page))

        def showOptionsDialog(self, parent=None, currentPage=""):
            self.calls.append(("showOptionsDialog", parent, currentPage))

        def showProjectPropertiesDialog(self, currentPage=""):
            self.calls.append(("showProjectPropertiesDialog", currentPage))

        def locatorSearch(self, text):
            self.calls.append(("locatorSearch", text))

        def viewMenu(self):
            return self._mw.findChild(QMenu, "mViewMenu")

        def pluginHelpMenu(self):
            return self._mw.findChild(QMenu, "mPluginHelpMenu")

    def _action(mw, name, text, checkable=False):
        act = QAction(text, mw)
        act.setObjectName(name)
        act.setCheckable(checkable)
        return act

    def build_main_window():
        mw = QMainWindow()
        mw.setObjectName("QgisApp")
        mw.setCentralWidget(QWidget(mw))
        mw.resize(1200, 800)

        file_tb = QToolBar("Projekt", mw)
        file_tb.setObjectName("mFileToolBar")
        for name, text in (("mActionNewProject", "&Neu"), ("mActionSaveProject", "&Speichern")):
            file_tb.addAction(_action(mw, name, text))
        mw.addToolBar(Qt.TopToolBarArea, file_tb)

        nav_tb = QToolBar("Navigation", mw)
        nav_tb.setObjectName("mMapNavToolBar")
        group = QActionGroup(mw)
        group.setExclusive(True)
        for name, text in (("mActionPan", "Karte verschieben"), ("mActionZoomIn", "Hineinzoomen")):
            act = _action(mw, name, text, checkable=True)
            group.addAction(act)
            nav_tb.addAction(act)
        mw.findChild(QAction, "mActionPan").setChecked(True)
        mw.addToolBar(Qt.TopToolBarArea, nav_tb)

        mw.addToolBarBreak(Qt.TopToolBarArea)
        plugin_tb = QToolBar("Erweiterungen", mw)
        plugin_tb.setObjectName("mPluginToolBar")
        mw.addToolBar(Qt.TopToolBarArea, plugin_tb)

        digi_tb = QToolBar("Digitalisierung", mw)
        digi_tb.setObjectName("mDigitizeToolBar")
        delete = _action(mw, "mActionDeleteSelected", "Ausgewähltes löschen")
        delete.setEnabled(False)
        digi_tb.addAction(delete)
        mw.addToolBar(Qt.TopToolBarArea, digi_tb)
        digi_tb.hide()  # war schon vor dem Ribbon ausgeblendet

        dock = QDockWidget("Layer", mw)
        dock.setObjectName("Layers")
        mw.addDockWidget(Qt.LeftDockWidgetArea, dock)

        menu = QMenu("Layer hinzufügen", mw)
        menu.setObjectName("mAddLayerMenu")
        menu.addAction(_action(mw, "mActionAddOgrLayer", "Vektorlayer hinzufügen…"))
        mw.menuBar().addMenu(menu)

        view = QMenu("Ansicht", mw)
        view.setObjectName("mViewMenu")
        view.addAction(_action(mw, "mActionZoomFullExtent", "Volle Ausdehnung"))
        mw.menuBar().addMenu(view)

        help_menu = QMenu("Hilfe", mw)
        help_menu.setObjectName("mHelpMenu")
        plugin_help = help_menu.addMenu("Erweiterungen")
        plugin_help.setObjectName("mPluginHelpMenu")
        mw.menuBar().addMenu(help_menu)

        plugin_act = QAction("Werkzeugkiste", mw)
        plugin_act.setObjectName("toolboxAction")
        plugin_tb.addAction(plugin_act)
        return mw

    @pytest.fixture
    def main_window(qgis_app):
        mw = build_main_window()
        mw.show()
        QgsApplication.processEvents()
        yield mw
        mw.close()
        mw.deleteLater()
        QgsApplication.processEvents()

    @pytest.fixture
    def fake_iface(main_window):
        return FakeIface(main_window)

    @pytest.fixture
    def layers(tmp_path):
        """Vektorlayer, Tabelle und Rasterlayer (Speicher bzw. kleines GeoTIFF)."""
        from osgeo import gdal
        gdal.UseExceptions()
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsRasterLayer, QgsVectorLayer
        vector = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "Punkte", "memory")
        feats = []
        for i in range(3):
            f = QgsFeature(vector.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(i, i)))
            f.setAttributes(["p%d" % i])
            feats.append(f)
        vector.dataProvider().addFeatures(feats)
        table = QgsVectorLayer("None?field=wert:integer", "Tabelle", "memory")
        path = str(tmp_path / "raster.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, 1, gdal.GDT_Byte)
        ds.SetGeoTransform((0, 1, 0, 4, 0, -1))
        ds = None
        raster = QgsRasterLayer(path, "Raster")
        assert vector.isValid() and table.isValid() and raster.isValid()
        return {"vector": vector, "table": table, "raster": raster}

    @pytest.fixture
    def settings(tmp_path):
        """Eigene INI-Datei, damit Tests das echte QGIS-Profil nicht berühren."""
        return QgsSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
