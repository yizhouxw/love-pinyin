"""Matcher boundary tests use explicit test heads, never recognition accuracy fixtures."""

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.pretrained_runtime import (
    PretrainedMatcher,
    component_decision,
    signal_guard,
)


def waveform():
    # Synthetic numeric boundary fixture, not evidence of pronunciation validity.
    values = np.zeros(10000, dtype=np.float32)
    phase = np.arange(4000, dtype=np.float32)
    values[2000:6000] = 0.15 * np.cos(phase * 0.15)
    return values


def matcher_fixture(monkeypatch):
    matcher = PretrainedMatcher.__new__(PretrainedMatcher)
    matcher.metadata = {
        "model": "test-only",
        "variant": "test-only",
        "vocabulary": {"onset": ["b", "p"], "rime": ["a", "o"], "tone": ["1", "2"]},
        "thresholds": {"probability": 0.8, "margin": 0.2},
    }
    matcher.targets = {"test-ba1": {"id": "test-ba1", "onset": "b", "rime": "a", "tone": 1}}
    matcher.lock = threading.Lock()
    matcher.problem = ""
    matcher.encoder = object()
    matcher.normalization = {
        "mean": np.zeros(5),
        "scale": np.ones(5),
        "pitch_mean": np.zeros(68),
        "pitch_scale": np.ones(68),
    }

    class TestSession:
        def run(self, outputs, inputs):
            return [np.asarray([[5, -5]], dtype=np.float32) for _ in range(3)]

    matcher.session = TestSession()
    monkeypatch.setattr(
        "pinyin_matcher.pretrained_runtime.represent",
        lambda encoder, samples: {"pooled": np.ones(5), "pitch": np.ones(68)},
    )
    return matcher


def test_component_comparison_requires_all_three_heads_and_preserves_abstention():
    threshold = {"probability": 0.8, "margin": 0.2}
    confident = [np.asarray([0.9, 0.1])] * 3
    assert component_decision(confident, [0, 0, 0], threshold) == "matched"
    assert component_decision(confident, [0, 0, 1], threshold) == "retry"
    assert (
        component_decision(confident[:2] + [np.asarray([0.55, 0.45])], [0, 0, 0], threshold)
        == "uncertain"
    )
    with pytest.raises(ValueError, match="OUTPUT_INVALID"):
        component_decision(confident[:2] + [np.asarray([np.nan, 0])], [0, 0, 0], threshold)


def test_silence_noise_and_multiple_utterances_are_not_pronunciation_errors():
    assert signal_guard(np.zeros(8000, dtype=np.float32)) == "SILENCE_OR_TOO_QUIET"
    rng = np.random.default_rng(17)
    assert signal_guard(rng.normal(0, 0.1, 16000).astype(np.float32)) == "NONSPEECH_BROADBAND_INPUT"
    assert (
        signal_guard(np.concatenate([waveform(), waveform()]))
        == "MULTIPLE_SEPARATED_SPEECH_REGIONS"
    )
    assert signal_guard(waveform()) is None


def test_model_missing_unknown_target_invalid_audio_and_busy_fail_closed(tmp_path, monkeypatch):
    assert PretrainedMatcher(tmp_path).match("missing", b"")["status"] == "unavailable"
    matcher = matcher_fixture(monkeypatch)
    assert matcher.match("outside", b"")["reason"] == "TARGET_NOT_TRAINED"
    assert matcher.match("test-ba1", b"invalid")["status"] == "uncertain"
    matcher.lock.acquire()
    assert matcher.match("test-ba1", encode_wav(waveform()))["reason"] == "MODEL_BUSY"
    matcher.lock.release()
    result = matcher.match("test-ba1", encode_wav(waveform()))
    assert result["status"] == "matched"
    assert result["experimental"] is True and result["toneAssessed"] is False
    assert "internalEvidence" not in result


def test_cancel_or_timeout_during_encoder_cannot_return_late_match(monkeypatch):
    matcher = matcher_fixture(monkeypatch)
    cancel = threading.Event()

    def cancel_during(encoder, samples):
        cancel.set()
        return {"pooled": np.ones(5), "pitch": np.ones(68)}

    monkeypatch.setattr("pinyin_matcher.pretrained_runtime.represent", cancel_during)
    assert matcher.match("test-ba1", encode_wav(waveform()), cancel=cancel)["reason"] == "CANCELLED"
    assert not matcher.lock.locked()

    def slow_encoder(encoder, samples):
        time.sleep(0.01)
        return {"pooled": np.ones(5), "pitch": np.ones(68)}

    monkeypatch.setattr("pinyin_matcher.pretrained_runtime.represent", slow_encoder)
    assert (
        matcher.match("test-ba1", encode_wav(waveform()), timeout=0.002)["reason"]
        == "MATCH_TIMEOUT"
    )
    assert not matcher.lock.locked()


def test_missing_required_pitch_cannot_become_a_confident_zero_contour(monkeypatch):
    matcher = matcher_fixture(monkeypatch)

    class MissingPitch:
        def vector(self, samples):
            return np.zeros(68, dtype=np.float32), {"available": False}

    matcher.pitch_override = MissingPitch()
    result = matcher.match("test-ba1", encode_wav(waveform()))
    assert result["status"] == "uncertain"
    assert result["reason"] == "PITCH_EVIDENCE_UNAVAILABLE"


def test_corrupted_head_is_rejected_before_any_encoder_load(tmp_path):
    from pinyin_matcher.pretrained_features import configuration

    metadata = {
        "schemaVersion": 1,
        "model": "hanziflow",
        "configuration": configuration(),
        "thresholds": {"probability": 0.8, "margin": 0.2},
        "vocabulary": {"onset": ["b"], "rime": ["a"], "tone": ["1"]},
        "coveredTargets": [{"id": "test-ba1", "onset": "b", "rime": "a", "tone": 1}],
        "headOnnxSha256": "deliberately-wrong",
        "normalizationSha256": "wrong",
    }
    (tmp_path / "model.json").write_text(json.dumps(metadata))
    (tmp_path / "heads.onnx").write_bytes(b"corrupt-test-artifact")
    matcher = PretrainedMatcher(Path(tmp_path))
    assert matcher.match("test-ba1", encode_wav(waveform()))["reason"] == "MODEL_DIGEST_MISMATCH"


def test_bundle_digest_binds_encoder_and_rejects_path_escape(tmp_path):
    from pinyin_matcher.catalog import fingerprint

    encoder = tmp_path / "encoder.onnx"
    encoder.write_bytes(b"original-test-model")
    metadata = {
        "packageFiles": {"encoder.onnx": {"sha256": fingerprint(encoder)}},
    }
    encoder.write_bytes(b"changed-test-model")
    (tmp_path / "model.json").write_text(json.dumps(metadata))
    assert PretrainedMatcher(tmp_path).problem == "BUNDLE_RESOURCE_DIGEST_MISMATCH"

    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_bytes(b"file outside bundle")
    metadata["packageFiles"] = {
        "../" + outside.name: {"sha256": fingerprint(outside)},
    }
    (tmp_path / "model.json").write_text(json.dumps(metadata))
    assert PretrainedMatcher(tmp_path).problem == "BUNDLE_RESOURCE_DIGEST_MISMATCH"
