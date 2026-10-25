"""Boundary/regression tests. Signal fixtures prove mechanics, not pronunciation accuracy."""

import itertools
import json
import subprocess
import sys

import numpy as np
import pytest
from scipy.special import log_softmax

from pinyin_matcher.audio import AudioRejected, decode_wav, encode_wav, features
from pinyin_matcher.catalog import load_catalog
from pinyin_matcher.data import read_manifest
from pinyin_matcher.inference import PinyinMatcher, ctc_log_probability


def test_ctc_forward_matches_enumerated_paths_and_repeated_phone_rules():
    logits = log_softmax(np.array([[1, 3, 0], [2, 1, 4], [3, 4, 1], [4, 0, 2]]), axis=1)
    for target in [[], [1], [1, 1], [1, 2], [2, 1]]:
        probability = 0
        for path in itertools.product(range(3), repeat=4):
            collapsed = [
                token
                for index, token in enumerate(path)
                if token and (index == 0 or token != path[index - 1])
            ]
            if collapsed == target:
                probability += np.exp(sum(logits[i, token] for i, token in enumerate(path)))
        assert np.exp(ctc_log_probability(logits, target)) == pytest.approx(probability)
    assert ctc_log_probability(logits[:1], [1, 1]) == -np.inf


def test_wav_rejects_truncation_duration_stereo_and_silence():
    silence = encode_wav(np.zeros(16000))
    assert decode_wav(silence).shape == (16000,)
    with pytest.raises(AudioRejected, match="SILENCE"):
        features(decode_wav(silence))
    with pytest.raises(AudioRejected, match="TRUNCATED"):
        decode_wav(silence[:-10])
    changed = bytearray(silence)
    changed[22:24] = (2).to_bytes(2, "little")
    with pytest.raises(AudioRejected, match="PCM16"):
        decode_wav(bytes(changed))
    with pytest.raises(AudioRejected, match="TOO_LONG"):
        decode_wav(bytes(300000))
    with pytest.raises(AudioRejected, match="WAV_INVALID"):
        decode_wav(b"not an audio file")


def test_phonetic_catalog_has_separate_forms_normalized_umlaut_and_no_target_in_features():
    catalog = load_catalog()
    by_py = {t["pinyin"]: t for t in catalog["targets"]}
    assert by_py["jū"]["rime"] == by_py["yū"]["rime"] == "ü"
    assert by_py["zhī"]["rime"] != by_py["jī"]["rime"]
    assert by_py["b"]["form"] == "initial-reading"
    assert by_py["b"]["tone"] == 5
    assert by_py["b"]["standardAudioId"] == "daily-b"
    assert by_py["b"]["id"] != by_py["bō"]["id"]
    assert len(catalog["pilotIds"]) == 32
    assert all("v" not in t["pinyin"] for t in catalog["targets"])


