"""Grafischer Ribbon-Editor „Ribbon anpassen“.

Aufbau:

- Kopf: Titel, aktuelle Anordnung, Rückgängig/Wiederholen;
- Tableiste: Tabs wie im Ribbon, Auge blendet aus, „＋ Tab“;
- Schnellzugriff (Befehle hineinziehen, sortieren, herausziehen) und
  Vorschau des gewählten Tabs: Gruppen als
  Karten mit ihren Einträgen in echter Größe und mit Kontur-Icons;
- unten links die Palette (alle Befehle oder Gruppen der Definition),
  unten rechts die Eigenschaften des gewählten Elements.

Alle Änderungen laufen über ``core.editor.Editor`` (mit Verlauf). Der
Dialog baut nach jeder Änderung Tableiste und Vorschau neu auf und stellt
die Auswahl wieder her (Orte statt Objekte). Gespeichert wird erst mit
„Speichern“ (``Arrangements.save_editor``); danach baut das Plugin den
Ribbon neu auf.

Ziehen und Ablegen: Befehle und Gruppen aus der Palette, Einträge
innerhalb und zwischen Gruppen und Tabs (über einem Tab wechselt die
Vorschau nach kurzer Zeit), Gruppen und Tabs sortieren, zurück in die
Palette entfernt. Gültige Ziele zeigen eine Einfügemarke, ungültige nichts
(der Grund steht in der Statuszeile); am Rand rollt die Vorschau mit.
Geprüft wird mit denselben Regeln wie beim Einfügen per Tastatur
(``core.editor.can_*``). Abgelegt wird erst nach ``QDrag.exec``.

Tastatur (alles ohne Maus bedienbar): Pfeiltasten wählen, Strg+Pfeil
verschiebt, Entf entfernt, Strg+X/Strg+V verschiebt zwischen Gruppen und
Tabs, Eingabe auf einer Palettenkachel fügt in die gewählte Gruppe ein, F2
benennt um, Leertaste blendet ein und aus, Strg+Z/Strg+Y.
"""

from qgis.PyQt.QtCore import QPoint, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QCursor, QDrag, QKeySequence
from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                                 QLineEdit, QMenu, QMessageBox, QPushButton, QShortcut, QSplitter,
                                 QToolButton, QVBoxLayout)

from ..core import customization as cz
from ..core import editor as ed
from ..core.editor import EditError, Editor, Place
from ..core.model import CommandRef, Menu, Row, Split
from ..core.search import ribbon_entries
from . import guide, icons, theme
from .editor_widgets import (MIME_TYPE, GroupCard, NewGroupCard, Palette, Preview, QuickStrip, TabChip,
                             TabStrip, chip_pixmap, drag_pixmap, menu_entries, mime, scroll_area)
from ..core.i18n import tr

TITLE = tr("Customize Ribbon")
DEFAULT_SIZE = (1200, 760)
FIXED_TAB_LABEL = tr("Tabs of the definition keep their label.")
NEED_GROUP = tr("Please select a group in the preview first (or “＋ Group”).")
ONLY_HIDE_TAB = tr("Contextual tabs of the definition can only be hidden.")
REMOVE_TAB_TEXT = tr("Really delete the default tab “%s”? You can bring it back with "
                     "“Restore Deleted Tab”.")
DISCARD_TEXT = tr("The changes in the editor will be lost. Close anyway?")
HOVER_SWITCH_MS = 600       # über einem Tab: so lange, bis die Vorschau wechselt
SCROLL_MARGIN = 36          # Rand der Vorschau, an dem beim Ziehen gerollt wird
SCROLL_STEP = 18
SCROLL_MS = 30
TAB_ORDER_HINT = tr("Main tabs come before contextual tabs.")
QUICK_ONLY_BUTTONS = tr("Only buttons can go into Quick Access (no controls, galleries or menus).")


def confirm_discard(parent):
    """Rückfrage beim Schließen mit Änderungen (in Tests ersetzt)."""
    answer = QMessageBox.question(parent, TITLE, DISCARD_TEXT, QMessageBox.Yes | QMessageBox.No,
                                  QMessageBox.No)
    return answer == QMessageBox.Yes


def confirm_remove_tab(parent, label):
    """Rückfrage vor dem Löschen eines Haupt-Tabs der Definition (in Tests ersetzt)."""
    answer = QMessageBox.question(parent, TITLE, REMOVE_TAB_TEXT % label, QMessageBox.Yes | QMessageBox.No,
                                  QMessageBox.No)
    return answer == QMessageBox.Yes


def tab_title(tab):
    return "%s: %s" % (tab.context, tab.label) if tab.contextual else tab.label


def kind_text(element):
    if isinstance(element, Split):
        return tr("Split button of the definition (content view only)")
    if isinstance(element, Menu):
        return tr("Menu of the definition (content view only)")
    if isinstance(element, Row):
        return tr("Row of the definition")
    if isinstance(element, CommandRef):
        cmd = element.command
        if cmd.gallery is not None:
            return tr("Gallery")
        return tr("Control") if cmd.kind == "control" else tr("Command")
    return tr("Missing in the definition")


def editor_qss(t):
    c = lambda k: theme.css(k, t)  # noqa: E731
    return "\n".join([
        "#ribbon_editor_title { font-size: 15px; font-weight: 600; color: %s; }" % c("text"),
        "#ribbon_editor_caption { color: %s; font-weight: 600; }" % c("muted"),
        "#ribbon_editor_empty { color: %s; }" % c("faint"),
        "#ribbon_editor_preview, #ribbon_editor_tabs, #ribbon_editor_quick { background: transparent; }",
        ("QScrollArea#ribbon_editor_scroll, QScrollArea#ribbon_editor_scroll > QWidget#qt_scrollarea_viewport "
         "{ background: transparent; border: 0px; }"),
        ("#ribbon_editor_preview_frame { background: %s; border: 1px solid %s; border-radius: 10px; }"
         % (c("win"), c("div"))),
        ("#ribbon_editor_props { background: %s; border: 1px solid %s; border-radius: 8px; }"
         % (c("surf"), c("bord"))),
        "#ribbon_editor_props QLabel#ribbon_editor_prop_title { font-weight: 600; font-size: 13px; }",
        "#ribbon_editor_props QLabel#ribbon_editor_prop_muted { color: %s; }" % c("muted"),
        ("QToolButton#ribbon_editor_size, QToolButton#ribbon_editor_mode { border: 1px solid %s; "
         "padding: 3px 10px; border-radius: 6px; }") % c("bord"),
        ("QToolButton#ribbon_editor_size:checked, QToolButton#ribbon_editor_mode:checked "
         "{ background: %s; color: %s; border-color: %s; }") % (c("accS"), c("accT"), c("acc")),
        "QToolButton#ribbon_editor_eye, QToolButton#ribbon_editor_more { padding: 1px; border-radius: 4px; }",
    ])


