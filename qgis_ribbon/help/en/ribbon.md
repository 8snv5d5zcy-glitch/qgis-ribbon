# Working with the ribbon

[Contents](index.md)

![The ribbon with the Map tab](../images/en/tab_map.png)

The ribbon consists of the **header** (Quick Access Toolbar, tabs, command search, minimize and help buttons) and the **ribbon area** with the groups of the selected tab.

## Tabs

| Tab | Groups |
|---|---|
| Map | Clipboard, Navigate, Layer, Selection, Query, Labeling |
| Insert | Project, New Layers, Styles, Favorites |
| Analysis | Geoprocessing, Tools |
| View | Link, Windows, Accessibility, Navigation |
| Edit | Clipboard, Editing, Snapping, Construction, Features, Selection, Tools, Elevation |
| Imagery | Align, Analysis |
| Share | Package, Save As, Output |
| Extensions | commands of installed plugins, see [Extensions](extensions.md) |

![The Edit tab](../images/en/tab_edit.png)

When you start editing a layer, the ribbon switches to the **Edit** tab.

**Construction › Advanced Digitizing** turns the construction aids on or off (distance, angle, coordinates while digitizing). It is available while a tool that supports it is active, for example **Create** or **Modify**. While it is on, QGIS opens its panel whenever you pick such a tool; **Construction Panel** shows or hides the panel. The small icons in **Snapping** switch tracing, self-snapping and snapping to intersections.

## Contextual tabs

Some tabs only appear when they fit the active layer in the Layers panel. They stand on the right in a colored frame with the name of their context:

- **Vector Layer:** Appearance, Labeling, Data
- **Table** (layer without geometry): Data
- **Raster Layer:** Appearance

![Contextual tab Appearance of a vector layer](../images/en/contextual.png)

Commands that cannot be used at the moment (for example *Clear Selection* without a selection) are grayed out.

## Buttons, menus and galleries

- **Large, medium and small buttons** run a command. Buttons that switch something on or off (for example a map tool) stay highlighted while active.
- **Split buttons** have two parts: the upper or left part runs the main command, the arrow ▾ opens related commands.
- **Menus** (label with ▾) open a list of commands.
- **Galleries** show a selection of tools or styles (for example the geoprocessing tools in the Analysis tab). The arrow at the side shows all items. Which items appear can be changed, see [Customizing the ribbon](customize.md).
- **Controls** such as fields for scale, opacity or font act directly on the active layer.
- **Dialog launcher:** the small arrow ↘ in the lower right corner of a group opens the matching QGIS dialog with more settings.
- **Tooltips** show the name, a description and the keyboard shortcut of a command.

When the window is narrow, groups on the right collapse into a single button. A click on it shows the group as a drop-down.

## Quick Access Toolbar

The small icons at the left of the header are the **Quick Access Toolbar**. Its commands are available whichever tab is selected.

![Menu of the Quick Access Toolbar](../images/en/quick_access_menu.png)

- **Add a command:** right-click a command in the ribbon and choose **Add to Quick Access Toolbar**.
- **Remove a command:** uncheck it in the ▾ menu, or right-click it and choose **Remove from Quick Access Toolbar**.
- **Order:** in the editor, see [Customizing the ribbon](customize.md).
- **Restore Defaults** in the ▾ menu restores the shipped commands.

The ▾ menu also contains the settings of the ribbon: KeyTips, minimizing, the editor, arrangements, appearance, the classic QGIS interface and this guide. The same entries are in the right-click menu of the ribbon:

![Right-click menu of the ribbon](../images/en/context_menu.png)

## Minimizing the ribbon

The ribbon can be reduced to its header to leave more room for the map:

- the **^** button at the right of the header,
- **Ctrl+F1**,
- double-click a tab,
- **Minimize the Ribbon** in the ▾ menu or the right-click menu.

![Minimized ribbon](../images/en/minimized.png)

While minimized, a click on a tab shows the ribbon above the map. It closes again when you click outside it. To show the ribbon permanently, use the pin button, Ctrl+F1, or double-click a tab again. The state is kept for the next start.

## Command search

The search field at the right of the header finds commands by name or description, see [Keyboard: KeyTips and search](keyboard.md).
