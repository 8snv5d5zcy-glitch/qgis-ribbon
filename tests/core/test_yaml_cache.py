"""Zwischenspeicher der mitgelieferten YAML-Dateien."""
import json
import os

import pytest

from qgis_ribbon.core import config_loader, icons, yaml_cache


@pytest.fixture(autouse=True)
def no_global_dir():
    yaml_cache.set_dir(None)
    yield
    yaml_cache.set_dir(None)


def counting_reader(calls):
    def read(path):
        calls.append(path)
        return {"wert": 1, "liste": [1, "zwei", True, None], "text": "Größe"}
    return read


def test_without_dir_always_reads_yaml(tmp_path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1\n", encoding="utf-8")
    calls = []
    for _ in range(2):
        yaml_cache.load(str(src), counting_reader(calls))
    assert len(calls) == 2


def test_second_load_comes_from_cache(tmp_path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1\n", encoding="utf-8")
    calls = []
    first = yaml_cache.load(str(src), counting_reader(calls), str(tmp_path / "cache"))
    second = yaml_cache.load(str(src), counting_reader(calls), str(tmp_path / "cache"))
    assert len(calls) == 1
    assert first == second


def test_global_dir_is_used(tmp_path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1\n", encoding="utf-8")
    yaml_cache.set_dir(str(tmp_path / "cache"))
    calls = []
    yaml_cache.load(str(src), counting_reader(calls))
    yaml_cache.load(str(src), counting_reader(calls))
    assert len(calls) == 1
    assert yaml_cache.get_dir() == str(tmp_path / "cache")


def test_changed_yaml_invalidates_cache(tmp_path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1\n", encoding="utf-8")
    cache = str(tmp_path / "cache")
    calls = []
    yaml_cache.load(str(src), counting_reader(calls), cache)
    src.write_text("x: 22\n", encoding="utf-8")   # andere Größe
    yaml_cache.load(str(src), counting_reader(calls), cache)
    st = os.stat(src)
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))   # gleiche Größe, neue Zeit
    yaml_cache.load(str(src), counting_reader(calls), cache)
    assert len(calls) == 3


def test_broken_cache_falls_back_to_yaml(tmp_path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1\n", encoding="utf-8")
    cache = str(tmp_path / "cache")
    calls = []
    yaml_cache.load(str(src), counting_reader(calls), cache)
    with open(yaml_cache.cache_file(str(src), cache), "w", encoding="utf-8") as fh:
        fh.write("{kaputt")
    data = yaml_cache.load(str(src), counting_reader(calls), cache)
    assert len(calls) == 2
    assert data["text"] == "Größe"
    with open(yaml_cache.cache_file(str(src), cache), encoding="utf-8") as fh:
        assert json.load(fh)["data"] == data   # neu geschrieben


def test_unwritable_dir_is_ignored(tmp_path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1\n", encoding="utf-8")
    blocker = tmp_path / "datei"
    blocker.write_text("", encoding="utf-8")
    calls = []
    data = yaml_cache.load(str(src), counting_reader(calls), str(blocker / "cache"))
    assert data["wert"] == 1
    assert not os.path.exists(str(blocker) + ".tmp")


def test_cache_files_differ_per_path(tmp_path):
    a = yaml_cache.cache_file(str(tmp_path / "x" / "ribbon.yaml"), "c")
    b = yaml_cache.cache_file(str(tmp_path / "y" / "ribbon.yaml"), "c")
    assert a != b
    assert os.path.basename(a).startswith("ribbon_")


def test_shipped_files_survive_json_round_trip(tmp_path):
    """Definition und Icon-Set enthalten nur JSON-taugliche Werte: Ergebnis wie aus dem YAML."""
    cache = str(tmp_path / "cache")
    direct = config_loader.load()
    config_loader.load(cache_dir=cache)
    assert config_loader.load(cache_dir=cache) == direct
    for path, read in ((config_loader.DEFAULT_CONFIG, config_loader.read_yaml),
                       (icons.DEFAULT_ICONS, icons.read_yaml)):
        data = read(path)
        assert json.loads(json.dumps(data)) == data
    plain = icons.load()
    yaml_cache.set_dir(cache)
    icons.load()
    cached = icons.load()
    for attr in ("motifs", "commands", "menus", "ui"):
        assert getattr(cached, attr) == getattr(plain, attr)


def test_read_yaml_reports_syntax_errors(tmp_path):
    bad = tmp_path / "kaputt.yaml"
    bad.write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(config_loader.ConfigError):
        config_loader.read_yaml(str(bad))
    with pytest.raises(icons.IconError):
        icons.read_yaml(str(bad))
