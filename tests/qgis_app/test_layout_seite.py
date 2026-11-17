"""Tab Layout im Layout-Fenster: Seitenbefehle, „Zu Seite“, Seitenbefehle im Bericht.

Echte Layouts, das Fenster ist die Attrappe aus ``test_designer_ribbon``.
"""
import pytest
from qgis.core import Qgis, QgsLayoutItemPage, QgsLayoutSize, QgsPrintLayout, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QComboBox, QToolButton, QWidget

from qgis_ribbon.qgis_integration import layout_ops

from test_designer_ribbon import (FakeDesigner, designer, designer_iface, registry, report, ribbons,  # noqa: F401
                                  settle)


def a4(pages=1):
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    for _ in range(pages - 1):
        page = QgsLayoutItemPage(layout)
        page.setPageSize("A4", QgsLayoutItemPage.Orientation.Portrait)
        layout.pageCollection().addPage(page)
    layout.undoStack().stack().clear()
    return layout


def size_of(page):
    size = page.pageSize()
    return round(size.width()), round(size.height())


def index(layout):
    return layout.undoStack().stack().index()


@pytest.fixture
def paged():
    d = FakeDesigner(master=a4(pages=1))
    d.window().show()
    settle()
    yield d
    d.window().close()
    d.window().deleteLater()
    settle()


def open_ribbon(ribbons, designer):  # noqa: F811
    ribbons.start()
    ribbons.opened(designer)
    settle()
    return ribbons.ribbons[designer.window()]


# layout_ops

def test_orientation_swaps_width_and_height_as_one_step():
    layout = a4()
    page = layout.pageCollection().page(0)
    before = size_of(page)
    layout_ops.toggle_orientation(layout, page)
    assert size_of(page) == (before[1], before[0])
    assert index(layout) == 1
    layout.undoStack().stack().undo()
    assert size_of(page) == before


def test_delete_page_is_one_step_and_keeps_the_last_page():
    layout = a4(pages=2)
    pages = layout.pageCollection()
    assert layout_ops.delete_page(layout, pages.page(1))
    assert pages.pageCount() == 1 and index(layout) == 1
    assert not layout_ops.delete_page(layout, pages.page(0))
    assert pages.pageCount() == 1 and index(layout) == 1
    layout.undoStack().stack().undo()
    assert pages.pageCount() == 2


def test_margin_guides_sit_at_the_margin_and_are_not_doubled():
    layout = a4()
    page = layout.pageCollection().page(0)
    width, height = size_of(page)
    assert layout_ops.add_margin_guides(layout, page, 10) == 4
    guides = layout.guides().guidesOnPage(0)
    found = sorted((g.orientation() == Qt.Orientation.Horizontal, round(g.layoutPosition())) for g in guides)
    assert found == sorted([(True, 10), (True, height - 10), (False, 10), (False, width - 10)])
    assert index(layout) == 1
    assert layout_ops.add_margin_guides(layout, page, 10) == 0 and index(layout) == 1
    assert layout_ops.add_margin_guides(layout, page, 5) == 4
    layout.undoStack().stack().undo()
    layout.undoStack().stack().undo()
    assert layout.guides().guidesOnPage(0) == []


def test_margin_guides_on_the_second_page_only():
    layout = a4(pages=2)
    layout_ops.add_margin_guides(layout, layout.pageCollection().page(1), 20)
    assert len(layout.guides().guidesOnPage(1)) == 4 and layout.guides().guidesOnPage(0) == []


def test_page_labels():
    assert layout_ops.page_labels(a4(pages=3)) == ["Seite 1 von 3", "Seite 2 von 3", "Seite 3 von 3"]


# Im Ribbon

def test_new_page_commands_resolve_and_act_on_the_shown_page(ribbons, paged):  # noqa: F811
    ribbon = open_ribbon(ribbons, paged)
    layout = paged.master()
    for cid in ("seite_ausrichtung", "seite_loeschen", "seite_raender", "zu_seite"):
        assert ribbon.resolver.resolve(ribbons.base.commands[cid]).available, cid
    page = layout.pageCollection().page(0)
    before = size_of(page)
    ribbon.widget.findChild(QToolButton, "ribbon_btn_seite_ausrichtung").click()
    assert size_of(page) == (before[1], before[0])


