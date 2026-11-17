"""Einfügen mit Voreinstellungen: Nordpfeil, Maßstabsleiste, Karte, Grundausstattung.

Echte Layouts; die Ribbon-Tests nutzen die Attrappe des Fensters aus ``test_designer_ribbon``.
"""
import os

import pytest
from qgis.core import (QgsLayoutItem, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemPage,
                       QgsLayoutItemPicture, QgsLayoutItemScaleBar, QgsPrintLayout, QgsProject, QgsRectangle,
                       QgsReferencedRectangle, QgsBookmark)
from qgis.PyQt.QtWidgets import QMenu, QToolButton, QWidget

from qgis_ribbon.qgis_integration import layout_insert, layout_ops

from test_designer_ribbon import (FakeDesigner, designer, designer_iface, registry, report, ribbons,  # noqa: F401
                                  settle)


def blank(size="A4", orientation=QgsLayoutItemPage.Orientation.Landscape):
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    layout.pageCollection().page(0).setPageSize(size, orientation)
    layout.undoStack().stack().clear()
    return layout


def with_map(layout):
    item = layout_insert.new_map(layout, layout_insert.page_rect(layout, 0).adjusted(20, 30, -60, -40),
                                 QgsRectangle(0, 0, 1000, 1000), QgsProject.instance().crs())
    layout.addLayoutItem(item)
    layout.undoStack().stack().clear()
    return item


@pytest.fixture
def paged():
    d = FakeDesigner(master=blank())
    d.window().show()
    settle()
    yield d
    d.window().close()
    d.window().deleteLater()
    settle()


def kinds(layout, kind):
    return [i for i in layout.items() if isinstance(i, kind)]


def index(layout):
    return layout.undoStack().stack().index()


def inside(item, rect, tolerance=0.01):
    r = layout_insert.item_rect(item)
    return (r.left() >= rect.left() - tolerance and r.top() >= rect.top() - tolerance
            and r.right() <= rect.right() + tolerance and r.bottom() <= rect.bottom() + tolerance)


# Bausteine

def test_north_arrows_come_from_the_svg_folders():
    arrows = layout_insert.north_arrows()
    assert len(arrows) >= 11
    assert all(os.path.basename(p).startswith("NorthArrow_") and os.path.isfile(p) for p in arrows)


def test_north_arrow_is_linked_sized_and_top_right_in_the_map():
    layout = blank()
    map_item = with_map(layout)
    pic = layout_insert.insert_north_arrow(layout, layout_insert.north_arrows()[2])
    assert pic.linkedMap() is map_item
    assert pic.northMode() == QgsLayoutItemPicture.NorthMode.GridNorth
    assert round(pic.rect().width()) == 20 and round(pic.rect().height()) == 20
    m, r = layout_insert.item_rect(map_item), layout_insert.item_rect(pic)
    assert round(m.right() - r.right()) == 5 and round(r.top() - m.top()) == 5
    assert layout.selectedLayoutItems() == [pic]
    assert index(layout) == 1
    layout.undoStack().stack().undo()
    assert kinds(layout, QgsLayoutItemPicture) == []


def test_scale_bar_has_the_style_and_sits_below_the_map():
    layout = blank()
    map_item = with_map(layout)
    for n, (style, _name) in enumerate(layout_ops.scalebar_styles(), 1):
        bar = layout_insert.insert_scale_bar(layout, style)
        assert bar.style() == style and bar.linkedMap() is map_item
        m, r = layout_insert.item_rect(map_item), layout_insert.item_rect(bar)
        assert round(r.left()) == round(m.left()) and r.top() > m.bottom()
        assert index(layout) == n
    layout.undoStack().stack().undo()
    assert len(kinds(layout, QgsLayoutItemScaleBar)) == len(layout_ops.scalebar_styles()) - 1


