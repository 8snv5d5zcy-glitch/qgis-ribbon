"""Bedienfeld „Passpunkte“ einer Sitzung „Georeferenzieren in der Karte“.

Entsteht mit der Sitzung (``GeorefManager.started``) rechts als angedocktes Bedienfeld und
verschwindet mit ihr. Tabelle: Nummer, aktiv, Bild X/Y (Spalte, Zeile), Ziel X/Y, Restfehler in
Bildpunkten; in der Kopfzeile Verfahren und mittlerer Fehler. Abhaken rechnet neu, die Auswahl
hebt die Marke in der Karte hervor; Löschen und Auf Punkt zoomen arbeiten auf der Auswahl.
"""

from qgis.core import QgsPointXY
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDockWidget, QHBoxLayout, QHeaderView, QLabel,
                                 QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import georef
from ..core.i18n import tr
from ..qgis_integration import georef_session
from ..qgis_integration.signals import SignalHub

DOCK_NAME = "QgisRibbonGeorefPoints"


def method_name(method):
    names = {
        georef.AUTO: tr("Automatic"), georef.TRANSLATION: tr("Translation"), georef.HELMERT: tr("Helmert"),
        georef.AFFINE: tr("Affine"), georef.POLY2: tr("Polynomial 2"), georef.POLY3: tr("Polynomial 3"),
        georef.TPS: tr("Thin Plate Spline"), georef.PROJECTIVE: tr("Projective"),
    }
    return names.get(method, method)


def missing_text(missing):
    if missing == 1:
        return tr("1 more control point needed")
    return tr("%d more control points needed") % missing


def _number(value, digits=3):
    return "" if value is None else "%.*f" % (digits, value)


class PointsPanel(QDockWidget):
    COLUMNS = 7

    def __init__(self, iface, manager):
        QDockWidget.__init__(self, tr("Control Points"), iface.mainWindow())
        self.setObjectName(DOCK_NAME)
        self.iface = iface
        self.manager = manager
        self._filling = False
        body = QWidget(self)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 4, 4, 4)
        self.summary = QLabel(body)
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, self.COLUMNS, body)
        self.table.setHorizontalHeaderLabels([tr("No."), tr("Active"), tr("Image X"), tr("Image Y"),
                                              tr("Target X"), tr("Target Y"), tr("Residual (px)")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._on_item)
        self.table.itemSelectionChanged.connect(self._on_selection)
        lay.addWidget(self.table)
        buttons = QHBoxLayout()
        self.delete_button = QPushButton(tr("Delete"), body)
        self.delete_button.clicked.connect(self.delete_selected)
        self.zoom_button = QPushButton(tr("Zoom to Point"), body)
        self.zoom_button.clicked.connect(self.zoom_selected)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.zoom_button)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.setWidget(body)
        self.refresh()

    def session(self):
        return self.manager.session

    def selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def refresh(self):
        session = self.session()
        self._filling = True
        try:
            points = session.points if session is not None else ()
            res = session.residuals if session is not None else None
            self.table.setRowCount(len(points))
            for i, p in enumerate(points):
                r = res[i] if res is not None else None
                cells = [str(i + 1), "", _number(p.col, 2), _number(p.row, 2), _number(p.x), _number(p.y),
                         _number(r.pixels if r is not None else None, 2)]
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                    if col == 1:
                        flags |= Qt.ItemFlag.ItemIsUserCheckable
                        item.setCheckState(Qt.CheckState.Checked if p.active else Qt.CheckState.Unchecked)
                    else:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item.setFlags(flags)
                    self.table.setItem(i, col, item)
            self.summary.setText(self._summary(session))
        finally:
            self._filling = False
        self._on_selection()

    def _summary(self, session):
        if session is None:
            return ""
        used = session.used_method()
        if used is None:
            if not session.points:
                return tr("No control points yet: click on the image, then on the target in the map.")
            missing = georef.available(session.method, session.active_count())[1]
            return "%s: %s" % (method_name(session.method), missing_text(missing))
        text = tr("Transformation: %s") % method_name(used)
        error = session.mean_error()
        if error is not None:
            text += " · " + tr("mean error %.2f px") % error
        return text

    def _on_item(self, item):
        if self._filling or item.column() != 1 or self.session() is None:
            return
        self.session().set_point_active(item.row(), item.checkState() == Qt.CheckState.Checked)

    def _on_selection(self):
        rows = self.selected_rows()
        self.delete_button.setEnabled(bool(rows))
        self.zoom_button.setEnabled(len(rows) == 1)
        session = self.session()
        if session is not None:
            session.set_highlight(rows[0] if len(rows) == 1 else None)

    def delete_selected(self):
        if self.session() is not None:
            self.session().remove_points(self.selected_rows())

    def zoom_selected(self):
        rows = self.selected_rows()
        session = self.session()
        if session is None or len(rows) != 1:
            return
        p = session.points[rows[0]]
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        extent.scale(0.5 if extent.width() > 0 else 1.0, QgsPointXY(p.x, p.y))
        canvas.setExtent(extent)
        canvas.refresh()


class PanelController(QObject):
    """Bedienfeld zur laufenden Sitzung: entsteht mit ihr rechts angedockt und verschwindet mit ihr."""

    panelVisibility = pyqtSignal()      # Bedienfeld gezeigt oder verborgen (Button „Passpunkttabelle“)

    def __init__(self, iface, manager):
        QObject.__init__(self)
        self.iface = iface
        self.manager = manager
        self.panel = None
        self.hub = SignalHub()
        self.hub.connect(manager, "changed", self._on_changed)
        self._on_changed()

    def _on_changed(self):
        session = self.manager.session
        if session is None:
            self._remove()
            return
        if self.panel is None:
            self.panel = PointsPanel(self.iface, self.manager)
            self.panel.visibilityChanged.connect(self.panelVisibility)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)
            self.panel.show()
        else:
            self.panel.refresh()

    def _remove(self):
        if self.panel is None:
            return
        panel, self.panel = self.panel, None
        panel.visibilityChanged.disconnect(self.panelVisibility)
        self.iface.removeDockWidget(panel)
        panel.setParent(None)
        panel.deleteLater()

    def close(self):
        self.hub.disconnect_all()
        self._remove()


_CONTROLLER = None


def install(iface, manager):
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = PanelController(iface, manager)
    return _CONTROLLER


def uninstall():
    global _CONTROLLER
    if _CONTROLLER is not None:
        _CONTROLLER.close()
        _CONTROLLER.deleteLater()
        _CONTROLLER = None


def controller():
    return _CONTROLLER


def georef_tabelle(env, command):
    """Bedienfeld Passpunkte zeigen oder verbergen (abgehakt, solange es zu sehen ist)."""
    from ..qgis_integration.georef_commands import SessionAction

    def visible(_session):
        ctl = controller()
        return ctl is not None and ctl.panel is not None and ctl.panel.isVisible()

    def toggle(_session, checked):
        ctl = install(env.iface, georef_session.install(env.iface))
        ctl._on_changed()
        if ctl.panel is not None:
            ctl.panel.setVisible(bool(checked))

    act = env.keep(SessionAction(env, command.label, toggle, checked=visible))
    if env.hub is not None:
        env.hub.connect(install(env.iface, georef_session.install(env.iface)), "panelVisibility", act.refresh)
    return act
