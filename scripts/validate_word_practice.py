"""Validate word source inventory and production voice coverage."""

import argparse
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from server import learning_audio, word_practice


def validate(release: bool = False) -> None:
    data = json.loads(word_practice.CONTENT.read_text())
    lessons = data["lessons"]
    assert len(lessons) == len({lesson["id"] for lesson in lessons}) == 38
    assert len(set("".join(lesson["characters"] for lesson in lessons))) == 280
    source = Path(data["source"]["file"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == data["source"]["sha256"]
    for lesson in lessons:
        assert lesson["read"] and 1 <= lesson["page"] <= 4
        assert len(lesson["characterItems"]) == len(set(lesson["characters"]))
        for mode in ("read", "write"):
            words = lesson[mode]
            assert len(words) == len({word["text"] for word in words})
            for word in words:
                assert word["text"].strip() == word["text"] and not any(
                    char.isspace() for char in word["text"]
                )
                assert unicodedata.normalize("NFC", word["pinyin"]) == word["pinyin"]
        if lesson["reciteRequirement"] or lesson["reading"]:
            assert lesson["passages"]
        for passage in lesson["passages"]:
            assert 1 <= passage["page"] <= 104 and passage["paragraphs"]
    images = json.loads((word_practice.CONTENT.parent / "images.json").read_text())["items"]
    words = {word["text"] for lesson in lessons for word in lesson["read"] + lesson["write"]}
    assert images.keys() == words
    assert len({item["id"] for item in images.values()}) == len(words)
    for word, item in images.items():
        assert re.fullmatch(r"[0-9a-f]{16}", item["id"])
        assert item["description"] and item["scene"] and item["variant"]
        image = word_practice.CONTENT.parents[2] / "public/word-illustrations" / f"{item['id']}.svg"
        raw = image.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        root = ET.fromstring(raw)
        assert root.attrib["viewBox"] == "0 0 360 240"
        assert root.find("{http://www.w3.org/2000/svg}title").text == word
        assert (
            sum(
                node.tag.rsplit("}", 1)[-1] in {"path", "circle", "rect", "ellipse"}
                for node in root.iter()
            )
            > 1
        )
        assert not any(
            node.tag.endswith(("script", "image", "foreignObject")) for node in root.iter()
        )
    scripts = word_practice.scripts()
    assert scripts.keys() <= learning_audio.narration_scripts().keys()
    if release:
        assets = learning_audio.available_assets()
        missing = {key for key in scripts if not assets.get(key)}
        assert not missing, f"Missing word practice voices: {sorted(missing)}"
    print(f"Word practice: {len(lessons)} lessons, {len(scripts)} voice IDs validated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    validate(parser.parse_args().release)
