"""Elemente im Layout-Fenster fertig eingestellt einfügen.

Galerien für Nordpfeil, Maßstabsleiste und Karte sowie die Grundausstattung (Titel,
Karte, Legende, Maßstabsleiste, Nordpfeil). Jedes Element wird vollständig
eingerichtet, bevor es ins Layout kommt: ``addLayoutItem`` legt dann genau einen
Rückgängig-Schritt an, mehrere Elemente fasst ein Makro zu einem zusammen. Danach
ist das neue Element gewählt, der passende Kontext-Tab erscheint.

Bezugskarte ist die Referenzkarte des Layouts (ohne eigene Wahl die größte Karte),
sonst die erste Karte. Positionen rechnen in Layout-Einheiten; Maße in Millimetern
werden umgerechnet.
"""

import glob
import os

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsLayoutItemLabel, QgsLayoutItemLegend,
                       QgsLayoutItemMap, QgsLayoutItemPicture, QgsLayoutItemScaleBar, QgsLayoutMeasurement,
                       QgsLayoutPoint, QgsLayoutSize, QgsProject)
from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap

from ..core.i18n import tr
from . import layer_ops, layout_ops
from .custom_commands import GalleryEntry

MM = Qgis.LayoutUnit.Millimeters
ARROW_MM = 20          # Nordpfeil 20 × 20 mm
INSET_MM = 5           # Abstand vom Kartenrand
GAP_MM = 5             # Abstand zwischen Elementen
PAGE_MARGIN_MM = 10    # Rand der Seite
TITLE_MM = 12          # Höhe des Titels
TITLE_PT = 20          # Schriftgröße des Titels
LEGEND_MIN_MM = 50     # Breite der Legendenspalte (quer) mindestens
SCALE_BAND_MM = 20     # Platz unter der Karte für die Maßstabsleiste
LEGEND_BAND_MM = 60    # Platz unter der Karte für Legende und Maßstab (hoch)
DEFAULT_ARROW = "northarrow_02.svg"
ICON_PX = 32

# Kontur-Motiv je Maßstabsstil (ID der Registry von QGIS)
SCALEBAR_MOTIFS = {
    "Single Box": "massstab_einfache_box", "Double Box": "massstab_doppelte_box",
    "Line Ticks Middle": "massstab_striche_mitte", "Line Ticks Down": "massstab_striche_unten",
    "Line Ticks Up": "massstab_striche_oben", "stepped": "massstab_stufen", "hollow": "massstab_hohl",
    "Numeric": "massstab_numerisch",
}

NO_MAP = tr("The layout has no map yet. Insert a map first.")
NO_LAYOUT = tr("Select a section with a layout first.")


def to_units(layout, value_mm):
    return layout.convertToLayoutUnits(QgsLayoutMeasurement(value_mm, MM))


def item_rect(item):
    """Rechteck des Elements in Layout-Einheiten (ohne Drehung)."""
    return QRectF(item.pos(), item.rect().size())


def page_rect(layout, index):
    page = layout.pageCollection().page(index)
    return QRectF(page.pos(), page.rect().size())


def place(item, rect):
    """Element auf ``rect`` (Layout-Einheiten, absolute Lage) setzen."""
    units = item.layout().units()
    item.attemptResize(QgsLayoutSize(rect.width(), rect.height(), units))
    item.attemptMove(QgsLayoutPoint(rect.x(), rect.y(), units))


def move_to(item, x, y):
    item.attemptMove(QgsLayoutPoint(x, y, item.layout().units()))


def on_page(layout, index, kind):
    return [i for i in layout.items() if isinstance(i, kind) and i.page() == index]


def reference_map(layout):
    if layout is None:
        return None
    ref = layout.referenceMap()
    if ref is not None:
        return ref
    maps = layout_ops.layout_maps(layout)
    return maps[0] if maps else None


