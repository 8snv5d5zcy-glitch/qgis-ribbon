"""Druck-Layouts: neues Layout mit Seitengröße, Wechsel zum Hauptfenster.

„Neues Layout“ mit Seitengröße löst die QGIS-Aktion aus, damit deren
Namensabfrage bleibt. QGIS legt das Layout und das Fenster darin synchron an;
die Seitengröße wird gesetzt, sobald ``layoutDesignerOpened`` kommt. Bricht der
Nutzer die Abfrage ab, kommt das Signal nicht, und nichts ändert sich.

„Neu aus Vorlage“ zählt die Vorlagen beim Öffnen des Menüs auf, „Seitengröße“ ändert
die gezeigte Seite als einen Rückgängig-Schritt.

Elementwerte (Tab Format): Lesen und Schreiben der gewählten Elemente. Jede
Änderung läuft mit ``beginCommand``/``endCommand`` und landet so im Rückgängig-
Verlauf des Layouts, bei mehreren Elementen als ein Schritt (Makro). Lesen
liefert bei verschiedenen Werten ``MIXED``.
"""

import os

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsExpression, QgsLayoutItem, QgsLayoutItemMap,
                       QgsLayoutItemPage, QgsLayoutMeasurement, QgsLayoutMultiFrame, QgsLayoutPoint, QgsLayoutSize,
                       QgsPrintLayout, QgsProject, QgsReadWriteContext, QgsUnitTypes)
from qgis.PyQt.QtCore import QFile, QIODevice, Qt
from qgis.PyQt.QtWidgets import QAction, QApplication, QFileDialog, QInputDialog, QMenu
from qgis.PyQt.QtXml import QDomDocument

from ..core.i18n import tr
from . import layer_ops, layout_state, qt_compat

MIXED = object()   # Elemente haben verschiedene Werte

LOG_TAG = "QGIS Ribbon"
NEW_LAYOUT_ACTION = "mActionNewPrintLayout"
ORIENTATIONS = {"landscape": QgsLayoutItemPage.Orientation.Landscape,
                "portrait": QgsLayoutItemPage.Orientation.Portrait}
PAGE_SIZES = ("A4", "A3", "A2", "A1", "A0")


def set_first_page(layout, size, orientation):
    """Erste Seite auf ``size`` (z. B. „A3“) und ``orientation`` setzen; True bei Erfolg.

    Läuft an einem frischen Layout, deshalb ohne Eintrag im Rückgängig-Verlauf.
    """
    page = layout.pageCollection().page(0)
    if page is None or not page.setPageSize(size, ORIENTATIONS[orientation]):
        return False
    layout.pageCollection().reflow()
    return True


def new_layout(iface, size, orientation):
    """Neues Layout über die QGIS-Aktion anlegen und seine Seite einstellen."""
    action = iface.mainWindow().findChild(QAction, NEW_LAYOUT_ACTION)
    if action is None:
        raise RuntimeError(tr("QGIS action %s not found") % NEW_LAYOUT_ACTION)

    def opened(designer):
        if set_first_page(designer.layout(), size, orientation):
            designer.view().zoomFull()

    iface.layoutDesignerOpened.connect(opened)
    try:
        action.trigger()
    finally:
        iface.layoutDesignerOpened.disconnect(opened)


def show_main_window(iface):
    """Hauptfenster nach vorn holen; aus dem Minimieren in die Größe von vorher."""
    window = iface.mainWindow()
    if window.isMinimized():
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    window.raise_()
    window.activateWindow()


def new_layout_command(env, command):
    size, orientation = command.source.get("args")
    return lambda: new_layout(env.iface, size, orientation)


def main_window_command(env, _command):
    return lambda: show_main_window(env.iface)


# Vorlagen und Seitengrößen

def template_files():
    """[(Name, Pfad)] der Vorlagen (.qpt) aus den Vorlagenordnern von QGIS, nach Namen sortiert."""
    found = {}
    for folder in QgsApplication.layoutTemplatePaths():
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                stem, ext = os.path.splitext(name)
                if ext.lower() == ".qpt":
                    found.setdefault(stem, os.path.join(folder, name))
    return sorted(found.items(), key=lambda entry: entry[0].lower())