def test_scale_bar_goes_into_the_map_without_room_below():
    layout = blank()
    map_item = with_map(layout)
    map_item.attemptResize(map_item.sizeWithUnits().__class__(150, 190, layout.units()))
    bar = layout_insert.insert_scale_bar(layout, "Single Box")
    assert inside(bar, layout_insert.item_rect(map_item))


def test_without_a_map_nothing_is_inserted():
    layout = blank()
    assert layout_insert.insert_north_arrow(layout, layout_insert.north_arrows()[0]) is None
    assert layout_insert.insert_scale_bar(layout, "Single Box") is None
    assert index(layout) == 0


def test_reference_map_comes_first():
    layout = blank()
    first = with_map(layout)
    second = with_map(layout)
    assert layout_insert.reference_map(layout) in (first, second)
    layout.setReferenceMap(second)
    assert layout_insert.reference_map(layout) is second


def test_map_fills_the_empty_page_then_half_a_page():
    layout = blank()
    page = layout_insert.page_rect(layout, 0)
    first = layout_insert.insert_map(layout, 0, QgsRectangle(0, 0, 100, 100), QgsProject.instance().crs())
    r = layout_insert.item_rect(first)
    assert round(r.left() - page.left()) == 10 and round(page.bottom() - r.bottom()) == 10
    second = layout_insert.insert_map(layout, 0, QgsRectangle(0, 0, 100, 100), QgsProject.instance().crs())
    assert round(second.rect().width()) == round(page.width() / 2)
    assert index(layout) == 2 and layout.selectedLayoutItems() == [second]
    layout.undoStack().stack().undo()
    assert kinds(layout, QgsLayoutItemMap) == [first]


def test_map_follows_a_theme():
    layout = blank()
    item = layout_insert.insert_map(layout, 0, QgsRectangle(0, 0, 100, 100), QgsProject.instance().crs(), "Thema")
    assert item.followVisibilityPreset() and item.followVisibilityPresetName() == "Thema"


@pytest.mark.parametrize("size, orientation", [
    ("A4", QgsLayoutItemPage.Orientation.Portrait),
    ("A4", QgsLayoutItemPage.Orientation.Landscape),
    ("A3", QgsLayoutItemPage.Orientation.Landscape),
])
def test_basic_kit_on_an_empty_page(size, orientation, designer_iface):  # noqa: F811
    layout = blank(size, orientation)
    new = layout_insert.basic_kit(layout, 0, designer_iface.mapCanvas())
    assert len(new) == 5 and index(layout) == 1
    page = layout_insert.page_rect(layout, 0)
    for item in new:
        assert inside(item, page), type(item).__name__
    map_item = kinds(layout, QgsLayoutItemMap)[0]
    assert kinds(layout, QgsLayoutItemLegend)[0].linkedMap() is map_item
    assert kinds(layout, QgsLayoutItemScaleBar)[0].linkedMap() is map_item
    assert kinds(layout, QgsLayoutItemPicture)[0].linkedMap() is map_item
    assert os.path.basename(kinds(layout, QgsLayoutItemPicture)[0].picturePath()) == "NorthArrow_02.svg"
    assert not kinds(layout, QgsLayoutItemLegend)[0].resizeToContents()   # fest, nie über die Seite hinaus
    assert kinds(layout, QgsLayoutItemLabel)[0].text()
    layout.undoStack().stack().undo()
    assert [i for i in layout.items() if isinstance(i, QgsLayoutItem) and not isinstance(i, QgsLayoutItemPage)] == []


def test_basic_kit_keeps_the_map_and_adds_only_what_is_missing(designer_iface):  # noqa: F811
    layout = blank()
    map_item = with_map(layout)
    new = layout_insert.basic_kit(layout, 0, designer_iface.mapCanvas())
    assert map_item not in new and len(new) == 4
    assert kinds(layout, QgsLayoutItemMap) == [map_item]
    assert layout_insert.basic_kit(layout, 0, designer_iface.mapCanvas()) == []
    assert index(layout) == 1


