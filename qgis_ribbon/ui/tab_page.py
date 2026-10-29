"""Seite eines Tabs: Gruppen nebeneinander, getrennt durch Linien.

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


def divider_pixels(ratio):
    """Breite der Gruppentrenner in Gerätepixeln: 1, ab 150 % Skalierung 2 (scharf, kein Bruchteil)."""
    return 2 if ratio >= 1.5 else 1


def divider_x(left, gap, ratio, pixels):
    """Logische x-Mitte des Trenners, auf ganze Gerätepixel gelegt (sonst unscharf)."""
    first = int(round((left - gap / 2.0) * ratio - pixels / 2.0))
    return (first + pixels / 2.0) / ratio


class PageInner(QWidget):
    """Gruppen in einer Zeile; zeichnet die Trennlinien zwischen den Gruppen."""

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.groups = []

    def paintEvent(self, _event):  # noqa: N802 (Qt)
        if len(self.groups) < 2:
            return
        painter = QPainter(self)
        ratio = self.devicePixelRatioF()
        pixels = divider_pixels(ratio)
        pen = QPen(theme.color("gdiv"))
        pen.setWidthF(pixels / ratio)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        # Fast über die volle Höhe der Gruppe (Befehle und Beschriftung)
        top = theme.PAGE_TOP + 1
        bottom = self.height() - 3
        for g in self.groups[1:]:
            if g.isHidden():
                continue
            x = divider_x(g.geometry().left(), theme.GROUP_GAP, ratio, pixels)
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        painter.end()


class TabPage(QScrollArea):
    def __init__(self, tab, ctx, parent=None):
        QScrollArea.__init__(self, parent)
        self.tab = tab
        self.setObjectName("ribbon_page_" + tab.id)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = PageInner(self)
        lay = QHBoxLayout(inner)
        lay.setContentsMargins(2, theme.PAGE_TOP, 2, 0)
        lay.setSpacing(theme.GROUP_GAP)
        self.groups = []
        ctx.begin_tab(tab.id)  # KeyTip-Ziele dieses Tabs in Aufbaureihenfolge
        for group in tab.groups:
            gw = GroupWidget(group, ctx, inner)
            self.groups.append(gw)
            lay.addWidget(gw, 0, Qt.AlignmentFlag.AlignTop)
        lay.addStretch(1)
        ctx.end_tab()
        inner.groups = self.groups
        self.setWidget(inner)
        self.inner = inner
        self.last_layout_ms = None   # Messpunkt: Umstellen nach Größenänderung
        self._width = None
        if any(v.kind == "gallery" for g in self.groups for v in g.views):
            size = builtin_commands.gallery_size(ctx.env)
            ctx.hub.connect(size, "changed", self.gallery_size_changed)

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
