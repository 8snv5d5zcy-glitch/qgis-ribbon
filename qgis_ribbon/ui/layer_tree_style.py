"""Optionsfelder statt Kontrollkästchen für Layer in exklusiven Gruppen.

In einer exklusiven Gruppe (QGIS: „Mutually Exclusive Group“) kann nur ein
Eintrag sichtbar sein. Der Layerbaum zeigt dann Kreise statt Haken, damit man
das im Inhalt sieht. QGIS setzt die Exklusivität selbst durch; hier wird nur
anders gezeichnet.

Umsetzung: ``ExclusiveRadioStyle`` ist ein Stil, der jeden Aufruf an den
bisherigen Stil der Layerliste weiterreicht (in QGIS ein eigener Proxy-Stil
für die Layer-Indikatoren). Nur zwei Stellen weichen ab:

- ``drawControl(CE_ItemViewItem)`` eines Eintrags in einer exklusiven Gruppe:
  der bisherige Stil zeichnet den Eintrag, danach übermalt dieser Stil das
  Feld des Kontrollkästchens mit dem Hintergrund und zeichnet das Optionsfeld.
- ``drawPrimitive(PE_IndicatorItemViewItemCheck)``: Weg über ein Stylesheet
  (Qt zeichnet Einträge mit Stylesheet-Regeln selbst und fragt nur das
  Kontrollkästchen beim Stil an).

Der bisherige Stil wird nicht umgehängt (``QProxyStyle`` würde ihn übernehmen
und auf sich umlenken, das ließe sich nicht zurücknehmen), sondern nur
aufgerufen. ``LayerTreeRadios.restore`` setzt ihn wieder ein. Ein Stylesheet
am Hauptfenster (Gesamtbild, Hell/Dunkel) legt Qt selbst über den gesetzten
Stil; der Stil bleibt dabei erhalten.

Neu zeichnen: Wechsel über den Ribbon zeichnen selbst neu; für das
Kontextmenü der Layerliste hängt sich ``LayerTreeRadios`` an dessen Signal
``contextMenuAboutToShow`` und zeichnet nach einem gewählten Eintrag neu.
"""

from qgis.PyQt.QtCore import QRect, Qt, QTimer
from qgis.PyQt.QtWidgets import (QCommonStyle, QStyle, QStyleOptionButton,
                                 QStyleOptionViewItem)


def _view_item(option):
    return option if isinstance(option, QStyleOptionViewItem) else None


class ExclusiveRadioStyle(QCommonStyle):
    """Reicht alles an ``base`` weiter; Einträge exklusiver Gruppen bekommen Kreise."""

    def __init__(self, base, is_exclusive):
        QCommonStyle.__init__(self)
        self.base = base
        self.is_exclusive = is_exclusive     # QModelIndex -> bool

    def _exclusive(self, option):
        opt = _view_item(option)
        if opt is None or not opt.index.isValid():
            return False
        if not opt.features & QStyleOptionViewItem.HasCheckIndicator:
            return False
        try:
            return bool(self.is_exclusive(opt.index))
        except Exception:  # noqa: BLE001 - Zeichnen darf nie scheitern
            return False

    def radio_option(self, option, rect):
        radio = QStyleOptionButton()
        radio.rect = QRect(rect)
        radio.palette = option.palette
        radio.direction = option.direction
        radio.fontMetrics = option.fontMetrics
        state = option.state & (QStyle.State_Enabled | QStyle.State_Active)
        if option.checkState == Qt.Unchecked:
            state |= QStyle.State_Off
        else:
            state |= QStyle.State_On
        radio.state = state
        return radio

    def draw_radio(self, option, rect, painter, widget):
        self.base.drawPrimitive(QStyle.PE_IndicatorRadioButton,
                                self.radio_option(option, rect), painter, widget)

    # Abweichungen
    def drawControl(self, element, option, painter, widget=None):  # noqa: N802 (Qt)
        if element != QStyle.CE_ItemViewItem or not self._exclusive(option):
            self.base.drawControl(element, option, painter, widget)
            return
        self.base.drawControl(element, option, painter, widget)
        # Das Kontrollkästchen übermalen (Hintergrund und Auswahl wie der Eintrag), dann der Kreis.
        # Ein Ausschneiden vorher hilft nicht: Qt setzt beim Zeichnen des Eintrags eine eigene Maske.
        check = self.base.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, widget)
        painter.save()
        painter.setClipRect(check)
        if option.backgroundBrush.style() != Qt.NoBrush:
            painter.fillRect(check, option.backgroundBrush)
        elif option.features & QStyleOptionViewItem.Alternate:
            painter.fillRect(check, option.palette.alternateBase())
        else:
            painter.fillRect(check, option.palette.base())
        self.base.drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter, widget)
        painter.restore()
        self.draw_radio(option, check, painter, widget)

    def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802 (Qt)
        if element == QStyle.PE_IndicatorItemViewItemCheck and self._exclusive(option):
            self.draw_radio(option, option.rect, painter, widget)
            return
        self.base.drawPrimitive(element, option, painter, widget)

    # Alles andere unverändert
    def drawComplexControl(self, control, option, painter, widget=None):  # noqa: N802 (Qt)
        self.base.drawComplexControl(control, option, painter, widget)

    def subElementRect(self, element, option, widget=None):  # noqa: N802 (Qt)
        return self.base.subElementRect(element, option, widget)

    def subControlRect(self, control, option, sub, widget=None):  # noqa: N802 (Qt)
        return self.base.subControlRect(control, option, sub, widget)

    def hitTestComplexControl(self, control, option, pos, widget=None):  # noqa: N802 (Qt)
        return self.base.hitTestComplexControl(control, option, pos, widget)

    def sizeFromContents(self, kind, option, size, widget=None):  # noqa: N802 (Qt)
        return self.base.sizeFromContents(kind, option, size, widget)

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802 (Qt)
        return self.base.pixelMetric(metric, option, widget)

    def styleHint(self, hint, option=None, widget=None, data=None):  # noqa: N802 (Qt)
        return self.base.styleHint(hint, option, widget, data)

    def standardIcon(self, icon, option=None, widget=None):  # noqa: N802 (Qt)
        return self.base.standardIcon(icon, option, widget)

    def standardPixmap(self, pixmap, option=None, widget=None):  # noqa: N802 (Qt)
        return self.base.standardPixmap(pixmap, option, widget)

    def generatedIconPixmap(self, mode, pixmap, option):  # noqa: N802 (Qt)
        return self.base.generatedIconPixmap(mode, pixmap, option)

    def standardPalette(self):  # noqa: N802 (Qt)
        return self.base.standardPalette()

    def layoutSpacing(self, c1, c2, orientation, option=None, widget=None):  # noqa: N802 (Qt)
        return self.base.layoutSpacing(c1, c2, orientation, option, widget)

    def polish(self, target):
        return self.base.polish(target)

    def unpolish(self, target):
        return self.base.unpolish(target)

    def itemPixmapRect(self, rect, alignment, pixmap):  # noqa: N802 (Qt)
        return self.base.itemPixmapRect(rect, alignment, pixmap)

    def itemTextRect(self, metrics, rect, alignment, enabled, text):  # noqa: N802 (Qt)
        return self.base.itemTextRect(metrics, rect, alignment, enabled, text)

    def drawItemPixmap(self, painter, rect, alignment, pixmap):  # noqa: N802 (Qt)
        self.base.drawItemPixmap(painter, rect, alignment, pixmap)

    def drawItemText(self, painter, rect, flags, palette, enabled, text,  # noqa: N802 (Qt)
                     role=None):
        if role is None:
            self.base.drawItemText(painter, rect, flags, palette, enabled, text)
        else:
            self.base.drawItemText(painter, rect, flags, palette, enabled, text, role)


