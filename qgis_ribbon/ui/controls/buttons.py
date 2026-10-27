"""Buttons und Menüs des Ribbons (Button, Split, Menü, Zeile).

Jeder Ribbon-Eintrag ist eine eigene ``ProxyAction`` mit deutscher
Beschriftung. Sie löst die QGIS-Quelle aus und spiegelt deren Zustand
(aktiv, abgehakt) über das Signal ``changed`` der QGIS-Aktion. Die
QGIS-Aktion selbst bleibt unverändert; ihr Shortcut gilt weiter in QGIS und
steht nur im Tooltip.

Bedienbar ist ein Eintrag, wenn die Quelle verfügbar und aktiv ist und alle
Bedingungen des Befehls gelten (``enabled_when``, Kontextlogik).

Tooltips (Rich-Tooltip): Titel, Beschreibung aus der Ribbon-Definition,
QGIS-Text, Tastenkürzel und ggf. der Grund, warum der Eintrag grau ist.

Große Split-Buttons sind wie in Pro zweigeteilt: oben das Icon (löst den
Hauptbefehl aus), unten Beschriftung mit Pfeil (öffnet das Menü).

Tastatur: Jedes Element meldet sich beim Aufbau als KeyTip-Ziel an
(``BuildContext.add_target``): Beschriftung, Widget und was beim Kürzel
passiert. Split-Buttons öffnen per Tastatur ein Menü mit dem Hauptbefehl
oben, Menü-Buttons ihr Menü, Steuerelemente bekommen den Fokus.
"""

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtWidgets import (QAction, QHBoxLayout, QMenu, QSizePolicy, QToolButton,
                                 QVBoxLayout, QWidget)

from .. import icons, menu_anchor, theme
from ..html_text import escape
from ...core.i18n import tr

MENU_ARROW = "\u25be"  # ▾ hinter der Beschriftung von Menü-Teilen
SPLIT_TOP_HEIGHT = 40   # großer Split-Button: Icon-Teil, der Rest ist Beschriftung mit Pfeil
SPLIT_PADDING = 12      # Rand links und rechts neben der Beschriftung des Split-Buttons
MENU_INDICATOR = 14     # Platz für den Menüpfeil mittlerer Buttons


class Target(object):
    """KeyTip-Ziel: Element im Ribbon, das per Tastatur ausgelöst werden kann."""

    __slots__ = ("label", "widget", "activate", "command")

    def __init__(self, label, widget, activate, command=None):
        self.label = label
        self.widget = widget
        self.activate = activate
        self.command = command


class BuildContext(object):
    """Gemeinsame Abhängigkeiten beim Aufbau: Resolver, Signal-Hub, Kontextlogik.

    ``proxies`` führt je Befehl mit Bedingungen die gebauten Einträge, damit
    eine Zustandsänderung nur diese neu bewertet. ``targets`` führt je Tab
    die KeyTip-Ziele in Aufbaureihenfolge, ``widget_commands`` den Befehl
    hinter einem Widget (Kontextmenü, Suche). ``after_trigger`` läuft nach
    jedem ausgelösten Befehl (z. B. aufgeklappten Ribbon wieder schließen).
    """

    def __init__(self, resolver, hub, logic=None):
        self.resolver = resolver
        self.hub = hub
        self.logic = logic
        self.proxies = {}  # Befehls-ID -> [ProxyAction oder Steuerelement]
        self.targets = {}  # Tab-ID -> [Target]
        self.widget_commands = {}  # Widget -> Command
        self.trigger_hooks = []
        self._tab = None

    def begin_tab(self, tab_id):
        self._tab = tab_id
        self.targets[tab_id] = []

    def end_tab(self):
        self._tab = None

    def add_target(self, widget, label, activate, command=None):
        """KeyTip-Ziel anmelden (nur während des Aufbaus eines Tabs); gibt das Ziel zurück.

        Wechselt ein Element später seine Darstellung (adaptive Breite), setzt
        es ``widget`` und ``activate`` des Ziels neu; das Kürzel bleibt.
        """
        target = None
        if self._tab is not None:
            target = Target(label, widget, activate, command)
            self.targets[self._tab].append(target)
        if command is not None:
            self.widget_commands[widget] = command
        return target

    def after_trigger(self):
        for hook in list(self.trigger_hooks):
            hook()

    @property
    def env(self):
        """Umgebung der eigenen Befehle (iface, Layer-Beobachter)."""
        return self.resolver.env

    def allowed(self, command):
        return self.logic is None or self.logic.command_enabled(command.id)

    def register(self, proxy):
        """Eintrag mit ``command`` und ``sync()`` für Zustandsänderungen anmelden."""
        if proxy.command.enabled_when:
            self.proxies.setdefault(proxy.command.id, []).append(proxy)

    def unregister(self, proxy):
        entries = self.proxies.get(proxy.command.id, [])
        if proxy in entries:
            entries.remove(proxy)

    def refresh(self, command_id):
        for proxy in self.proxies.get(command_id, ()):
            proxy.sync()