def test_title_comes_from_the_layout_name(designer_iface):  # noqa: F811
    layout = blank()
    layout.setName("Stadtplan")
    layout_insert.basic_kit(layout, 0, designer_iface.mapCanvas())
    assert kinds(layout, QgsLayoutItemLabel)[0].text() == "Stadtplan"


# Galerien

def test_galleries_offer_entries_and_gray_without_a_map(ribbons, paged):  # noqa: F811
    ribbons.start()
    ribbons.opened(paged)
    settle()
    ribbon = ribbons.ribbons[paged.window()]
    env = ribbon.env
    arrows = layout_insert.north_arrow_gallery(env, None)()
    bars = layout_insert.scale_bar_gallery(env, None)()
    assert len(arrows) == len(layout_insert.north_arrows()) and len(bars) == len(layout_ops.scalebar_styles())
    assert all(e.callback is None and e.tooltip == layout_insert.NO_MAP for e in arrows + bars)
    assert all(e.motif in layout_insert.SCALEBAR_MOTIFS.values() for e in bars)
    assert all(not e.icon.isNull() for e in arrows)
    maps = layout_insert.map_gallery(env, None)()
    maps[0].callback()
    layout = paged.master()
    assert len(kinds(layout, QgsLayoutItemMap)) == 1
    arrows = layout_insert.north_arrow_gallery(env, None)()
    arrows[0].callback()
    layout_insert.scale_bar_gallery(env, None)()[1].callback()
    assert len(kinds(layout, QgsLayoutItemPicture)) == 1
    assert kinds(layout, QgsLayoutItemScaleBar)[0].style() == layout_ops.scalebar_styles()[1][0]


def test_map_gallery_lists_themes_and_bookmarks(ribbons, paged):  # noqa: F811
    project = QgsProject.instance()
    bookmark = QgsBookmark()
    bookmark.setName("Altstadt")
    bookmark.setExtent(QgsReferencedRectangle(QgsRectangle(10, 10, 20, 20), project.crs()))
    bid = project.bookmarkManager().addBookmark(bookmark)[0]
    try:
        ribbons.start()
        ribbons.opened(paged)
        settle()
        env = ribbons.ribbons[paged.window()].env
        labels = [e.label for e in layout_insert.map_gallery(env, None)()]
        assert labels[0] == "Aktuelle Kartenansicht" and "Altstadt" in labels
    finally:
        project.bookmarkManager().removeBookmark(bid)


def test_insert_tab_shows_basic_kit_and_gallery_menus(ribbons, paged):  # noqa: F811
    ribbons.start()
    ribbons.opened(paged)
    settle()
    ribbon = ribbons.ribbons[paged.window()]
    ribbon.widget.select_tab("einfuegen")
    settle()
    kit = ribbon.widget.findChild(QToolButton, "ribbon_btn_grundausstattung")
    assert kit is not None and kit.isEnabled()
    for split in ("element_karte", "element_massstab", "element_nordpfeil"):
        btn = ribbon.widget.findChild(QWidget, "ribbon_split_" + split)
        assert btn is not None, split
        menu = btn.menu if not isinstance(btn, QToolButton) else btn.menu()
        assert isinstance(menu, QMenu)
        menu.aboutToShow.emit()
        texts = [a.text() for a in menu.actions() if a.text()]
        assert texts[0].endswith("aufziehen"), texts
    kit.click()
    settle()
    assert len(kinds(paged.master(), QgsLayoutItemMap)) == 1


def test_gallery_entries_are_gray_in_a_report_without_section(ribbons, report):  # noqa: F811
    ribbons.start()
    ribbons.opened(report)
    settle()
    env = ribbons.ribbons[report.window()].env
    for factory in (layout_insert.north_arrow_gallery, layout_insert.scale_bar_gallery, layout_insert.map_gallery):
        entries = factory(env, None)()
        assert entries and all(e.callback is None for e in entries)
