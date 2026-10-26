"""Deterministic non-speech fixtures for rejection contracts, not speech accuracy."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import signal

from pinyin_matcher.audio import SAMPLE_RATE, encode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.generate import atomic_json


def prepare(output: Path):
    if output.exists():
        raise ValueError("CHALLENGE_DIRECTORY_ALREADY_EXISTS")
    output.mkdir(parents=True)
    rows = []
    for category in ("silence", "white-noise", "pink-noise", "clicks", "hum", "chirp"):
        for index in range(8):
            seed = 318202600 + index
            rng = np.random.default_rng(seed)
            count = SAMPLE_RATE * (1 + index % 4)
            times = np.arange(count) / SAMPLE_RATE
            noise = rng.normal(0, 1, count)
            if category == "silence":
                samples = np.zeros(count)
            elif category == "white-noise":
                samples = noise * 0.05
            elif category == "pink-noise":
                spectrum = np.fft.rfft(noise)
                spectrum /= np.sqrt(np.maximum(np.fft.rfftfreq(count), 1 / count))
                samples = np.fft.irfft(spectrum, count)
                samples *= 0.05 / np.std(samples)
            elif category == "clicks":
                samples = np.zeros(count)
                locations = rng.choice(count, count // 320, replace=False)
                samples[locations] = rng.uniform(-0.4, 0.4, len(locations))
            elif category == "hum":
                frequency = rng.uniform(47, 62)
                samples = 0.04 * np.sin(2 * np.pi * frequency * times)
                samples += 0.015 * np.sin(2 * np.pi * frequency * 3 * times)
            else:
                samples = 0.07 * signal.chirp(times, 80 + index * 20, times[-1], 1500)
            key = f"mechanical-{category}-{index}"
            file = output / (key + ".wav")
            file.write_bytes(encode_wav(samples.astype(np.float32)))
            rows.append(
                {
                    "id": key,
                    "file": file.name,
                    "sha256": fingerprint(file),
                    "sourceRootId": key,
                    "split": "calibration",
                    "case": "non-speech",
                    "expectedMatch": False,
                    "clearAudio": False,
                    "category": category,
                    "generator": "deterministic-signal-fixture",
                    "seed": seed,
                    "labelProvenance": "mechanical non-speech; never pronunciation validation",
                }
            )
    manifest = {
        "version": 1,
        "cohort": "mechanical-non-speech-contract-only",
        "realRecording": False,
        "realChildAccuracyEstablished": False,
        "items": rows,
    }
    atomic_json(output / "manifest.json", manifest)
    return {"manifest": str(output / "manifest.json"), "items": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().output)))
