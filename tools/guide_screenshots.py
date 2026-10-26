"""Bilder für die Anleitung im echten QGIS, je Sprache.

Läuft als Startskript in QGIS mit eigenem Profil. Die Sprache von QGIS kommt
aus dem Profil (``[locale]`` in ``QGIS/QGIS3.ini``), die des Ribbons aus
``RIBBON_LANG``. Beispiel (PowerShell, Englisch):

    $p = "$env:TEMP\\guide_profil_en"
    New-Item -ItemType Directory -Force "$p\\profiles\\default\\QGIS" | Out-Null
    Set-Content -Encoding ascii "$p\\profiles\\default\\QGIS\\QGIS3.ini" `
        "[locale]`r`noverrideFlag=true`r`nuserLocale=en_US`r`nglobalLocale=en_US"
    $env:RIBBON_REPO = "<Projektordner>"; $env:RIBBON_LANG = "en"
    & "C:\\Program Files\\QGIS 3.44.15\\bin\\qgis-ltr-bin.exe" --profiles-path $p `
        --nologo --noversioncheck --noplugins --code tools\\guide_screenshots.py

Für Deutsch ``de_DE`` und ``RIBBON_LANG = "de"``. Das QGIS-Fenster muss
sichtbar sein (Menüs und Listen sind eigene Fenster und werden einzeln
aufgenommen und über das Fensterbild gelegt).

Daten: nur die mit QGIS gelieferte Weltkarte (Natural Earth, gemeinfrei),
``resources/data/world_map.gpkg``. Ergebnis: ``qgis_ribbon/help/images/<sprache>/``
und ``guide_screenshots_<sprache>.json`` (Fehler je Bild) im Temp-Ordner. Danach wird
QGIS beendet. Nur Standardbibliothek und QGIS.
"""

import json
import os
import re
import sys
import tempfile
import time
import traceback

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QPoint, QRect, Qt, QTimer
from qgis.PyQt.QtGui import QPainter, QPixmap
from qgis.utils import iface

REPO = os.environ.get("RIBBON_REPO") or os.getcwd()
LANG = os.environ.get("RIBBON_LANG", "en")
OUT = os.path.join(REPO, "qgis_ribbon", "help", "images", LANG)
WIDTH, HEIGHT = 1400, 860
WORLD = os.path.join(QgsApplication.pkgDataPath(), "resources", "data", "world_map.gpkg")


def settle(n=8):
    for _ in range(n):
        QgsApplication.processEvents()
        time.sleep(0.03)


def save(pix, name, jpg=False):
    path = os.path.join(OUT, name + (".jpg" if jpg else ".png"))
    if jpg:
        pix.save(path, "JPG", 88)
    else:
        pix.save(path, "PNG")
    return path


def composed(base, popups=(), crop=None):
    """Bild von ``base`` mit darübergelegten Fenstern (Menüs, Listen); optional zugeschnitten."""
    pix = base.grab()
    origin = base.mapToGlobal(QPoint(0, 0))
    painter = QPainter(pix)
    for w in popups:
        if w is not None and w.isVisible():
            painter.drawPixmap(w.mapToGlobal(QPoint(0, 0)) - origin, w.grab())
    painter.end()
    if crop is not None:
        pix = pix.copy(crop)
    return pix


def popup_bottom(base, popups):
    origin = base.mapToGlobal(QPoint(0, 0))
    return max((w.mapToGlobal(QPoint(0, 0)).y() - origin.y() + w.height() for w in popups if w.isVisible()),
               default=0)


