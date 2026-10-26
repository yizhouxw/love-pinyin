"""Numerical activity guards; synthetic signals do not validate pronunciation."""

import numpy as np
import pytest

from pinyin_matcher.audio import SAMPLE_RATE, AudioRejected, quality_check


def test_short_periodic_activity_does_not_lose_duration_at_zero_crossings():
    # 100ms of periodic energy in a valid 150ms recording. The old sample-count
    # guard counted fewer than 100ms solely because each period crosses zero.
    samples = np.zeros(2400, dtype=np.float32)
    times = np.arange(1600) / SAMPLE_RATE
    samples[320:1920] = 0.04 * np.sin(2 * np.pi * 200 * times)
    assert np.count_nonzero(np.abs(samples) > 0.005) < 1600
    assert quality_check(samples)["durationSeconds"] == 0.15


def test_quiet_periodic_activity_uses_frame_energy_not_peak_occupancy():
    times = np.arange(2400) / SAMPLE_RATE
    for phase in (0, np.pi / 4):
        samples = (0.0072 * np.sin(2 * np.pi * 200 * times + phase)).astype(np.float32)
        assert np.count_nonzero(np.abs(samples) > 0.005) < 1600
        assert quality_check(samples)["rms"] > 0.005


@pytest.mark.parametrize("amplitude", [0, 0.001, 0.004])
def test_silent_or_low_energy_input_remains_rejected(amplitude):
    samples = np.full(3200, amplitude, dtype=np.float32)
    with pytest.raises(AudioRejected, match="SILENCE_OR_TOO_QUIET"):
        quality_check(samples)


def test_brief_loud_burst_cannot_replace_required_active_duration():
    samples = np.zeros(3200, dtype=np.float32)
    samples[480:1280] = 0.1
    assert np.sqrt(np.mean(samples**2)) > 0.002
    with pytest.raises(AudioRejected, match="SILENCE_OR_TOO_QUIET"):
        quality_check(samples)


def test_duration_and_clipping_guards_remain_enforced():
    with pytest.raises(AudioRejected, match="AUDIO_DURATION_INVALID"):
        quality_check(np.full(1280, 0.1, dtype=np.float32))
    with pytest.raises(AudioRejected, match="CLIPPED_AUDIO"):
        quality_check(np.ones(3200, dtype=np.float32))


def test_broadband_noise_is_still_rejected_by_the_speech_guard():
    from pinyin_matcher.pretrained_runtime import signal_guard

    samples = np.random.default_rng(18).normal(0, 0.08, SAMPLE_RATE).astype(np.float32)
    assert signal_guard(samples) == "NONSPEECH_BROADBAND_INPUT"
