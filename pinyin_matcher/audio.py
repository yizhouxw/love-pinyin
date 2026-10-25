"""Bounded WAV decoding and target-independent CPU acoustic features."""

import io
import wave
from functools import lru_cache

import numpy as np
from scipy import signal

SAMPLE_RATE = 16000
MAX_SECONDS = 8
MAX_BYTES = 44 + SAMPLE_RATE * MAX_SECONDS * 2 + 4096
FEATURE_VERSION = "logmel64-pitch4-v1"


class AudioRejected(ValueError):
    pass


def decode_wav(payload: bytes) -> np.ndarray:
    if len(payload) > MAX_BYTES:
        raise AudioRejected("AUDIO_TOO_LONG")
    try:
        with wave.open(io.BytesIO(payload), "rb") as audio:
            if (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
                audio.getcomptype(),
            ) != (1, 2, SAMPLE_RATE, "NONE"):
                raise AudioRejected("PCM16_MONO_16KHZ_REQUIRED")
            frames = audio.getnframes()
            if not 2400 <= frames <= SAMPLE_RATE * MAX_SECONDS:
                raise AudioRejected("AUDIO_DURATION_INVALID")
            raw = audio.readframes(frames)
            if len(raw) != frames * 2:
                raise AudioRejected("AUDIO_TRUNCATED")
    except (wave.Error, EOFError) as error:
        raise AudioRejected("WAV_INVALID") from error
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    return samples


def encode_wav(samples: np.ndarray) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        audio.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def quality_check(samples: np.ndarray) -> dict:
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise AudioRejected("AUDIO_INVALID")
    if not 2400 <= len(samples) <= SAMPLE_RATE * MAX_SECONDS:
        raise AudioRejected("AUDIO_DURATION_INVALID")
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms < 0.002 or np.count_nonzero(np.abs(samples) > 0.005) < 1600:
        raise AudioRejected("SILENCE_OR_TOO_QUIET")
    if float(np.mean(np.abs(samples) >= 0.99)) > 0.05:
        raise AudioRejected("CLIPPED_AUDIO")
    return {"durationSeconds": len(samples) / SAMPLE_RATE, "rms": rms}


def trim_silence(samples: np.ndarray) -> np.ndarray:
    # Energy trimming preserves quiet unvoiced consonants with an 80ms margin.
    energy = signal.convolve(samples * samples, np.ones(160) / 160, mode="same")
    threshold = max(float(energy.max()) * 0.0003, 1e-7)
    active = np.flatnonzero(energy > threshold)
    if not len(active):
        return samples
    return samples[max(0, active[0] - 1280) : min(len(samples), active[-1] + 1281)]


@lru_cache(maxsize=1)
def mel_filters() -> np.ndarray:
    def hz_to_mel(x):
        return 2595 * np.log10(1 + x / 700)

    points = 700 * (10 ** (np.linspace(hz_to_mel(40), hz_to_mel(7600), 66) / 2595) - 1)
    frequencies = np.fft.rfftfreq(512, 1 / SAMPLE_RATE)
    filters = []
    for left, center, right in zip(points[:-2], points[1:-1], points[2:], strict=True):
        filters.append(
            np.maximum(
                0,
                np.minimum(
                    (frequencies - left) / (center - left), (right - frequencies) / (right - center)
                ),
            )
        )
    return np.asarray(filters, dtype=np.float32)


def features(samples: np.ndarray, *, check: bool = True) -> tuple[np.ndarray, dict]:
    info = quality_check(samples) if check else {"durationSeconds": len(samples) / SAMPLE_RATE}
    samples = trim_silence(samples)
    # Normalize overall gain only. Frequency shape and pitch contour stay intact.
    samples = samples / max(float(np.sqrt(np.mean(samples * samples))), 0.01) * 0.1
    padded = np.pad(samples, (320, 320))
    windows = np.lib.stride_tricks.sliding_window_view(padded, 640)[::160].copy()
    spectral = windows[:, 120:520] * np.hanning(400)
    power = np.abs(np.fft.rfft(spectral, 512)) ** 2
    mel = np.log(np.maximum(power @ mel_filters().T, 1e-6))
    # Fixed affine scale, not per-frequency utterance normalization (which erases vowels).
    mel = np.clip((mel + 3) / 5, -3, 3)
    frames = windows - windows.mean(axis=1, keepdims=True)
    ac = np.fft.irfft(np.abs(np.fft.rfft(frames, 2048)) ** 2, 2048)[:, :300]
    # YIN cumulative normalized difference. The two lag-dependent energy terms
    # avoid the edge-energy bias of selecting an autocorrelation peak alone.
    cumulative = np.pad(np.cumsum(frames * frames, axis=1), ((0, 0), (1, 0)))
    lags = np.arange(1, 300)
    difference = np.maximum(
        0, cumulative[:, 640 - lags] + cumulative[:, -1:] - cumulative[:, lags] - 2 * ac[:, 1:]
    )
    normalized = difference * lags / np.maximum(np.cumsum(difference, axis=1), 1e-9)
    valleys = (normalized[:, 17:266] < normalized[:, 16:265]) & (
        normalized[:, 17:266] <= normalized[:, 18:267]
    )
    candidates = valleys & (normalized[:, 17:266] < 0.2)
    lag = np.argmax(candidates, axis=1) + 18
    probability = 1 - normalized[np.arange(len(normalized)), lag - 1]
    energy = np.sqrt(np.mean(windows * windows, axis=1))
    voiced = candidates.any(axis=1) & (probability > 0.8) & (energy > 0.005)
    f0 = np.where(voiced, SAMPLE_RATE / lag, 0)
    log_f0 = np.where(voiced, np.log2(np.maximum(f0, 1) / 220), 0)
    center = float(np.median(log_f0[voiced])) if voiced.any() else 0
    relative = np.where(voiced, log_f0 - center, 0)
    delta = np.clip(np.gradient(relative), -0.3, 0.3)
    pitch = np.stack([log_f0, relative, delta, voiced.astype(np.float32)], axis=1)
    info.update(
        {
            "voicedFrames": int(voiced.sum()),
            "frames": len(mel),
            "medianF0": float(np.median(f0[voiced])) if voiced.any() else None,
        }
    )
    return np.concatenate([mel, pitch], axis=1).astype(np.float32), info
