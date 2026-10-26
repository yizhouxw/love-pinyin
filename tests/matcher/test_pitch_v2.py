"""Numerical contracts only; generated signals do not establish tone accuracy."""

import os
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher.audio import AudioRejected, decode_wav
from pinyin_matcher.pitch_v2 import contour, track


def test_low_fundamental_tracks_below_a_stronger_harmonic():
    # A mechanical tracker regression, not a Mandarin pronunciation test.
    time = np.arange(16000, dtype=np.float64) / 16000
    samples = 0.12 * np.sin(2 * np.pi * 80 * time) + 0.24 * np.sin(2 * np.pi * 160 * time)
    result = track(samples)
    stable = result.f0[20:-20]
    assert np.mean(np.abs(stable - 80) < 2) > 0.95


def test_relative_contour_gain_invariance_and_input_bounds():
    time = np.arange(8000, dtype=np.float64) / 16000
    samples = 0.2 * np.sin(2 * np.pi * (140 * time + 30 * time * time))
    first, info = contour(samples)
    second, _ = contour(samples * 0.25)
    assert first.shape == (32, 4)
    assert first.dtype == np.float32
    assert np.isfinite(first).all()
    assert info["voicedFrames"] >= 8
    np.testing.assert_allclose(first, second, atol=1e-5)
    with pytest.raises(AudioRejected):
        contour(np.full(8000, np.nan))


def test_noise_is_not_forced_into_a_fundamental():
    samples = np.random.default_rng(19).normal(0, 0.1, 16000)
    result = track(samples)
    assert result.voiced.sum() < 8
    with pytest.raises(AudioRejected, match="NO_RELIABLE_VOICED_SPEECH"):
        contour(samples)
    with pytest.raises(AudioRejected, match="SILENCE_OR_TOO_QUIET"):
        contour(np.zeros(16000))


def test_optional_licensed_waveform_extraction_is_target_independent():
    path = os.environ.get("MATCHER_PITCH_WAV")
    if not path:
        pytest.skip("set MATCHER_PITCH_WAV to an authorized local source recording")
    samples = decode_wav(Path(path).read_bytes())
    value, summary = contour(samples)
    assert value.shape == (32, 4)
    assert summary["voicedFrames"] >= 8
    assert 60 <= summary["medianF0"] <= 900


def test_swift_tracker_missing_or_corrupt_model_never_falls_back(tmp_path):
    from pinyin_matcher.pitch_swift import SwiftPitch

    with pytest.raises(ValueError, match="PITCH_TRACKER_MODEL_DIGEST_MISMATCH"):
        SwiftPitch(tmp_path / "missing.onnx")
    broken = tmp_path / "broken.onnx"
    broken.write_bytes(b"not a pitch model")
    with pytest.raises(ValueError, match="PITCH_TRACKER_MODEL_DIGEST_MISMATCH"):
        SwiftPitch(broken)


def test_optional_real_swift_model_has_complete_contour_and_rejects_noise(monkeypatch):
    model = os.environ.get("MATCHER_SWIFT_MODEL")
    path = os.environ.get("MATCHER_PITCH_WAV")
    if not model or not path:
        pytest.skip("set MATCHER_SWIFT_MODEL and MATCHER_PITCH_WAV for local artifact verification")
    import socket

    from pinyin_matcher.pitch_swift import SwiftPitch

    def blocked(*args, **kwargs):
        raise AssertionError("runtime pitch must not access the network")

    monkeypatch.setattr(socket, "create_connection", blocked)
    tracker = SwiftPitch(Path(model))
    assert tracker.session.get_providers() == ["CPUExecutionProvider"]
    samples = decode_wav(Path(path).read_bytes())
    value, summary = tracker.contour(samples)
    assert value.shape == (32, 4)
    assert summary["voicedFrames"] >= 6
    assert np.isfinite(value).all()
    with pytest.raises(AudioRejected, match="NO_RELIABLE_VOICED_SPEECH"):
        tracker.contour(np.random.default_rng(37).normal(0, 0.1, 16000).astype(np.float32))