def own_style(view):
    """Der Stil, den die Ansicht selbst gesetzt hat (ohne Stylesheet-Hülle), sonst None."""
    style = view.style()
    if style.metaObject().className() != "QStyleSheetStyle":
        return style
    # Mit Stylesheet liefert style() Qts Hülle; der eigene Stil ist ein Kind der Ansicht
    # (QGIS hängt seinen Stil an die Layerliste, dieser Stil hängt sich dahinter)
    own = [c for c in view.findChildren(QStyle, options=Qt.FindDirectChildrenOnly)
           if c.metaObject().className() != "QStyleSheetStyle"]
    radios = [c for c in own if isinstance(c, ExclusiveRadioStyle)]
    if radios:
        return radios[-1]
    return own[0] if own else None


def layer_tree_exclusive(view):
    """Prüffunktion für Indizes der Layerliste: liegt der Eintrag in einer exklusiven Gruppe?"""
    from qgis.core import QgsLayerTreeGroup

    def check(index):
        node = view.index2node(index)
        parent = node.parent() if node is not None else None
        return isinstance(parent, QgsLayerTreeGroup) and parent.isMutuallyExclusive()
    return check


class LayerTreeRadios(object):
    """Legt den Stil über eine Ansicht und nimmt ihn exakt zurück."""

    def __init__(self, view, is_exclusive, hub=None):
        self.view = view
        self.is_exclusive = is_exclusive
        self.hub = hub
        self.previous = None       # eigener Stil der Ansicht vorher (None: Stil der Anwendung)
        self.had_own = False
        self.style = None

    def install(self):
        if self.style is not None or self.view is None:
            return
        self.previous = own_style(self.view)
        self.had_own = self.previous is not None
        base = self.previous if self.had_own else self.view.style()
        self.style = ExclusiveRadioStyle(base, self.is_exclusive)
        self.style.setParent(self.view)    # wie der QGIS-Stil: hinter der Stylesheet-Hülle auffindbar
        self.view.setStyle(self.style)
        if self.hub is not None and hasattr(self.view, "contextMenuAboutToShow"):
            self.hub.connect(self.view, "contextMenuAboutToShow", self._watch_menu)
        self.update()

    def _watch_menu(self, menu):
        # Das Menü entsteht bei jedem Öffnen neu und stirbt danach; die Verbindung mit ihm
        menu.triggered.connect(lambda _action: QTimer.singleShot(0, self.update))

    def update(self):
        try:
            self.view.viewport().update()
        except RuntimeError:
            pass

    def restore(self):
        if self.style is None:
            return
        try:
            self.view.setStyle(self.previous if self.had_own else None)
            self.view.viewport().update()
        except RuntimeError:
            pass   # Ansicht schon gelöscht (Beenden)
        # Erst nach der Ereignisschleife freigeben: Qts Stylesheet-Hülle des alten Stils
        # wird verzögert abgebaut und darf bis dahin noch auf ihn zeigen.
        retired = self.style
        try:
            retired.setParent(None)
        except RuntimeError:
            pass
        QTimer.singleShot(0, lambda: retired)
        self.style = None
        self.previous = None