def layout_from_template(project, path, name):
    """Neues Drucklayout ``name`` aus der Vorlage ``path``; Fehler als RuntimeError."""
    document = QDomDocument()
    source = QFile(path)
    if not source.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError(path)
    try:
        read = document.setContent(source)
    finally:
        source.close()
    if not (read[0] if isinstance(read, tuple) else read):
        raise RuntimeError(path)
    layout = QgsPrintLayout(project)
    _items, loaded = layout.loadFromTemplate(document, QgsReadWriteContext())
    if not loaded:
        raise RuntimeError(path)
    layout.setName(name)
    layout.undoStack().stack().clear()
    return layout


def new_from_template(iface, path):
    """Name erfragen, Layout aus der Vorlage anlegen und im eigenen Fenster öffnen."""
    project = QgsProject.instance()
    manager = project.layoutManager()
    window = QApplication.activeWindow() or iface.mainWindow()
    title = os.path.splitext(os.path.basename(path))[0]
    name, accepted = QInputDialog.getText(window, tr("New Layout from Template"), tr("Name of the new layout:"),
                                          text=manager.generateUniqueTitle() if manager.layoutByName(title) else title)
    if not accepted or not name.strip():
        return None
    message = None
    layout = None
    if manager.layoutByName(name.strip()) is not None:
        message = tr("A layout with this name already exists: %s") % name.strip()
    else:
        try:
            layout = layout_from_template(project, path, name.strip())
        except RuntimeError:
            message = tr("The template could not be read: %s") % path
    if message is not None:
        iface.messageBar().pushMessage(LOG_TAG, message, level=Qgis.MessageLevel.Warning, duration=8)
        return None
    manager.addLayout(layout)
    iface.openLayoutDesigner(layout)
    return layout


def new_from_template_menu(env, command):
    def choose():
        window = QApplication.activeWindow() or env.iface.mainWindow()
        path, _filter = QFileDialog.getOpenFileName(window, tr("New Layout from Template"), "",
                                                    tr("Layout templates") + " (*.qpt)")
        if path:
            new_from_template(env.iface, path)

    def fill(menu):
        files = template_files()
        for name, path in files:
            menu.addAction(name).triggered.connect(lambda _c=False, p=path: new_from_template(env.iface, p))
        if not files:
            menu.addAction(tr("No templates found")).setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Choose Template File …")).triggered.connect(lambda _c=False: choose())

    return _filled_menu(env, command, "ribbon_layout_aus_vorlage", fill)


def set_page_size(layout, page, size, orientation):
    """Größe einer Seite ändern, als ein Rückgängig-Schritt; Elemente bleiben an ihrer Stelle auf den Seiten."""
    pages = layout.pageCollection()
    stack = layout.undoStack()
    stack.beginCommand(page, tr("Change page size"))
    pages.beginPageSizeChange()
    changed = page.setPageSize(size, ORIENTATIONS[orientation])
    pages.endPageSizeChange()
    pages.reflow()
    if changed:
        stack.endCommand()
    else:
        stack.cancelCommand()
    return changed


def current_page(env):
    """Seite, die das Layout-Fenster gerade zeigt; (None, None) ohne Layout (Bericht zu Beginn)."""
    layout = env.items.layout if env.items is not None else None
    if layout is None:
        return None, None
    return layout, layout.pageCollection().page(max(env.designer.view().currentPage(), 0))


def page_size_menu(env, command):
    def choose(size, orientation):
        layout, page = current_page(env)
        if page is not None:
            set_page_size(layout, page, size, orientation)

    def fill(menu):
        if current_page(env)[1] is None:
            menu.addAction(tr("No page to change")).setEnabled(False)
            return
        for size in PAGE_SIZES:
            for text, orientation in ((tr("%s Landscape"), "landscape"), (tr("%s Portrait"), "portrait")):
                menu.addAction(text % size).triggered.connect(
                    lambda _c=False, s=size, o=orientation: choose(s, o))
            menu.addSeparator()
        # Trenner hinter der letzten Größe entfällt
        menu.removeAction(menu.actions()[-1])

    return _filled_menu(env, command, "ribbon_seite_groesse", fill)


# Elementwerte

REFERENCE_POINTS = ("UpperLeft", "UpperMiddle", "UpperRight", "MiddleLeft", "Middle", "MiddleRight",
                    "LowerLeft", "LowerMiddle", "LowerRight")


def reference_point(name):
    return getattr(QgsLayoutItem.ReferencePoint, name)


