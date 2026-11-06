"""Source consistency and production narration boundary checks."""

import json

from scripts.validate_word_practice import validate
from server import learning_audio, word_practice


def test_word_practice_source_and_voice_registration():
    validate()
    scripts = word_practice.scripts()
    for asset_id, text in scripts.items():
        assert learning_audio.narration_scripts()[asset_id] == text
        assert not learning_audio._LATIN.search(text)


def test_revised_textbook_and_pinyin_context_regressions():
    data = json.loads(word_practice.CONTENT.read_text())
    lessons = {lesson["title"]: lesson for lesson in data["lessons"]}
    assert "我的小书包" in lessons["小书包"]["passages"][0]["paragraphs"][0]["text"]
    assert "上课静悄悄" not in str(lessons["小书包"]["passages"])
    words = {word["text"]: word["pinyin"] for lesson in data["lessons"] for word in lesson["read"]}
    assert words["转笔刀"] == "zhuàn bǐ dāo"
    assert words["开心地说"] == "kāi xīn de shuō"
    assert words["长短"] == "cháng duǎn"
    assert words["船长"] == "chuán zhǎng"
    assert words["爸爸"] == "bà ba"
