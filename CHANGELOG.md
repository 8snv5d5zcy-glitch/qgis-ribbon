# Changelog

## 1.6.1 (2026-10-30)

- Fixed: on macOS the ribbon failed to load with `AttributeError: 'RibbonTabBar' object has no attribute '_metrics'`. On macOS Qt lays out the tab bar while it is still being created; the tab bar, the tab pages and the guide now set up their state first.
- macOS: shortcuts that macOS uses itself are replaced. Minimize the ribbon with ⌥⌘T (⌘F1 mirrors the displays), add a command to Quick Access in the ribbon editor with ⌃Q (⌘Q quits QGIS), redo in the editor with ⇧⌘Z.
- macOS: tooltips, messages and the KeyTip hints show the Mac keys (⌘Z, ⌥, ⌫) instead of Ctrl, Alt and Del. Windows and Linux are unchanged.
- Hide QGIS Menu Bar is no longer offered when the menu bar is native (macOS, global menus on Linux): it is outside the QGIS window and cannot be hidden there.
- Guide: new section On the Mac on the Keyboard page.

## 1.6.0 (2026-10-29)

- Labeling tab: the new Label Classes button switches between labeling by class (rule-based) and one simple label. With classes on, all groups of the tab (visibility range, text symbol, placement) read and change only the class chosen in the list; before, most of them changed all classes. With classes off, they control the simple label and the class commands are grayed out.
- The scale limits of a class are stored in the scale range of its rule, the values shown in the rule list of the layer properties. Clear Limits removes the range of the rule and any range in the label settings; a hint shows when a class has such an additional range.
- Switching never loses a version: the label version that is not in use is kept as XML in the layer (custom properties) and saved with the project. The first switch turns the simple label into the class Default, switched off, so nothing is labeled twice. New Class switches classes on and creates a class that is switched on.
- Fixed: choosing Graduated in the symbology gallery failed with an error.
- Symbol group: Class is grayed out when the symbology has a single symbol, because there is nothing to choose.

## 1.5.0 (2026-10-29)

- Appearance tab of vector layers, new Symbol group: choose a class (category, class or rule, also by clicking it in the Layers panel) and change its fill color, outline color and width directly; with All … the width applies to every class. Edit Symbol opens the QGIS symbol editor for the class. Works with single symbol, categorized, graduated and rule-based symbology and inside point cluster and displacement; every change is one step on the style undo stack.
- Hide QGIS Menu Bar (▾ menu and right-click menu) for more room: the menu bar gets no height, keyboard shortcuts and Alt+letter keep working, and a ☰ button at the left of the ribbon header opens all QGIS menus. The classic interface and deactivating the plugin always bring the menu bar back.
- 82 further commands in the ribbon editor and the search: every page of the options dialog (**Options: …**), Manage and Install Plugins, the help commands (About, Check QGIS Version, Report an Issue, API documentation …), decorations (grid, scale bar, north arrow, title, copyright, image, layout extents), layer visibility, full screen, map only, panels and toolbars, elevation profile, 3D globe and more, and every menu of the QGIS menu bar as a dropdown (**Project Menu** … and **QGIS Menus** with all of them). Search Settings now opens the Locator page of the options.
- Arrangements: new Save Arrangement saves changes into the current arrangement (the one loaded or saved last); Save Current Arrangement As … creates a new one and asks before overwriting an existing name.
- The dropdowns of split buttons and menus can be customized too, for example Advanced Digitizing: in the ribbon editor drop a command (also of another plugin) onto the middle of a button with ▾, or use Customize Dropdown … in its properties. The change applies wherever the button appears; arrangement format 4 (older formats are still read).
- Every gallery can be customized, also dropdown galleries such as Basemap or Bookmarks: right-click the gallery in the ribbon (Customize Gallery …) or use the new button in the ribbon editor. Galleries accept any button, including commands of other plugins and Toolbox tools; a plugin command stays as a placeholder while its plugin is not loaded.
- Buttons with a dropdown keep their dropdown when the window is wide; their entries are no longer shown again as small buttons next to them (that caused duplicates).
- View tab: Simulate Color Blindness is a single button with the QGIS preview menu; the separate Deuteranopia Preview is still available in the ribbon editor.
- Edit tab, Construction: one Advanced Digitizing button with Construction Panel in its dropdown instead of two buttons side by side. Advanced Digitizing only switches the construction aids on or off and no longer opens the panel (also not when changing tools); Construction Panel only shows or hides the panel.

## 1.4.1 (2026-10-27)

- Qt6 preparation for QGIS 4: all Qt and QGIS enums are fully qualified, `exec()` replaces `exec_()`, mouse and drag positions go through one helper. One code base for QGIS 3.44 (Qt5) and QGIS 4 (Qt6), `supportsQt6=True` in the metadata. Not yet tested on QGIS 4. No change in behavior.

## 1.4.0 (2026-10-27)

- New Fields group in the Data tab of vector layers and tables: Add Field (name, type, length, precision, alias, comment), Delete Fields, Rename Field and the Field Calculator. In edit mode changes go into the edit buffer, otherwise they are written to the data source after confirmation; buttons follow what the data source supports.
- 94 further QGIS commands available in the ribbon editor and in the search (command pool), among them direct access to the pages of the layer, project and options dialogs, Save Style and layer tree actions; QGIS submenus open below the search field.
- Ribbon editor: built-in tabs and groups (also plugin groups in the Extensions tab) can be deleted, not only hidden, and restored later.
- Layer tree shows mutually exclusive groups with round check boxes, wider opacity slider, stronger group separators, no tab jump away from your own tabs, plugin menus open below their button.

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
