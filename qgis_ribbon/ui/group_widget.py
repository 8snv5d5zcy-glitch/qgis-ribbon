"""Gruppe im Ribbon: Spalten mit Buttons, Beschriftung darunter.

Große Elemente belegen eine eigene Spalte. Mittlere und kleine Elemente
sowie Zeilen werden zu Spalten mit höchstens ``theme.ROWS`` Einträgen
gestapelt. Ein Dialog-Launcher (``Group.launcher``) sitzt als kleines Symbol
rechts neben der Gruppenbeschriftung.

Adaptive Breite: Jede Gruppe kennt mehrere Fassungen
(``variants``), von eingeklappt (ein Button, der die Gruppe als Popup
öffnet) über verkleinert (weniger Galerie-Kacheln, groß → mittel,
mittel → klein, Galerie als Dropdown) und die definierte Fassung bis
erweitert (mehr Galerie-Kacheln). Dropdowns von Split-Buttons und Menüs
bleiben auch bei viel Platz Dropdowns: Ihre Einträge zusätzlich neben dem
Button zu zeigen, führte zu Dopplungen.
Die Seite wählt je Gruppe eine Fassung
(``core.adaptive``) und setzt sie mit ``apply``. Die Elemente werden dabei
nicht neu gebaut, sondern umgestellt; zusätzliche Widgets (kompakter
Split-Button, Galerie als Dropdown) entstehen erst, wenn sie gebraucht
werden. KeyTip-Ziele zeigen danach auf
das jeweils sichtbare Widget, die Kürzel bleiben gleich.
"""

from qgis.PyQt.QtCore import QPoint, QSize, Qt
from qgis.PyQt.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
                                 QToolButton, QVBoxLayout, QWidget)

from ..core.model import CommandRef, Menu, Row, Split
from . import icons, theme
from .controls import buttons
from .controls.gallery import RibbonGallery, gallery_button
from ..core.i18n import tr

COLLAPSED = "collapsed"
DROPDOWN = "dropdown"
SIZES = ("large", "medium", "small")
LAUNCHER_SIZE = 16


def element_widget(element, ctx, parent):
    if isinstance(element, CommandRef):
        return buttons.command_widget(element.command, element.size, ctx, parent)
    if isinstance(element, Split):
        return buttons.split_button(element, ctx, parent)
    if isinstance(element, Menu):
        g = element.gallery
        if g is not None and g.gallery is not None and g.gallery.display == "ribbon":
            return RibbonGallery(g, ctx, parent, items=element.items)
        return buttons.menu_button(element, ctx, parent)
    if isinstance(element, Row):
        return buttons.row_widget(element, ctx, parent)
    raise TypeError(tr("Unknown element: %r") % (element,))


def launcher_button(command, ctx, parent):
    """Kleines Symbol an der Gruppe, das den zugehörigen Dialog öffnet."""
    btn = QToolButton(parent)
    btn.setAutoRaise(True)
    act = buttons.ProxyAction(command, ctx, btn)
    act.setIcon(icons.ui_icon("launcher"))
    if act.icon().isNull():
        act.setIconText("↘")  # ↘ ohne Icon-Set
    btn.setDefaultAction(act)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    btn.setIconSize(QSize(11, 11))
    btn.setFixedSize(LAUNCHER_SIZE, LAUNCHER_SIZE)
    btn.setObjectName("ribbon_launcher_" + command.id)
    btn.setProperty("ribbon_launcher", True)
    ctx.add_target(btn, command.label, lambda: buttons.activate_button(btn), command)
    return btn


