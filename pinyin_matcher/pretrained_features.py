"""Target-independent representations shared by training and CPU inference."""

import json
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import features, trim_silence
from pinyin_matcher.catalog import ROOT

CONFIG_PATH = ROOT / "content/pronunciation-pretrained-experiment.json"


def configuration():
    return json.loads(CONFIG_PATH.read_text())


def encoder(name: str, directory: Path, *, device="cpu"):
    if name == "sensevoice":
        from pinyin_matcher.pretrained_sensevoice import SenseVoiceFeatures

        return SenseVoiceFeatures(directory, device=device)
    from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

    return Wav2VecEvidence(name, directory, device=device)


def pool_frames(frames: np.ndarray) -> np.ndarray:
    """Mean/std and temporal thirds preserve local phone evidence."""
    if frames.ndim != 2 or not len(frames) or not np.isfinite(frames).all():
        raise ValueError("ENCODER_FEATURES_INVALID")
    bins = configuration()["features"]["poolBins"]
    sections = np.array_split(frames, bins)
    pools = [frames.mean(0), frames.std(0)]
    pools.extend(section.mean(0) if len(section) else frames.mean(0) for section in sections)
    return np.concatenate(pools).astype(np.float32)


def pitch_vector(samples: np.ndarray) -> np.ndarray:
    """Relative F0, delta, voicing and quality; never expected-text labels."""
    count = configuration()["features"]["pitchFrames"]
    acoustic, info = features(samples, check=False)
    voiced = acoustic[:, 67] > 0.5
    positions = np.flatnonzero(voiced)
    if len(positions) < 5:
        return np.zeros(count * 2 + 4, dtype=np.float32)
    relative = acoustic[voiced, 65]
    contour = np.interp(
        np.linspace(0, len(relative) - 1, count), np.arange(len(relative)), relative
    )
    delta = np.gradient(contour)
    return np.r_[
        contour,
        delta,
        len(positions) / len(acoustic),
        min(float(np.ptp(relative)), 3),
        (positions[-1] - positions[0] + 1) / len(acoustic),
        min(info["medianF0"] or 0, 800) / 400,
    ].astype(np.float32)


def represent(model, samples: np.ndarray) -> dict:
    samples = trim_silence(samples)
    if hasattr(model, "evidence"):
        evidence = model.evidence(samples)
    else:
        evidence = {"frames": model.extract(samples), "native": {}}
    return {
        "pooled": pool_frames(evidence["frames"]),
        "pitch": pitch_vector(samples),
        "frames": evidence["frames"],
        **{"native_" + key: value for key, value in evidence["native"].items()},
    }


def represent_batch(model, samples: list[np.ndarray]) -> list[dict]:
    """Offline accelerator batching; all padding is masked by the encoders."""
    samples = [trim_silence(s) for s in samples]
    if hasattr(model, "evidence_batch"):
        evidence = model.evidence_batch(samples)
    elif hasattr(model, "extract_batch"):
        evidence = [{"frames": f, "native": {}} for f in model.extract_batch(samples)]
    else:
        return [represent(model, s) for s in samples]
    return [
        {
            "pooled": pool_frames(e["frames"]),
            "pitch": pitch_vector(s),
            "frames": e["frames"],
            **{"native_" + key: value for key, value in e["native"].items()},
        }
        for e, s in zip(evidence, samples, strict=True)
    ]
