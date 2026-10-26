"""Datenmodell des Ribbons (ohne qgis-Imports).

Befehle (``Command``) sind einmal definiert und werden von den Elementen der
Gruppen referenziert. Elemente einer Gruppe:

- ``CommandRef``: ein Befehl als Button (groß, mittel oder klein);
- ``Split``: Hauptbefehl mit Dropdown-Menü;
- ``Menu``: Dropdown-Button ohne eigenen Befehl, optional mit Galerie;
- ``Row``: Zeile kleiner Buttons ohne Beschriftung (Toolbar in einer Gruppe).

Menüeinträge sind ``Command`` oder ``SubMenu``. Ein Steuerelement
(``kind: control``) kann eine Galerie tragen (``Gallery``): feste Einträge
(andere Befehle) und die Darstellung im Ribbon oder als Dropdown. Einträge,
die erst zur Laufzeit feststehen (Lesezeichen, Grundkarten ...), liefert der
eigene Befehl selbst. Gruppen haben optional einen Dialog-Launcher.
Alle Objekte sind unveränderlich; Listen sind Tupel.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Union
from .i18n import tr

# Größen: large = großes Icon mit Text darunter, medium = kleines Icon mit
# Text daneben, small = nur kleines Icon (Text im Tooltip).
SIZES = ("large", "medium", "small")
# Befehlsarten: button = auslösbarer Befehl, control = Steuerelement
# (Regler, Combobox, Galerie).
COMMAND_KINDS = ("button", "control")
# Galerie-Darstellung: ribbon = Icon-Reihe direkt im Ribbon mit Aufklapp-Pfeil,
# dropdown = Button, der die Galerie als Raster aufklappt.
GALLERY_DISPLAYS = ("ribbon", "dropdown")


@dataclass(frozen=True)
class Source:
    type: str
    params: Dict[str, object] = field(default_factory=dict, hash=False, compare=True)

    def get(self, key, default=None):
        return self.params.get(key, default)


@dataclass(frozen=True)
class Gallery:
    items: Tuple["Command", ...] = ()
    display: str = "dropdown"
    columns: int = 4

    def __post_init__(self):
        if self.display not in GALLERY_DISPLAYS:
            raise ValueError(tr("Invalid gallery display: %r") % self.display)
        if self.columns < 1:
            raise ValueError(tr("Gallery needs at least one column"))


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    source: Source
    kind: str = "button"
    icon: Optional[str] = None
    # Bedingungen (core.conditions), die alle gelten müssen, damit der Befehl
    # bedienbar ist. Gilt zusätzlich zum Zustand der QGIS-Quelle.
    enabled_when: Tuple[str, ...] = ()
    # Beschreibung für den Tooltip (Rich-Tooltip: Titel, Beschreibung, Tastenkürzel)
    description: Optional[str] = None
    gallery: Optional[Gallery] = None

    def __post_init__(self):
        if self.kind not in COMMAND_KINDS:
            raise ValueError(tr("Invalid command kind: %r") % self.kind)
        if self.gallery is not None and self.kind != "control":
            raise ValueError(tr("Gallery only on controls (kind: control): %s") % self.id)


@dataclass(frozen=True)
class SubMenu:
    label: str
    items: Tuple["MenuItem", ...]
    icon: Optional[str] = None
    gallery: Optional[Command] = None
    key: Optional[str] = None       # wie Menu.key (Icons, unabhängig von der Sprache)


MenuItem = Union[Command, SubMenu]


def _check_size(size):
    if size not in SIZES:
        raise ValueError(tr("Invalid size: %r") % size)


@dataclass(frozen=True)
class CommandRef:
    command: Command
    size: str = "large"

    def __post_init__(self):
        _check_size(self.size)


@dataclass(frozen=True)
class Split:
    command: Command
    items: Tuple[MenuItem, ...]
    size: str = "large"
    label: Optional[str] = None

    def __post_init__(self):
        _check_size(self.size)

    @property
    def display_label(self):
        return self.label or self.command.label


@dataclass(frozen=True)
class Menu:
    label: str
    items: Tuple[MenuItem, ...]
    size: str = "large"
    icon: Optional[str] = None
    gallery: Optional[Command] = None
    # Schlüssel für Anpassungen (``customization.element_key``), unabhängig von der
    # Sprache; ohne Angabe die Beschriftung
    key: Optional[str] = None

    def __post_init__(self):
        _check_size(self.size)


@dataclass(frozen=True)
class Row:
    commands: Tuple[Command, ...]


Element = Union[CommandRef, Split, Menu, Row]


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    elements: Tuple[Element, ...] = ()
    # Dialog-Launcher: kleiner Pfeil unten rechts an der Gruppe
    launcher: Optional[Command] = None


@dataclass(frozen=True)
class Tab:
    id: str
    label: str
    groups: Tuple[Group, ...] = ()
    # Kontext-Tabs: Beschriftung der Kontextgruppe (z. B. "Vektorlayer") und
    # Bedingungen für die Sichtbarkeit (alle müssen gelten).
    context: Optional[str] = None
    visible_when: Tuple[str, ...] = ()
    # Ereignisse (core.conditions.EVENTS), bei denen der Tab nach vorn kommt.
    activate_on: Tuple[str, ...] = ()
    # Inhalt erst zur Laufzeit: "erweiterungen" = Aktionen anderer Plugins
    dynamic: Optional[str] = None

    @property
    def contextual(self):
        return self.context is not None


@dataclass(frozen=True)
class ExtensionSources:
    """Wo Plugins ihre Aktionen ablegen (Abschnitt ``extensions`` der Definition)."""

    menus: Tuple[str, ...] = ()          # Plugin-Menüs (objectName), je Plugin ein Untermenü
    toolbars: Tuple[str, ...] = ()       # QGIS-Werkzeugleisten, in die Plugins Buttons legen
    qgis_toolbars: Tuple[str, ...] = ()  # übrige QGIS-Werkzeugleisten (keine Plugin-Leisten)
    hide: bool = True                    # Plugin-Werkzeugleisten ausblenden

    def plugin_toolbar(self, name):
        """Eigene Werkzeugleiste eines Plugins (weder QGIS-Leiste noch Sammelleiste)?"""
        return name not in self.qgis_toolbars and name not in self.toolbars


@dataclass(frozen=True)
class Ribbon:
    tabs: Tuple[Tab, ...]
    commands: Dict[str, Command] = field(default_factory=dict, hash=False)
    quick_access: Tuple[Command, ...] = ()
    hide_toolbars: Tuple[str, ...] = ()
    extensions: ExtensionSources = field(default_factory=ExtensionSources)

    def tab(self, tab_id):
        for t in self.tabs:
            if t.id == tab_id:
                return t
        raise KeyError(tab_id)


def iter_commands(item):
    """Alle Befehle eines Elements, Menüeintrags, einer Gruppe oder eines Tabs.

    Enthält auch die festen Galerie-Einträge und die Dialog-Launcher.
    """
    if isinstance(item, Command):
        yield item
        if item.gallery is not None:
            for c in item.gallery.items:
                yield from iter_commands(c)
    elif isinstance(item, CommandRef):
        yield from iter_commands(item.command)
    elif isinstance(item, Split):
        yield from iter_commands(item.command)
        for i in item.items:
            yield from iter_commands(i)
    elif isinstance(item, (Menu, SubMenu)):
        if item.gallery is not None:
            yield from iter_commands(item.gallery)
        for i in item.items:
            yield from iter_commands(i)
    elif isinstance(item, Row):
        for c in item.commands:
            yield from iter_commands(c)
    elif isinstance(item, Group):
        for e in item.elements:
            yield from iter_commands(e)
        if item.launcher is not None:
            yield item.launcher
    elif isinstance(item, Tab):
        for g in item.groups:
            yield from iter_commands(g)
    else:
        raise TypeError(tr("Unknown ribbon object: %r") % (item,))