class RibbonEditor(QDialog):
    def __init__(self, arrangements, parent=None):
        QDialog.__init__(self, parent)
        self.setObjectName("ribbon_editor")
        self.setWindowTitle(TITLE)
        self.setStyleSheet(theme.dialog_qss(theme.current()) + "\n" + editor_qss(theme.current()))
        self.arrangements = arrangements
        # Mit allen Werkzeugen des Werkzeugkastens; ohne Plugin die Definition selbst
        self.base = arrangements.editor_base() if hasattr(arrangements, "editor_base") else arrangements.base
        self.editor = Editor(self.base, arrangements.current(), arrangements.quick_ids())
        self._warnings = list(arrangements.warnings)
        self.places = {e.ref[0].id: e.path for e in ribbon_entries(self.base)}
        main = [t for t in self.editor.arr.tabs if not t.contextual]
        self.current_tab = (main or self.editor.arr.tabs)[0].id
        self.selection = ("tab", self.current_tab)
        self.target = None          # Gruppe, in die die Palette einfügt (Place)
        self.target_item = None     # Eintrag darin, hinter den eingefügt wird
        self.clip = None            # ausgeschnittener Eintrag (Place)
        self.widgets = {}           # Auswahl -> Widget
        self._message = ""
        self._error = False
        self._label_edit = None
        self._drag = None           # laufender Zieh-Vorgang: Nutzlast wie die Auswahl
        self._drag_running = False  # innerhalb von QDrag.exec
        self._drag_source = None
        self._pending = None        # Ablegen, das nach QDrag.exec ausgeführt wird
        self._graveyard = None      # beim Ziehen abgebaute Widgets (erst danach löschen)
        self._hover_tab = None
        self._scroll = None
        self._tab_sig = None
        self._quick_sig = None
        self._refreshing = False
        self._build()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_SWITCH_MS)
        self._hover_timer.timeout.connect(self._hover_switch)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(SCROLL_MS)
        self._scroll_timer.timeout.connect(self._scroll_tick)
        size = self._user_size()
        self.resize(*size)
        self.refresh()
        if self._warnings:
            self.set_status(tr("Notes while reading the customization: ") + "; ".join(self._warnings))

    # Aufbau
    def _user_size(self):
        user = getattr(self.arrangements, "user", None)
        stored = user.editor_size() if user is not None and hasattr(user, "editor_size") else None
        return stored or DEFAULT_SIZE

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(TITLE, self)
        title.setObjectName("ribbon_editor_title")
        head.addWidget(title)
        head.addSpacing(16)
        self.arrangement_label = QLabel(self)
        self.arrangement_label.setObjectName("ribbon_editor_caption")
        head.addWidget(self.arrangement_label)
        head.addStretch(1)
        self.undo_button = QToolButton(self)
        self.undo_button.setObjectName("ribbon_editor_undo")
        self.undo_button.setIcon(icons.ui_icon("rueckgaengig"))
        self.undo_button.setIconSize(QSize(18, 18))
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QToolButton(self)
        self.redo_button.setObjectName("ribbon_editor_redo")
        self.redo_button.setIcon(icons.ui_icon("wiederholen"))
        self.redo_button.setIconSize(QSize(18, 18))
        self.redo_button.clicked.connect(self.redo)
        for b, text in ((self.undo_button, tr("Undo")), (self.redo_button, tr("Redo"))):
            b.setFocusPolicy(Qt.TabFocus)
            if b.icon().isNull():
                b.setText(text)
            head.addWidget(b)
        lay.addLayout(head)

        self.tab_strip = TabStrip(self, self)
        self.add_tab_button = QToolButton(self.tab_strip)
        self.add_tab_button.setObjectName("ribbon_editor_add_tab")
        self.add_tab_button.setText(tr("＋ Tab"))
        self.add_tab_button.setToolTip(tr("Create a custom tab"))
        self.add_tab_button.clicked.connect(self.new_tab)
        self.tab_area = scroll_area(self.tab_strip)
        self.tab_area.setFixedHeight(40)
        lay.addWidget(self.tab_area)

        frame = QFrame(self)
        frame.setObjectName("ribbon_editor_preview_frame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(6, 6, 6, 6)
        fl.setSpacing(6)
        self.quick = QuickStrip(self, frame)
        fl.addWidget(self.quick)
        self.preview = Preview(frame)
        self.preview_area = scroll_area(self.preview)
        self.preview_area.setFixedHeight(GroupCard.HEIGHT + 16 + 12)   # Ränder und Bildlaufleiste
        fl.addWidget(self.preview_area)
        lay.addWidget(frame)

        split = QSplitter(Qt.Horizontal, self)
        self.palette_box = Palette(self, self.base, split)
        split.addWidget(self.palette_box)
        self.props = QFrame(split)
        self.props.setObjectName("ribbon_editor_props")
        self.props_lay = QVBoxLayout(self.props)
        self.props_lay.setContentsMargins(12, 10, 12, 10)
        self.props_lay.setSpacing(6)
        split.addWidget(self.props)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 420])
        lay.addWidget(split, 1)

        self.status = QLabel(self)
        self.status.setObjectName("ribbon_editor_status")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        foot = QHBoxLayout()
        self.reset_button = QPushButton(tr("Restore Defaults"), self)
        self.reset_button.setToolTip(
            tr("Tabs, groups and Quick Access as in the definition (can be undone; galleries stay)"))
        self.reset_button.clicked.connect(self.reset_all)
        foot.addWidget(self.reset_button)
        self.restore_button = QPushButton(tr("Restore Deleted Tab"), self)
        self.restore_button.setObjectName("ribbon_editor_restore_tab")
        self.restore_button.setToolTip(tr("Bring back a deleted tab of the definition with all its groups"))
        self.restore_menu = QMenu(self.restore_button)
        self.restore_menu.aboutToShow.connect(self._fill_restore_menu)
        self.restore_button.setMenu(self.restore_menu)
        foot.addWidget(self.restore_button)
        self.help_button = QPushButton(tr("Help"), self)
        self.help_button.setToolTip(tr("Guide: customizing the ribbon (F1)"))
        self.help_button.clicked.connect(lambda: guide.show_help("customize", self))
        foot.addWidget(self.help_button)
        foot.addStretch(1)
        self.cancel_button = QPushButton(tr("Cancel"), self)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton(tr("Save"), self)
        self.save_button.setObjectName("ribbon_editor_save")
        self.save_button.clicked.connect(self.save)
        for b in (self.reset_button, self.restore_button, self.help_button, self.cancel_button,
                  self.save_button):
            b.setAutoDefault(False)
            b.setDefault(False)
        foot.addWidget(self.cancel_button)
        foot.addWidget(self.save_button)
        lay.addLayout(foot)

        keys = [(QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo), (QKeySequence.Save, self.save),
                (QKeySequence.HelpContents, lambda: guide.show_help("customize", self))]
        if QKeySequence("Ctrl+Y") not in QKeySequence.keyBindings(QKeySequence.Redo):
            keys.append((QKeySequence("Ctrl+Y"), self.redo))   # Strg+Y auch außerhalb von Windows
        for seq, slot in keys:
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)

    # Auffrischen
    def refresh(self, focus=False):
        """Tableiste, Schnellzugriff und Vorschau neu aufbauen und die Auswahl wiederherstellen."""
        self._refreshing = True   # Fokuswechsel beim Abbau ändern die Auswahl nicht
        try:
            self._refresh(focus)
        finally:
            self._refreshing = False

    def _refresh(self, focus):
        arr = self.editor.arr
        ids = [t.id for t in arr.tabs]
        if self.current_tab not in ids:
            self.current_tab = ids[0]
        self.widgets = {}
        keep = self._graveyard if self._drag_running else None
        sig = []
        for t in arr.tabs:
            title = tab_title(self.base.tab(t.id)) if t.standard else t.label
            context = self.base.tab(t.id).context if t.standard else None
            sig.append((t.id, title, context, t.visible))
        if sig != self._tab_sig:
            # Tableiste nur bei Änderungen neu: ein Klick auf einen Tab behält seinen Chip (Ziehen)
            chips = []
            for (tab_id, title, context, visible), t in zip(sig, arr.tabs):
                chip = TabChip(self, t, title, context, tab_id == self.current_tab, self.tab_strip)
                chip.setAccessibleName(tr("Tab %s%s") % (title, "" if visible else tr(", hidden")))
                chips.append(chip)
            self.tab_strip.fill(chips, self.add_tab_button, keep)
            self._tab_sig = sig
        for chip in self.tab_strip.chips:
            chip.set_current(chip.sel[1] == self.current_tab)
            self.widgets[chip.sel] = chip

        quick_ids = [c for c in self.editor.quick_ids() if c in self.base.commands]
        if quick_ids != self._quick_sig:
            self.quick.fill([self.base.commands[c] for c in quick_ids], keep)
            self._quick_sig = quick_ids
        for tile in self.quick.tiles:
            self.widgets[tile.sel] = tile

        # Beim Abbau wandert der Fokus weiter und QScrollArea rollt dorthin; Position behalten
        bar = self.preview_area.horizontalScrollBar()
        scroll = bar.value()
        self.preview.clear(keep)
        bar.setValue(scroll)
        tab = arr.tab(self.current_tab)
        for gi, group in enumerate(tab.groups):
            card = GroupCard(self, self.base, arr, tab.id, gi, self.preview)
            self.preview.lay.addWidget(card, 0, Qt.AlignTop)
            self.preview.cards.append(card)
            where = tr("Group %s") % group.label
            card.header.setAccessibleName(tr("Group %s%s%s") % (
                group.label, tr(", customized") if cz.is_modified(self.base, group) else "",
                "" if group.visible else tr(", hidden")))
            self.widgets[card.header.sel] = card.header
            for tile in card.tiles:
                tile.setAccessibleName(ed.describe(self.base, tile.item, where))
                tile.setToolTip(ed.describe(self.base, tile.item, where))
                tile.marked = self.clip == tile.sel[1]
                self.widgets[tile.sel] = tile
        self.preview.new_card = NewGroupCard(self, tab.id, self.preview)
        self.preview.lay.addWidget(self.preview.new_card, 0, Qt.AlignTop)
        self.widgets[self.preview.new_card.sel] = self.preview.new_card
        self.preview.lay.addStretch(1)

        self.palette_box.update_checks(ed.tab_commands(self.base, arr, self.current_tab)
                                       if self.palette_box.mode == Palette.MODE_COMMANDS else
                                       {g.ref for g in tab.groups if g.ref})
        self.palette_box.set_unused(self._unused())
        self._update_header()
        if self.selection not in self.widgets and self.selection[0] != "palette":
            self.selection = ("tab", self.current_tab)
        if self.target is not None and not self._valid_group(self.target):
            self.target, self.target_item = None, None
        # Neue Kinder zeigt Qt erst nach der Ereignisschleife; den Fokus brauchen sie sofort
        for w in list(self.preview.cards) + list(self.widgets.values()):
            w.show()
        self._apply_selection(focus)
        self._update_status()

    def _unused(self):
        if self.palette_box.mode == Palette.MODE_COMMANDS:
            used = ed.ribbon_commands(self.base, self.editor.arr)
            return set(self.base.commands) - used
        present = {g.ref for t in self.editor.arr.tabs if t.visible for g in t.groups if g.visible and g.ref}
        return set(cz.standard_groups(self.base)) - present

    def palette_mode_changed(self):
        if hasattr(self, "palette_box"):
            self.refresh()

    def _valid_group(self, place):
        try:
            return place.tab == self.current_tab and 0 <= place.group < len(self.editor.arr.tab(place.tab).groups)
        except KeyError:
            return False

    def _update_header(self):
        if self.editor.dirty:
            text = tr("Arrangement: changed (not saved yet)")
        elif self.arrangements.is_standard():
            text = tr("Arrangement: Default")
        else:
            name = self.arrangements.active_name()
            text = tr("Arrangement: %s") % (name or tr("customized"))
        self.arrangement_label.setText(text)
        self.undo_button.setEnabled(self.editor.can_undo)
        self.redo_button.setEnabled(self.editor.can_redo)
        self.undo_button.setToolTip(tr("Undo: %s (Ctrl+Z)") % self.editor.undo_label()
                                    if self.editor.can_undo else tr("Undo (Ctrl+Z)"))
        self.redo_button.setToolTip(tr("Redo: %s (Ctrl+Y)") % self.editor.redo_label()
                                    if self.editor.can_redo else tr("Redo (Ctrl+Y)"))

    def set_status(self, text, error=False):
        self._message = text or ""
        self._error = error
        self._update_status()

    def _update_status(self):
        problems = self.editor.problems()
        self.save_button.setEnabled(not problems)
        self.restore_button.setEnabled(bool(self.editor.removed_tabs()))
        empty = [g.label for t in self.editor.arr.tabs for g in t.groups if g.custom and not g.items]
        if problems:
            text, error = tr("Cannot be saved: ") + " ".join(problems), True
        else:
            text, error = self._message, self._error
            if empty:
                hint = tr("Empty custom groups are discarded when saving: %s.") % ", ".join(
                    tr("“%s”") % e for e in empty)
                text = (text + " " + hint).strip()
        self.status.setText(text)
        self.status.setStyleSheet("color: %s;" % theme.css("err") if error else "")

    # Auswahl
    def focus_in(self, sel):
        """Ein Teil bekommt den Fokus (Tab-Taste, Klick): wählen, außer beim Neuaufbau."""
        if not self._refreshing:
            self.select(sel)

    def select(self, sel, focus=False):
        """Element wählen; ein anderer Tab wechselt die Vorschau."""
        kind = sel[0]
        if kind == "tab" and sel[1] != self.current_tab:
            self.current_tab = sel[1]
            self.selection = sel
            self.refresh(focus=focus)
            self.preview_area.horizontalScrollBar().setValue(0)
            return
        if kind in ("group", "item"):
            place = sel[1]
            self.target = Place(place.tab, place.group)
            self.target_item = place.item if kind == "item" else None
        self.selection = sel
        self._apply_selection(focus)

    def _apply_selection(self, focus=False):
        for s, w in self.widgets.items():
            w.set_selected(s == self.selection)
        for card in self.preview.cards:
            card.update()
        widget = self.widgets.get(self.selection)
        if widget is not None:
            if focus:
                widget.setFocus(Qt.OtherFocusReason)
            if self.selection[0] in ("group", "item", "newgroup"):
                self.preview_area.ensureWidgetVisible(widget, 20, 4)
            elif self.selection[0] == "tab":
                self.tab_area.ensureWidgetVisible(widget, 20, 0)
        self._fill_properties()

    def is_target(self, place):
        return self.target == place

    def selected_widget(self):
        return self.widgets.get(self.selection)

    def widget_for(self, sel):
        return self.widgets[sel]

    def card(self, gi):
        return self.preview.cards[gi]

    # Ausführen
    def do(self, fn, *args, select=None, message=None, **kwargs):
        """Editor-Operation ausführen; Hinweis bei ``EditError``. Gibt das Ergebnis oder None zurück."""
        try:
            result = fn(*args, **kwargs)
        except EditError as exc:
            self.set_status(str(exc), error=True)
            return None
        if select is not None:
            new_sel = select(result) if callable(select) else select
            if new_sel is not None:
                if new_sel[0] == "tab":
                    self.current_tab = new_sel[1]
                elif new_sel[0] in ("group", "item", "newgroup"):
                    self.current_tab = new_sel[1].tab if new_sel[0] != "newgroup" else new_sel[1]
                    if new_sel[0] in ("group", "item"):
                        self.target = Place(new_sel[1].tab, new_sel[1].group)
                        self.target_item = new_sel[1].item
                self.selection = new_sel
        self._message, self._error = (message or ""), False
        self.refresh(focus=self._focus_in_editor())
        return result if result is not None else True

    def _focus_in_editor(self):
        """Fokus nach einer Änderung auf die Auswahl, außer Palette und Eingabefelder behalten ihn."""
        w = self.focusWidget()
        keep = (self.palette_box.list, self.palette_box.search, self.palette_box.filter, self._label_edit)
        return w not in keep

    def undo(self):
        label = self.editor.undo()
        if label:
            self._message, self._error = tr("Undone: %s") % label, False
            self.refresh(focus=True)

    def redo(self):
        label = self.editor.redo()
        if label:
            self._message, self._error = tr("Redone: %s") % label, False
            self.refresh(focus=True)

    # Tabs
    def new_tab(self):
        index = None
        if self.selection[0] == "tab":
            index = ed.tab_index(self.editor.arr, self.selection[1]) + 1
        return self.do(self.editor.new_tab, index, select=lambda p: ("tab", p.tab),
                       message=tr("New tab created. Change the label on the right (F2)."))

    # Gruppen
    def new_group(self, item=None):
        tab = self.editor.arr.tab(self.current_tab)
        index = self.target.group + 1 if self.target is not None and self._valid_group(self.target) \
            else len(tab.groups)
        return self.do(self.editor.new_group, self.current_tab, index, item=item,
                       select=lambda p: ("group", p),
                       message=tr("New group created. Insert commands from the palette (Enter) or drag them in."))

    def toggle_visible(self, sel):
        kind = sel[0]
        if kind == "tab":
            tab = self.editor.arr.tab(sel[1])
            return self.do(self.editor.set_tab_visible, sel[1], not tab.visible, select=sel)
        if kind in ("group", "item"):
            place = sel[1]
            group = self.editor.arr.tab(place.tab).groups[place.group]
            return self.do(self.editor.set_group_visible, place.tab, place.group, not group.visible,
                           select=("group", Place(place.tab, place.group)))
        return None

    def group_menu(self, sel, button=None):
        """Menü ⋯ einer Gruppe (ohne Anzeige für Tests über ``group_menu_actions``)."""
        self.select(sel)
        menu = self.group_menu_actions(sel)
        if button is not None:
            menu.popup(button.mapToGlobal(button.rect().bottomLeft()))
        return menu

    def group_menu_actions(self, sel):
        place = sel[1]
        tab = self.editor.arr.tab(place.tab)
        group = tab.groups[place.group]
        menu = QMenu(self)
        menu.addAction(tr("Rename (F2)"), lambda: self.rename(sel))
        menu.addAction(tr("Hide") if group.visible else tr("Show"), lambda: self.toggle_visible(sel))
        act = menu.addAction(tr("Reset to Default"), lambda: self.reset_group(sel))
        act.setEnabled(cz.is_modified(self.base, group))
        if cz.can_remove_group(tab, group):
            menu.addAction(tr("Delete (Del)"), lambda: self.remove(sel))
        return menu

    def reset_group(self, sel):
        place = sel[1]
        return self.do(self.editor.reset_group, place.tab, place.group,
                       select=("group", Place(place.tab, place.group)),
                       message=tr("Group as in the definition."))

    # Entfernen, Umbenennen, Verschieben
    def remove(self, sel):
        kind = sel[0]
        if kind == "item":
            place = sel[1]
            n = len(ed.items_at(self.editor.arr, self.base, place.tab, place.group))

            def after(_item):
                if n - 1 <= 0:
                    return ("group", Place(place.tab, place.group))
                return ("item", Place(place.tab, place.group, min(place.item, n - 2)))
            if self.clip == place:
                self.clip = None
            return self.do(self.editor.remove_item, place, select=after, message=tr("Removed."))
        if kind == "group":
            place = sel[1]
            n = len(self.editor.arr.tab(place.tab).groups)

            def after_group(deleted):
                if not deleted:
                    return sel
                if n - 1 <= 0:
                    return ("newgroup", place.tab)
                return ("group", Place(place.tab, min(place.group, n - 2)))
            tab = self.editor.arr.tab(place.tab)
            home = tab.is_home(tab.groups[place.group])
            return self.do(self.editor.remove_group, place.tab, place.group, select=after_group,
                           message=tr("Group deleted. Bring it back from the palette (Groups) or with Ctrl+Z.")
                           if home else None)
        if kind == "tab":
            index = ed.tab_index(self.editor.arr, sel[1])
            tab = self.editor.arr.tab(sel[1])
            confirm = tab.standard and not tab.contextual and not cz.is_last_main_tab(self.editor.arr, tab)
            if confirm and not confirm_remove_tab(self, tab.label):
                return None

            def after_tab(deleted):
                if not deleted:
                    return sel
                tabs = self.editor.arr.tabs
                return ("tab", tabs[min(index, len(tabs) - 1)].id)
            deleted = self.do(self.editor.remove_tab, sel[1], select=after_tab)
            if deleted is False:
                self.set_status(ONLY_HIDE_TAB)
            return deleted
        if kind == "quick":
            n = len(self.editor.quick_ids())

            def after_quick(_r):
                return ("quick", min(sel[1], n - 2)) if n > 1 else ("tab", self.current_tab)
            return self.do(self.editor.quick_remove, sel[1], select=after_quick,
                           message=tr("Removed from Quick Access."))
        return None

    def rename(self, sel):
        if sel != self.selection:
            self.select(sel)
        kind = sel[0]
        if kind == "tab" and self.editor.arr.tab(sel[1]).standard:
            self.set_status(FIXED_TAB_LABEL)
            return False
        if kind == "item":
            sel = ("group", Place(sel[1].tab, sel[1].group))
            self.select(sel)
        if kind not in ("tab", "group", "item") or self._label_edit is None:
            return False
        self._label_edit.setFocus(Qt.ShortcutFocusReason)
        self._label_edit.selectAll()
        return True

    def commit_label(self, sel, text):
        if sel[0] == "tab":
            if text.strip() == self.editor.arr.tab(sel[1]).label:
                return None
            return self.do(self.editor.rename_tab, sel[1], text, select=sel)
        place = sel[1]
        if text.strip() == self.editor.arr.tab(place.tab).groups[place.group].label:
            return None
        return self.do(self.editor.rename_group, place.tab, place.group, text, select=sel)

    def move_by(self, sel, delta):
        kind = sel[0]
        if kind == "item":
            place = sel[1]
            n = len(ed.items_at(self.editor.arr, self.base, place.tab, place.group))
            if 0 <= place.item + delta < n:
                return self.do(self.editor.move_item_by, place, delta, select=lambda p: ("item", p))
            # am Rand der Gruppe: in die Nachbargruppe
            gi = place.group + delta
            if not 0 <= gi < len(self.editor.arr.tab(place.tab).groups):
                self.set_status(tr("Cannot move further."))
                return None
            index = len(ed.items_at(self.editor.arr, self.base, place.tab, gi)) if delta < 0 else 0
            return self.do(self.editor.move_item, place, place.tab, gi, index, select=lambda p: ("item", p))
        if kind == "group":
            place = sel[1]
            return self.do(self.editor.move_group_by, place.tab, place.group, delta,
                           select=lambda p: ("group", p) if p else sel)
        if kind == "tab":
            return self.do(self.editor.move_tab_by, sel[1], delta, select=sel)
        if kind == "quick":
            ids = self.editor.quick_ids()
            target = sel[1] + delta
            if not 0 <= target < len(ids):
                return None
            return self.do(self.editor.quick_insert, target + (1 if delta > 0 else 0), ids[sel[1]],
                           select=("quick", target))
        return None

    def cut(self, sel):
        if sel[0] != "item":
            return False
        self.clip = sel[1]
        self.set_status(tr("Cut: “%s”. Choose a target (group or item, also in another tab) and press Ctrl+V.")
                        % cz.item_label(self.base, self.editor.item(sel[1])))
        self.refresh(focus=True)
        return True

    def paste(self, sel):
        if self.clip is None:
            self.set_status(tr("Nothing cut (Ctrl+X on an item)."))
            return None
        src, kind = self.clip, sel[0]
        if kind == "item":
            dst, index = sel[1], sel[1].item + 1
        elif kind == "group":
            dst = sel[1]
            index = len(ed.items_at(self.editor.arr, self.base, dst.tab, dst.group))
        elif kind == "newgroup":
            res = self.do(self.editor.move_item_to_new_group, src, sel[1], None,
                          select=lambda p: ("group", p), message=tr("Moved into a new group."))
            if res is not None:
                self.clip = None
            return res
        else:
            self.set_status(NEED_GROUP)
            return None
        res = self.do(self.editor.move_item, src, dst.tab, dst.group, index,
                      select=lambda p: ("item", p), message=tr("Moved."))
        if res is not None:
            self.clip = None
            self.refresh(focus=True)
        return res

    # Tastatur
    def key(self, sel, event):
        """Taste auf einem Teil des Editors. True, wenn verarbeitet."""
        k = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        kind = sel[0]
        if k in (Qt.Key_Delete, Qt.Key_Backspace) and not ctrl:
            self.remove(sel)
            return True
        if k == Qt.Key_F2:
            self.rename(sel)
            return True
        if ctrl and k == Qt.Key_X:
            self.cut(sel)
            return True
        if ctrl and k == Qt.Key_V:
            self.paste(sel)
            return True
        if k == Qt.Key_Space and kind in ("tab", "group"):
            self.toggle_visible(sel)
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if kind == "newgroup":
                self.new_group()
            elif kind == "tab":
                self._focus_first_in_preview()
            elif kind == "item" and k != Qt.Key_Space:
                tile = self.widgets.get(sel)
                if tile is not None and tile.menu:
                    self.show_contents(tile)
            return True
        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            delta = -1 if k in (Qt.Key_Left, Qt.Key_Up) else 1
            if ctrl:
                if kind == "item" and k in (Qt.Key_Up, Qt.Key_Down):
                    return True
                self.move_by(sel, delta)
            else:
                self.navigate(sel, k)
            return True
        if k == Qt.Key_Escape and self.clip is not None:
            self.clip = None
            self.set_status(tr("Cut canceled."))
            self.refresh(focus=True)
            return True
        return False

    def palette_key(self, event):
        """Tasten der Palette, die der Editor übernimmt (Strg+V fügt den Ausschnitt nicht ein)."""
        if event.key() == Qt.Key_Q and event.modifiers() & Qt.ControlModifier:
            self.add_to_quick_access()
            return True
        return False

    def _preview_order(self):
        out = []
        for card in self.preview.cards:
            out.append(card.header.sel)
            out.extend(t.sel for t in card.tiles)
        out.append(self.preview.new_card.sel)
        return out

    def _focus_first_in_preview(self):
        order = self._preview_order()
        self.select(order[0], focus=True)

    def navigate(self, sel, k):
        kind = sel[0]
        if kind == "tab":
            ids = [t.id for t in self.editor.arr.tabs]
            i = ids.index(sel[1])
            if k in (Qt.Key_Left, Qt.Key_Right):
                j = i + (1 if k == Qt.Key_Right else -1)
                if 0 <= j < len(ids):
                    self.select(("tab", ids[j]), focus=True)
            elif k == Qt.Key_Down:
                self._focus_first_in_preview()
            return
        if kind == "quick":
            n = len(self.quick.tiles)
            if k in (Qt.Key_Left, Qt.Key_Right):
                j = sel[1] + (1 if k == Qt.Key_Right else -1)
                if 0 <= j < n:
                    self.select(("quick", j), focus=True)
            elif k == Qt.Key_Down:
                self._focus_first_in_preview()
            elif k == Qt.Key_Up:
                self.select(("tab", self.current_tab), focus=True)
            return
        order = self._preview_order()
        if sel not in order:
            return
        i = order.index(sel)
        if k in (Qt.Key_Left, Qt.Key_Right):
            j = i + (1 if k == Qt.Key_Right else -1)
            if 0 <= j < len(order):
                self.select(order[j], focus=True)
            return
        if kind == "item":
            place = sel[1]
            card = self.preview.cards[place.group]
            tile = card.tiles[place.item]
            col = card.columns[tile.col]
            r = tile.row + (1 if k == Qt.Key_Down else -1)
            if 0 <= r < len(col):
                self.select(col[r].sel, focus=True)
            elif r < 0:
                self.select(card.header.sel, focus=True)
            return
        if kind == "group":
            card = self.preview.cards[sel[1].group]
            if k == Qt.Key_Down and card.tiles:
                self.select(card.tiles[0].sel, focus=True)
            elif k == Qt.Key_Up:
                target = ("quick", 0) if self.quick.tiles else ("tab", self.current_tab)
                self.select(target, focus=True)
            return
        if kind == "newgroup" and k == Qt.Key_Up:
            self.select(("tab", self.current_tab), focus=True)

    def keyPressEvent(self, event):  # noqa: N802 (Qt)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()   # Eingabe speichert nie versehentlich
            return
        QDialog.keyPressEvent(self, event)

    # Palette
    def insert_from_palette(self, picked=None):
        picked = picked or self.palette_box.current()
        if picked is None:
            self.set_status(tr("Please select an item in the palette."))
            return None
        kind, value = picked
        if kind == "group":
            index = self.target.group + 1 if self.target is not None and self._valid_group(self.target) else None
            return self.do(self.editor.copy_group_ref, value, self.current_tab, index,
                           select=lambda p: ("group", p),
                           message=tr("Group copied.")) and self._keep_palette_focus(picked)
        if self.target is None or not self._valid_group(self.target):
            self.set_status(NEED_GROUP, error=True)
            return None
        index = self.target_item + 1 if self.target_item is not None else None
        res = self.do(self.editor.insert_command, self.target.tab, self.target.group, index, value,
                      select=lambda p: ("item", p),
                      message=tr("“%s” inserted.") % self.base.commands[value].label)
        if res is not None:
            self._keep_palette_focus(picked)
        return res

    def _keep_palette_focus(self, picked):
        """Nach dem Einfügen bleibt die Palette bedienbar (nächste Eingabe fügt dahinter ein)."""
        if self.palette_box.list.hasFocus() or self.focusWidget() is None:
            self.palette_box.select(*picked)
            self.palette_box.list.setFocus()
        return True

    def add_to_quick_access(self, command_id=None):
        if command_id is None:
            picked = self.palette_box.current()
            if picked is None or picked[0] != "command":
                return None
            command_id = picked[1]
        return self.do(self.editor.quick_insert, len(self.editor.quick_ids()), command_id,
                       message=tr("“%s” in Quick Access.") % self.base.commands[command_id].label)

    # Inhalt von Splits und Menüs ansehen
    def show_contents(self, tile, popup=True):
        menu = QMenu(self)
        menu.setObjectName("ribbon_editor_contents")
        head = menu.addAction(tr("Content (view only in the editor)"))
        head.setEnabled(False)
        menu.addSeparator()
        for level, label in menu_entries(tile.element):
            menu.addAction("    " * level + label)
        if popup:
            menu.popup(tile.mapToGlobal(tile.rect().bottomLeft()))
        return menu

    # Eigenschaften
    def _clear_props(self):
        if self._label_edit is not None:
            self._label_edit.blockSignals(True)
            self._label_edit = None
        while self.props_lay.count():
            it = self.props_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()  # sonst zeigt Qt sie später als eigenes Fenster
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                lay = it.layout()
                while lay.count():
                    sub = lay.takeAt(0).widget()
                    if sub is not None:
                        sub.hide()  # sonst zeigt Qt sie später als eigenes Fenster
                        sub.setParent(None)
                        sub.deleteLater()

    def _prop_label(self, text, name=None, wrap=True):
        label = QLabel(text, self.props)
        if name:
            label.setObjectName(name)
        label.setWordWrap(wrap)
        self.props_lay.addWidget(label)
        return label

    def _prop_button(self, text, slot, enabled=True, name=None):
        b = QPushButton(text, self.props)
        b.setAutoDefault(False)
        if name:
            b.setObjectName(name)
        b.setEnabled(enabled)
        b.clicked.connect(slot)
        self.props_lay.addWidget(b, 0, Qt.AlignLeft)
        return b

    def _label_field(self, sel, text, editable=True):
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Label:"), self.props))
        edit = QLineEdit(text, self.props)
        edit.setObjectName("ribbon_editor_label")
        edit.setEnabled(editable)
        edit.editingFinished.connect(lambda: self._label_done(sel, edit))
        row.addWidget(edit, 1)
        self.props_lay.addLayout(row)
        self._label_edit = edit
        return edit

    def _label_done(self, sel, edit):
        if self._label_edit is not edit:
            return
        refocus = edit.hasFocus()
        self.commit_label(sel, edit.text())
        if refocus and self.selected_widget() is not None:
            self.selected_widget().setFocus()

    def _visible_box(self, sel, visible):
        box = QCheckBox(tr("Visible"), self.props)
        box.setObjectName("ribbon_editor_visible")
        box.setChecked(visible)
        box.toggled.connect(lambda _on: self.toggle_visible(sel))
        self.props_lay.addWidget(box)
        return box

    def _fill_properties(self):
        self._clear_props()
        sel = self.selection
        kind = sel[0]
        try:
            fill = getattr(self, "_props_" + kind)
            fill(sel)
        except (KeyError, IndexError, EditError):
            self._prop_label(tr("Nothing selected."), "ribbon_editor_prop_muted")
        self.props_lay.addStretch(1)

    def _props_tab(self, sel):
        tab = self.editor.arr.tab(sel[1])
        base_tab = self.base.tab(tab.id) if tab.standard else None
        self._prop_label(tr("Tab “%s”") % (tab_title(base_tab) if base_tab else tab.label), "ribbon_editor_prop_title")
        if base_tab is not None and base_tab.contextual:
            what = tr("Contextual tab (appears when the active layer matches: %s)") % base_tab.context
        else:
            what = tr("Tab of the definition") if tab.standard else tr("Custom tab")
        self._prop_label(what, "ribbon_editor_prop_muted")
        self._label_field(sel, tab.label, editable=not tab.standard)
        self._visible_box(sel, tab.visible)
        self._prop_label(tr("%d groups") % len(tab.groups), "ribbon_editor_prop_muted")
        if not cz.can_remove_tab(tab):
            self._prop_label(ONLY_HIDE_TAB, "ribbon_editor_prop_muted")
        else:
            self._prop_button(tr("Delete Tab"), lambda: self.remove(sel), name="ribbon_editor_remove",
                              enabled=not cz.is_last_main_tab(self.editor.arr, tab))

    def _props_group(self, sel):
        place = sel[1]
        tab = self.editor.arr.tab(place.tab)
        group = tab.groups[place.group]
        self._prop_label(tr("Group “%s”") % group.label, "ribbon_editor_prop_title")
        if group.custom:
            what = tr("Custom group")
        elif tab.is_home(group):
            what = tr("Group of the definition") + (tr(" · customized") if cz.is_modified(self.base, group) else "")
        else:
            home = self.base.tab(group.home_tab)
            what = tr("Copy from tab “%s”") % tab_title(home) + (
                tr(" · customized") if cz.is_modified(self.base, group) else "")
        self._prop_label(what, "ribbon_editor_prop_muted")
        self._label_field(sel, group.label)
        self._visible_box(sel, group.visible)
        row = QHBoxLayout()
        if not group.custom:
            b = QPushButton(tr("Reset to Default"), self.props)
            b.setObjectName("ribbon_editor_reset_group")
            b.setAutoDefault(False)
            b.setEnabled(cz.is_modified(self.base, group))
            b.clicked.connect(lambda: self.reset_group(sel))
            row.addWidget(b)
        if cz.can_remove_group(tab, group):
            b = QPushButton(tr("Delete Group"), self.props)
            b.setObjectName("ribbon_editor_remove")
            b.setAutoDefault(False)
            b.clicked.connect(lambda: self.remove(sel))
            row.addWidget(b)
        row.addStretch(1)
        self.props_lay.addLayout(row)
        self._prop_label(tr("To insert: select a command in the palette and press Enter, or drag it here. "
                            "Drag the group by its header to move it (also onto another tab)."),
                         "ribbon_editor_prop_muted")

    def _props_item(self, sel):
        place = sel[1]
        item = self.editor.item(place)
        element = cz.item_element(self.base, item)
        group = self.editor.arr.tab(place.tab).groups[place.group]
        tab = self.editor.arr.tab(place.tab)
        self._prop_label(cz.item_label(self.base, item), "ribbon_editor_prop_title")
        self._prop_label(kind_text(element), "ribbon_editor_prop_muted")
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Size:"), self.props))
        self._size_buttons = QButtonGroup(self.props)
        for size in cz.SIZES:
            b = QToolButton(self.props)
            b.setObjectName("ribbon_editor_size")
            b.setText(cz.SIZE_LABELS[size])
            b.setCheckable(True)
            b.setChecked(item.size == size)
            b.setEnabled(item.size is not None)
            b.setProperty("ribbon_size_value", size)
            b.clicked.connect(lambda _c=False, s=size: self.set_size(sel, s))
            self._size_buttons.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        self.props_lay.addLayout(row)
        title = tab_title(self.base.tab(tab.id)) if tab.standard else tab.label
        self._prop_label(tr("Location: group “%s” · tab “%s”") % (group.label, title))
        description = getattr(getattr(element, "command", None), "description", None)
        if description:
            self._prop_label(description, "ribbon_editor_prop_muted")
        entries = menu_entries(element) if element is not None else []
        if entries:
            self._prop_label(tr("Content: ") + ", ".join(label for _l, label in entries), "ribbon_editor_prop_muted")
        self._prop_button(tr("Remove"), lambda: self.remove(sel), name="ribbon_editor_remove")

    def set_size(self, sel, size):
        return self.do(self.editor.set_size, sel[1], size, select=sel)

    def _props_newgroup(self, sel):
        self._prop_label(tr("New Group"), "ribbon_editor_prop_title")
        self._prop_label(tr("Creates a custom group. Commands dropped here go into a new group."),
                         "ribbon_editor_prop_muted")
        self._prop_button(tr("Create Group"), lambda: self.new_group())

    def _props_quick(self, sel):
        ids = self.editor.quick_ids()
        cmd = self.base.commands[ids[sel[1]]]
        self._prop_label(cmd.label, "ribbon_editor_prop_title")
        self._prop_label(tr("Quick Access, position %d") % (sel[1] + 1), "ribbon_editor_prop_muted")
        self._prop_label(tr("Move: drag or Ctrl+Arrow. Remove: drag into the palette or Del."),
                         "ribbon_editor_prop_muted")
        self._prop_button(tr("Remove from Quick Access"), lambda: self.remove(sel),
                          name="ribbon_editor_remove")

    def _props_palette(self, sel):
        _p, kind, value = sel
        if kind == "group":
            _tab, group = cz.standard_groups(self.base)[value]
            self._prop_label(tr("Group “%s”") % group.label, "ribbon_editor_prop_title")
            self._prop_label(tr("from tab “%s”") % tab_title(_tab), "ribbon_editor_prop_muted")
            self._prop_label(", ".join(cz.item_label(self.base, i) for i in cz.standard_items(self.base, value)))
            target = self.editor.arr.tab(self.current_tab)
            self._prop_button(tr("Copy into tab “%s” (Enter)") % target.label, self.insert_from_palette,
                              name="ribbon_editor_insert")
            return
        cmd = self.base.commands[value]
        self._prop_label(cmd.label, "ribbon_editor_prop_title")
        if cmd.description:
            self._prop_label(cmd.description, "ribbon_editor_prop_muted")
        place = self.places.get(cmd.id)
        self._prop_label(tr("In the definition: %s") % place if place
                         else tr("In the definition only as a menu or gallery item"), "ribbon_editor_prop_muted")
        if self.target is not None and self._valid_group(self.target):
            group = self.editor.arr.tab(self.target.tab).groups[self.target.group]
            text, ok = tr("Insert into “%s” (Enter)") % group.label, True
        else:
            text, ok = tr("Insert into a group (select a group first)"), False
        self._prop_button(text, self.insert_from_palette, enabled=ok, name="ribbon_editor_insert")
        self._prop_button(tr("Add to Quick Access (Ctrl+Q)"), lambda: self.add_to_quick_access(cmd.id),
                          enabled=ed.quick_allowed(cmd), name="ribbon_editor_quick_add")

    # Ganzes
    def _fill_restore_menu(self):
        self.restore_menu.clear()
        for t in self.editor.removed_tabs():
            self.restore_menu.addAction(t.label, lambda _c=False, tid=t.id: self.restore_tab(tid))

    def restore_tab(self, tab_id):
        return self.do(self.editor.restore_tab, tab_id, select=lambda p: ("tab", p.tab),
                       message=tr("Tab restored with all its groups."))

    def reset_all(self):
        self.clip = None
        return self.do(self.editor.reset_all, select=("tab", self.current_tab),
                       message=tr("Defaults restored. Undo with Ctrl+Z, applied only with “Save”."))

    def save(self):
        if self.editor.problems():
            self._update_status()
            return False
        arr, _dropped, qat = self.editor.result()
        self._remember_size()
        self.arrangements.save_editor(arr, qat)
        self.accept()
        return True

    def _remember_size(self):
        user = getattr(self.arrangements, "user", None)
        if user is not None and hasattr(user, "set_editor_size"):
            user.set_editor_size(self.width(), self.height())

    def reject(self):
        if self.editor.dirty and not confirm_discard(self):
            return
        self._remember_size()
        QDialog.reject(self)

    # Ziehen und Ablegen
    def start_drag(self, widget):
        """Ziehen eines Teils der Vorschau, der Tableiste oder des Schnellzugriffs beginnen."""
        payload = widget.sel
        if payload[0] not in ("item", "group", "tab", "quick") or self._drag is not None:
            return None
        drag = QDrag(self)   # nicht die Kachel: die wird beim Ablegen neu aufgebaut
        drag.setMimeData(mime("%s:%s" % (payload[0], payload[1])))
        drag.setPixmap(drag_pixmap(widget))
        hot = widget.mapFromGlobal(QCursor.pos())
        drag.setHotSpot(QPoint(max(0, min(hot.x(), widget.width() - 1)),
                               max(0, min(hot.y(), widget.height() - 1))))
        widget.marked = True
        widget.update()
        self._drag_source = widget
        return self._exec_drag(drag, payload)

    def start_palette_drag(self, picked):
        """Ziehen einer Palettenkachel (Befehl oder Gruppe der Definition) beginnen."""
        if self._drag is not None:
            return None
        kind, value = picked
        payload = ("command", value) if kind == "command" else ("groupref", value)
        drag = QDrag(self)
        drag.setMimeData(mime("%s:%s" % payload))
        item = self.palette_box.list.currentItem()
        if item is not None:
            drag.setPixmap(chip_pixmap(self.palette_box.list, item.icon(), item.text()))
            drag.setHotSpot(QPoint(12, 12))
        return self._exec_drag(drag, payload)

    def _exec_drag(self, drag, payload):
        self.begin_drag(payload)
        self._drag_running = True
        try:
            drag.exec_(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
        finally:
            self._drag_running = False
            run = self.end_drag()
        return run() if run is not None else None

    def begin_drag(self, payload):
        """Zieh-Vorgang mit ``payload`` (wie die Auswahl: ("item", Place), ("command", id) …)."""
        self._drag = payload
        self._pending = None
        self._graveyard = []
        self._hover_tab = None

    def end_drag(self):
        """Zieh-Vorgang beenden: Marken weg, Zeitgeber aus. -> Ablegen, das noch aussteht."""
        self._hover_timer.stop()
        self._scroll_timer.stop()
        self._scroll = None
        self._hover_tab = None
        self._clear_marks()
        src = self._drag_source
        if src is not None:
            src.marked = src.sel[0] == "item" and self.clip == src.sel[1]
            src.update()
        for w in self._graveyard or ():
            w.deleteLater()
        run, self._pending = self._pending, None
        self._drag, self._drag_source, self._graveyard = None, None, None
        self._update_status()
        return run

    def _finish(self, run):
        """Ablegen: während ``QDrag.exec`` merken (die Quelle steht noch im Aufrufstapel), sonst gleich."""
        if self._drag_running:
            self._pending = run
            return True
        self.end_drag()
        return run()

    def _clear_marks(self):
        for card in self.preview.cards:
            if card.drop_index is not None:
                card.drop_index = None
                card.update()
        new_card = self.preview.new_card
        if new_card is not None and new_card.active:
            new_card.active = False
            new_card.update()
        for strip in (self.preview, self.tab_strip, self.quick):
            if strip.drop_gap is not None:
                strip.drop_gap = None
                strip.update()
        for chip in self.tab_strip.chips:
            if chip.drop_active:
                chip.drop_active = False
                chip.update()
        self.palette_box.list.set_drop_active(False)

    def _drag_note(self, text):
        """Hinweis beim Ziehen in der Statuszeile (ohne die Meldung zu ersetzen)."""
        self.status.setText(text or self._message)
        self.status.setStyleSheet("")

    def drag_leave(self):
        if self._drag is not None:
            self._clear_marks()
            self._auto_scroll(None, None)

    def _handle(self, plan, widget, event, drop=False):
        """Gemeinsamer Ablauf für Ziehen über (``drop`` False) und Ablegen auf ``widget``."""
        if self._drag is None or not event.mimeData().hasFormat(MIME_TYPE):
            event.ignore()
            return None
        try:
            mark, run, hint = plan(widget, event.pos())
        except (EditError, KeyError, IndexError):
            mark, run, hint = None, None, None
        self._clear_marks()
        if run is None:
            self._drag_note(hint)
            event.ignore()
            return None
        self._drag_note(None)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        if not drop:
            mark()
            return True
        return self._finish(run)

    # Ziele: (Marke setzen, Ablegen, Hinweis); ungültig -> (None, None, Hinweis oder None)
    def _item_of_drag(self):
        kind, value = self._drag
        if kind == "item":
            return self.editor.item(value)
        if kind == "command":
            return ed.command_item(self.base, value)
        return None

    def _plan_group(self, card, pos):
        kind, value = self._drag
        if kind in ("group", "groupref"):
            return self._plan_preview(self.preview, card.mapTo(self.preview, pos))
        if kind not in ("item", "command"):
            return None, None, None
        tab_id, gi = card.place.tab, card.place.group
        index = card.index_at(pos)
        item = self._item_of_drag()
        label = cz.item_label(self.base, item)
        same = kind == "item" and (value.tab, value.group) == (tab_id, gi)
        hint = ed.can_insert(self.editor.arr, self.base, tab_id, gi, item, ignore=value.item if same else None)
        if hint:
            return None, None, hint
        if kind == "item":
            def run():
                return self.do(self.editor.move_item, value, tab_id, gi, index,
                               select=lambda p: ("item", p), message=tr("“%s” moved.") % label)
        else:
            def run():
                return self.do(self.editor.insert_command, tab_id, gi, index, value,
                               select=lambda p: ("item", p), message=tr("“%s” inserted.") % label)

        def mark():
            card.drop_index = index
            card.update()
        return mark, run, None

    def _plan_new_group(self, card, pos):
        kind, value = self._drag
        if kind in ("group", "groupref"):
            return self._plan_preview(self.preview, card.mapTo(self.preview, pos))
        if kind not in ("item", "command"):
            return None, None, None
        tab_id = card.sel[1]
        item = self._item_of_drag()
        hint = ed.can_insert(self.editor.arr, self.base, tab_id, None, item)
        if hint:
            return None, None, hint
        message = tr("New group with “%s”.") % cz.item_label(self.base, item)
        if kind == "item":
            def run():
                return self.do(self.editor.move_item_to_new_group, value, tab_id, None,
                               select=lambda p: ("group", p), message=message)
        else:
            def run():
                return self.do(self.editor.new_group, tab_id, None, item=item,
                               select=lambda p: ("group", p), message=message)

        def mark():
            card.active = True
            card.update()
        return mark, run, None

    def _plan_preview(self, preview, pos):
        kind, value = self._drag
        if kind not in ("group", "groupref"):
            return None, None, None
        tab_id = self.current_tab
        gap = preview.gap_at(pos)
        if kind == "group":
            hint = ed.can_move_group(self.editor.arr, self.base, value.tab, value.group, tab_id)

            def run():
                return self.do(self.editor.move_group, value.tab, value.group, tab_id, gap,
                               select=lambda p: ("group", p), message=tr("Group moved."))
        else:
            hint = ed.can_copy_group_ref(self.editor.arr, self.base, value, tab_id)

            def run():
                return self.do(self.editor.copy_group_ref, value, tab_id, gap,
                               select=lambda p: ("group", p), message=tr("Group copied."))
        if hint:
            return None, None, hint

        def mark():
            preview.drop_gap = gap
            preview.update()
        return mark, run, None

    def _plan_tab(self, chip, pos):
        kind, value = self._drag
        if kind == "tab":
            return self._plan_strip(self.tab_strip, chip.mapTo(self.tab_strip, pos))
        tab_id = chip.sel[1]
        if kind == "group":
            hint = ed.can_move_group(self.editor.arr, self.base, value.tab, value.group, tab_id)

            def run():
                return self.do(self.editor.move_group, value.tab, value.group, tab_id, None,
                               select=lambda p: ("group", p),
                               message=tr("Group moved to “%s”.") % chip.title)
        elif kind == "groupref":
            hint = ed.can_copy_group_ref(self.editor.arr, self.base, value, tab_id)

            def run():
                return self.do(self.editor.copy_group_ref, value, tab_id, None,
                               select=lambda p: ("group", p),
                               message=tr("Group copied into “%s”.") % chip.title)
        else:
            # Einträge legt man in eine Gruppe; über dem Tab wechselt nur die Vorschau
            return None, None, None
        if hint:
            return None, None, hint

        def mark():
            chip.drop_active = True
            chip.update()
        return mark, run, None

    def _plan_strip(self, strip, pos):
        kind, value = self._drag
        if kind != "tab":
            return None, None, None
        gap = strip.gap_at(pos)
        if gap not in ed.tab_gaps(self.editor.arr, value):
            return None, None, TAB_ORDER_HINT

        def run():
            return self.do(self.editor.move_tab, value, gap, select=("tab", value), message=tr("Tab moved."))

        def mark():
            strip.drop_gap = gap
            strip.update()
        return mark, run, None

    def _plan_quick(self, strip, pos):
        kind, value = self._drag
        if kind == "command":
            cid = value if ed.quick_allowed(self.base.commands[value]) else None
        elif kind == "item":
            cid = ed.quick_command(self.base, self.editor.item(value))
        elif kind == "quick":
            cid = self.editor.quick_ids()[value]
        else:
            return None, None, None
        if cid is None:
            return None, None, QUICK_ONLY_BUTTONS
        gap = strip.gap_at(pos)

        def run():
            return self.do(self.editor.quick_insert, gap, cid,
                           select=lambda _r: ("quick", self.editor.quick_ids().index(cid)),
                           message=tr("“%s” in Quick Access.") % self.base.commands[cid].label)

        def mark():
            strip.drop_gap = gap
            strip.update()
        return mark, run, None

    def _plan_palette(self, lst, _pos):
        kind, value = self._drag
        if kind not in ("item", "group", "quick"):
            return None, None, None
        sel = (kind, value)

        def run():
            return self.remove(sel)

        def mark():
            lst.set_drop_active(True)
        return mark, run, None

    # Ereignisse der Widgets
    def drag_over_group(self, card, event):
        self._auto_scroll(self.preview_area, card.mapToGlobal(event.pos()))
        return self._handle(self._plan_group, card, event)

    def drop_on_group(self, card, event):
        return self._handle(self._plan_group, card, event, drop=True)

    def drag_over_new_group(self, card, event):
        self._auto_scroll(self.preview_area, card.mapToGlobal(event.pos()))
        return self._handle(self._plan_new_group, card, event)

    def drop_on_new_group(self, card, event):
        return self._handle(self._plan_new_group, card, event, drop=True)

    def drag_over_preview(self, preview, event):
        self._auto_scroll(self.preview_area, preview.mapToGlobal(event.pos()))
        return self._handle(self._plan_preview, preview, event)

    def drop_on_preview(self, preview, event):
        return self._handle(self._plan_preview, preview, event, drop=True)

    def drag_over_tab(self, chip, event):
        self._auto_scroll(self.tab_area, chip.mapToGlobal(event.pos()))
        self._hover(chip)
        return self._handle(self._plan_tab, chip, event)

    def drag_leave_tab(self, chip):
        if self._hover_tab == chip.sel[1]:
            self._hover_timer.stop()
            self._hover_tab = None
        self.drag_leave()

    def drop_on_tab(self, chip, event):
        return self._handle(self._plan_tab, chip, event, drop=True)

    def drag_over_strip(self, strip, event):
        self._auto_scroll(self.tab_area, strip.mapToGlobal(event.pos()))
        return self._handle(self._plan_strip, strip, event)

    def drop_on_strip(self, strip, event):
        return self._handle(self._plan_strip, strip, event, drop=True)

    def drag_over_quick(self, strip, event):
        return self._handle(self._plan_quick, strip, event)

    def drop_on_quick(self, strip, event):
        return self._handle(self._plan_quick, strip, event, drop=True)

    def drag_over_palette(self, lst, event):
        return self._handle(self._plan_palette, lst, event)

    def drop_on_palette(self, lst, event):
        return self._handle(self._plan_palette, lst, event, drop=True)

    # Tab wechseln und rollen beim Ziehen
    def _hover(self, chip):
        tab_id = chip.sel[1]
        if self._drag is None or self._drag[0] in ("tab", "quick") or tab_id == self.current_tab:
            self._hover_timer.stop()
            self._hover_tab = None
            return
        if self._hover_tab != tab_id:
            self._hover_tab = tab_id
            self._hover_timer.start()

    def _hover_switch(self):
        """Über einem Tab verweilt: Vorschau auf diesen Tab (der Zieh-Vorgang läuft weiter)."""
        tab_id, self._hover_tab = self._hover_tab, None
        if self._drag is None or tab_id is None or tab_id == self.current_tab:
            return
        if tab_id not in {t.id for t in self.editor.arr.tabs}:
            return
        self.current_tab = tab_id
        if self.selection[0] in ("group", "item", "newgroup"):
            self.selection = ("tab", tab_id)
        self.refresh()
        self.preview_area.horizontalScrollBar().setValue(0)

    def _auto_scroll(self, area, global_pos):
        """Am linken/rechten Rand von ``area`` rollen, solange der Zeiger dort steht."""
        step = 0
        if area is not None and self._drag is not None:
            vp = area.viewport()
            x = vp.mapFromGlobal(global_pos).x()
            if x < SCROLL_MARGIN:
                step = -SCROLL_STEP
            elif x > vp.width() - SCROLL_MARGIN:
                step = SCROLL_STEP
            bar = area.horizontalScrollBar()
            if (step < 0 and bar.value() <= bar.minimum()) or (step > 0 and bar.value() >= bar.maximum()):
                step = 0
        if step:
            self._scroll = (area, step)
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        else:
            self._scroll = None
            self._scroll_timer.stop()

    def _scroll_tick(self):
        if self._scroll is None or self._drag is None:
            self._scroll_timer.stop()
            return
        area, step = self._scroll
        bar = area.horizontalScrollBar()
        bar.setValue(bar.value() + step)
        if bar.value() in (bar.minimum(), bar.maximum()):
            self._scroll_timer.stop()
