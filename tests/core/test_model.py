import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qgis_ribbon.core.model import (Command, CommandRef, Group, Menu, Row, Source,  # noqa: E402
                                    Split, SubMenu, Tab, iter_commands)


def cmd(cid, kind="button"):
    return Command(id=cid, label=cid.title(), source=Source("qgis_action", {"object_name": cid}),
                   kind=kind)


def test_command_rejects_invalid_kind():
    with pytest.raises(ValueError):
        cmd("pan", kind="slider")


def test_elements_reject_invalid_size():
    with pytest.raises(ValueError):
        CommandRef(cmd("pan"), size="huge")
    with pytest.raises(ValueError):
        Split(cmd("pan"), (cmd("zoom"),), size="tiny")


def test_split_display_label_falls_back_to_command():
    assert Split(cmd("pan"), ()).display_label == "Pan"
    assert Split(cmd("pan"), (), label="Auswählen").display_label == "Auswählen"


def test_iter_commands_walks_all_elements():
    gallery = cmd("galerie", kind="control")
    group = Group("g", "G", (
        CommandRef(cmd("a")),
        Split(cmd("b"), (cmd("c"), SubMenu("Sub", (cmd("d"),)))),
        Menu("M", (cmd("e"),), gallery=gallery),
        Row((cmd("f"), cmd("g"))),
    ))
    tab = Tab("t", "T", (group,))
    assert [c.id for c in iter_commands(tab)] == ["a", "b", "c", "d", "galerie", "e", "f", "g"]


def test_contextual_tab_flag():
    assert not Tab("karte", "Karte").contextual
    assert Tab("daten", "Daten", context="Vektorlayer", visible_when=("x",)).contextual


def test_iter_commands_includes_gallery_items_and_launcher():
    from qgis_ribbon.core.model import Gallery
    gallery = Command(id="galerie", label="Galerie", source=Source("custom", {"id": "x"}),
                      kind="control", gallery=Gallery(items=(cmd("a"), cmd("b"))))
    group = Group("g", "G", (Menu("M", (cmd("e"),), gallery=gallery),), launcher=cmd("opt"))
    assert [c.id for c in iter_commands(group)] == ["galerie", "a", "b", "e", "opt"]


def test_gallery_only_on_controls():
    from qgis_ribbon.core.model import Gallery
    with pytest.raises(ValueError):
        Command(id="x", label="X", source=Source("custom", {"id": "x"}), gallery=Gallery())
    with pytest.raises(ValueError):
        Gallery(display="band")
