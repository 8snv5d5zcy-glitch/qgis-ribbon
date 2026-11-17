# Keyboard: KeyTips and search

[Contents](index.md)

## KeyTips

Every tab and every command in the ribbon has a KeyTip: one or two letters that run it from the keyboard.

1. Press and release **Alt** (without another key in between). Letters appear on the tabs, numbers on the Quick Access Toolbar and **Q** on the search field.

   ![KeyTips of the header](../images/en/keytips.png)

2. Type the letter of a tab. The tab opens and shows the KeyTips of its commands.

   ![KeyTips of the Map tab](../images/en/keytips_tab.png)

3. Type the KeyTip of a command. Buttons run, menus open, and fields such as scale or font get the keyboard focus.

| Key | Effect |
|---|---|
| Alt (press and release) | show KeyTips, or hide them again |
| 1 – 9 | command of the Quick Access Toolbar |
| Q | command search |
| Esc | back one level |
| Backspace | delete the last typed letter of a two-letter KeyTip |
| mouse click, other window | end KeyTip mode |

Alt together with a letter (for example Alt+F) still opens the QGIS menus as before. Collapsed groups in a narrow window get their own KeyTip, which opens the group; the KeyTips of the commands stay the same.

## Customizing KeyTips

**Customize KeyTips …** in the ▾ menu of the Quick Access Toolbar or in the right-click menu opens a list of all KeyTips.

![Customize KeyTips](../images/en/keytip_dialog.png)

- **Filter** finds items by name, tab or KeyTip.
- Double-click the **Own** column and type one or two letters. Leave it empty to use the automatic KeyTip again.
- The other KeyTips of the same level adapt automatically. Conflicts are pointed out below the list.
- **Reset All** removes all of your own KeyTips.
- Quick Access (1–9) and search (Q) are fixed.

Your own KeyTips are part of the arrangement, see [Customizing the ribbon](customize.md).

## Command search

The field **Search commands** at the right of the header finds commands by their name, description or location in the ribbon, commands of the QGIS menus and toolbars (also from their dropdowns) that are not in the ribbon, the functions of the ribbon itself, and every tool of the Processing Toolbox including your own scripts and models.

![Command search](../images/en/search.png)

- Open: click the field, or **Alt**, then **Q**.
- In a narrow window the field becomes narrower and finally a magnifier button; clicking it or **Alt**, then **Q** opens the field over the tabs.
- Each result shows where the command is located (for example *Analysis › Tools*). Commands of the QGIS menus are marked with *QGIS:*, commands without a place in the ribbon (such as **Properties: Metadata** or **Project Properties: CRS**) with *Command pool*. A QGIS submenu such as **Recent Projects** opens below the search field. The location is shown dimmed next to the name; if the list is too narrow, the location is shortened, never the name.
- Functions of the ribbon have the location *Ribbon*: for example *customize* finds **Customize Ribbon**, *dark* the dark mode under *Ribbon › Appearance*, as well as arrangements, **Classic QGIS Interface** and the guide.
- **New Script**, **New Model** and their neighbours (script from template, open, add to toolbox) are in the **Analysis** tab, group **Tools**, in the dropdown **Scripts and Models**, and can be found with the search.
- Processing tools are listed with *Toolbox › provider › group*, after the commands of the ribbon and the QGIS menus; your own scripts and models come before the other tools. A result opens the tool's dialog. The internal name and the tags of a tool are searched too (for example *fix* finds **Fix Geometries**), also when the tool is in the ribbon. New and deleted scripts are found right away.
- **Enter** runs the first result, the arrow keys choose another one.
- **Esc** clears the field and returns to the map.
- Upper and lower case do not matter. German umlauts can be typed as ae, oe, ue and ss.

## Other shortcuts

| Key | Effect |
|---|---|
| Ctrl+F1 | minimize the ribbon or show it again |
| F1 in the editor | this guide |

The QGIS keyboard shortcuts (for example Ctrl+S, Ctrl+Z) keep working. Tooltips in the ribbon show the shortcut of a command.

## On the Mac

The ribbon uses the Mac keys. Tooltips and messages show them with their symbols.

| Windows, Linux | Mac |
|---|---|
| Ctrl (Ctrl+Z, Ctrl+X …) | ⌘ Command (⌘Z, ⌘X …) |
| Alt for the KeyTips | ⌥ Option, press and release |
| Ctrl+F1, minimize the ribbon | ⌥⌘T |
| Ctrl+Y, redo in the editor | ⇧⌘Z |
| Ctrl+Q, add to Quick Access in the editor | ⌃Q (Control), because ⌘Q quits QGIS |
| Delete in the editor | ⌫ |

The menu bar is at the top of the screen on the Mac, so **Hide QGIS Menu Bar** is not offered there.