def common(items, getter):
    """Gemeinsamer Wert von ``getter(item)`` oder ``MIXED``; None ohne Elemente."""
    value = None
    for n, item in enumerate(items):
        current = getter(item)
        if n == 0:
            value = current
        elif current != value:
            return MIXED
    return value


def unit_suffix(items, getter):
    """Abgekürzte Einheit, wenn alle Elemente dieselbe haben, sonst leer."""
    units = common(items, lambda i: getter(i).units())
    return "" if units is None or units is MIXED else " " + QgsUnitTypes.toAbbreviatedString(units)


def change(items, text, undo, apply):
    """``apply(item)`` auf jedes Element anwenden, als ein Rückgängig-Schritt.

    ``undo`` ist ein Name aus ``QgsLayoutItem`` (z. B. ``UndoRotation``). Aufeinanderfolgende
    Änderungen desselben Werts desselben Elements fasst QGIS zu einem Schritt zusammen.
    Das Bedienfeld Elementeigenschaften liest bei ``changed`` neu; viele Setter von QGIS senden
    es nicht, deshalb hier.
    """
    items = [i for i in items if i is not None]
    if not items:
        return
    code = getattr(QgsLayoutItem.UndoCommand, undo or "UndoNone")
    stack = items[0].layout().undoStack() if len(items) > 1 else None
    if stack is not None:
        stack.beginMacro(text)
    try:
        for item in items:
            item.beginCommand(text, code)
            apply(item)
            item.endCommand()
            item.changed.emit()
    finally:
        if stack is not None:
            stack.endMacro()


def position_of(item):
    return item.positionWithUnits()


def size_of(item):
    return item.sizeWithUnits()


def frame_width_of(item):
    return item.frameStrokeWidth()


def set_position(items, axis, value):
    def apply(item):
        point = item.positionWithUnits()
        x, y = (value, point.y()) if axis == "x" else (point.x(), value)
        item.attemptMove(QgsLayoutPoint(x, y, point.units()))

    change(items, tr("Move item"), "UndoIncrementalMove", apply)


def set_size(items, axis, value):
    def apply(item):
        current = item.sizeWithUnits()
        w, h = (value, current.height()) if axis == "w" else (current.width(), value)
        item.attemptResize(QgsLayoutSize(w, h, current.units()))

    change(items, tr("Resize item"), "UndoIncrementalResize", apply)


def set_rotation(items, angle):
    change(items, tr("Rotate item"), "UndoRotation", lambda item: item.setItemRotation(angle))


def set_reference_point(items, name):
    point = reference_point(name)
    change(items, tr("Change reference point"), None, lambda item: item.setReferencePoint(point))


def set_frame_enabled(items, on):
    change(items, tr("Toggle item frame"), None, lambda item: item.setFrameEnabled(bool(on)))


def set_frame_color(items, color):
    change(items, tr("Change frame color"), "UndoStrokeColor", lambda item: item.setFrameStrokeColor(color))


def set_frame_width(items, value):
    change(items, tr("Change frame width"), "UndoStrokeWidth",
           lambda item: item.setFrameStrokeWidth(QgsLayoutMeasurement(value, item.frameStrokeWidth().units())))


def set_background_enabled(items, on):
    change(items, tr("Toggle item background"), None, lambda item: item.setBackgroundEnabled(bool(on)))


def set_background_color(items, color):
    change(items, tr("Change background color"), "UndoBackgroundColor",
           lambda item: item.setBackgroundColor(color))


def set_opacity(items, value):
    change(items, tr("Change item opacity"), "UndoOpacity", lambda item: item.setItemOpacity(value))


def set_blend_mode(items, mode):
    change(items, tr("Change blend mode"), None, lambda item: item.setBlendMode(mode))


def item_options_command(env, _command):
    """Dialog-Launcher: Bedienfeld „Elementeigenschaften“ für das erste gewählte Element."""
    def show():
        designer = env.designer
        items = env.items.items() if getattr(env, "items", None) is not None else []
        if designer is not None and items:
            designer.showItemOptions(items[0], True)

    return show


# Werte einer Elementart (Kontext-Tabs Karte, Text, Legende, Maßstab, Bild, Form, Tabelle)

def selected_of_kind(env, kind):
    """Das einzige gewählte Element, wenn es von dieser Art ist; sonst None."""
    items = env.items.items() if getattr(env, "items", None) is not None else []
    return items[0] if len(items) == 1 and layout_state.kind_of(items[0]) == kind else None


