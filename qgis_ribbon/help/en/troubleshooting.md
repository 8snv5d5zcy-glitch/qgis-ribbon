# Settings, reset and troubleshooting

[Contents](index.md)

## Where the settings are stored

All settings of the ribbon are stored in your QGIS user profile under the key `qgis_ribbon`: the current arrangement, saved arrangements, appearance, minimized state, Quick Access and KeyTips. Another profile starts with the default ribbon.

Settings are not stored in projects. Only domains of layers without a suitable data source are stored in the project (see [Additional tools](tools.md)).

## Reset

| What | How |
|---|---|
| Tabs, groups, galleries, Quick Access, KeyTips | **Arrangements › Default Arrangement** |
| Tabs, groups and Quick Access in the editor | **Restore Defaults** in the editor (can be undone) |
| a single group | menu ⋯ of the group in the editor |
| Quick Access only | **Restore Defaults** in the ▾ menu |
| KeyTips only | **Reset All** in Customize KeyTips |
| everything | delete the group `qgis_ribbon` in **Settings › Options › Advanced** (Advanced Settings Editor) and restart QGIS |

Save your arrangement first with **Arrangements › Export …** if you might want it back.

## Common questions

**The ribbon is gone and the QGIS toolbars are back.**
The classic QGIS interface is active. Choose **View › Ribbon Interface**.

**A command is grayed out.**
It needs a matching active layer (for example a vector layer, or a layer in edit mode), a selection, or a plugin that is not loaded. The tooltip shows the reason for missing commands.

**The ribbon shows German texts (or English).**
The ribbon follows the QGIS language. Change it under **Settings › Options › General** and restart QGIS.

**Toolbars of a plugin are missing.**
While the ribbon is active, plugin toolbars are hidden. Their commands are in the [Extensions](extensions.md) tab.

**Alt does not show the KeyTips.**
Press and release Alt alone, without another key, while the QGIS main window is active. Alt with a letter opens the QGIS menus.

## Uninstalling

**Plugins › Manage and Install Plugins …** deactivates or uninstalls QGIS Ribbon. QGIS then shows its toolbars and the previous window layout again. The settings under `qgis_ribbon` stay in the profile; delete them as described above if needed.

## Reporting problems

Please report bugs and suggestions in the [issue tracker](https://github.com/8snv5d5zcy-glitch/qgis-ribbon/issues). Helpful details are the QGIS version, the operating system, the steps to reproduce, and messages from the QGIS log panel (tab *QGIS Ribbon*).