class ElementView(object):
    """Ein Element der Gruppe mit seinen Darstellungen."""

    def __init__(self, element, ctx, parent):
        self.element = element
        self.ctx = ctx
        self.parent = parent
        self.widget = element_widget(element, ctx, parent)
        self.mode = None
        self._compact = None      # kompakter Split-Button
        self._dropdown = None     # Galerie als Dropdown-Button
        if isinstance(self.widget, RibbonGallery):
            self.kind = "gallery"
        elif isinstance(self.widget, buttons.LargeSplitButton):
            self.kind = "split"
        elif isinstance(self.widget, QToolButton) and self.widget.property("ribbon_size"):
            self.kind = "button"
        else:
            self.kind = "fixed"
        self.size = getattr(element, "size", None)
        self._fixed_width = None
        # KeyTip-Ziel des Buttons, um es nach dem Aufklappen zurückzusetzen
        self._target = getattr(self.widget, "target", None)
        self._activate = self._target.activate if self._target is not None else None

    # Fassungen
    def ideal(self):
        if self.kind == "gallery":
            return self.widget.ideal_count()
        if self.kind in ("button", "split"):
            return self.size
        return "fixed"

    def smaller(self):
        """Verkleinerte Größen ab der definierten (ohne sie)."""
        if self.kind not in ("button", "split"):
            return []
        return list(SIZES[SIZES.index(self.size) + 1:])

    def is_column(self, mode):
        return mode in ("large", DROPDOWN) or isinstance(mode, int)

    def width(self, mode):
        w = self.widget
        if self.kind == "gallery":
            if mode == DROPDOWN:
                return buttons.button_width(w.expand, "large", self.label(), True)
            return w.width_for(mode)
        if self.kind == "split":
            if mode == "large":
                return w.large_width()
            return buttons.button_width(w.bottom, mode, self.label(), True)
        if self.kind == "button":
            return buttons.button_width(w, mode, w.property("ribbon_text"),
                                        bool(w.property("ribbon_menu")))
        if self._fixed_width is None:
            self._fixed_width = w.sizeHint().width()
        return self._fixed_width

    def label(self):
        if isinstance(self.element, Split):
            return self.element.display_label
        if isinstance(self.element, Menu):
            return self.element.label
        if isinstance(self.element, CommandRef):
            return self.element.command.label
        return ""

    # Umstellen
    def apply(self, mode):
        """Darstellung einstellen; gibt die Platzierung zurück: [(Widget, 'col'|'stack')]."""
        self.mode = mode
        w = self.widget
        if self.kind == "fixed":
            return [(w, "stack")]
        if self.kind == "gallery":
            if mode == DROPDOWN:
                drop = self._dropdown_button()
                w.hide()
                self._retarget(w.expand_target, drop, lambda: buttons.activate_button(drop))
                return [(drop, "col")]
            if self._dropdown is not None:
                self._dropdown.hide()
            self._retarget(w.expand_target, w.expand, lambda: buttons.activate_button(w.expand))
            w.set_visible(mode)
            return [(w, "col")]
        out = []
        if self.kind == "split":
            if mode == "large":
                if self._compact is not None:
                    self._compact.hide()
                self._retarget(w.target, w, lambda: buttons.keyboard_menu(w, w.action, w.menu))
                out.append((w, "col"))
            else:
                compact = self._compact_button()
                w.hide()
                buttons.apply_size(compact, mode, self.label(), True)
                self._retarget(w.target, compact, compact.keyboard)
                out.append((compact, "stack"))
        else:
            self._retarget(self._target, w, self._activate)
            buttons.apply_size(w, mode, w.property("ribbon_text"), bool(w.property("ribbon_menu")))
            out.append((w, "col" if mode == "large" else "stack"))
        return out

    def _retarget(self, target, widget, activate):
        if target is not None:
            target.widget = widget
            target.activate = activate

    def _compact_button(self):
        if self._compact is None:
            self._compact = buttons.compact_split(self.element, self.ctx, self.parent,
                                                  self.widget.menu)
        return self._compact

    def _dropdown_button(self):
        if self._dropdown is None:
            el = self.element
            if isinstance(el, Menu):
                self._dropdown = gallery_button(el.gallery, "large", self.ctx, self.parent,
                                                items=el.items)
            else:
                self._dropdown = gallery_button(el.command, "large", self.ctx, self.parent)
        return self._dropdown

    def first_icon(self):
        w = self.widget
        if self.kind == "split":
            return w.action.icon()
        if self.kind == "gallery":
            tiles = w.grid.tiles
            return tiles[0].defaultAction().icon() if tiles else None
        if isinstance(w, QToolButton):
            return w.icon()
        return None


def _place(placements):
    """Platzierungen -> Spalten [(Art, [Widgets])]; 'col' eigene Spalte, sonst je ROWS gestapelt."""
    cols = []
    stack = []

    def flush():
        if stack:
            cols.append(("stack", list(stack)))
            del stack[:]

    for widget, how in placements:
        if how == "col":
            flush()
            cols.append(("col", [widget]))
        else:
            stack.append(widget)
            if len(stack) == theme.ROWS:
                flush()
    flush()
    return cols


