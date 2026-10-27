import pytest

from pinyin_matcher.pretrained_native_clips import selected_items


def test_selection_is_per_speaker_deterministic_and_does_not_depend_on_input_order():
    items = [
        {"speakerId": f"speaker-{i:02}", "id": f"speaker-{i:02}-utterance-{j}"}
        for i in range(20)
        for j in range(4)
    ]
    first = selected_items(items, 20261027, 2)
    assert first == selected_items(list(reversed(items)), 20261027, 2)
    assert len(first) == 40
    assert all(sum(x["speakerId"] == f"speaker-{i:02}" for x in first) == 2 for i in range(20))


def test_selection_rejects_incomplete_speaker_inventory():
    with pytest.raises(ValueError, match="SPEAKER_INVENTORY_CHANGED"):
        selected_items([{"speakerId": "only-one", "id": "one"}], 20261027, 1)