def test_catalog_compiler_is_reproducible_and_tts_text_is_explicit():
    from pinyin_matcher.catalog import ROOT

    subprocess.run(
        [sys.executable, "-m", "pinyin_matcher.compile_targets", "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    training = json.loads((ROOT / "content/pronunciation-training.json").read_text())
    challenges = json.loads((ROOT / "content/pronunciation-challenges.json").read_text())
    explicit = {
        entry["pinyin"]: entry["ttsText"]
        for entry in training["pilotDefinitions"] + challenges["definitions"]
    }
    for target in load_catalog()["targets"]:
        assert target["ttsText"] == explicit.get(target["pinyin"])


def test_missing_model_invalid_target_and_busy_are_explicit(tmp_path):
    matcher = PinyinMatcher(tmp_path)
    assert matcher.match("unknown", b"")["reason"] == "TARGET_NOT_FOUND"
    result = matcher.match("pm-ma1", b"")
    assert result["status"] == "unavailable"
    assert result["toneAssessed"] is False
    assert "score" not in result


def test_lineage_and_duplicate_audio_cannot_cross_splits(tmp_path):
    rows = []
    for i, split in enumerate(["train", "test"]):
        rows.append(
            {
                "id": str(i),
                "targetId": "pm-ma1",
                "split": split,
                "voiceFamilyId": "same-parent",
                "referenceRootId": str(i),
                "sha256": str(i),
                "file": str(i) + ".wav",
            }
        )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": 1, "cohort": "synthetic", "items": rows}))
    with pytest.raises(ValueError, match="LINEAGE"):
        read_manifest(path, verify_audio=False)
    rows[1]["voiceFamilyId"] = "different-family"
    rows[1]["referenceRootId"] = rows[0]["referenceRootId"]
    path.write_text(json.dumps({"version": 1, "cohort": "synthetic", "items": rows}))
    with pytest.raises(ValueError, match="LINEAGE"):
        read_manifest(path, verify_audio=False)
    rows[1]["referenceRootId"] = "different-reference"
    rows[1]["sha256"] = rows[0]["sha256"]
    path.write_text(json.dumps({"version": 1, "cohort": "synthetic", "items": rows}))
    with pytest.raises(ValueError, match="AUDIO_LEAKAGE"):
        read_manifest(path, verify_audio=False)
    rows[1]["sha256"] = "different-wave"
    for row in rows:
        row["referenceSha256"] = "same-clone-reference-wave"
    path.write_text(json.dumps({"version": 1, "cohort": "synthetic", "items": rows}))
    with pytest.raises(ValueError, match="REFERENCE_AUDIO_LEAKAGE"):
        read_manifest(path, verify_audio=False)


def test_dataset_path_escape_is_rejected(tmp_path):
    row = {
        "id": "one",
        "targetId": "pm-ma1",
        "split": "train",
        "voiceFamilyId": "family",
        "referenceRootId": "root",
        "sha256": "unused",
        "file": "../outside.wav",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": 1, "cohort": "synthetic", "items": [row]}))
    with pytest.raises(ValueError, match="PATH"):
        read_manifest(path, verify_audio=False)


def test_merge_preserves_quarantine_paths_relative_to_merged_dataset(tmp_path):
    from pinyin_matcher.catalog import fingerprint
    from pinyin_matcher.train import merge_manifests

    source = tmp_path / "engine"
    source.mkdir()
    for name in ["valid.wav", "quarantined.wav"]:
        (source / name).write_bytes(encode_wav(np.zeros(16000)))
    row = {
        "id": "valid",
        "targetId": "pm-ma1",
        "split": "train",
        "voiceFamilyId": "family",
        "referenceRootId": "reference",
        "sha256": fingerprint(source / "valid.wav"),
        "file": "valid.wav",
    }
    manifest = source / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "cohort": "synthetic",
                "items": [row],
                "quarantined": [{**row, "id": "excluded", "file": "quarantined.wav"}],
            }
        )
    )
    output = tmp_path / "merged.json"
    merge_manifests([manifest], output)
    merged = json.loads(output.read_text())
    assert merged["items"][0]["file"] == "engine/valid.wav"
    assert merged["quarantined"][0]["file"] == "engine/quarantined.wav"


def test_model_digest_path_threshold_and_corrupt_onnx_are_safe_failures(tmp_path):
    from pinyin_matcher.audio import FEATURE_VERSION
    from pinyin_matcher.catalog import CATALOG, fingerprint

    model = tmp_path / "bad.onnx"
    model.write_bytes(b"corrupt onnx")
    metadata = {
        "version": "test",
        "status": "experimental",
        "file": "bad.onnx",
        "sha256": fingerprint(model),
        "catalogSha256": fingerprint(CATALOG),
        "featureVersion": FEATURE_VERSION,
        "coveredTargetIds": ["pm-ma1", "pm-ma2"],
        "onsets": ["m"],
        "rimes": ["a"],
        "thresholds": {"minimumScore": -3, "minimumMargin": 0.5, "minimumCtc": -1},
    }
    path = tmp_path / "model.json"
    path.write_text(json.dumps(metadata))
    matcher = PinyinMatcher(tmp_path)
    assert matcher.session is None
    assert matcher.match("pm-ma1", b"")["status"] == "unavailable"
    metadata["sha256"] = "wrong"
    path.write_text(json.dumps(metadata))
    assert PinyinMatcher(tmp_path).problem == "MODEL_DIGEST_MISMATCH"
    metadata["sha256"] = fingerprint(model)
    metadata["thresholds"]["minimumScore"] = float("nan")
    path.write_text(json.dumps(metadata))
    assert PinyinMatcher(tmp_path).problem == "MODEL_THRESHOLDS_INVALID"
    metadata["thresholds"]["minimumScore"] = -3
    metadata["thresholds"]["minimumMargin"] = -1
    path.write_text(json.dumps(metadata))
    assert PinyinMatcher(tmp_path).problem == "MODEL_THRESHOLDS_INVALID"