class GroupPopup(QFrame):
    """Eingeklappte Gruppe: ihr Inhalt als Popup unter dem Button."""

    def __init__(self, group):
        QFrame.__init__(self, group, Qt.WindowType.Popup)
        self.setObjectName("ribbon_group_popup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 2)
        lay.setSpacing(0)


class GroupWidget(QWidget):
    def __init__(self, group, ctx, parent=None):
        QWidget.__init__(self, parent)
        self.group = group
        self.ctx = ctx
        self.setObjectName("ribbon_group_" + group.id)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(theme.GROUP_PADDING, 0, theme.GROUP_PADDING, 0)
        outer.setSpacing(0)
        self._outer = outer

        self.body = QWidget(self)
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        content = QWidget(self.body)
        self.content = content
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(theme.GROUP_SPACING)
        self.grid.setVerticalSpacing(theme.ROW_SPACING)
        content.setFixedHeight(theme.CONTENT_HEIGHT)
        self.views = [ElementView(el, ctx, content) for el in group.elements]

        footer = QWidget(self.body)
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(0)
        label = QLabel(group.label, footer)
        label.setObjectName("ribbon_group_label")
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        font = label.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 0.92)
        label.setFont(font)
        label.setFixedHeight(theme.GROUP_LABEL_HEIGHT)
        self.label = label
        self.launcher = None
        if group.launcher is not None:
            # Gleicher Abstand links, damit die Beschriftung mittig bleibt
            foot.addSpacing(LAUNCHER_SIZE)
            foot.addWidget(label, 1)
            self.launcher = launcher_button(group.launcher, ctx, footer)
            foot.addWidget(self.launcher, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            foot.addWidget(label, 1)
        footer.setFixedHeight(theme.GROUP_LABEL_HEIGHT)
        body.addWidget(content)
        body.addWidget(footer)
        outer.addWidget(self.body)

        self.collapse_button = None
        self.popup = None
        self.collapsed = False
        self.variant = None
        self._variants = None
        ctx.trigger_hooks.append(self.close_popup)
        self.apply(self.ideal_index())

    # Fassungen
    def invalidate(self):
        self._variants = None

    def variants(self):
        """Fassungen von schmal nach breit: [(Modi je Element oder COLLAPSED, Breite)]."""
        if self._variants is not None:
            return self._variants
        views = self.views
        ideal = [v.ideal() for v in views]

        down = []
        cur = list(ideal)
        # 1. Galerien: Kachel für Kachel weniger (bis 2)
        while True:
            nxt = [m - 1 if v.kind == "gallery" and m > 2 else m for v, m in zip(views, cur)]
            if nxt == cur:
                break
            cur = nxt
            down.append(list(cur))
        # 2. groß -> mittel, 3. mittel -> klein
        for frm, to in (("large", "medium"), ("medium", "small")):
            nxt = [to if v.kind in ("button", "split") and m == frm and to in v.smaller()
                   else m for v, m in zip(views, cur)]
            if nxt != cur:
                cur = nxt
                down.append(list(cur))
        # 4. Galerien als Dropdown
        nxt = [DROPDOWN if v.kind == "gallery" else m for v, m in zip(views, cur)]
        if nxt != cur:
            down.append(nxt)

        up = []
        cur = list(ideal)
        # 1. Galerien: Kachel für Kachel mehr
        while True:
            nxt = [m + 1 if v.kind == "gallery" and m < len(v.widget.grid.tiles) else m
                   for v, m in zip(views, cur)]
            if nxt == cur:
                break
            cur = nxt
            up.append(list(cur))

        ideal_w = self.width_for(ideal)
        result = [(ideal, ideal_w)]
        last = ideal_w
        for modes in down:
            w = self.width_for(modes)
            if w < last:
                result.insert(0, (modes, w))
                last = w
        cw = self.collapsed_width()
        if cw < last:
            result.insert(0, (COLLAPSED, cw))
        last = ideal_w
        for modes in up:
            w = self.width_for(modes)
            if w > last:
                result.append((modes, w))
                last = w
        self._variants = result
        return result

    def ideal_index(self):
        return next(i for i, (m, _w) in enumerate(self.variants()) if m != COLLAPSED
                    and m == [v.ideal() for v in self.views])

    def widths(self):
        return [w for _m, w in self.variants()]

    def width_for(self, modes):
        cols = []
        stack = []

        def flush():
            if stack:
                cols.append(max(stack))
                del stack[:]

        for v, mode in zip(self.views, modes):
            w = v.width(mode)
            if v.is_column(mode):
                flush()
                cols.append(w)
            else:
                stack.append(w)
                if len(stack) == theme.ROWS:
                    flush()
        flush()
        content = sum(cols) + theme.GROUP_SPACING * max(0, len(cols) - 1)
        return max(content, self.footer_width()) + 2 * theme.GROUP_PADDING

    def footer_width(self):
        extra = 2 * LAUNCHER_SIZE if self.launcher is not None else 0
        return self.label.fontMetrics().horizontalAdvance(self.group.label) + 8 + extra

    def collapsed_width(self):
        ref = self.label
        label = theme.wrap_label(self.group.label) + " " + buttons.MENU_ARROW
        return (max(theme.LARGE_MIN_WIDTH, buttons.text_width(ref, label) + theme.LARGE_PADDING)
                + 2 * theme.GROUP_PADDING)

    # Umstellen
    def apply(self, index):
        variants = self.variants()
        index = max(0, min(index, len(variants) - 1))
        if index == self.variant:
            return
        self.variant = index
        modes, width = variants[index]
        if modes == COLLAPSED:
            self._collapse()
            self.setFixedWidth(width)
            return
        self._expand()
        self._apply_modes(modes)
        self.setFixedWidth(width)

    def mode_names(self):
        modes, _w = self.variants()[self.variant]
        return modes

    # Eingeklappt
    def _collapse(self):
        if self.collapsed:
            return
        self.collapsed = True
        if self.collapse_button is None:
            self.collapse_button = self._make_collapse_button()
        # Inhalt in der definierten Fassung ins Popup
        self._apply_modes([v.ideal() for v in self.views])
        if self.popup is None:
            self.popup = GroupPopup(self)
        self._outer.removeWidget(self.body)
        self.popup.layout().addWidget(self.body)
        self.body.show()
        self._outer.addWidget(self.collapse_button)
        self.collapse_button.show()

    def _apply_modes(self, modes):
        placements = []
        for v, mode in zip(self.views, modes):
            placements.extend(v.apply(mode))
        while self.grid.count():
            self.grid.takeAt(0)
        for c, (kind, widgets) in enumerate(_place(placements)):
            if kind == "col":
                self.grid.addWidget(widgets[0], 0, c, theme.ROWS, 1, Qt.AlignmentFlag.AlignTop
                                    | Qt.AlignmentFlag.AlignLeft)
            else:
                for r, w in enumerate(widgets):
                    self.grid.addWidget(w, r, c, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            for w in widgets:
                w.show()
        for r in range(theme.ROWS):
            self.grid.setRowMinimumHeight(r, theme.ROW_HEIGHT)

    def _expand(self):
        if not self.collapsed:
            return
        self.collapsed = False
        self.close_popup()
        self.popup.layout().removeWidget(self.body)
        self._outer.removeWidget(self.collapse_button)
        self.collapse_button.hide()
        self.body.setParent(self)
        self._outer.addWidget(self.body)
        self.body.show()

    def _make_collapse_button(self):
        btn = QToolButton(self)
        buttons.set_size(btn, "large")
        btn.setFixedHeight(theme.CONTENT_HEIGHT + theme.GROUP_LABEL_HEIGHT)
        icon = next((v.first_icon() for v in self.views
                     if v.first_icon() is not None and not v.first_icon().isNull()), None)
        if icon is not None:
            btn.setIcon(icon)
        btn.setText(theme.wrap_label(self.group.label) + " " + buttons.MENU_ARROW)
        btn.setToolTip(tr("<b>%s</b><br>Open group") % self.group.label)
        btn.setObjectName("ribbon_group_button_" + self.group.id)
        btn.clicked.connect(self.open_popup)
        return btn

    def open_popup(self):
        if not self.collapsed or self.popup is None:
            return False
        btn = self.collapse_button
        pos = btn.mapToGlobal(QPoint(0, btn.height()))
        self.popup.adjustSize()
        self.popup.move(pos)
        self.popup.show()
        self.popup.raise_()
        return True

    def close_popup(self):
        try:
            if self.popup is not None and self.popup.isVisible():
                self.popup.hide()
        except RuntimeError:
            pass