def tooltip(label, resolved, description=None):
    parts = ["<b>%s</b>" % escape(label)]
    if description:
        parts.append(escape(description))
    if resolved.qgis_text and resolved.qgis_text != label:
        parts.append("QGIS: %s" % escape(resolved.qgis_text))
    if resolved.shortcut:
        parts.append(tr("Shortcut: %s") % escape(resolved.shortcut))
    if not resolved.available and resolved.reason:
        parts.append("<i>%s</i>" % escape(resolved.reason))
    return "<br>".join(parts)


class ProxyAction(QAction):
    """Ribbon-Eintrag für einen Befehl; spiegelt die QGIS-Aktion, falls vorhanden."""

    def __init__(self, command, ctx, parent, label=None):
        QAction.__init__(self, parent)
        self.command = command
        self._ctx = ctx
        res = ctx.resolver.resolve(command)
        self.resolved = res
        text = label or command.label
        self.setText(text)
        self.setIconText(text)
        self.setIcon(icons.command_icon(command, res.icon))
        self.setToolTip(tooltip(text, res, command.description))
        self.setObjectName("ribbon_" + command.id)
        src = res.action
        if src is not None:
            self.setCheckable(src.isCheckable())
            ctx.hub.connect(src, "changed", self.sync)
        ctx.register(self)
        self.sync()
        self.triggered.connect(self._run)

    def sync(self):
        src = self.resolved.action
        allowed = self._ctx.allowed(self.command)
        if src is None:
            self.setEnabled(self.resolved.available and allowed)
            return
        self.setEnabled(src.isEnabled() and allowed)
        if src.isCheckable():
            self.setChecked(src.isChecked())

    def _run(self, _checked=False):
        if self.command.source.type in menu_anchor.FOREIGN_SOURCES:
            # Plugins öffnen ihr Menü oft selbst am ausgeblendeten Leistenknopf
            with menu_anchor.anchored(menu_anchor.trigger_widget(self)):
                self._ctx.resolver.trigger(self.command)
        else:
            self._ctx.resolver.trigger(self.command)
        # Bei exklusiven Werkzeugen ändert sich die QGIS-Aktion evtl. nicht
        # (schon aktiv); der eigene Haken wurde aber umgeschaltet.
        self.sync()
        self._ctx.after_trigger()


def activate_button(btn):
    """Button per Tastatur auslösen: Menü öffnen oder Aktion auslösen. False, wenn grau."""
    if not btn.isEnabled():
        return False
    if btn.menu() is not None and btn.popupMode() == QToolButton.InstantPopup:
        # popup statt showMenu: showMenu blockiert (exec) und hielte den Ereignisfilter fest
        btn.menu().popup(btn.mapToGlobal(btn.rect().bottomLeft()))
    elif btn.defaultAction() is not None:
        btn.defaultAction().trigger()
    else:
        btn.click()
    return True


def keyboard_menu(owner, main_action, menu):
    """Menü eines Split-Buttons für die Tastatur: Hauptbefehl oben, dann die Einträge."""
    if not owner.isEnabled():
        return False
    popup = QMenu(owner)
    popup.setToolTipsVisible(True)
    popup.setAttribute(Qt.WA_DeleteOnClose)
    popup.setObjectName("ribbon_keyboard_menu")
    if main_action is not None and main_action.isEnabled():
        popup.addAction(main_action)
        popup.addSeparator()
    menu.aboutToShow.emit()  # Zustände und Laufzeit-Einträge (Galerien) wie beim Öffnen
    for act in menu.actions():
        popup.addAction(act)
    popup.popup(owner.mapToGlobal(owner.rect().bottomLeft()))
    return True


def _base_button(parent, size):
    btn = QToolButton(parent)
    btn.setAutoRaise(True)
    set_size(btn, size)
    return btn


