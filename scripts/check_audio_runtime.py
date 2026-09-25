"""Check local DSP availability with synthetic signals, never grade a child's speech."""

import json
import platform
from importlib.metadata import version

import librosa
import numpy as np

sample_rate = 16000
signal = np.sin(2 * np.pi * 220 * np.arange(sample_rate) / sample_rate).astype(np.float32)
pitch = librosa.yin(signal, fmin=70, fmax=800, sr=sample_rate)
median_hz = float(np.median(pitch))
assert abs(median_hz - 220) < 5, median_hz
print(
    json.dumps(
        {
            "purpose": "synthetic DSP runtime check; not pronunciation validation",
            "architecture": platform.machine(),
            "librosa": version("librosa"),
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "medianHz": round(median_hz, 2),
            "status": "passed",
        },
        ensure_ascii=False,
        indent=2,
    )
)