def test_delete_and_go_to_page_need_two_pages(ribbons, paged):  # noqa: F811
    ribbon = open_ribbon(ribbons, paged)
    layout = paged.master()
    delete = ribbon.widget.findChild(QToolButton, "ribbon_btn_seite_loeschen")
    go = ribbon.widget.findChild(QWidget, "ribbon_control_zu_seite")
    assert not delete.isEnabled() and not go.isEnabled()
    page = QgsLayoutItemPage(layout)
    page.setPageSize("A4", QgsLayoutItemPage.Orientation.Portrait)
    layout.pageCollection().addPage(page)
    settle()
    assert delete.isEnabled() and go.isEnabled()
    combo = go.findChild(QComboBox)
    assert [combo.itemText(n) for n in range(combo.count())] == ["Seite 1 von 2", "Seite 2 von 2"]
    combo.activated.emit(1)
    assert paged.view().fitted[0] == page.sceneBoundingRect() and paged.view().zoom_signals == 1
    paged.view().page = 1
    paged.view().pageChanged.emit(1)
    settle()
    assert combo.currentIndex() == 1
    delete.click()
    settle()
    assert layout.pageCollection().pageCount() == 1
    assert not delete.isEnabled() and not go.isEnabled()


def test_margin_menu_places_guides_and_shows_them(ribbons, paged):  # noqa: F811
    ribbon = open_ribbon(ribbons, paged)
    show = paged.window().findChild(QAction, "mActionShowGuides")
    show.setCheckable(True)
    show.setChecked(False)
    menu = layout_ops.margin_guides_menu(ribbon.env, ribbons.base.commands["seite_raender"])
    menu.aboutToShow.emit()
    entries = [a.text() for a in menu.actions()]
    assert entries == ["5 mm Rand", "10 mm Rand", "15 mm Rand", "20 mm Rand"]
    menu.actions()[1].trigger()
    assert len(paged.master().guides().guidesOnPage(0)) == 4 and show.isChecked()


def test_page_commands_are_gray_in_a_report_without_section(ribbons, report):  # noqa: F811
    ribbon = open_ribbon(ribbons, report)
    ribbon.widget.select_tab("layout")
    settle()
    for cid in ("seiten_hinzufuegen", "seitengroesse", "seite_ausrichtung", "seite_raender", "seite_loeschen"):
        assert not ribbon.widget.findChild(QToolButton, "ribbon_btn_" + cid).isEnabled(), cid
    assert not ribbon.widget.findChild(QWidget, "ribbon_control_zu_seite").isEnabled()
    # Abschnitt gewählt: Seitenbefehle wieder bedienbar
    report.view().layoutSet.emit(a4())
    settle()
    ribbon = ribbons.ribbons[report.window()]
    ribbon.widget.select_tab("layout")
    settle()
    for cid in ("seiten_hinzufuegen", "seitengroesse", "seite_ausrichtung", "seite_raender"):
        assert ribbon.widget.findChild(QToolButton, "ribbon_btn_" + cid).isEnabled(), cid


def test_quick_access_offers_pdf_export(ribbons, paged):  # noqa: F811
    ribbon = open_ribbon(ribbons, paged)
    assert ribbon.widget.findChild(QToolButton, "ribbon_qat_export_pdf") is not None


def test_units_of_the_guides_follow_the_layout():
    layout = a4()
    page = layout.pageCollection().page(0)
    layout_ops.add_margin_guides(layout, page, 10)
    guide = layout.guides().guidesOnPage(0)[0]
    assert guide.position().units() == layout.units()
    assert layout.units() == Qgis.LayoutUnit.Millimeters
    assert QgsLayoutSize(1, 1).units() == Qgis.LayoutUnit.Millimeters
