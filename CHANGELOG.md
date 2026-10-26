# Changelog

## 1.3.0 (2026-10-26)

- Appearance tab for vector and raster layers: visibility range, effects (opacity, blending mode, for vector layers also feature blending mode) and compare (swipe, flicker with adjustable interval).
- Vector layers: aggregation for point layers (point cluster, point displacement, heatmap; None restores the previous symbology).
- New contextual tabs: Group (render as group, mutually exclusive, zoom to group; opacity, blending mode and visibility range for the group), Vector Tiles (symbology, labels on/off), Point Cloud (rendering, point size, maximum error) and Mesh (scalar and vector dataset, mesh frame).
- 15 new commands and controls with icons of the own icon set; guide extended in both languages.

## 1.2.1 (2026-10-26)

- Fix: QGIS could crash on exit (access violation) when a plugin whose commands the ribbon shows in the Extensions tab was unloaded before the ribbon.

## 1.2.0 (2026-10-26)

- Edit tab, Editing: **Save** and **Discard** act on the active layer only and keep editing on; **Discard** asks first. **Save All** and **Discard All** (formerly Save Edits and Discard Edits) act on all layers being edited and show a layer stack in their icons.
- Labeling tab: **New Class** creates a label class from the selected one, **Delete Class** removes the selected one (the last class stays).
- **Label** sets a placement that fits the geometry, for lines Parallel; before, new labels on lines could stay invisible.
- Labeling tab: the separate Expression button is gone; the Field box has its own expression button. Expression is still available in the ribbon editor.

## 1.1.0 (2026-10-26)

- Edit tab: new group Construction with the Advanced Digitizing switch and the Construction Panel; Snapping gains tracing, self-snapping and snapping to intersections.
- Map tab, Labeling: show/hide, pin, highlight pinned, move, rotate and change labels.
- 23 further QGIS commands from the hidden toolbars can be added in the ribbon editor (for example Zoom Out, Refresh, Field Calculator, Temporal Controller) and are found by the command search.
- 28 new icons in the own icon set.

## 1.0.0 (2026-10-26)

First public release.

- Ribbon with the tabs Map, Insert, Analysis, View, Edit, Imagery, Share and Extensions, and contextual tabs for vector layers, tables and rasters.
- Buttons in three sizes, split buttons, menus, galleries, controls for layer and label settings, dialog launchers, rich tooltips, adaptive width.
- Quick Access Toolbar, KeyTips (Alt) with your own KeyTips, command search, minimizing.
- Graphical ribbon editor with drag and drop, keyboard operation and undo; gallery customization; arrangements to save, load, export and import.
- Appearance: automatic, light or dark, accent colors Moss, Cobalt and Amber, own icon set, optional style for the whole QGIS window, Windows high-contrast support.
- Extensions tab for plugin commands; own Processing scripts, models and all toolbox tools in the editor.
- Domains dialog and further own commands where QGIS has no single command.
- Switch to the classic QGIS interface; deactivating the plugin restores QGIS exactly.
- User interface in English and German; built-in guide in both languages.
