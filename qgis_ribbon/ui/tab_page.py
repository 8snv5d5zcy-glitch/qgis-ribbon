"""Seite eines Tabs: Gruppen nebeneinander, getrennt durch kurze Linien.

Adaptive Breite: Bei jeder Größenänderung wählt die Seite je Gruppe eine
Fassung (``core.adaptive.choose``), sodass die Breite der Ribbon-Fläche
möglichst ausgenutzt wird. Nur Gruppen, deren Fassung wechselt, werden
umgestellt. Passt selbst die schmalste Fassung nicht, scrollt die Seite.
"""

import time

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QPainter, QPen
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QWidget

from ..core import adaptive
from ..qgis_integration import builtin_commands
from . import theme
from .controls.custom import LayerControl
from .group_widget import GroupWidget


class PageInner(QWidget):
    """Gruppen in einer Zeile; zeichnet die Trennlinien zwischen den Gruppen."""

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.groups = []

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        if len(self.groups) < 2:
            return
        painter = QPainter(self)
        pen = QPen(theme.color("div"))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        top = theme.PAGE_TOP + 6
        bottom = self.height() - 8
        for g in self.groups[1:]:
            if g.isHidden():
                continue
            x = g.geometry().left() - theme.GROUP_GAP / 2.0 - 0.5
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        painter.end()


class TabPage(QScrollArea):
    def __init__(self, tab, ctx, parent=None):
        QScrollArea.__init__(self, parent)
        self.tab = tab
        self.setObjectName("ribbon_page_" + tab.id)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = PageInner(self)
        lay = QHBoxLayout(inner)
        lay.setContentsMargins(2, theme.PAGE_TOP, 2, 0)
        lay.setSpacing(theme.GROUP_GAP)
        self.groups = []
        ctx.begin_tab(tab.id)  # KeyTip-Ziele dieses Tabs in Aufbaureihenfolge
        for group in tab.groups:
            gw = GroupWidget(group, ctx, inner)
            self.groups.append(gw)
            lay.addWidget(gw, 0, Qt.AlignTop)
        lay.addStretch(1)
        ctx.end_tab()
        inner.groups = self.groups
        self.setWidget(inner)
        self.inner = inner
        self.last_layout_ms = None   # Messpunkt: Umstellen nach Größenänderung
        self._width = None
        if any(v.kind == "gallery" for g in self.groups for v in g.views):
            size = builtin_commands.gallery_size(ctx.env)
            ctx.hub.connect(size.changed, self.gallery_size_changed)

    def refresh_stale(self):
        """Steuerelemente nachlesen, die verborgen eine Änderung verpasst haben.

        Bei sichtbarem Fenster erledigt das ``showEvent`` der Steuerelemente; ohne
        (Fenster noch nicht gezeigt) kommt kein Show-Ereignis, daher beim Tabwechsel.
        """
        for control in self.findChildren(LayerControl):
            control.refresh_if_stale()

    def available_width(self):
        return self.viewport().width() - 4

    def gallery_size_changed(self, _compact=None):
        for g in self.groups:
            g.invalidate()
            g.variant = None
        self._width = None
        self.relayout()

    def relayout(self, force=False):
        """Fassungen der Gruppen für die verfügbare Breite wählen und setzen."""
        width = self.available_width()
        if width <= 0 or (width == self._width and not force):
            return
        start = time.perf_counter()
        self._width = width
        widths = [g.widths() for g in self.groups]
        ideal = [g.ideal_index() for g in self.groups]
        choice = adaptive.choose(widths, ideal, width, theme.GROUP_GAP)
        for g, i in zip(self.groups, choice):
            g.apply(i)
        self.inner.update()
        self.last_layout_ms = (time.perf_counter() - start) * 1000.0

    def resizeEvent(self, event):  # noqa: N802 (Qt)
        QScrollArea.resizeEvent(self, event)
        self.relayout()

    def showEvent(self, event):  # noqa: N802 (Qt)
        QScrollArea.showEvent(self, event)
        self.relayout()