def test_pitch_feature_tracks_a_known_sweep_and_rejects_noise():
    # This verifies the estimator's numerical behavior only, not speech scoring.
    from scipy.signal import chirp

    t = np.arange(16000) / 16000
    wave = (0.15 * chirp(t, 150, 1, 300)).astype(np.float32)
    array, info = features(wave)
    voiced = array[array[:, -1] > 0.5, 64]
    assert info["voicedFrames"] > 70
    assert np.median(voiced[-15:]) - np.median(voiced[:15]) > 0.6
    _, noisy = features(np.random.default_rng(7).normal(0, 0.1, 16000).astype(np.float32))
    assert noisy["voicedFrames"] < 8


def test_tone_contour_is_invariant_to_content_and_absolute_pitch():
    from pinyin_matcher.contour import contour

    acoustic = np.zeros((80, 68), dtype=np.float32)
    acoustic[:, 64] = np.linspace(-0.2, 0.3, 80)
    acoustic[:, 67] = 1
    expected = contour(acoustic)
    changed = acoustic.copy()
    changed[:, :64] = np.random.default_rng(9).normal(0, 1, (80, 64))
    changed[:, 64] += 1
    assert np.allclose(contour(changed), expected, atol=1e-6)
    changed[:, 67] = 0
    with pytest.raises(AudioRejected, match="VOICED"):
        contour(changed)


def test_busy_and_pre_cancelled_requests_never_enter_native_inference(tmp_path):
    import threading

    matcher = PinyinMatcher(tmp_path)
    # Test-only session sentinel: neither branch may attempt to invoke a backend.
    matcher.session = object()
    matcher.metadata = {"coveredTargetIds": ["pm-ma1", "pm-ma2"]}
    matcher.lock.acquire()
    try:
        assert matcher.match("pm-ma1", b"")["reason"] == "MATCHER_BUSY"
    finally:
        matcher.lock.release()
    cancel = threading.Event()
    cancel.set()
    assert matcher.match("pm-ma1", b"", cancel=cancel)["reason"] == "MATCH_CANCELLED"
    assert matcher.lock.acquire(blocking=False)
    matcher.lock.release()


def test_missing_catalog_combination_and_extra_phones_cannot_force_a_match(tmp_path):
    catalog = load_catalog()
    tokens = catalog["tokens"]

    class TestOnlyAcoustics:
        def __init__(self, phones, tone):
            self.phones, self.tone = phones, tone

        def run(self, names, inputs, run_options=None):
            output = np.full((1, inputs["acoustic"].shape[1], len(tokens)), -10, dtype=np.float32)
            output[:, :, 0] = 10
            for i, phone in enumerate(self.phones):
                output[0, 10 + i * 20, 0] = -10
                output[0, 10 + i * 20, tokens.index(phone)] = 10
            tone = np.full((1, 6), -10, dtype=np.float32)
            tone[0, self.tone] = 10
            return (
                output,
                np.array([[10, -10]], dtype=np.float32),
                np.array([[10]], dtype=np.float32),
                tone,
            )

    matcher = PinyinMatcher(tmp_path)
    matcher.metadata = {
        "coveredTargetIds": ["pm-ba1", "pm-pa1"],
        "onsets": ["b", "p"],
        "rimes": ["a"],
        "decisionVersion": 2,
        "toneEnabled": True,
        "thresholds": {"minimumScore": -100, "minimumMargin": 0, "minimumCtc": -100},
    }
    t = np.arange(16000) / 16000
    from scipy.signal import chirp

    payload = encode_wav((0.1 * chirp(t, 150, 1, 250)).astype(np.float32))
    # The catalogue has bā but no bà here. A confident tone-4 prediction must
    # not be silently converted into bā simply because it is the best allowed label.
    matcher.session = TestOnlyAcoustics(["I_b", "F_a"], 4)
    assert matcher.match("pm-ba1", payload)["status"] == "uncertain"
    # Likewise, extra complete phone sequences must not be discarded.
    matcher.session = TestOnlyAcoustics(["I_b", "F_a", "I_p", "F_a"], 1)
    assert matcher.match("pm-ba1", payload)["status"] == "uncertain"
