"""Pitch cache/feature boundaries are numerical, not tone-accuracy evidence."""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.pretrained_pitch import (
    FEATURE_VERSION,
    PitchCache,
    prepare,
    select_rows,
    vector_from_track,
)


def track_fixture(good=(0, 1, 2, 8, 9, 10)):
    voiced = np.zeros(11, dtype=bool)
    voiced[list(good)] = True
    f0 = np.zeros(11, dtype=np.float32)
    f0[list(good)] = np.resize([100, 100, 100, 200, 200, 200], len(good))
    return SimpleNamespace(f0=f0, voiced=voiced, seconds=np.arange(11) * 0.016)


def test_contour_samples_real_times_without_concatenating_unvoiced_gap():
    vector, info = vector_from_track(track_fixture())
    assert vector.shape == (68,) and np.isfinite(vector).all() and info["available"]
    # Frame9/31 is time-position2.903: the long gap retains its duration.
    assert -0.45 < vector[9] < -0.25
    assert vector[64] == pytest.approx(6 / 11)
    assert vector[66] == pytest.approx(1)
    assert vector[67] == pytest.approx(150 / 400)


def test_weak_voicing_is_zero_with_explicit_unavailable_evidence():
    vector, info = vector_from_track(track_fixture((0, 1, 2, 9, 10)))
    assert np.count_nonzero(vector) == 0
    assert not info["available"] and info["flags"] == ["PITCH_INSUFFICIENT_VOICING"]


def test_relative_contour_is_octave_shift_invariant_but_median_scalar_is_explicit():
    first = track_fixture()
    shifted = track_fixture()
    shifted.f0 *= 2
    a, _ = vector_from_track(first)
    b, _ = vector_from_track(shifted)
    np.testing.assert_allclose(a[:67], b[:67], atol=1e-6)
    assert b[67] == pytest.approx(a[67] * 2)


def test_split_metadata_is_checked_without_opening_ignored_paths():
    rows = [
        {"id": split, "split": split, "speakerId": split, "file": "NEVER_OPEN"}
        for split in ("train", "calibration", "test", "diagnostic")
    ]
    selected, ignored = select_rows({"items": rows})
    assert [r["id"] for r in selected] == ["train", "calibration"]
    assert ignored == {"test": 1, "diagnostic": 1}
    rows[-1]["speakerId"] = "train"
    with pytest.raises(ValueError, match="SOURCE_LEAKAGE"):
        select_rows({"items": rows})


def test_include_test_is_rejected_before_any_manifest_or_model_access(tmp_path):
    with pytest.raises(ValueError, match="TEST_AUDIO_FORBIDDEN"):
        prepare(tmp_path / "missing", tmp_path / "missing-model", tmp_path, include_test=True)


def test_cache_keeps_flagged_rows_and_detects_changed_audio_and_payload(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_pitch as module

    rows = []
    for index, split in enumerate(("train", "calibration")):
        wave = encode_wav(0.1 * np.sin(np.arange(6400) * (0.12 + index * 0.01)))
        file = tmp_path / f"test-only-{index}.wav"
        file.write_bytes(wave)
        rows.append(
            {
                "id": str(index),
                "split": split,
                "speakerId": split,
                "sha256": hashlib.sha256(wave).hexdigest(),
                "file": str(file),
                "numericalQualityFlags": ["TEST_NUMERICAL_FLAG"] if index else [],
            }
        )
    rows.append(
        {
            "id": "test",
            "split": "test",
            "speakerId": "reserved",
            "file": str(tmp_path / "NEVER_OPEN"),
            "sha256": "no-final-audio-read",
        }
    )
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"items": rows}))
    monkeypatch.setattr(module, "cache_identity", lambda *args: {"test-only-numeric-fixture": True})

    class NumericOnlyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def vector(self, samples):
            return np.ones(68, dtype=np.float32), {"available": True, "flags": []}

    monkeypatch.setattr(module, "PitchExtractor", NumericOnlyExtractor)
    output = tmp_path / "pitch"
    result = prepare(source, tmp_path / "not-a-real-model", output)
    assert result["featureVersion"] == FEATURE_VERSION
    assert result["counts"]["rows"] == 2 and result["counts"]["available"] == 1
    cache = PitchCache(output / "manifest.json")
    assert cache.read(rows[0])[0].sum() == 68
    vector, info = cache.read(rows[1])
    assert not vector.any() and not info["available"]
    assert info["flags"] == ["TEST_NUMERICAL_FLAG"]
    with pytest.raises(ValueError, match="TEST_AUDIO_FORBIDDEN"):
        cache.read(rows[2])
    changed = {**rows[0], "sha256": "changed-input"}
    with pytest.raises(ValueError, match="ROW_IDENTITY"):
        cache.read(changed)
    payload = output / result["items"][0]["file"]
    payload.write_bytes(b"corrupted-test-only-payload")
    with pytest.raises(ValueError, match="CACHE_DIGEST"):
        cache.read(rows[0])
