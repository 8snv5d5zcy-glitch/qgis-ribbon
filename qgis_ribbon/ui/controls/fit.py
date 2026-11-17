"""Breite von Eingabefeldern aus der Schrift (Maßstab, Zahl mit Einheit, Auswahl).

Feste Pixelbreiten passen nur zu einer Schrift: unter Windows mit 125 % oder in
QGIS 4 (breitere Schrift) zeigte ein Maßstabsfeld von „1:5000“ nur „0“, ein
Zahlenfeld im Layout-Fenster schnitt „mm“ ab. Hier wird die Breite für einen
Mustertext („1:1.000.000“, „9999,99 mm“, längster Eintrag) samt Rahmen,
Pfeilen und Knöpfen des Felds über den Stil berechnet. Die Felder werden nie
schmaler als ihre bisherige feste Breite.
"""

from qgis.gui import QgsScaleWidget
from qgis.PyQt.QtCore import QLocale, QRect, QSize
from qgis.PyQt.QtWidgets import (QAbstractSpinBox, QComboBox, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox,
                                 QToolButton)

FIT_MAX = 320       # breiter wird ein Feld durch seinen Inhalt nicht
CLEAR_BUTTON = 18   # Löschknopf in Qgs-Feldern (Icon 16 px und Rand)
SAMPLE_NUMBER = 9999.99


def scale_sample():
    """Längster üblicher Maßstab in der Schreibweise des Gebietsschemas („1:1.000.000“)."""
    return "1:" + QLocale().toString(1000000)


def _spin_option(widget):
    opt = QStyleOptionSpinBox()
    opt.initFrom(widget)
    return opt


def _combo_option(widget):
    opt = QStyleOptionComboBox()
    opt.initFrom(widget)
    return opt


def text_width(widget, text):
    widget.ensurePolished()
    return widget.fontMetrics().horizontalAdvance(text)


def spin_width(spin, sample):
    """Breite eines Zahlenfelds für ``sample`` (mit Präfix und Einheit), mit Pfeilen und Rahmen."""
    fm = spin.fontMetrics()
    size = QSize(text_width(spin, sample) + 8, fm.height())   # Cursor und Innenrand
    width = spin.style().sizeFromContents(QStyle.ContentsType.CT_SpinBox, _spin_option(spin), size, spin).width()
    if getattr(spin, "showClearButton", None) is not None and spin.showClearButton():
        width += CLEAR_BUTTON
    return width


def combo_width(combo, sample=None):
    """Breite einer Auswahl für ihren längsten Eintrag (oder ``sample``), mit Icon, Pfeil und Rahmen."""
    combo.ensurePolished()
    if sample is None:
        return combo.sizeHint().width()   # Qt rechnet mit dem längsten Eintrag samt Icon
    fm = combo.fontMetrics()
    extra = combo.iconSize().width() + 4 if any(not combo.itemIcon(i).isNull() for i in range(combo.count())) else 0
    text = text_width(combo, sample) + extra + 4
    size = QSize(text, fm.height())
    width = combo.style().sizeFromContents(QStyle.ContentsType.CT_ComboBox, _combo_option(combo), size, combo).width()
    if combo.isEditable():
        # Platz neben dem Textfeld (Pfeil, Rahmen) aus dem Stil: unter Fusion (Linux) größer, als
        # sizeFromContents annimmt; dazu Rahmen und Innenrand des Textfelds selbst
        opt = _combo_option(combo)
        opt.editable = True
        opt.rect = QRect(0, 0, 400, fm.height() + 8)
        edit = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt,
                                            QStyle.SubControl.SC_ComboBoxEditField, combo)
        width = max(width, text + 4 + opt.rect.width() - edit.width())
    return width


def longest_item(combo):
    texts = [combo.itemText(i) for i in range(combo.count())]
    fm = combo.fontMetrics()
    return max(texts, key=fm.horizontalAdvance) if texts else ""


def scale_width(widget):
    """Maßstabsfeld (QgsScaleWidget): Auswahl mit Löschknopf plus Knopf „aktueller Maßstab“."""
    combo = widget.findChild(QComboBox)
    width = combo_width(combo, scale_sample()) + CLEAR_BUTTON if combo is not None else 0
    if combo is not None:
        # Die Auswahl selbst bekommt die Mindestbreite: unter Fusion (Linux) verteilt das Feld seinen Platz
        # sonst anders und die Auswahl wird schmaler als berechnet
        combo.setMinimumWidth(width)
    for btn in widget.findChildren(QToolButton):
        if btn.parent() is widget and not btn.isHidden():
            width += btn.sizeHint().width() + widget.layout().spacing() if widget.layout() else 0
    return max(width, widget.minimumSizeHint().width())


def editor_width(editor, sample=None):
    """Breite, die ``editor`` für seinen Inhalt braucht, oder None (andere Felder).

    ``sample``: Mustertext; ohne: Maßstab, Zahl 9999,99 mit Präfix und Einheit
    bzw. der längste Eintrag einer Auswahl.
    """
    if isinstance(editor, QgsScaleWidget):
        return scale_width(editor)
    if isinstance(editor, QAbstractSpinBox) and hasattr(editor, "textFromValue"):
        if sample is None:
            value = min(editor.maximum(), SAMPLE_NUMBER)
            sample = editor.prefix() + editor.textFromValue(value) + editor.suffix()
        return spin_width(editor, sample)
    if isinstance(editor, QComboBox) and not editor.isEditable():
        return combo_width(editor, sample)
    return None
