"""Hilfe: Bedienungsanleitung des Ribbons in einem QGIS-Fenster.

Die Anleitung liegt als Markdown in ``qgis_ribbon/help/<sprache>/``, eine
Datei je Thema (``TOPICS``), Bilder in ``help/images/<sprache>/``. Dieselben
Dateien zeigt GitHub als Dokumentation. ``HelpBrowser`` stellt sie mit
``QTextBrowser.setMarkdown`` dar: Links auf andere Seiten bleiben im Fenster
(mit Zurück/Vor), Links ins Netz öffnet der Standardbrowser. Bilder werden
auf die Fensterbreite verkleinert. Sprache wie die Oberfläche
(``core.i18n``); fehlt eine Seite, gilt die englische.

Aufrufwege: Button „?“ in der Kopfzeile des Ribbons, Menü ▾ und Rechtsklick
(„Ribbon-Anleitung …“), QGIS-Menü Hilfe › Plugins und „Hilfe“ in den
Dialogen des Ribbons (jeweils mit passendem Thema). Es gibt höchstens ein
Fenster; ``show_help`` bringt es nach vorn und wechselt das Thema,
``close_help`` schließt es beim Entladen.
"""

import io
import os

from qgis.PyQt.QtCore import QSize, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QImageReader, QTextCursor
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QTextBrowser,
                                 QToolButton, QVBoxLayout)

from ..core import i18n
from ..core.i18n import tr
from . import theme

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "help")
TOPICS = ("index", "ribbon", "keyboard", "customize", "appearance", "extensions", "tools",
          "troubleshooting")
ONLINE = "https://github.com/8snv5d5zcy-glitch/qgis-ribbon/blob/main/qgis_ribbon/help/%s/%s.md"
TITLE = tr("QGIS Ribbon Guide")
MENU_TEXT = tr("Ribbon Guide …")
TIP = tr("Guide: using and customizing the ribbon")
IMAGE_MARGIN = 28

_window = {"dialog": None}


def page_path(topic, language=None):
    """Datei eines Themas in der Sprache (sonst Englisch); None, wenn es keine gibt."""
    for lang in (language or i18n.language(), i18n.SOURCE_LANGUAGE):
        path = os.path.join(HELP_DIR, lang, "%s.md" % topic)
        if os.path.isfile(path):
            return path
    return None


def topic_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def language_of(path):
    return os.path.basename(os.path.dirname(path))


class HelpBrowser(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent, Qt.Window)
        self.setObjectName("ribbon_help")
        theme.style_dialog(self)
        self.setWindowTitle(TITLE)
        self.resize(940, 760)
        self.history = []
        self.position = -1
        self.path = None

        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.back = self._button(tr("Back"), self.go_back)
        self.forward = self._button(tr("Forward"), self.go_forward)
        self.home = self._button(tr("Contents"), lambda: self.show_topic("index"))
        self.online = self._button(tr("Open Online"), self.open_online)
        self.online.setToolTip(tr("Open this page on GitHub in the web browser"))
        for b in (self.back, self.forward, self.home):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.online)
        lay.addLayout(bar)
        self.view = QTextBrowser(self)
        self.view.setObjectName("ribbon_help_view")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        lay.addWidget(self.view, 1)
        self._update_buttons()

    def _button(self, text, slot):
        b = QToolButton(self)
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.clicked.connect(slot)
        return b

    # Navigation
    def show_topic(self, topic):
        path = page_path(topic) or page_path("index")
        if path is not None:
            self.open_path(path)

    def open_path(self, path, record=True):
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
        doc = self.view.document()
        doc.setBaseUrl(QUrl.fromLocalFile(path))
        self.view.setMarkdown(text)
        self._fit_images(path)
        self.path = path
        title = next((ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("#")), "")
        self.setWindowTitle("%s – %s" % (TITLE, title) if title else TITLE)
        if record:
            del self.history[self.position + 1:]
            self.history.append(path)
            self.position = len(self.history) - 1
        self._update_buttons()

    def go_back(self):
        if self.position > 0:
            self.position -= 1
            self.open_path(self.history[self.position], record=False)

    def go_forward(self):
        if self.position < len(self.history) - 1:
            self.position += 1
            self.open_path(self.history[self.position], record=False)

    def open_online(self):
        if self.path is not None:
            QDesktopServices.openUrl(QUrl(ONLINE % (language_of(self.path), topic_of(self.path))))

    def _update_buttons(self):
        self.back.setEnabled(self.position > 0)
        self.forward.setEnabled(self.position < len(self.history) - 1)

    def _on_link(self, url):
        if url.isRelative() and self.path is not None:
            url = QUrl.fromLocalFile(self.path).resolved(url)
        if url.isLocalFile():
            target = url.toLocalFile()
            if target.endswith(".md") and os.path.isfile(target):
                self.open_path(target)
                return
        QDesktopServices.openUrl(url)

    # Bilder
    def _fit_images(self, path):
        """Bilder breiter als das Fenster verkleinern (Seitenverhältnis bleibt)."""
        width = max(200, self.view.viewport().width() - IMAGE_MARGIN)
        base = QUrl.fromLocalFile(path)
        doc = self.view.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isImageFormat():
                    img = fmt.toImageFormat()
                    size = QImageReader(base.resolved(QUrl(img.name())).toLocalFile()).size()
                    if size.isValid() and size.width() > width:
                        img.setWidth(width)
                        img.setHeight(size.height() * width / size.width())
                        cur = QTextCursor(doc)
                        cur.setPosition(frag.position())
                        cur.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                        cur.setCharFormat(img)
                it += 1
            block = block.next()

    def resizeEvent(self, event):  # noqa: N802 (Qt)
        QDialog.resizeEvent(self, event)
        if self.path is not None and event.oldSize() != QSize(-1, -1) \
                and abs(event.size().width() - event.oldSize().width()) > 40:
            bar = self.view.verticalScrollBar()
            pos = bar.value()
            self.open_path(self.path, record=False)
            bar.setValue(pos)


def show_help(topic="index", parent=None):
    """Anleitung zum Thema zeigen (ein Fenster für alle Aufrufe).

    Ist ein modaler Dialog offen (Editor, Kürzel …), gehört das Fenster ihm:
    sonst sperrt der Dialog die Eingabe in die Anleitung.
    """
    owner = QApplication.activeModalWidget() or parent
    dlg = _window["dialog"]
    if dlg is not None and dlg.parentWidget() is not owner:
        close_help()
        dlg = None
    if dlg is None:
        dlg = HelpBrowser(owner)
        dlg.destroyed.connect(lambda _o=None: _window.update(dialog=None))
        _window["dialog"] = dlg
    dlg.show()
    dlg.show_topic(topic)
    dlg.raise_()
    dlg.activateWindow()
    return dlg


def close_help():
    dlg = _window["dialog"]
    _window["dialog"] = None
    if dlg is not None:
        dlg.close()
        dlg.setParent(None)
        dlg.deleteLater()


def help_button(box, topic, parent):
    """Knopf „Hilfe“ in einer ``QDialogButtonBox``, öffnet das Thema."""
    btn = box.addButton(QDialogButtonBox.Help)
    btn.setText(tr("Help"))
    box.helpRequested.connect(lambda: show_help(topic, parent))
    return btn