def add_items(layout, items, text, select=True):
    """Fertige Elemente als ein Rückgängig-Schritt hinzufügen; das letzte wird gewählt."""
    stack = layout.undoStack()
    stack.beginMacro(text)
    try:
        for item in items:
            layout.addLayoutItem(item)
    finally:
        stack.endMacro()
    if select and items:
        layout.setSelectedItem(items[-1])
    return items


# Nordpfeil

def north_arrows():
    """Pfade der Nordpfeile aus den SVG-Ordnern von QGIS, je Dateiname einmal, sortiert."""
    found = {}
    for folder in QgsApplication.svgPaths():
        for path in glob.glob(os.path.join(folder, "arrows", "NorthArrow_*.svg")):
            found.setdefault(os.path.basename(path).lower(), path)
    return [found[key] for key in sorted(found)]


def default_north_arrow():
    """Klassischer Pfeil (wie QGIS beim Einfügen eines Nordpfeils), sonst der erste."""
    paths = north_arrows()
    for path in paths:
        if os.path.basename(path).lower() == DEFAULT_ARROW:
            return path
    return paths[0] if paths else ""


def arrow_icon(path):
    """Vorschau eines Nordpfeils mit dunkler Füllung (manche SVGs sind ohne Parameter weiß)."""
    black = QColor(Qt.GlobalColor.black)
    image, _fits = QgsApplication.svgCache().svgAsImage(path, ICON_PX, black, black, 0.2, 1.0)
    return QIcon(QPixmap.fromImage(image))


def north_arrow(layout, map_item, path):
    """Nordpfeil als Bild, mit der Karte verknüpft, 20 × 20 mm oben rechts in der Karte."""
    pic = QgsLayoutItemPicture(layout)
    pic.setPicturePath(path)
    pic.setLinkedMap(map_item)
    pic.setNorthMode(QgsLayoutItemPicture.NorthMode.GridNorth)
    size, inset = to_units(layout, ARROW_MM), to_units(layout, INSET_MM)
    r = item_rect(map_item)
    place(pic, QRectF(r.right() - inset - size, r.top() + inset, size, size))
    return pic


def insert_north_arrow(layout, path):
    map_item = reference_map(layout)
    if map_item is None:
        return None
    return add_items(layout, [north_arrow(layout, map_item, path)], tr("Insert north arrow"))[0]


# Maßstabsleiste

def scale_bar(layout, map_item, style):
    """Maßstabsleiste im Stil ``style``, mit der Karte verknüpft, in Standardgröße."""
    bar = QgsLayoutItemScaleBar(layout)
    bar.applyDefaultSettings()
    bar.setStyle(style)
    bar.setLinkedMap(map_item)
    bar.applyDefaultSize()
    bar.update()
    return bar


def place_below(item, map_item, page):
    """Unten links unter die Karte; reicht der Platz auf der Seite nicht, unten links in die Karte."""
    layout = item.layout()
    r, gap = item_rect(map_item), to_units(layout, GAP_MM)
    height = item.rect().height()
    if r.bottom() + gap + height <= page.bottom():
        move_to(item, r.left(), r.bottom() + gap)
    else:
        inset = to_units(layout, INSET_MM)
        move_to(item, r.left() + inset, r.bottom() - inset - height)


def insert_scale_bar(layout, style):
    map_item = reference_map(layout)
    if map_item is None:
        return None
    bar = scale_bar(layout, map_item, style)
    place_below(bar, map_item, page_rect(layout, max(map_item.page(), 0)))
    return add_items(layout, [bar], tr("Insert scale bar"))[0]


# Karte

def canvas_extent(canvas):
    settings = canvas.mapSettings()
    return settings.visibleExtent(), settings.destinationCrs()


def new_map(layout, rect, extent, crs, theme=None):
    """Kartenrahmen auf ``rect`` mit der Ausdehnung ``extent`` (in ``crs``); ``theme``: folgt dem Kartenthema."""
    item = QgsLayoutItemMap(layout)
    place(item, rect)
    target = item.crs()
    if crs.isValid() and target.isValid() and crs != target:
        extent = QgsCoordinateTransform(crs, target, QgsProject.instance()).transformBoundingBox(extent)
    if not extent.isEmpty():
        item.zoomToExtent(extent)
    if theme:
        item.setFollowVisibilityPreset(True)
        item.setFollowVisibilityPresetName(theme)
    return item


