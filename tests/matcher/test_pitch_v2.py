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


def _support_fixture(gap=15, weak_frames=4, tail_confidence=0.6, tail_rms=0.002):
    """Mechanical support contract, deliberately not a tone-accuracy experiment."""
    from pinyin_matcher.pitch_v2 import PitchTrack

    size = 20 + gap + weak_frames
    voiced = np.zeros(size, dtype=bool)
    voiced[:20] = True
    voiced[-weak_frames:] = True
    f0 = np.where(voiced, 220.0, 0).astype(np.float32)
    f0[-weak_frames:] = 80
    confidence = np.where(voiced, 0.99, 0).astype(np.float32)
    confidence[-weak_frames:] = tail_confidence
    rms = np.full(size, 0.1, dtype=np.float32)
    rms[-weak_frames:] = tail_rms
    return PitchTrack(f0, confidence, voiced, rms, np.arange(size) * 0.016)


def test_component_support_discards_only_short_weak_disconnected_islands():
    from pinyin_matcher.pitch_swift import component_support

    good, info = component_support(_support_fixture())
    assert good.tolist() == list(range(20))
    assert info["removedVoicedFrames"] == 4
    for changes in [
        {"gap": 5},
        {"weak_frames": 7},
        {"tail_confidence": 0.9},
        {"tail_rms": 0.05},
    ]:
        pitch = _support_fixture(**changes)
        retained, details = component_support(pitch)
        assert retained.tolist() == np.flatnonzero(pitch.voiced).tolist()
        assert details["removedVoicedFrames"] == 0


def test_component_support_keeps_connected_low_trough_and_declining_tail():
    from pinyin_matcher.pitch_swift import component_support

    for frequencies in [
        [220, 200, 170, 120, 70, 55],
        [160, 100, 60, 50, 90, 140],
    ]:
        pitch = _support_fixture(gap=0, weak_frames=6)
        pitch.f0[-6:] = frequencies
        retained, details = component_support(pitch)
        assert retained.tolist() == list(range(26))
        assert details["removedVoicedFrames"] == 0


def test_swift_v1_is_unchanged_and_v2_is_explicit_without_model_loading():
    from pinyin_matcher.pitch_swift import (
        COMPONENT_PITCH_FEATURE_VERSION,
        PITCH_FEATURE_VERSION,
        SwiftPitch,
    )

    pitch = _support_fixture()
    tracker = object.__new__(SwiftPitch)
    tracker.track = lambda *args, **kwargs: pitch
    tracker.feature_version = PITCH_FEATURE_VERSION
    old, old_info = tracker.contour(np.zeros(1))
    good = np.flatnonzero(pitch.voiced)
    positions = np.linspace(good[0], good[-1], 32)
    relative = np.interp(positions, good, np.log2(pitch.f0[good])) - np.median(
        np.log2(pitch.f0[good])
    )
    expected = np.stack(
        [
            relative,
            np.gradient(relative),
            np.interp(positions, np.arange(len(pitch.f0)), pitch.confidence),
            np.interp(positions, np.arange(len(pitch.f0)), pitch.voiced.astype(np.float32)),
        ],
        axis=1,
    ).astype(np.float32)
    np.testing.assert_array_equal(old, expected)
    assert "removedVoicedFrames" not in old_info
    tracker.feature_version = COMPONENT_PITCH_FEATURE_VERSION
    new, new_info = tracker.contour(np.zeros(1))
    assert new_info["removedVoicedFrames"] == 4
    np.testing.assert_array_equal(new[:, 0], np.zeros(32))
    with pytest.raises(ValueError, match="PITCH_FEATURE_VERSION_UNSUPPORTED"):
        SwiftPitch(Path("not-read.onnx"), feature_version="unregistered-version")


def test_optional_speech_derived_component_preserves_connected_standard_low_tail():
    model = os.environ.get("MATCHER_SWIFT_MODEL")
    path = os.environ.get("MATCHER_PITCH_WAV")
    if not model or not path:
        pytest.skip("set licensed speech/model paths for speech-derived support regression")
    from pinyin_matcher.pitch_swift import SwiftPitch, component_support
    from pinyin_matcher.pitch_v2 import PitchTrack

    source = SwiftPitch(Path(model)).track(decode_wav(Path(path).read_bytes()))
    good = np.flatnonzero(source.voiced)
    groups = np.split(good, np.flatnonzero(np.diff(good) > 6) + 1)
    main = max(groups, key=len)
    # Original connected F0 samples, including any actual low/creaky tail, survive unchanged.
    retained, _ = component_support(source)
    assert set(main) <= set(retained)
    # Append a scaled, detached fragment of the same actual speech-derived track.
    part = main[-4:]
    detached = PitchTrack(
        np.concatenate([source.f0, np.zeros(10), source.f0[part]]),
        np.concatenate([source.confidence, np.zeros(10), np.full(4, 0.6)]),
        np.concatenate([source.voiced, np.zeros(10, dtype=bool), np.ones(4, dtype=bool)]),
        np.concatenate([source.rms, np.zeros(10), source.rms[part] * 0.001]),
        np.arange(len(source.f0) + 14) * 0.016,
    )
    supported, info = component_support(detached)
    assert supported.tolist() == retained.tolist()
    assert info["removedVoicedFrames"] >= 4


def test_optional_actual_v4_bundle_loads_and_uses_bit_exact_v1_features():
    bundle = os.environ.get("MATCHER_V4_MODEL")
    path = os.environ.get("MATCHER_PITCH_WAV")
    if not bundle or not path:
        pytest.skip("set existing V4 bundle and licensed waveform for backward compatibility")
    from pinyin_matcher.inference import PinyinMatcher
    from pinyin_matcher.pitch_swift import PITCH_FEATURE_VERSION

    matcher = PinyinMatcher(Path(bundle))
    assert matcher.capabilities()["available"], matcher.problem
    assert matcher.metadata["pitchTone"]["featureVersion"] == PITCH_FEATURE_VERSION
    assert matcher.pitch_tracker.feature_version == PITCH_FEATURE_VERSION
    samples = decode_wav(Path(path).read_bytes())
    pitch = matcher.pitch_tracker.track(samples)
    actual, summary = matcher.pitch_tracker.contour(samples)
    good = np.flatnonzero(pitch.voiced)
    positions = np.linspace(good[0], good[-1], 32)
    relative = np.clip(
        np.interp(positions, good, np.log2(pitch.f0[good])) - np.median(np.log2(pitch.f0[good])),
        -2,
        2,
    )
    original_formula = np.stack(
        [
            relative,
            np.gradient(relative),
            np.interp(positions, np.arange(len(pitch.f0)), pitch.confidence),
            np.interp(positions, np.arange(len(pitch.f0)), pitch.voiced.astype(np.float32)),
        ],
        axis=1,
    ).astype(np.float32)
    np.testing.assert_array_equal(actual, original_formula)
    assert summary == pitch.summary()
