# QGIS Ribbon

A ribbon interface for [QGIS](https://qgis.org): commands sorted into tabs and groups, contextual tabs for the active layer, a Quick Access Toolbar, KeyTips for the keyboard and a command search, instead of the QGIS toolbars.

*Deutsch: [siehe unten](#deutsch).*

![QGIS with the ribbon](qgis_ribbon/help/images/en/window.jpg)

## Features

- **Tabs** Map, Insert, Analysis, View, Edit, Imagery, Share and Extensions; **contextual tabs** for vector layers, tables and rasters.
- **Controls:** large, medium and small buttons, split buttons, menus, galleries, fields for scale, opacity or fonts, dialog launchers, rich tooltips; groups collapse in narrow windows.
- **Quick Access Toolbar**, **KeyTips** (press Alt), **command search** (Alt, then Q), minimizing (Ctrl+F1).
- **Ribbon editor:** drag and drop commands into any group, create your own tabs and groups, hide and reorder, fully usable by keyboard, with undo.
- **Arrangements:** save, load, export and import complete ribbon setups as JSON files.
- **Appearance:** automatic, light or dark, three accent colors, own icon set, optional style for the whole QGIS window.
- **Extensions tab:** commands of installed plugins, your own Processing scripts and models, every toolbox tool.
- **Extra tools** where QGIS has no single command, for example a dialog for attribute domains.
- **English and German** user interface, following the QGIS language, with a built-in illustrated **guide** (Help › Plugins › QGIS Ribbon Guide).
- The print layout window has its own ribbon: tabs for the selected item, reports, templates and page sizes. It can be switched off separately.
- The ribbon only calls existing QGIS functions. The menu bar and panels stay unchanged. Deactivating the plugin, or **Classic QGIS Interface**, restores the QGIS toolbars and window layout exactly.

| | |
|---|---|
| ![Customize Ribbon](qgis_ribbon/help/images/en/editor.png) | ![Dark mode](qgis_ribbon/help/images/en/dark_window.jpg) |

## Installation

In QGIS: **Plugins › Manage and Install Plugins …**, search for *QGIS Ribbon*, **Install**.

Manual installation: download the ZIP of a release and use **Install from ZIP** in the same dialog.

Requirements: QGIS 3.44 or later, including QGIS 4. Developed and tested on Windows with QGIS 3.44.15 and QGIS 4.2.3. The automated tests also run on Linux with the same versions; on macOS they have only had a trial run. On macOS with QGIS 3.44 there are no KeyTips (see Troubleshooting). Older 4.x versions are not tested. No extra Python packages (PyYAML ships with QGIS).

## Documentation

The guide is part of the plugin and also readable here:

- English: [qgis_ribbon/help/en/index.md](qgis_ribbon/help/en/index.md)
- Deutsch: [qgis_ribbon/help/de/index.md](qgis_ribbon/help/de/index.md)

## Relation to ArcGIS Pro

The layout follows the ribbon concept of ArcGIS Pro so that users switching from it find their way around QGIS quickly. QGIS Ribbon is an independent project. It is **not affiliated with, sponsored or endorsed by Esri**. It contains no Esri icons, texts or graphics; all labels, descriptions and icons are its own. ArcGIS and ArcGIS Pro are trademarks of Esri.

## Reporting problems

Please use the [issue tracker](https://github.com/8snv5d5zcy-glitch/qgis-ribbon/issues). Helpful details: QGIS version, operating system, steps to reproduce, and messages from the log panel (tab *QGIS Ribbon*).

## Troubleshooting

**QGIS crashes at every start.** Up to version 1.7.0, QGIS 3.44 on macOS could crash shortly after start with the plugin active; 1.7.1 fixes this. To get QGIS running again, start it once without plugins and update or uninstall QGIS Ribbon in the plugin manager:

```
open -a QGIS --args --noplugins
```

(Windows: `qgis-ltr-bin.exe --noplugins` or `qgis-bin.exe --noplugins` in the `bin` folder of QGIS.) If that does not help, quit QGIS and delete the plugin folder `qgis_ribbon` in the profile folder:

- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

For QGIS 4 the folder is `QGIS4` instead of `QGIS3`; for another profile, its name instead of `default`.

**No KeyTips on macOS with QGIS 3.44.** There, the application-wide event filter the KeyTips need crashes QGIS (PyQt5 on macOS), so the plugin leaves them out. Menus that other plugins open from their own button then appear where that hidden toolbar button was. QGIS 4 on macOS is not affected.

## Development

```
qgis_ribbon/            the plugin (packaged into the ZIP)
  core/                 pure Python, no qgis imports, tested with pytest
  qgis_integration/     connection to QGIS
  ui/                   widgets and dialogs
  config/               ribbon definition (YAML), icons, themes
  i18n/                 translation catalogs (English -> German)
  help/                 guide pages and screenshots
tests/                  pytest (core without QGIS, qgis_app with QGIS)
tools/                  ZIP build, icon builder, guide screenshots, test runner for QGIS
```

- Tests without QGIS: `python -m pytest` (Python 3, pytest, PyYAML; tests that need QGIS are left out).
- All tests in QGIS Python (Windows): `tools\qgis_pytest.cmd`.
- Build the plugin ZIP: `python tools/build_zip.py` (writes `dist/qgis_ribbon-<version>.zip`).
- English is the source language. German texts are in `qgis_ribbon/i18n/de.json` (texts in the code) and `de_ribbon.json` and `de_ribbon_layout.json` (texts of the ribbon definitions). Other languages can be added as `<lang>.json`, `<lang>_ribbon.json` and `<lang>_ribbon_layout.json`.
- The ribbon definition `qgis_ribbon/config/ribbon_arcgis.yaml` describes tabs, groups, commands (with the QGIS action, menu, dialog or Processing tool they call), conditions and galleries; `core/config_loader.py` checks it on load.
- Icons are drawn at runtime from `config/icons/kontur.yaml`, which `tools/kontur_icons.py` generates.
- Screenshots of the guide: `tools/guide_screenshots.py` (runs inside QGIS, uses the Natural Earth world map shipped with QGIS).

## License

Copyright (C) 2026 Paul Liecke

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version. See [LICENSE](LICENSE).

Screenshots show map data from [Natural Earth](https://www.naturalearthdata.com) (public domain). The basemaps offered in the ribbon have their own terms: basemap.de © GeoBasis-DE / BKG (CC BY 4.0), OpenTopoMap © OpenStreetMap contributors, SRTM, © OpenTopoMap (CC-BY-SA).

---

## Deutsch

QGIS Ribbon ersetzt die Werkzeugleisten von QGIS durch ein Ribbon: Befehle in Tabs und Gruppen, Kontext-Tabs für den aktiven Layer, Schnellzugriffsleiste, Tastaturkürzel (Alt) und Befehlssuche. Das Ribbon lässt sich grafisch anpassen; Anordnungen lassen sich speichern und als Datei weitergeben. Die Oberfläche gibt es auf Deutsch und Englisch, sie folgt der Sprache von QGIS.

- Installation: **Erweiterungen › Erweiterungen verwalten und installieren …**, nach *QGIS Ribbon* suchen, **Installieren**.
- Anleitung: im Plugin unter **Hilfe › Erweiterungen › Anleitung QGIS Ribbon** oder hier: [qgis_ribbon/help/de/index.md](qgis_ribbon/help/de/index.md).
- Das Ribbon ruft nur vorhandene QGIS-Funktionen auf. Abschalten stellt die Werkzeugleisten von QGIS genau wieder her.
- Das Bedienkonzept folgt ArcGIS Pro. QGIS Ribbon ist ein unabhängiges Projekt, nicht mit Esri verbunden und nicht von Esri unterstützt, und enthält keine Icons, Texte oder Grafiken von Esri.
- Lizenz: GNU GPL Version 2 oder später.
