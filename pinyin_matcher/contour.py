"""Target/content/absolute-pitch independent, voiced relative F0 contour."""

import numpy as np

from pinyin_matcher.audio import AudioRejected

PITCH_FEATURE_VERSION = "relative-voiced-contour32-v1"


def contour(acoustic: np.ndarray) -> np.ndarray:
    pitch = acoustic[acoustic[:, 67] > 0.5, 64]
    if len(pitch) < 8:
        raise AudioRejected("NO_RELIABLE_VOICED_SPEECH")
    pitch = np.median(
        np.lib.stride_tricks.sliding_window_view(np.pad(pitch, (1, 1), mode="edge"), 3), axis=1
    )
    pitch = pitch - np.median(pitch)
    relative = np.interp(np.linspace(0, len(pitch) - 1, 32), np.arange(len(pitch)), pitch)
    return np.stack([relative, np.gradient(relative)], axis=1).astype(np.float32)
