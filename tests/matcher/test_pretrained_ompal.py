"""Expert judgments and frozen speaker boundaries cannot be silently rewritten."""

import hashlib

import pytest

from pinyin_matcher.pretrained_ompal import (
    BASE,
    blob_sha1,
    download,
    expert_component,
    expert_word,
    speaker_split,
)


def test_only_three_unanimous_raters_establish_component_correctness():
    assert expert_component(["1", "1", "1"]) == "unanimous-correct"
    assert expert_component([0, 0, 0]) == "unanimous-error"
    assert expert_component(["1", "0", "1"]) == "ambiguous"
    assert expert_component(["1", "1"]) == "ambiguous"
    assert expert_component(1) == "ambiguous"
    assert expert_component(["1", "1", "2"]) == "ambiguous"


def test_known_error_is_negative_but_native_aggregate_is_not_invented_raters():
    word = {"phoneme_consonant": [1, 1, 1], "phoneme_vowel": [1, 0, 1], "tone": [0, 0, 0]}
    record = expert_word(word, reference=False)
    assert record["expertLabel"] == "unanimous-error"
    assert record["componentExpertLabels"]["rime"] == "ambiguous"
    assert record["expertRatings"]["tone"] == [0, 0, 0]
    native = expert_word({"phoneme_consonant": 1, "phoneme_vowel": 1, "tone": 1}, reference=True)
    assert native["expertLabel"] == "native-reference-aggregate"
    assert native["expertRaterCount"] is None
    assert native["expertRatings"]["tone"] == 1


def test_stable_speaker_splits_keep_native_references_out_of_training_and_final():
    speakers = [f"SPEAKER02{i:03}" for i in range(1, 47)] + [
        f"SPEAKER01{i:03}" for i in range(1, 4)
    ]
    first = speaker_split(speakers)
    assert first == speaker_split(list(reversed(speakers)))
    assert {
        name: list(first.values()).count(name)
        for name in ("train", "calibration", "test", "diagnostic")
    } == {
        "train": 28,
        "calibration": 8,
        "test": 10,
        "diagnostic": 3,
    }
    assert all(first[s] == "diagnostic" for s in speakers if s.startswith("SPEAKER01"))


def test_pinned_blob_and_sha_are_checked_before_any_audio_is_saved(tmp_path, monkeypatch):
    payload = b"test-only-boundary-fixture"
    entry = {
        "path": "wav/SPEAKER/test.wav",
        "url": BASE + "wav/SPEAKER/test.wav",
        "bytes": len(payload),
        "gitBlobSha1": blob_sha1(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    monkeypatch.setattr("pinyin_matcher.pretrained_ompal.fetch_bytes", lambda url: payload)
    path = download(entry, tmp_path)
    assert path.read_bytes() == payload
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="PINNED_BLOB_MISMATCH"):
        download(entry, tmp_path)
    with pytest.raises(ValueError, match="SOURCE_PATH_INVALID"):
        download({**entry, "path": "../escape.wav"}, tmp_path)
