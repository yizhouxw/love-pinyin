"""Complete word coverage, original deterministic SVG assets and explicit semantic recipes."""

import hashlib
import json

from scripts.build_word_images import CATALOG, OUT, scene
from server.word_practice import CONTENT


def test_every_read_and_write_word_has_a_verified_picture():
    lessons = json.loads(CONTENT.read_text())["lessons"]
    items = json.loads(CATALOG.read_text())["items"]
    words = {word["text"] for lesson in lessons for word in lesson["read"] + lesson["write"]}
    assert set(items) == words
    assert len(items) == 736
    for word, item in items.items():
        assert item["scene"] and item["variant"] and word in item["description"]
        assert (
            hashlib.sha256((OUT / f"{item['id']}.svg").read_bytes()).hexdigest() == item["sha256"]
        )
        assert len(scene(item["scene"], item["variant"])) > 80


def test_distinguishes_meaningful_similar_words_and_special_objects():
    items = json.loads(CATALOG.read_text())["items"]
    assert items["转笔刀"]["variant"] == "sharpener"
    assert items["上火"]["scene"] == "body"
    assert items["火山"]["variant"] == "volcano"
    assert items["雨伞"]["variant"] != items["跳伞"]["variant"]
    assert items["一模一样"]["variant"] != items["独一无二"]["variant"]
    assert items["红灯"]["variant"] != items["绿灯"]["variant"]


def test_lesson_picker_has_all_eight_textbook_units():
    lessons = json.loads(CONTENT.read_text())["lessons"]
    assert {lesson["unit"] for lesson in lessons} == set(range(1, 9))
    assert [sum(lesson["unit"] == unit for lesson in lessons) for unit in range(1, 9)] == [
        5,
        3,
        6,
        6,
        5,
        5,
        4,
        4,
    ]