def layout_maps(layout):
    """Kartenrahmen des Layouts (ohne 3D-Karten)."""
    return [i for i in layout.items() if isinstance(i, QgsLayoutItemMap)]


# Karte

def set_map_scale(item, scale):
    change([item], tr("Change map scale"), "UndoZoomContent", lambda i: i.setScale(scale))


def set_map_rotation(item, angle):
    change([item], tr("Change map rotation"), "UndoMapRotation", lambda i: i.setMapRotation(angle))


def _to_crs(rect, source, target):
    if source == target:
        return rect
    return QgsCoordinateTransform(source, target, QgsProject.instance()).transformBoundingBox(rect)


def map_from_canvas(item, canvas):
    """Ausdehnung des Kartenrahmens auf die der Hauptkarte setzen."""
    settings = canvas.mapSettings()
    extent = _to_crs(settings.visibleExtent(), settings.destinationCrs(), item.crs())
    change([item], tr("Change map extent"), "UndoZoomContent", lambda i: i.zoomToExtent(extent))


def canvas_from_map(item, canvas):
    """Hauptkarte auf die Ausdehnung des Kartenrahmens setzen."""
    canvas.setExtent(_to_crs(item.extent(), item.crs(), canvas.mapSettings().destinationCrs()))
    canvas.refresh()


def map_to_bookmark(item, bookmark):
    extent = bookmark.extent()
    rect = _to_crs(extent, extent.crs(), item.crs())
    change([item], tr("Change map extent"), "UndoZoomContent", lambda i: i.zoomToExtent(rect))


def refresh_map(item):
    item.invalidateCache()
    item.refresh()


def set_map_theme(item, theme):
    """Kartenthema, dem der Rahmen folgt; None: keinem. Schließt gesperrte Layer und Stile aus."""
    def apply(i):
        if theme is not None:
            i.setLayers([])
            i.setLayerStyleOverrides({})
            i.setKeepLayerSet(False)
            i.setKeepLayerStyles(False)
            i.setFollowVisibilityPresetName(theme)
        i.setFollowVisibilityPreset(theme is not None)
        i.invalidateCache()

    change([item], tr("Change map theme"), None, apply)


def set_keep_layers(item, on, canvas):
    """Layer des Rahmens sperren (die der Hauptkarte) oder wieder freigeben, wie im Bedienfeld."""
    def apply(i):
        if on:
            i.setLayers(canvas.mapSettings().layers())
            i.setFollowVisibilityPreset(False)
        else:
            i.setLayers([])
            i.setKeepLayerStyles(False)
            i.setLayerStyleOverrides({})
        i.setKeepLayerSet(bool(on))
        i.invalidateCache()

    change([item], tr("Lock map layers"), None, apply)


def set_keep_styles(item, on):
    def apply(i):
        if on:
            i.storeCurrentLayerStyles()
        else:
            i.setLayerStyleOverrides({})
        i.setKeepLayerStyles(bool(on))
        i.invalidateCache()

    change([item], tr("Lock map styles"), None, apply)


# Texte und Schrift (Textelement, Maßstab)

def set_label_text(item, text):
    change([item], tr("Change label text"), "UndoLabelText", lambda i: i.setText(text))


def _edit_format(item, text, undo, edit):
    def apply(i):
        fmt = i.textFormat()
        edit(fmt)
        i.setTextFormat(fmt)

    change([item], text, undo, apply)


def set_font_family(item, family):
    def edit(fmt):
        font = fmt.font()
        font.setFamily(family)
        fmt.setFont(font)

    _edit_format(item, tr("Change font"), "UndoLabelFont", edit)


def set_font_size(item, size):
    _edit_format(item, tr("Change font size"), "UndoLabelFont", lambda fmt: fmt.setSize(size))


def set_font_color(item, color):
    _edit_format(item, tr("Change font color"), "UndoLabelFontColor", lambda fmt: fmt.setColor(color))


def set_text_format(item, fmt):
    change([item], tr("Change font"), "UndoLabelFont", lambda i: i.setTextFormat(fmt))


def set_label_alignment(item, horizontal, value):
    change([item], tr("Change text alignment"), None,
           lambda i: i.setHAlign(value) if horizontal else i.setVAlign(value))


