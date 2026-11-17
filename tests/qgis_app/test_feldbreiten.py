"""Feldbreiten aus der Schrift: Maßstab, Zahl mit Einheit, Auswahl mit festen Einträgen."""
import pytest
from qgis.core import QgsApplication
from qgis.gui import QgsDoubleSpinBox, QgsScaleWidget
from qgis.PyQt.QtWidgets import QComboBox, QWidget

from qgis_ribbon.plugin import RibbonPlugin
from qgis_ribbon.ui.controls import fit


def settle():
    for _ in range(4):
        QgsApplication.processEvents()


@pytest.fixture
def plugin(fake_iface, settings):
    p = RibbonPlugin(fake_iface, settings=settings)
    p.initGui()
    settle()
    yield p
    p.unload()
    settle()


def text_fits(line_edit, text):
    """Der Text passt in das Eingabefeld (Rand des Felds abgezogen)."""
    return line_edit.width() - 2 >= line_edit.fontMetrics().horizontalAdvance(text)


def build_all(plugin):
    w = plugin.widget
    for i in range(len(plugin.ribbon.tabs)):
        w.ensure_built(i)
    return w


def test_scale_fields_show_a_long_scale(fake_iface, plugin, layers):
    fake_iface.set_active_layer(layers["vector"])
    settle()
    w = build_all(plugin)
    fields = w.findChildren(QgsScaleWidget)
    assert fields
    for field in fields:
        field.setScale(1000000)
        field.window().show()
        settle()
        combo = field.findChild(QComboBox)
        edit = combo.lineEdit()
        assert text_fits(edit, fit.scale_sample()), "%r" % dict(
            name=field.objectName(), combo=combo.width(), edit=edit.width(),
            advance=edit.fontMetrics().horizontalAdvance(fit.scale_sample()),
            text_width=fit.text_width(combo, fit.scale_sample()),
            combo_width=fit.combo_width(combo, fit.scale_sample()),
            scale_width=fit.scale_width(field), field=field.width(), field_min=field.minimumWidth(),
            combo_min=combo.minimumWidth(), margins=edit.textMargins().left() + edit.textMargins().right(),
            style=combo.style().objectName(),
            buttons=[(b.width(), b.sizeHint().width()) for b in field.children()
                     if b.isWidgetType() and b is not combo])


def test_spin_with_unit_fits_its_largest_value():
    host = QWidget()
    spin = QgsDoubleSpinBox(host)
    spin.setRange(-1, 100000)
    spin.setDecimals(2)
    spin.setSuffix(" mm")
    spin.setShowClearButton(False)
    spin.setFixedWidth(fit.spin_width(spin, spin.textFromValue(9999.99) + " mm"))
    spin.setValue(9999.99)
    host.show()
    settle()
    assert text_fits(spin.lineEdit(), spin.text())
    host.deleteLater()


def test_snapping_mode_shows_its_longest_item(fake_iface, plugin, layers):
    """Einrastmodus: „Erweiterte Konfiguration“ steht ganz im Feld."""
    w = build_all(plugin)
    control = w.findChild(QWidget, "ribbon_control_einrasten_modus")
    assert control is not None
    combo = control.editor
    text = fit.longest_item(combo)
    assert text and combo.width() >= min(fit.combo_width(combo), fit.FIT_MAX), (text, combo.width())