def set_size(btn, size):
    """Button auf groß/mittel/klein einstellen (beim Aufbau und bei adaptiver Breite)."""
    if size == "large":
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setIconSize(QSize(theme.LARGE_ICON, theme.LARGE_ICON))
        btn.setMinimumWidth(theme.LARGE_MIN_WIDTH)
        btn.setMaximumWidth(16777215)
        btn.setFixedHeight(theme.CONTENT_HEIGHT)
        btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    elif size == "medium":
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setIconSize(QSize(theme.SMALL_ICON, theme.SMALL_ICON))
        btn.setMinimumWidth(0)
        btn.setMaximumWidth(16777215)
        btn.setFixedHeight(theme.ROW_HEIGHT)
        btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    else:
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setIconSize(QSize(theme.SMALL_ICON, theme.SMALL_ICON))
        btn.setMinimumWidth(0)
        btn.setFixedSize(theme.SMALL_WIDTH, theme.ROW_HEIGHT)
    if btn.property("ribbon_size") != size:
        btn.setProperty("ribbon_size", size)
        # Neu polieren nur, wenn das Stylesheet schon angewendet ist; sonst
        # greift die Eigenschaft beim ersten Polieren (spart je Button ~0,2 ms)
        if btn.testAttribute(Qt.WA_WState_Polished):
            style = btn.style()
            style.unpolish(btn)
            style.polish(btn)


def text_width(widget, text):
    """Breite einer (ggf. mehrzeiligen) Beschriftung in der Schrift des Widgets."""
    fm = widget.fontMetrics()
    return max(fm.horizontalAdvance(line) for line in (text or " ").splitlines())


def button_width(btn, size, text=None, menu=False):
    """Breite eines Buttons in einer Größe (aus der Schrift berechnet, nicht aus Qt-Vorschlägen)."""
    if size == "small":
        return theme.SMALL_WIDTH + (MENU_INDICATOR - 4 if menu else 0)
    text = btn.text() if text is None else text
    if size == "large":
        label = theme.wrap_label(text.replace("\n", " "))
        if menu and not label.endswith(MENU_ARROW):
            label = label + " " + MENU_ARROW
        return max(theme.LARGE_MIN_WIDTH, text_width(btn, label) + theme.LARGE_PADDING)
    return (text_width(btn, text.replace("\n", " ")) + theme.SMALL_ICON + theme.MEDIUM_PADDING
            + (MENU_INDICATOR if menu else 0))


def apply_size(btn, size, text, menu=False):
    """Größe einstellen, Beschriftung anpassen und Breite festlegen; gibt die Breite zurück."""
    set_size(btn, size)
    plain = text.replace("\n", " ")
    if size == "large":
        label = theme.wrap_label(plain)
        if menu:
            label += " " + MENU_ARROW
    else:
        label = plain
    if btn.defaultAction() is not None:
        btn.defaultAction().setIconText(label)
    else:
        btn.setText(label)
    width = button_width(btn, size, plain, menu)
    if size != "small" or menu:
        btn.setFixedWidth(width)
    return width


def command_button(command, size, ctx, parent, label=None):
    """Button für einen einzelnen Befehl."""
    btn = _base_button(parent, size)
    act = ProxyAction(command, ctx, btn, label=label)
    btn.setDefaultAction(act)
    menu = act.resolved.menu is not None
    if menu:  # vorhandenes QGIS-Menü als Dropdown
        btn.setMenu(act.resolved.menu)
        btn.setPopupMode(QToolButton.InstantPopup)
    remember(btn, act.text(), menu)
    apply_size(btn, size, act.text(), menu)
    btn.setObjectName("ribbon_btn_" + command.id)
    ctx.add_target(btn, act.text(), lambda: activate_button(btn), command)
    return btn


def remember(btn, text, menu=False):
    """Beschriftung und Menü eines Buttons für spätere Größenwechsel merken."""
    btn.setProperty("ribbon_text", text)
    btn.setProperty("ribbon_menu", bool(menu))


def build_menu(items, ctx, parent, gallery=None):
    """Menü aus Befehlen und Untermenüs, optional mit Galerie oben.

    Ein Galerie-Steuerelement als Menüeintrag wird an Ort und Stelle als
    Abschnitt mit seinen Einträgen eingefügt. Beim Öffnen lesen eigene
    Aktionen mit Zustand ihren Zustand neu (z. B. Abfragemodus).
    """
    from .gallery import add_gallery

    menu = QMenu(parent)
    menu.setToolTipsVisible(True)
    menu.aboutToShow.connect(lambda: _sync_menu(menu))
    if gallery is not None:
        add_gallery(menu, gallery, ctx)
        if items:
            menu.addSeparator()
    for item in items:
        if hasattr(item, "items"):  # SubMenu
            sub = build_menu(item.items, ctx, menu, item.gallery)
            sub.setTitle(item.label)
            if item.icon:
                sub.setIcon(icons.menu_icon(item.key or item.label, ctx.resolver.theme_icon(item.icon)))
            menu.addMenu(sub)
            continue
        if item.gallery is not None:
            add_gallery(menu, item, ctx, section=True)
            continue
        res = ctx.resolver.resolve(item)
        if res.menu is not None:
            # Vorhandenes QGIS-Menü einhängen (dessen eigene Menüaktion, unverändert)
            menu.addMenu(res.menu)
            continue
        menu.addAction(ProxyAction(item, ctx, menu))
    return menu


