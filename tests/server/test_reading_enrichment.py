import copy
import hashlib

import pytest
from fastapi import HTTPException
from pypinyin import Style, lazy_pinyin

from server import daily_reading, playback_settings, profile_backup, reading_timings
from tests.server.test_profile_import import confirm, preview


def set_gap(client, value):
    return client.put(
        "/api/v1/household/settings",
        json={"soundEnabled": True, "playbackGapSeconds": value},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )


def test_gap_settings_boundaries_persist_and_other_settings_preserve_them(paired_client):
    assert (
        paired_client.get("/api/v1/profiles/progress").json()["settings"]["playbackGapSeconds"] == 1
    )
    for value in (0.1, 0.3, 5):
        assert set_gap(paired_client, value).status_code == 200
        assert (
            paired_client.get("/api/v1/bootstrap").json()["profile"]["settings"][
                "playbackGapSeconds"
            ]
            == value
        )
    changed = paired_client.put(
        "/api/v1/household/settings",
        json={"soundEnabled": False},
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    )
    assert changed.json()["settings"]["playbackGapSeconds"] == 5
    for value in (0, 0.05, 5.1, 1.23, True, "0.3"):
        assert set_gap(paired_client, value).status_code == 422
    for value in (float("inf"), float("nan"), False, None):
        with pytest.raises(ValueError):
            playback_settings.gap_tenths(value)


def test_gap_backup_round_trip_and_missing_legacy_field_default(paired_client):
    set_gap(paired_client, 2.7)
    backup = paired_client.get("/api/v1/profiles/export").json()
    assert backup["profile"]["settings"]["playbackGapSeconds"] == 2.7
    set_gap(paired_client, 0.1)
    assert confirm(paired_client, preview(paired_client, backup).json()).status_code == 200
    assert (
        paired_client.get("/api/v1/profiles/progress").json()["settings"]["playbackGapSeconds"]
        == 2.7
    )
    del backup["profile"]["settings"]["playbackGapSeconds"]
    assert confirm(paired_client, preview(paired_client, backup).json()).status_code == 200
    assert (
        paired_client.get("/api/v1/profiles/progress").json()["settings"]["playbackGapSeconds"] == 1
    )
    for invalid in (False, 0, 5.2, 1.25, "1"):
        damaged = copy.deepcopy(backup)
        damaged["profile"]["settings"]["playbackGapSeconds"] = invalid
        with pytest.raises(HTTPException):
            profile_backup._validate_backup(damaged)


def test_all_word_building_items_have_tone_matching_examples_and_chinese_scripts():
    examples = daily_reading.word_examples()
    for day in daily_reading.load()["days"]:
        for section in day["sections"]:
            if "组词" not in section["title"]:
                continue
            for item in section["items"]:
                sample = examples[item["display"]]
                assert 1 <= len(sample["examples"]) <= 2
                for word in sample["examples"]:
                    pinyin = lazy_pinyin(word["text"], style=Style.TONE)
                    assert item["display"] in pinyin
                    assert word["pinyin"] == " ".join(pinyin)
                assert daily_reading.scripts()[sample["id"]] == sample["spokenText"]


def test_reading_timeline_rejects_wrong_audio_text_missing_units_and_invalid_times():
    item = {"spokenText": "弟弟哭了。", "syllables": ["dì", "di", "kū", "le"]}
    timeline = {
        "sha256": "a" * 64,
        "textSha256": hashlib.sha256(item["spokenText"].encode()).hexdigest(),
        "timings": [{"start": i * 0.2, "end": (i + 1) * 0.2} for i in range(4)],
    }
    asset = {"sha256": "a" * 64, "durationSeconds": 0.9}
    assert len(reading_timings.checked(item, asset, timeline)) == 4
    for broken in (
        {**timeline, "sha256": "b" * 64},
        {**timeline, "textSha256": "b" * 64},
        {**timeline, "timings": timeline["timings"][:-1]},
    ):
        with pytest.raises(ValueError):
            reading_timings.checked(item, asset, broken)
    for span in (
        {"start": 0.1, "end": float("nan")},
        {"start": 0, "end": 1.5},
        {"start": True, "end": 0.2},
        {"start": 0.4, "end": 0.3},
    ):
        broken = copy.deepcopy(timeline)
        broken["timings"][1] = span
        with pytest.raises(ValueError):
            reading_timings.checked(item, asset, broken)
