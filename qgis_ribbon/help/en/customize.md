# Customizing the ribbon

[Contents](index.md)

Everything in the ribbon can be changed: hide, rename or reorder tabs and groups, put commands into any group, create your own tabs and groups, and choose the commands of the Quick Access Toolbar and of the galleries. A set of these changes is called an **arrangement**.

## The editor

**Customize Ribbon …** in the ▾ menu of the Quick Access Toolbar or in the right-click menu of the ribbon opens the editor. It looks like the ribbon itself.

![Customize Ribbon](../images/en/editor.png)

- **Top:** the tabs. Contextual tabs are on the right and marked with their color.
- **Quick Access:** the commands of the Quick Access Toolbar.
- **Middle:** a preview of the selected tab with its groups.
- **Bottom left:** the commands. **Search** finds them by name or description. The list next to it filters: *All*, *Not in the ribbon*, *Extensions (plugins)*, *Own scripts and models*, *Toolbox (all tools)* or one tab. A check mark shows that a command is already in the selected tab. **Groups** shows whole groups instead of single commands.
- **Bottom right:** the properties of the selected tab, group or command (label, visibility, size).

Nothing changes in the ribbon until you click **Save**. **Cancel** asks before discarding changes. Every step can be undone with the arrows at the top right (Ctrl+Z, Ctrl+Y). **Restore Defaults** resets tabs, groups and Quick Access to the shipped state; this can also be undone.

### What you can do

| Task | Mouse | Keyboard |
|---|---|---|
| Choose a tab | click the tab | Left/Right arrow in the tab bar |
| Add a command | drag it from the commands into a group; a marker shows the position | select a group or item, select the command, Enter |
| Move an item | drag it, also into another group; hold it over another tab to switch there | Ctrl+arrow; Ctrl+X, choose the target, Ctrl+V |
| New group | click **＋ Group**, or drop a command on it | select **＋ Group**, Enter |
| Move a group | drag its header | select the group header, Ctrl+arrow |
| Copy a group of another tab | switch the commands to **Groups** and drag the tile into the preview or onto a tab | select the tile, Enter |
| New tab | **＋ Tab** | – |
| Reorder tabs | drag the tab (main tabs stay before contextual tabs) | select the tab, Ctrl+arrow |
| Remove | drag it back into the commands | Delete |
| Show or hide | eye icon on a tab or group | Space |
| Rename | double-click (your own tabs, all groups) | F2 |
| Item size | properties: large, medium, small | – |
| Quick Access | drag a command into the Quick Access row, reorder it there, drag it back to remove | Ctrl+Q in the commands, Ctrl+arrow, Delete |
| Reset one group | menu ⋯ of the group, or properties | – |
| Undo, redo | arrows at the top right | Ctrl+Z, Ctrl+Y |

Notes:

- A command can be in a group only once, but several times in the same tab.
- Contextual tabs only accept commands that can work there.
- A group of the shipped ribbon becomes your own version as soon as you change it. It is marked as *customized* and can be reset on its own.
- Split buttons, menus, galleries and rows of small buttons stay one unit. They can be moved and removed; ▾ shows their content.
- Empty groups of your own are dropped when saving.

## Customizing a gallery

Galleries (for example the geoprocessing tools in the Analysis tab or the basemaps in the Map tab) have **Customize Gallery …** in their menu.

![Customize Gallery](../images/en/gallery_dialog.png)

Double-click commands on the left or use **Add ›** to add them. Set the order on the right with **Move Up** and **Move Down** or by dragging. The ribbon shows the first items, the rest when the gallery is expanded. **Restore Defaults** brings back the shipped items.

## Arrangements

The submenu **Arrangements** in the ▾ menu and in the right-click menu manages your arrangements:

- **Save Current Arrangement As …** stores the current state under a name.
- Choose a saved arrangement to load it.
- **Default Arrangement** loads the ribbon as shipped (tabs, groups, galleries, Quick Access and KeyTips).
- **Delete** removes a saved arrangement.
- **Export …** writes the current arrangement to a JSON file, for example to share it with colleagues. **Import …** loads such a file.

If an arrangement names commands that are missing in this QGIS installation (for example of a plugin that is not installed), they appear grayed out, or are skipped with a message when importing.