def map_rect(layout, index):
    """Ohne Karte auf der Seite füllt die neue Karte die Seite (10 mm Rand), sonst halbe Seite in der Mitte."""
    page = page_rect(layout, index)
    if not on_page(layout, index, QgsLayoutItemMap):
        m = to_units(layout, PAGE_MARGIN_MM)
        return page.adjusted(m, m, -m, -m)
    w, h = page.width() / 2, page.height() / 2
    return QRectF(page.center().x() - w / 2, page.center().y() - h / 2, w, h)


def insert_map(layout, index, extent, crs, theme=None):
    item = new_map(layout, map_rect(layout, index), extent, crs, theme)
    return add_items(layout, [item], tr("Insert map"))[0]


# Grundausstattung

def kit_title(layout):
    project = QgsProject.instance()
    return project.metadata().title() or project.title() or layout.name() or tr("Title")


def title_label(layout, rect, text):
    label = QgsLayoutItemLabel(layout)
    label.setText(text)
    fmt = label.textFormat()
    fmt.setSize(TITLE_PT)
    fmt.setSizeUnit(Qgis.RenderUnit.Points)
    label.setTextFormat(fmt)
    place(label, rect)
    return label


def legend(layout, map_item, rect=None, x=0.0, y=0.0):
    """Legende zur Karte. Mit ``rect`` fest in diesem Rechteck (bei vielen Layern abgeschnitten statt
    über die Seite hinaus), sonst an ``x``, ``y`` mit der Größe ihres Inhalts."""
    item = QgsLayoutItemLegend(layout)
    item.setLinkedMap(map_item)
    item.setTitle(tr("Legend"))
    if rect is not None:
        item.setResizeToContents(False)
        place(item, rect)
    else:
        item.adjustBoxSize()
        move_to(item, x, y)
    return item


def basic_kit(layout, index, canvas, arrow=None, style="Single Box"):
    """Was auf der Seite fehlt anlegen: Titel, Karte, Legende, Maßstabsleiste, Nordpfeil.

    Angeordnet nach Größe und Ausrichtung der Seite; eine vorhandene Karte bleibt und
    wird Bezug der übrigen Elemente. Ein Rückgängig-Schritt. Gibt die neuen Elemente zurück.
    """
    page = page_rect(layout, index)
    m, gap = to_units(layout, PAGE_MARGIN_MM), to_units(layout, GAP_MM)
    content = page.adjusted(m, m, -m, -m)
    landscape = page.width() >= page.height()
    top = content.top() + to_units(layout, TITLE_MM) + gap
    new = []
    maps = on_page(layout, index, QgsLayoutItemMap)
    ref = reference_map(layout)
    map_item = ref if ref in maps else (maps[0] if maps else None)
    created_map = map_item is None
    legend_w = max(to_units(layout, LEGEND_MIN_MM), content.width() * 0.22)
    if created_map:
        if landscape:
            rect = QRectF(content.left(), top, content.width() - legend_w - gap,
                          content.bottom() - to_units(layout, SCALE_BAND_MM) - top)
        else:
            rect = QRectF(content.left(), top, content.width(),
                          content.bottom() - to_units(layout, LEGEND_BAND_MM) - top)
        extent, crs = canvas_extent(canvas)
        map_item = new_map(layout, rect, extent, crs)
        new.append(map_item)
    r = item_rect(map_item)
    if not on_page(layout, index, QgsLayoutItemLabel):
        new.append(title_label(layout, QRectF(content.left(), content.top(), content.width(),
                                              to_units(layout, TITLE_MM)), kit_title(layout)))
    has_legend = bool(on_page(layout, index, QgsLayoutItemLegend))
    if not has_legend:
        if created_map and not landscape:
            band = QRectF(content.left(), r.bottom() + gap, content.width() / 2 - gap / 2,
                          content.bottom() - r.bottom() - gap)
            item = legend(layout, map_item, band)
            item.setColumnCount(2)      # das Band ist niedrig: lieber breit als abgeschnitten
            new.append(item)
        elif content.right() - r.right() - gap >= to_units(layout, 40):
            column = QRectF(r.right() + gap, r.top(), content.right() - r.right() - gap,
                            min(r.height(), content.bottom() - r.top()))
            new.append(legend(layout, map_item, column))
        else:
            inset = to_units(layout, INSET_MM)
            new.append(legend(layout, map_item, x=r.left() + inset, y=r.top() + inset))
    if not on_page(layout, index, QgsLayoutItemScaleBar):
        bar = scale_bar(layout, map_item, style)
        if created_map and not landscape and not has_legend:
            move_to(bar, content.center().x() + gap / 2, r.bottom() + gap)
        else:
            place_below(bar, map_item, page)
        new.append(bar)
    arrows = [p for p in on_page(layout, index, QgsLayoutItemPicture) if p.linkedMap() is not None]
    if not arrows:
        path = arrow or default_north_arrow()
        if path:
            new.append(north_arrow(layout, map_item, path))
    if new:
        add_items(layout, new, tr("Insert basic layout"), select=False)
        layout.deselectAll()
    return new


