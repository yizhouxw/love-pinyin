"""DAILY-12: a changed source is reviewed, never mistaken for missing duplicate rows."""

import copy
import hashlib
import json
import math

import pytest
from fastapi import HTTPException

from scripts.build_first_tones import level_tone, pitch_period
from scripts.daily_reading_rules import unique_items
from scripts.validate_daily_reading import validate_normalization
from server import daily_pronunciation, daily_reading, source_audio
from server.content import load_curriculum


def catalogues():
    root = daily_reading.CONTENT.parent
    return (
        copy.deepcopy(daily_reading.load()),
        json.loads((root / "daily-reading-source.json").read_text()),
        daily_pronunciation.policy(),
        load_curriculum()["inventory"],
    )


def test_all_source_occurrences_accounted_for_within_each_section():
    data, ledger, policy, inventory = catalogues()
    validate_normalization(data, ledger, policy, inventory)
    assert sum(len(s["items"]) for s in ledger["sections"]) == 840
    duplicates = [len(s["items"]) - len(unique_items(s["items"])) for s in ledger["sections"]]
    assert sum(duplicates) == 55
    assert sum(n > 0 for n in duplicates) == 11
    # Identical pinyin across sections is retained. Tone and word-internal repetition matter.
    for section_id in ["day-08-section-1", "day-08-section-3"]:
        section = next(s for d in data["days"] for s in d["sections"] if s["id"] == section_id)
        assert any(i["display"] == "zhi" for i in section["items"])
    assert (
        len(
            unique_items(
                [
                    {"syllables": ["ā"]},
                    {"syllables": ["á"]},
                    {"syllables": ["ā"]},
                    {"syllables": ["mā", "ma"]},
                ]
            )
        )
        == 3
    )
    assert len(unique_items([{"syllables": ["ǖ"]}, {"syllables": ["u\u0308\u0304"]}])) == 1


def test_new_source_repetitions_do_not_change_expected_unique_items():
    data, ledger, policy, inventory = catalogues()
    ledger["sections"][0]["items"].append({**ledger["sections"][0]["items"][0], "id": "new-repeat"})
    validate_normalization(data, ledger, policy, inventory)
    ledger["sections"][0]["items"].append(
        {"id": "new-pinyin", "original": "ēi", "display": "ēi", "syllables": ["ēi"]}
    )
    with pytest.raises(ValueError, match="deduplication"):
        validate_normalization(data, ledger, policy, inventory)
    ledger["sourceSha256"] = "0" * 64
    with pytest.raises(ValueError, match="source ledger digest"):
        validate_normalization(data, ledger, policy, inventory)


@pytest.mark.parametrize("damage", ["duplicate", "wrong-tone", "neutral", "marked"])
def test_duplicate_wrong_tone_and_lost_light_tone_are_rejected(damage):
    data, ledger, policy, inventory = catalogues()
    if damage == "duplicate":
        data["days"][0]["sections"][0]["items"].append(data["days"][0]["sections"][0]["items"][0])
    elif damage == "wrong-tone":
        data["days"][3]["sections"][1]["items"][11]["audioIds"] = ["daily-nu2"]
    elif damage == "marked":
        data["days"][0]["sections"][0]["items"][1]["audioIds"] = ["daily-a1"]
    else:
        policy["neutralSyllableIndices"]["day-03-s3-i1"] = []
    with pytest.raises(ValueError):
        validate_normalization(data, ledger, policy, inventory)


def test_light_tone_words_sentences_and_marked_tones_keep_original_audio():
    data, _, _, _ = catalogues()
    words = [
        i
        for d in data["days"]
        for s in d["sections"]
        if s["kind"] in {"words", "sentences"}
        for i in s["items"]
    ]
    # Fixed reviewed baseline covers all remaining words/sentences and their full audio metadata.
    digest = hashlib.sha256(
        json.dumps(words, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    assert digest == "9a5ae07037430514bda328d7c1202a6ce8439000e1ba59a70e143903347e6054"


def test_local_first_tone_registration_rejects_stale_recipes_and_disabled_source(
    tmp_path, monkeypatch
):
    recipe = next(iter(daily_pronunciation.policy()["derivedFirstTones"].items()))
    asset_id, definition = recipe
    monkeypatch.setattr(source_audio, "SOURCE_DIR", tmp_path)
    monkeypatch.setattr(source_audio, "installed", lambda: True)
    entry = {"sha256": "a" * 64, "recipeSha256": daily_pronunciation.signature(definition)}
    manifest = tmp_path / "daily-first-tones.json"
    manifest.write_text(json.dumps({asset_id: entry}))
    assert daily_pronunciation.registered(asset_id) == (
        tmp_path / "clips" / f"{'a' * 64}.wav",
        "a" * 64,
    )
    entry["recipeSha256"] = "stale"
    manifest.write_text(json.dumps({asset_id: entry}))
    with pytest.raises(HTTPException):
        daily_pronunciation.registered(asset_id)
    monkeypatch.setattr(source_audio, "installed", lambda: False)
    with pytest.raises(HTTPException):
        daily_pronunciation.registered(asset_id)


def test_derived_audio_range_digest_and_source_disable(paired_client, monkeypatch):
    asset_id, recipe = next(iter(daily_pronunciation.policy()["derivedFirstTones"].items()))
    root = source_audio.SOURCE_DIR
    (root / "clips").mkdir(parents=True)
    # Transport fixture only; not a demonstration or pronunciation proof.
    payload = b"RIFF-synthetic-transport-fixture"
    digest = hashlib.sha256(payload).hexdigest()
    path = root / "clips" / f"{digest}.wav"
    path.write_bytes(payload)
    (root / "daily-first-tones.json").write_text(
        json.dumps(
            {asset_id: {"sha256": digest, "recipeSha256": daily_pronunciation.signature(recipe)}}
        )
    )
    monkeypatch.setattr(source_audio, "installed", lambda: True)
    url = f"/api/v1/daily-audio/{asset_id}"
    response = paired_client.get(url, headers={"Range": "bytes=2-7"})
    assert response.status_code == 206
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == payload[2:8]
    path.write_bytes(b"corrupt")
    assert paired_client.get(url).status_code == 404
    path.write_bytes(payload)
    monkeypatch.setattr(source_audio, "installed", lambda: False)
    assert paired_client.get(url).status_code == 404


def test_psola_levels_periods_without_changing_duration_or_unvoiced_edges():
    # Synthetic signal checks the DSP only, not pronunciation or children's assessment.
    rate = 16000
    voice = [
        0.2 * math.sin(2 * math.pi * (170 * n / rate + 60 * (n / rate) ** 2))
        for n in range(rate // 2)
    ]
    samples = [0.0] * 1600 + voice + [0.0] * 1600
    leveled, stats = level_tone(samples, rate, 300)
    assert len(leveled) == len(samples)
    assert leveled[:1500] == samples[:1500]
    assert leveled[-1500:] == samples[-1500:]
    assert stats["voicedSeconds"] > 0.3
    for steady in [False, True]:
        leveled, _ = level_tone(samples, rate, 300, steady_nucleus=steady)
        for center in [3000, 4500, 6000, 7500]:
            period = pitch_period(leveled[center - 320 : center + 320], rate)
            assert period is not None
            assert rate / period == pytest.approx(300, abs=12)
    with pytest.raises(ValueError, match="periodic speech"):
        level_tone([0.0] * 4000, rate, 300)
