"""Anleitung: Seiten je Sprache vollständig, Bilder und Links vorhanden."""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
HELP = os.path.join(ROOT, "qgis_ribbon", "help")
LANGUAGES = ("en", "de")
LINK = re.compile(r"(!?)\[[^\]]*\]\(([^)\s]+)\)")


def _topics():
    # guide.py importiert Qt; die Themen stehen dort als einfaches Tupel
    with io.open(os.path.join(ROOT, "qgis_ribbon", "ui", "guide.py"), encoding="utf-8") as fh:
        source = fh.read()
    match = re.search(r"^TOPICS = \(([^)]*)\)", source, re.M)
    return re.findall(r'"([a-z_]+)"', match.group(1))


TOPICS = _topics()


def test_topics_found():
    assert "index" in TOPICS and len(TOPICS) >= 5


@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_topic_has_a_page(lang):
    pages = sorted(n[:-3] for n in os.listdir(os.path.join(HELP, lang)) if n.endswith(".md"))
    assert pages == sorted(TOPICS)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_links_and_images_resolve(lang):
    folder = os.path.join(HELP, lang)
    for topic in TOPICS:
        with io.open(os.path.join(folder, topic + ".md"), encoding="utf-8") as fh:
            text = fh.read()
        assert text.startswith("# "), topic
        for image, target in LINK.findall(text):
            if target.startswith("https://"):
                continue
            assert "#" not in target, (topic, target)
            path = os.path.normpath(os.path.join(folder, target))
            assert os.path.isfile(path), (topic, target)
            if image:
                assert "/images/%s/" % lang in target, (topic, target)
            else:
                assert target.endswith(".md"), (topic, target)


def test_images_are_used_and_alike():
    used = set()
    for lang in LANGUAGES:
        for topic in TOPICS:
            with io.open(os.path.join(HELP, lang, topic + ".md"), encoding="utf-8") as fh:
                used.update(os.path.basename(t) for img, t in LINK.findall(fh.read()) if img)
    for lang in LANGUAGES:
        names = set(os.listdir(os.path.join(HELP, "images", lang)))
        assert names == set(os.listdir(os.path.join(HELP, "images", LANGUAGES[0]))), lang
        # guide.png ist für README und Plugin-Seite gedacht
        assert not (names - used - {"guide.png", "header.png"}), names - used


def test_pages_stay_small():
    for folder, _dirs, files in os.walk(os.path.join(HELP, "images")):
        for name in files:
            assert os.path.getsize(os.path.join(folder, name)) < 400 * 1024, name
