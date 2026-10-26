"""Fixed target-independent frame resampling, shared by training and CPU runtime."""

import numpy as np

TEMPORAL_BINS = 16


def temporal_vector(frames):
    frames = np.asarray(frames, dtype=np.float32)
    if frames.ndim != 2 or not len(frames) or not np.isfinite(frames).all():
        raise ValueError("TEMPORAL_FRAMES_INVALID")
    positions = np.linspace(0, len(frames) - 1, TEMPORAL_BINS)
    left = positions.astype(np.int64)
    right = np.minimum(left + 1, len(frames) - 1)
    weights = (positions - left).astype(np.float32)[:, None]
    return (frames[left] * (1 - weights) + frames[right] * weights).reshape(-1)