# Befehle und Galerien

def _target(env):
    """(Layout, Seitenindex) der gezeigten Seite oder (None, None)."""
    layout, page = layout_ops.current_page(env)
    if page is None:
        return None, None
    return layout, layout.pageCollection().pageNumber(page)


def _disable(entries, reason):
    for entry in entries:
        entry.callback = None
        entry.tooltip = reason
    return entries


def north_arrow_gallery(env, _command):
    def entries():
        layout, _index = _target(env)
        out = []
        for n, path in enumerate(north_arrows(), 1):
            def run(path=path):
                lay, _i = _target(env)
                if lay is not None:
                    insert_north_arrow(lay, path)

            out.append(GalleryEntry(tr("North Arrow %d") % n, run, icon=arrow_icon(path)))
        if layout is None:
            return _disable(out, NO_LAYOUT)
        return out if reference_map(layout) is not None else _disable(out, NO_MAP)

    return entries


def scale_bar_gallery(env, _command):
    def entries():
        layout, _index = _target(env)
        out = []
        for style, name in layout_ops.scalebar_styles():
            def run(style=style):
                lay, _i = _target(env)
                if lay is not None:
                    insert_scale_bar(lay, style)

            entry = GalleryEntry(name, run, motif=SCALEBAR_MOTIFS.get(style))
            out.append(entry)
        if layout is None:
            return _disable(out, NO_LAYOUT)
        return out if reference_map(layout) is not None else _disable(out, NO_MAP)

    return entries


def map_gallery(env, _command):
    def entries():
        layout, _index = _target(env)
        canvas = env.iface.mapCanvas()

        def insert(extent_of, theme=None):
            def run():
                lay, index = _target(env)
                if lay is not None:
                    extent, crs = extent_of()
                    insert_map(lay, index, extent, crs, theme)

            return run

        out = [GalleryEntry(tr("Current Map View"), insert(lambda: canvas_extent(canvas)),
                            tooltip=tr("New map with the extent of the main map."))]
        for theme in QgsProject.instance().mapThemeCollection().mapThemes():
            out.append(GalleryEntry(theme, insert(lambda: canvas_extent(canvas), theme),
                                    tooltip=tr("New map that follows the map theme."), section=tr("Map Themes")))
        for section, bookmark in layer_ops.bookmarks():
            out.append(GalleryEntry(bookmark.name(), insert(lambda b=bookmark: (b.extent(), b.extent().crs())),
                                    tooltip=tr("New map with the extent of the bookmark."),
                                    section=tr("Bookmarks: %s") % section))
        return out if layout is not None else _disable(out, NO_LAYOUT)

    return entries


def basic_kit_command(env, _command):
    def run():
        layout, index = _target(env)
        if layout is not None:
            basic_kit(layout, index, env.iface.mapCanvas())

    return run