def run():
    log = {"lang": LANG, "bilder": [], "fehler": {}}
    shots = []

    def shot(name):
        def deco(fn):
            shots.append((name, fn))
            return fn
        return deco

    try:
        os.makedirs(OUT, exist_ok=True)
        sys.path.insert(0, REPO)
        from qgis_ribbon.core import i18n
        i18n.set_language(LANG)
        from qgis_ribbon.plugin import RibbonPlugin
        from qgis_ribbon.ui import guide

        mw = iface.mainWindow()
        mw.showNormal()
        mw.resize(WIDTH, HEIGHT)
        mw.move(40, 40)
        project = QgsProject.instance()
        layers = {}
        for name in ("countries", "states_provinces"):
            lyr = QgsVectorLayer("%s|layername=%s" % (WORLD, name), name, "ogr")
            if lyr.isValid():
                lyr.loadDefaultStyle()
                project.addMapLayer(lyr)
                layers[name] = lyr
        if "states_provinces" in layers:
            iface.layerTreeView().layerTreeModel().rootGroup().findLayer(
                layers["states_provinces"]).setItemVisibilityChecked(False)
        settle()

        plugin = RibbonPlugin(iface)
        plugin.initGui()
        settle(20)
        w = plugin.widget
        bar = plugin.toolbar
        mw.raise_()
        mw.activateWindow()
        if "countries" in layers:
            iface.setActiveLayer(layers["countries"])
            iface.mapCanvas().setExtent(layers["countries"].extent())
        settle(30)
        iface.messageBar().clearWidgets()  # Meldungen des frischen Profils (z. B. Schriftdownload)
        settle()
        ribbon_rect =lambda: QRect(bar.mapTo(mw, QPoint(0, 0)), bar.size())  # noqa: E731

        @shot("window")
        def _():
            w.select_tab("karte")
            settle(20)
            return save(mw.grab(), "window", jpg=True)

        @shot("header")
        def _():
            return save(w.header.grab(), "header")

        @shot("tab_map")
        def _():
            w.select_tab("karte")
            settle()
            return save(bar.grab(), "tab_map")

        @shot("tab_edit")
        def _():
            w.select_tab("bearbeiten")
            settle()
            return save(bar.grab(), "tab_edit")

        @shot("contextual")
        def _():
            w.select_tab("vektor_darstellung")
            settle()
            return save(bar.grab(), "contextual")

        @shot("keytips")
        def _():
            w.select_tab("karte")
            settle()
            plugin.keytips.start()
            settle()
            pix = bar.grab()
            plugin.keytips.exit()
            return save(pix, "keytips")

        @shot("keytips_tab")
        def _():
            plugin.keytips.start()
            plugin.keytips.show_level1("karte")
            settle()
            pix = bar.grab()
            plugin.keytips.exit()
            return save(pix, "keytips_tab")

        @shot("search")
        def _():
            box = w.search
            box.setFocus()
            box.setText("buf")
            box.update_results("buf")
            settle()
            popup = box.completer.popup()
            rect = ribbon_rect()
            bottom = max(rect.bottom(), popup_bottom(mw, [popup]) + 8)
            pix = composed(mw, [popup], QRect(0, rect.top(), mw.width(), bottom - rect.top()))
            popup.hide()
            box.clear()
            iface.mapCanvas().setFocus()
            return save(pix, "search")

        @shot("context_menu")
        def _():
            w.select_tab("karte")
            settle()
            menu = w.context_menu(None)
            menu.popup(w.mapToGlobal(QPoint(420, 80)))
            settle()
            rect = ribbon_rect()
            bottom = popup_bottom(mw, [menu]) + 8
            pix = composed(mw, [menu], QRect(0, rect.top(), mw.width(), bottom - rect.top()))
            menu.hide()
            menu.deleteLater()
            return save(pix, "context_menu")

        @shot("appearance_menu")
        def _():
            from qgis.PyQt.QtWidgets import QMenu
            menu = QMenu(w)
            sub = w.add_design_menu(menu)
            menu.popup(w.mapToGlobal(QPoint(420, 80)))
            settle()
            act = sub.menuAction()
            menu.setActiveAction(act)
            sub.popup(menu.mapToGlobal(menu.actionGeometry(act).topRight()))
            settle()
            rect = ribbon_rect()
            bottom = popup_bottom(mw, [menu, sub]) + 8
            pix = composed(mw, [menu, sub], QRect(0, rect.top(), mw.width(), bottom - rect.top()))
            sub.hide()
            menu.hide()
            menu.deleteLater()
            return save(pix, "appearance_menu")

        @shot("quick_access_menu")
        def _():
            menu = w.quick.menu
            menu.popup(w.quick.customize.mapToGlobal(QPoint(0, w.quick.customize.height())))
            settle()
            rect = ribbon_rect()
            bottom = popup_bottom(mw, [menu]) + 8
            pix = composed(mw, [menu], QRect(0, rect.top(), mw.width(), bottom - rect.top()))
            menu.hide()
            return save(pix, "quick_access_menu")

        @shot("minimized")
        def _():
            w.set_minimized(True, save=False)
            settle()
            rect = ribbon_rect()
            pix = mw.grab().copy(QRect(0, rect.top(), mw.width(), rect.height() + 140))
            w.set_minimized(False, save=False)
            settle()
            return save(pix, "minimized")

        @shot("extensions")
        def _():
            w.select_tab("erweiterungen")
            settle()
            return save(bar.grab(), "extensions")

        @shot("dark")
        def _():
            w.select_tab("karte")
            plugin.themes.set("mode", "dunkel")
            settle(15)
            pix = bar.grab()
            plugin.themes.set("whole", True)
            settle(20)
            whole = mw.grab()
            plugin.themes.set("whole", False)
            plugin.themes.set("mode", "auto")
            settle(15)
            save(whole, "dark_window", jpg=True)
            return save(pix, "dark")

        def dialog_shot(name, dlg, size=None):
            if size is not None:
                dlg.resize(*size)
            dlg.show()
            settle(20)
            pix = dlg.grab()
            dlg.reject()
            dlg.deleteLater()
            settle()
            return save(pix, name)

        @shot("editor")
        def _():
            return dialog_shot("editor", w.customize_dialog(), (1240, 760))

        @shot("keytip_dialog")
        def _():
            return dialog_shot("keytip_dialog", w.keytip_dialog(), (760, 560))

        @shot("gallery_dialog")
        def _():
            from qgis_ribbon.ui.customize_dialog import GalleryDialog
            return dialog_shot("gallery_dialog", GalleryDialog(plugin.arrangements, "processing_galerie", mw),
                               (860, 560))

        @shot("domains")
        def _():
            from qgis_ribbon.qgis_integration import domains as store_mod
            from qgis_ribbon.ui.domain_dialog import DomainDialog
            from qgis.PyQt.QtWidgets import QLabel
            lyr = layers.get("countries")
            dlg = DomainDialog(lyr, store_mod.store_for(lyr), mw)
            # Nur im Dialog (nicht gespeichert): Beispieldomäne, Ordner der Datenquelle ausgeblendet
            head = dlg.findChild(QLabel, "ribbon_domain_source")
            head.setText(re.sub(r"[A-Za-z]:[/\\].*[/\\]", "", head.text()))
            dlg.new_domain("coded")
            dlg.name_edit.setText("continent")
            dlg.desc_edit.setText("Continent" if LANG == "en" else "Kontinent")
            names = (["Africa", "Asia", "Europe", "North America", "South America", "Oceania"] if LANG == "en"
                     else ["Afrika", "Asien", "Europa", "Nordamerika", "Südamerika", "Ozeanien"])
            for code, label in zip(["AF", "AS", "EU", "NA", "SA", "OC"], names):
                dlg._append_row(code, label)
            dlg._edited()
            return dialog_shot("domains", dlg, (860, 560))

        @shot("guide")
        def _():
            dlg = guide.show_help("ribbon", mw)
            dlg.resize(900, 640)
            settle(20)
            dlg.show_topic("ribbon")
            settle(10)
            pix = dlg.grab()
            guide.close_help()
            return save(pix, "guide")

        for name, fn in shots:
            try:
                log["bilder"].append(os.path.basename(fn()))
            except Exception:  # noqa: BLE001 - übrige Bilder trotzdem
                log["fehler"][name] = traceback.format_exc()
        plugin.unload()
        settle()
    except Exception:  # noqa: BLE001 - Ergebnis immer schreiben
        log["fehler"]["start"] = traceback.format_exc()
    with open(os.path.join(tempfile.gettempdir(), "guide_screenshots_%s.json" % LANG), "w",
              encoding="utf-8") as fh:
        json.dump(log, fh, indent=2, ensure_ascii=False)
    QgsProject.instance().clear()
    QgsProject.instance().setDirty(False)
    QTimer.singleShot(200, QgsApplication.instance().quit)


QTimer.singleShot(2500, run)