def split_menu(split, ctx, parent):
    """Menü eines Split-Buttons. Ist der einzige Eintrag ein QGIS-Menü, dient dieses
    direkt als Dropdown (statt eines Menüs mit nur einem Untermenü)."""
    if len(split.items) == 1 and not hasattr(split.items[0], "items") and split.items[0].gallery is None:
        res = ctx.resolver.resolve(split.items[0])
        if res.menu is not None:
            return res.menu
    return build_menu(split.items, ctx, parent)


def _sync_menu(menu):
    """Beim Öffnen: eigene Aktionen mit Zustand neu lesen (z. B. Einstellung ohne Signal).

    Nur hier, nicht in ``ProxyAction.sync``: sync läuft auch während des
    Auslösens und würde den gerade gesetzten Zustand sonst überschreiben.
    """
    for act in _menu_proxies(menu):
        src = act.resolved.action
        if src is not None and hasattr(src, "refresh"):
            src.refresh()
        act.sync()


def _menu_proxies(menu):
    """Eigene Einträge eines Menüs samt eigener Untermenüs (ohne eingehängte QGIS-Menüs)."""
    for act in menu.actions():
        sub = act.menu()
        if sub is not None and sub.parent() is menu:
            yield from _menu_proxies(sub)
        elif isinstance(act, ProxyAction):
            yield act


def _follow_menu(btn, menu):
    """Button bedienbar, solange ein Menüeintrag bedienbar ist; folgt Änderungen."""
    def update():
        btn.setEnabled(_any_enabled(menu))

    for act in _menu_proxies(menu):
        act.changed.connect(update)  # beide gehören zum Ribbon und sterben gemeinsam
    update()


def _any_enabled(menu):
    for act in menu.actions():
        if act.property("ribbon_dynamic"):
            # Laufzeit-Galerie: Einträge stehen erst beim Öffnen fest (der Platzhalter ist
            # unsichtbar und meldet sich deshalb bei Qt als deaktiviert)
            return True
        if act.isSeparator():
            continue
        if act.menu() is not None and act.menu().parent() is menu:
            if _any_enabled(act.menu()):
                return True
        elif act.isEnabled():
            return True
    return False


class LargeSplitButton(QWidget):
    """Großer Split-Button wie in Pro: Icon oben (Hauptbefehl), Beschriftung mit Pfeil unten (Menü)."""

    def __init__(self, split, ctx, parent):
        QWidget.__init__(self, parent)
        self.split = split
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top = QToolButton(self)
        self.top.setObjectName("ribbon_split_top")
        self.top.setAutoRaise(True)
        self.top.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.top.setIconSize(QSize(theme.LARGE_ICON, theme.LARGE_ICON))
        self.top.setFixedHeight(SPLIT_TOP_HEIGHT)
        self.top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom = QToolButton(self)
        self.bottom.setObjectName("ribbon_split_bottom")
        self.bottom.setAutoRaise(True)
        self.bottom.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.bottom.setFixedHeight(theme.CONTENT_HEIGHT - SPLIT_TOP_HEIGHT)
        self.bottom.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.menu = split_menu(split, ctx, self.bottom)
        self.action = ProxyAction(split.command, ctx, self.top, label=split.display_label)
        self.top.setDefaultAction(self.action)
        text = theme.wrap_label(split.display_label) + " " + MENU_ARROW
        self.bottom.setText(text)
        self.bottom.setToolTip(self.action.toolTip())
        self.bottom.setMenu(self.menu)
        self.bottom.setPopupMode(QToolButton.InstantPopup)
        _follow_menu(self.bottom, self.menu)
        lay.addWidget(self.top)
        lay.addWidget(self.bottom)
        # Breite aus der Beschriftung (Qt-Vorschläge sind mit Stylesheet und Menü zu breit)
        self.setFixedWidth(self.large_width())
        self.setFixedHeight(theme.CONTENT_HEIGHT)
        self.setProperty("ribbon_size", "large")
        self.target = ctx.add_target(self, split.display_label,
                                     lambda: keyboard_menu(self, self.action, self.menu),
                                     split.command)

    def large_width(self):
        return max(theme.LARGE_MIN_WIDTH, text_width(self.bottom, self.bottom.text()) + SPLIT_PADDING)


