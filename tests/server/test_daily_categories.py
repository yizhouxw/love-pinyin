"""Review regressions: preserve the source while separating phrases from sentences."""

import copy
import json

import pytest

from scripts.validate_daily_reading import validate_categories
from server import daily_reading


def catalogues():
    root = daily_reading.CONTENT.parent
    return (
        copy.deepcopy(daily_reading.load()),
        json.loads((root / "daily-reading-navigation.json").read_text()),
        json.loads((root / "daily-reading-hanzi.json").read_text()),
    )


def test_review_preserves_categories_and_unique_source_order():
    data, navigation, hanzi = catalogues()
    items = [
        item for day in data["days"] for section in day["sections"] for item in section["items"]
    ]
    assert len(items) == 785
    validate_categories(data, navigation, hanzi)
    assert len(hanzi) == 236
    for day, moved in zip(data["days"][10:], [6, 5, 4, 6], strict=True):
        words, sentences = day["sections"][-2:]
        assert words["kind"] == "words"
        assert sentences["kind"] == "sentences"
        assert len(sentences["items"]) == 3
        # Original IDs survive their move to the preceding word section.
        assert all(
            item["id"].split("-s")[1].split("-")[0] == ("6" if day["number"] == 11 else "7")
            for item in words["items"][-moved:]
        )


@pytest.mark.parametrize("number", [11, 12, 13, 14])
def test_a_word_moved_back_into_sentences_is_rejected(number):
    data, navigation, hanzi = catalogues()
    words, sentences = data["days"][number - 1]["sections"][-2:]
    word = words["items"].pop()
    sentences["items"].insert(0, word)
    navigation[words["id"]][-1]["itemIds"].remove(word["id"])
    navigation[sentences["id"]][0]["itemIds"].insert(0, word["id"])
    with pytest.raises(ValueError, match="word/sentence category"):
        validate_categories(data, navigation, hanzi)


def test_comparisons_and_spelling_cannot_be_labelled_as_words():
    data, navigation, hanzi = catalogues()
    for section_id in ["day-05-section-2", "day-06-section-3"]:
        bad = copy.deepcopy(navigation)
        bad[section_id][0]["family"] = "词句"
        with pytest.raises(ValueError, match="navigation category"):
            validate_categories(data, bad, hanzi)
    del hanzi["day-14-s7-i1"]
    with pytest.raises(ValueError, match="character coverage"):
        validate_categories(data, navigation, hanzi)
