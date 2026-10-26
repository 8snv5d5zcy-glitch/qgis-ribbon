import copy

import pytest

from qgis_ribbon.core import theme_tokens as tt


@pytest.fixture(scope="module")
def shipped():
    return tt.load()


def _data(shipped):
    return {
        "name": "Test",
        "modes": copy.deepcopy(shipped.modes),
        "accents": copy.deepcopy(shipped.accents),
        "default_accent": shipped.default_accent,
    }


def test_shipped_theme_loads_and_passes_contrast(shipped):
    assert tt.check(shipped) == []
    assert set(shipped.accent_ids()) == {"moos", "kobalt", "bernstein"}
    assert shipped.default_accent == "moos"


def test_tokens_include_accent_and_derived_values(shipped):
    t = shipped.tokens("dunkel", "kobalt")
    assert t["acc"] == shipped.accents["kobalt"]["dunkel"]["acc"]
    assert t["icf"] == t["acc"] + tt.ICON_FILL_ALPHA
    assert t["tipText"] == t["surf"]
    assert t["mode"] == "dunkel" and t["accent"] == "kobalt"


def test_unknown_accent_falls_back_to_default(shipped):
    assert shipped.tokens("hell", "gibtsnicht")["accent"] == "moos"


def test_contrast_values():
    assert tt.contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert tt.contrast("#777777", "#777777") == pytest.approx(1.0)


def test_low_contrast_is_reported(shipped):
    data = _data(shipped)
    data["modes"]["hell"]["muted"] = "#C0C0C0"
    with pytest.raises(tt.ThemeError) as exc:
        tt.parse(data)
    assert any("muted auf surf" in e for e in exc.value.errors)


def test_missing_and_invalid_tokens_are_collected(shipped):
    data = _data(shipped)
    del data["modes"]["dunkel"]["text"]
    data["modes"]["hell"]["surf"] = "weiss"
    data["modes"]["hell"]["extra"] = "#000000"
    data["accents"]["moos"]["hell"]["acc"] = "#12345"
    data["default_accent"] = "rot"
    with pytest.raises(tt.ThemeError) as exc:
        tt.parse(data)
    text = "\n".join(exc.value.errors)
    for part in ("dunkel.text", "hell.surf", "hell.extra", "moos.hell.acc", "Standard-Akzent"):
        assert part in text


def test_alpha_only_where_allowed(shipped):
    data = _data(shipped)
    data["modes"]["hell"]["text"] = "#1B2027FF"
    with pytest.raises(tt.ThemeError):
        tt.parse(data)
    assert tt.alpha("#00000066") == 0x66 and tt.alpha("#000000") == 255


@pytest.mark.parametrize("setting, lightness, mode", [
    ("auto", 240, "hell"), ("auto", 40, "dunkel"), ("hell", 40, "hell"),
    ("dunkel", 240, "dunkel"), ("unsinn", 40, "dunkel"),
])
def test_resolve_mode(setting, lightness, mode):
    assert tt.resolve_mode(setting, lightness) == mode