def compact_split(split, ctx, parent, menu):
    """Mittlere/kleine Fassung eines großen Split-Buttons (adaptive Breite), gleiches Menü."""
    btn = _base_button(parent, "medium")
    act = ProxyAction(split.command, ctx, btn, label=split.display_label)
    btn.setDefaultAction(act)
    btn.setMenu(menu)
    btn.setPopupMode(QToolButton.MenuButtonPopup)
    btn.setObjectName("ribbon_split_compact_" + split.command.id)
    remember(btn, act.text(), True)
    ctx.widget_commands[btn] = split.command
    btn.keyboard = lambda: keyboard_menu(btn, act, menu)
    return btn


def split_button(split, ctx, parent):
    """Hauptbefehl mit Dropdown. Ist der Hauptbefehl nicht verfügbar, öffnet der Klick das Menü."""
    if split.size == "large" and ctx.resolver.resolve(split.command).available:
        w = LargeSplitButton(split, ctx, parent)
        w.setObjectName("ribbon_split_" + split.command.id)
        return w
    btn = _base_button(parent, split.size)
    menu = split_menu(split, ctx, btn)
    act = ProxyAction(split.command, ctx, btn, label=split.display_label)
    if act.resolved.available:
        btn.setDefaultAction(act)
        btn.setMenu(menu)
        btn.setPopupMode(QToolButton.MenuButtonPopup)
        btn.keyboard = lambda: keyboard_menu(btn, act, menu)
        btn.target = ctx.add_target(btn, act.text(), btn.keyboard, split.command)
    else:
        btn.setIcon(act.icon())
        btn.setToolTip(act.toolTip())
        btn.setMenu(menu)
        btn.setPopupMode(QToolButton.InstantPopup)
        _follow_menu(btn, menu)
        btn.target = ctx.add_target(btn, act.text(), lambda: activate_button(btn), split.command)
    remember(btn, act.text(), True)
    apply_size(btn, split.size, act.text(), True)
    btn.setObjectName("ribbon_split_" + split.command.id)
    return btn


def menu_button(menu_el, ctx, parent):
    """Dropdown-Button ohne eigenen Befehl, optional mit Galerie oben im Menü."""
    btn = _base_button(parent, menu_el.size)
    menu = build_menu(menu_el.items, ctx, btn, menu_el.gallery)
    icon = ctx.resolver.theme_icon(menu_el.icon) if menu_el.icon else None
    if icon is None or icon.isNull():
        first = next((a for a in menu.actions() if not a.isSeparator() and not a.icon().isNull()), None)
        icon = first.icon() if first is not None else None
    key = menu_el.gallery.id if menu_el.gallery is not None else None
    own = icons.command_icon(menu_el.gallery, None) if key else None
    if own is None or own.isNull():
        own = icons.menu_icon(menu_el.key or menu_el.label, icon)
    if own is not None:
        btn.setIcon(own)
    description = menu_el.gallery.description if menu_el.gallery is not None else None
    btn.setToolTip("<b>%s</b>" % escape(menu_el.label)
                   + ("<br>%s" % escape(description) if description else ""))
    btn.setMenu(menu)
    btn.setPopupMode(QToolButton.InstantPopup)
    _follow_menu(btn, menu)
    remember(btn, menu_el.label, True)
    apply_size(btn, menu_el.size, menu_el.label, True)
    btn.target = ctx.add_target(btn, menu_el.label, lambda: activate_button(btn), menu_el.gallery)
    return btn


def command_widget(command, size, ctx, parent):
    """Widget für einen Befehl: Galerie, Steuerelement oder Button.

    Nicht registrierte Steuerelemente erscheinen als grauer Button mit Hinweis.
    """
    from ...qgis_integration import custom_commands
    from .custom import control_widget
    from .gallery import RibbonGallery, gallery_button

    cid = command.source.get("id") if command.source.type == "custom" else None
    if command.gallery is not None or (cid and custom_commands.kind_of(cid) == "gallery"):
        if command.gallery is not None and command.gallery.display == "ribbon" and size == "large":
            return RibbonGallery(command, ctx, parent)
        return gallery_button(command, size, ctx, parent)
    if command.kind == "control":
        w = control_widget(command, size, ctx, parent)
        if w is not None:
            return w
    return command_button(command, size, ctx, parent)


def row_widget(row, ctx, parent):
    """Zeile kleiner Buttons (und Steuerelemente) ohne Beschriftung."""
    w = QWidget(parent)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for cmd in row.commands:
        lay.addWidget(command_widget(cmd, "small", ctx, w))
    lay.addStretch(1)
    w.setFixedHeight(theme.ROW_HEIGHT)
    return w