def insert_dynamic_text(item, expression):
    """Ausdruck hinten an den Text anhängen; mehrzeilige Texte bleiben erhalten."""
    set_label_text(item, item.text() + expression)


def dynamic_texts(layout):
    """[(Beschriftung, Ausdruck)] wie im Menü „Dynamischer Text“ von QGIS."""
    out = [(tr("Current Date"), "[% format_date(now(), 'yyyy-MM-dd') %]"),
           (tr("Current Date and Time"), "[% format_date(now(), 'yyyy-MM-dd hh:mm') %]"),
           (tr("Layout Name"), "[% @layout_name %]"),
           (tr("Page Number"), "[% @layout_page %]"),
           (tr("Total Number of Pages"), "[% @layout_numpages %]"),
           (tr("Project Title"), "[% @project_title %]"),
           (tr("Project Path"), "[% @project_path %]"),
           (tr("Project Author"), "[% @project_author %]"),
           (tr("Layer Credits"), "[% array_to_string(map_credits()) %]"),
           (tr("Current User"), "[% @user_full_name %]")]
    for item in layout_maps(layout):
        if item.id():
            quoted = QgsExpression.quotedString(item.id())
            out.append((tr("Scale of %s") % item.id(),
                        "[% format_number(item_variables({0})['map_scale'], places:=0) %]".format(quoted)))
    return out


# Legende

def set_linked_map(item, linked):
    change([item], tr("Change linked map"), None, lambda i: i.setLinkedMap(linked))


def legend_auto_update(item):
    return qt_compat.legend_auto_update(item)


def set_legend_auto_update(item, on):
    change([item], tr("Change legend auto update"), None, lambda i: qt_compat.set_legend_auto_update(i, on))


def set_legend_filter(item, on):
    change([item], tr("Change legend filter"), None, lambda i: i.setLegendFilterByMapEnabled(bool(on)))


def set_legend_title(item, title):
    change([item], tr("Change legend title"), "UndoLegendText", lambda i: i.setTitle(title))


def set_legend_columns(item, count):
    change([item], tr("Change legend columns"), "UndoLegendColumnCount", lambda i: i.setColumnCount(int(count)))


def set_legend_resize(item, on):
    def apply(i):
        i.setResizeToContents(bool(on))
        if on:
            i.adjustBoxSize()

    change([item], tr("Change legend size"), None, apply)


# Maßstab

def scalebar_styles():
    """[(ID, sichtbarer Name)] der Maßstabsstile."""
    registry = QgsApplication.scaleBarRendererRegistry()
    return [(style, registry.visibleName(style)) for style in registry.sortedRendererList()]


def set_scalebar_style(item, style):
    change([item], tr("Change scale bar style"), None, lambda i: i.setStyle(style))


def set_scalebar_units(item, units):
    """Einheit wie im Bedienfeld: ``applyDefaultSize`` setzt auch Bezeichnung und Segmentlänge passend."""
    change([item], tr("Change scale bar units"), None, lambda i: i.applyDefaultSize(units))


def set_scalebar_segments(item, count):
    change([item], tr("Change scale bar segments"), "UndoScaleBarSegments",
           lambda i: i.setNumberOfSegments(int(count)))


def set_scalebar_length(item, value):
    change([item], tr("Change scale bar segment length"), "UndoScaleBarSegmentSize",
           lambda i: i.setUnitsPerSegment(value))


# Bild

def set_picture_path(item, path):
    change([item], tr("Change picture"), None, lambda i: i.setPicturePath(path))


def set_picture_resize_mode(item, mode):
    change([item], tr("Change picture size mode"), None, lambda i: i.setResizeMode(mode))


def set_picture_anchor(item, name):
    change([item], tr("Change picture alignment"), None, lambda i: i.setPictureAnchor(reference_point(name)))


def set_picture_map(item, linked):
    """Bild mit einer Karte drehen; None: nicht mehr. Die Drehung des Bilds bleibt dann stehen."""
    change([item], tr("Change picture rotation"), None, lambda i: i.setLinkedMap(linked))


# Form

def set_shape_symbol(item, symbol):
    change([item], tr("Change shape style"), "UndoShapeStyle", lambda i: i.setSymbol(symbol.clone()))


def set_shape_type(item, shape):
    change([item], tr("Change shape type"), None, lambda i: i.setShapeType(shape))


