"""CPU-only pitch tracking and content-independent, time-preserving tone features.

This extractor deliberately accepts waveform samples rather than a target, syllable
or acoustic-model representation. Its output cannot encode an expected answer.
It is an experimental candidate; reliable F0 does not itself establish a tone.
"""

from dataclasses import dataclass

import numpy as np
from scipy import signal

from pinyin_matcher.audio import SAMPLE_RATE, AudioRejected, quality_check, trim_silence

PITCH_FEATURE_VERSION = "relative-yin-adaptive-path-contour32-v2"
FRAME_LENGTH = 1024
HOP_LENGTH = 160


@dataclass(frozen=True)
class PitchTrack:
    f0: np.ndarray
    confidence: np.ndarray
    voiced: np.ndarray
    rms: np.ndarray
    seconds: np.ndarray

    def summary(self) -> dict:
        good = self.f0[self.voiced]
        return {
            "frames": len(self.f0),
            "voicedFrames": int(self.voiced.sum()),
            "medianF0": float(np.median(good)) if len(good) else None,
            "pitchRangeOctaves": float(np.ptp(np.log2(good))) if len(good) else None,
            "medianPeriodicity": float(np.median(self.confidence[self.voiced]))
            if len(good)
            else None,
        }


def _track_window(samples: np.ndarray, frame_length: int, *, check: bool = True) -> PitchTrack:
    """Track 60–900 Hz with interpolated YIN minima and a continuity path.

    The longer window accommodates low-pitch voices; frame centers remain 10 ms
    apart. The deterministic continuity path compares six minima per frame and
    penalizes octave jumps. It never coerces noise-only frames to be voiced.
    """
    samples = np.asarray(samples, dtype=np.float64)
    if check:
        quality_check(samples)
    elif samples.ndim != 1 or len(samples) < 2 or not np.isfinite(samples).all():
        raise AudioRejected("AUDIO_INVALID")
    samples = trim_silence(samples)
    samples = samples / max(float(np.sqrt(np.mean(samples * samples))), 0.01) * 0.1
    sos = signal.butter(2, 35, btype="highpass", fs=SAMPLE_RATE, output="sos")
    samples = signal.sosfiltfilt(sos, samples)
    frames = np.lib.stride_tricks.sliding_window_view(
        np.pad(samples, (frame_length // 2, frame_length // 2)), frame_length
    )[::HOP_LENGTH].copy()
    frames -= frames.mean(axis=1, keepdims=True)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    maximum_lag = int(SAMPLE_RATE / 60) + 2
    minimum_lag = int(SAMPLE_RATE / 900)
    ac = np.fft.irfft(np.abs(np.fft.rfft(frames, 2048)) ** 2, 2048)[:, : maximum_lag + 1]
    cumulative = np.pad(np.cumsum(frames * frames, axis=1), ((0, 0), (1, 0)))
    lags = np.arange(1, maximum_lag + 1)
    difference = np.maximum(
        0,
        cumulative[:, frame_length - lags]
        + cumulative[:, -1:]
        - cumulative[:, lags]
        - 2 * ac[:, 1:],
    )
    normalized = np.ones((len(frames), maximum_lag + 1), dtype=np.float64)
    normalized[:, 1:] = difference * lags / np.maximum(np.cumsum(difference, axis=1), 1e-12)
    candidate_lags = np.zeros((len(frames), 6), dtype=np.float64)
    candidate_values = np.full((len(frames), 6), 1.0, dtype=np.float64)
    for i, values in enumerate(normalized):
        local = np.flatnonzero((values[1:-1] < values[:-2]) & (values[1:-1] <= values[2:])) + 1
        local = local[(local >= minimum_lag) & (local <= maximum_lag - 1)]
        if not len(local):
            local = np.asarray([minimum_lag + np.argmin(values[minimum_lag:maximum_lag])])
        # Keep the earliest plausible valley as well as the deepest minima.
        selected = local[np.argsort(values[local], kind="stable")[:6]]
        plausible = local[values[local] < 0.25]
        if len(plausible) and plausible[0] not in selected:
            selected[-1] = plausible[0]
        for j, lag in enumerate(selected):
            curvature = values[lag - 1] - 2 * values[lag] + values[lag + 1]
            offset = (
                np.clip(0.5 * (values[lag - 1] - values[lag + 1]) / curvature, -0.5, 0.5)
                if curvature > 1e-12
                else 0
            )
            candidate_lags[i, j] = lag + offset
            candidate_values[i, j] = values[lag]
    valid = candidate_lags > 0
    log_frequency = np.log2(SAMPLE_RATE / np.maximum(candidate_lags, 1))
    emission = 6 * candidate_values + 0.20 * np.log2(
        np.maximum(candidate_lags, minimum_lag) / minimum_lag
    )
    emission[~valid] = 1e4
    active_energy = rms > max(0.003, float(rms.max()) * 0.025)
    # Unvoiced gaps cannot propagate an arbitrary fundamental to a new syllable.
    energetic = np.flatnonzero(active_energy)
    paths = np.zeros((len(frames), 6), dtype=np.int64)
    cost = emission[0].copy()
    for i in range(1, len(frames)):
        distance = np.abs(log_frequency[i, :, None] - log_frequency[i - 1, None, :])
        transition = 2 * distance + 0.4 * (distance > 0.3)
        if not active_energy[i] or not active_energy[i - 1]:
            transition *= 0
        combined = cost[None, :] + transition
        paths[i] = combined.argmin(axis=1)
        cost = emission[i] + combined.min(axis=1)
        cost -= cost.min()
    chosen = np.zeros(len(frames), dtype=np.int64)
    chosen[-1] = cost.argmin()
    for i in range(len(frames) - 1, 0, -1):
        chosen[i - 1] = paths[i, chosen[i]]
    indices = np.arange(len(frames))
    confidence = np.clip(1 - candidate_values[indices, chosen], 0, 1)
    voiced = active_energy & (confidence > 0.70) & valid[indices, chosen]
    frequency = SAMPLE_RATE / np.maximum(candidate_lags[indices, chosen], 1)
    frequency = np.where(voiced, frequency, 0)
    # A single isolated pitch estimate is not a trustworthy voiced interval.
    if len(energetic):
        isolated = signal.convolve(voiced.astype(np.int32), np.ones(3, dtype=np.int32), mode="same")
        voiced &= isolated >= 2
        frequency[~voiced] = 0
    return PitchTrack(
        frequency.astype(np.float32),
        confidence.astype(np.float32),
        voiced,
        rms.astype(np.float32),
        np.arange(len(frames), dtype=np.float32) * HOP_LENGTH / SAMPLE_RATE,
    )


def track(samples: np.ndarray, *, check: bool = True) -> PitchTrack:
    """Use 40 ms detail above 170 Hz, and 64 ms support for lower voices."""
    longer = _track_window(samples, FRAME_LENGTH, check=check)
    shorter = _track_window(samples, 640, check=False)
    choose_short = shorter.voiced & ((shorter.f0 >= 170) | ~longer.voiced)
    return PitchTrack(
        np.where(choose_short, shorter.f0, longer.f0),
        np.where(choose_short, shorter.confidence, longer.confidence),
        np.where(choose_short, shorter.voiced, longer.voiced),
        np.where(choose_short, shorter.rms, longer.rms),
        longer.seconds,
    )


def contour(samples: np.ndarray, *, check: bool = True) -> tuple[np.ndarray, dict]:
    """Return 32 x 4 relative-F0, change, periodicity and voicing features.

    Silence/creaky gaps retain their relative positions instead of being removed
    and concatenated. The absolute pitch is excluded to reduce voice shortcuts.
    """
    pitch = track(samples, check=check)
    good = np.flatnonzero(pitch.voiced)
    if len(good) < 8:
        raise AudioRejected("NO_RELIABLE_VOICED_SPEECH")
    first, last = int(good[0]), int(good[-1])
    positions = np.linspace(first, last, 32)
    log_f0 = np.log2(pitch.f0[good])
    # Median filtering suppresses isolated subharmonics without flattening a dip.
    log_f0 = np.median(
        np.lib.stride_tricks.sliding_window_view(np.pad(log_f0, (1, 1), mode="edge"), 3),
        axis=1,
    )
    relative = np.interp(positions, good, log_f0) - np.median(log_f0)
    relative = np.clip(relative, -2, 2)
    confidence = np.interp(positions, np.arange(len(pitch.f0)), pitch.confidence)
    voiced = np.interp(positions, np.arange(len(pitch.f0)), pitch.voiced.astype(np.float32))
    array = np.stack([relative, np.gradient(relative), confidence, voiced], axis=1).astype(
        np.float32
    )
    return array, pitch.summary()