def set_corner_radius(item, value):
    change([item], tr("Change corner radius"), "UndoShapeCornerRadius",
           lambda i: i.setCornerRadius(QgsLayoutMeasurement(value, i.cornerRadius().units())))


# Tabelle: Werte stehen am Multiframe, dessen Rückgängig-Schritte eigene Kennungen haben

def change_table(table, text, undo, apply):
    code = getattr(QgsLayoutMultiFrame.UndoCommand, undo or "UndoNone")
    table.beginCommand(text, code)
    apply(table)
    table.endCommand()
    table.changed.emit()


def set_table_layer(table, layer):
    change_table(table, tr("Change table layer"), None, lambda t: t.setVectorLayer(layer))


def set_table_rows(table, count):
    change_table(table, tr("Change table rows"), "UndoTableMaximumFeatures",
                 lambda t: t.setMaximumNumberOfFeatures(int(count)))


def set_table_filter(table, text):
    def apply(t):
        t.setFilterFeatures(bool(text))
        t.setFeatureFilter(text)

    change_table(table, tr("Change table filter"), None, apply)


def set_table_visible_only(table, on):
    change_table(table, tr("Change table filter"), None, lambda t: t.setDisplayOnlyVisibleFeatures(bool(on)))


# Atlas

def atlas_of(designer):
    """Atlas des Layout-Fensters; None bei einem Bericht (der hat keinen)."""
    atlas = getattr(designer.masterLayout(), "atlas", None) if designer is not None else None
    return atlas() if atlas is not None else None


def atlas_preview_on(designer):
    return designer is not None and designer.atlasPreviewEnabled() and atlas_of(designer) is not None


def atlas_names(atlas):
    """Namen der Atlas-Objekte in der Reihenfolge der Seiten."""
    return [atlas.nameForPage(n) for n in range(atlas.count())]


# Befehle

def _on_selected(env, kind, action):
    def run():
        item = selected_of_kind(env, kind)
        if item is not None:
            action(item)

    return run


def map_from_canvas_command(env, _command):
    return _on_selected(env, "map", lambda item: map_from_canvas(item, env.iface.mapCanvas()))


def canvas_from_map_command(env, _command):
    return _on_selected(env, "map", lambda item: canvas_from_map(item, env.iface.mapCanvas()))


def refresh_map_command(env, _command):
    return _on_selected(env, "map", refresh_map)


def _filled_menu(env, command, name, fill):
    """Eigenes Dropdown, das sich bei jedem Öffnen neu füllt."""
    menu = env.keep(QMenu(command.label))
    menu.setObjectName(name)

    def show():
        menu.clear()
        fill(menu)

    menu.aboutToShow.connect(show)
    return menu


def map_bookmarks_menu(env, command):
    def fill(menu):
        section = None
        for name, bookmark in layer_ops.bookmarks():
            if name != section:
                menu.addSection(name)
                section = name
            menu.addAction(bookmark.name()).triggered.connect(
                lambda _c=False, b=bookmark: _on_selected(env, "map", lambda i: map_to_bookmark(i, b))())
        if not menu.actions():
            menu.addAction(tr("No bookmarks")).setEnabled(False)

    return _filled_menu(env, command, "ribbon_karte_lesezeichen", fill)


def map_theme_menu(env, command):
    def fill(menu):
        item = selected_of_kind(env, "map")
        current = item.followVisibilityPresetName() if item is not None and item.followVisibilityPreset() else None

        def add(label, theme):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(theme == current)
            act.triggered.connect(
                lambda _c=False, t=theme: _on_selected(env, "map", lambda i: set_map_theme(i, t))())

        add(tr("No Map Theme"), None)
        themes = QgsProject.instance().mapThemeCollection().mapThemes()
        if themes:
            menu.addSeparator()
        for theme in themes:
            add(theme, theme)

    return _filled_menu(env, command, "ribbon_karte_thema", fill)


def dynamic_text_menu(env, command):
    def fill(menu):
        item = selected_of_kind(env, "label")
        if item is None:
            return
        for label, expression in dynamic_texts(item.layout()):
            menu.addAction(label).triggered.connect(
                lambda _c=False, e=expression: _on_selected(env, "label", lambda i: insert_dynamic_text(i, e))())

    return _filled_menu(env, command, "ribbon_text_dynamisch", fill)
