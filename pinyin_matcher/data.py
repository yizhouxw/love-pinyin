"""Synthetic lineage validation, deterministic augmentation and private dataset IO."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import signal

from pinyin_matcher.audio import SAMPLE_RATE, decode_wav, features
from pinyin_matcher.catalog import ROOT, fingerprint, targets_by_id

SPLITS = {"train", "calibration", "test"}
AUGMENT_VERSION = "environment-v2"


@lru_cache(maxsize=1)
def augmentation_config():
    return json.loads((ROOT / "content/pronunciation-training.json").read_text())["augmentation"]


def read_manifest(
    path: Path, *, verify_audio: bool = True, catalog: dict | None = None
) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("version") != 1 or data.get("cohort") != "synthetic":
        raise ValueError("SYNTHETIC_MANIFEST_REQUIRED")
    rows = data["items"]
    if not rows:
        raise ValueError("EMPTY_DATASET")
    known = targets_by_id(catalog)
    ids, hashes, family_splits, root_splits, reference_splits = set(), {}, {}, {}, {}
    audio_root = path.parent.resolve()
    for row in rows:
        if row["id"] in ids or row["targetId"] not in known or row["split"] not in SPLITS:
            raise ValueError("DATASET_REFERENCE_INVALID")
        ids.add(row["id"])
        for key, table in [("voiceFamilyId", family_splits), ("referenceRootId", root_splits)]:
            group = row[key]
            if table.setdefault(group, row["split"]) != row["split"]:
                raise ValueError("DATASET_LINEAGE_LEAKAGE")
        if hashes.setdefault(row["sha256"], row["split"]) != row["split"]:
            raise ValueError("DATASET_AUDIO_LEAKAGE")
        reference_hash = row.get("referenceSha256")
        if (
            reference_hash
            and reference_splits.setdefault(reference_hash, row["split"]) != row["split"]
        ):
            raise ValueError("DATASET_REFERENCE_AUDIO_LEAKAGE")
        file = (audio_root / row["file"]).resolve()
        if not file.is_relative_to(audio_root):
            raise ValueError("DATASET_PATH_INVALID")
        if verify_audio and fingerprint(file) != row["sha256"]:
            raise ValueError("DATASET_DIGEST_MISMATCH")
    return rows


def augment(samples: np.ndarray, seed: int, *, snr: float | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = samples.copy()
    configuration = augmentation_config()
    if rng.random() < 0.3:
        import librosa

        out = librosa.effects.time_stretch(
            out, rate=float(rng.uniform(*configuration["timeStretch"])), n_fft=512, hop_length=128
        )
    if rng.random() < 0.4:
        duration = rng.uniform(*configuration["reverbSeconds"])
        length = int(duration * SAMPLE_RATE)
        impulse = rng.normal(0, 0.05, length) * np.exp(-np.arange(length) / (length / 7))
        impulse[0] = 1
        out = signal.fftconvolve(out, impulse, mode="full")[: len(out)].astype(np.float32)
    if rng.random() < 0.75 or snr is not None:
        noise = rng.standard_normal(len(out))
        noise = signal.lfilter([1], [1, -rng.uniform(0, 0.85)], noise)
        level = snr if snr is not None else rng.choice(configuration["snrDb"])
        scale = np.sqrt(np.mean(out * out)) / max(np.sqrt(np.mean(noise * noise)), 1e-9)
        out += noise * scale * 10 ** (-level / 20)
    out *= 10 ** (rng.uniform(*configuration["gainDb"]) / 20)
    peak = float(np.max(np.abs(out)))
    if peak > 0.95:
        out *= 0.95 / peak
    return out.astype(np.float32)


def cache_features(manifest: Path, destination: Path) -> tuple[list[dict], dict[str, np.ndarray]]:
    rows = read_manifest(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for row in rows:
        cache = destination / (row["sha256"] + ".npz")
        if cache.exists():
            with np.load(cache, allow_pickle=False) as data:
                arrays[row["id"]] = data["features"]
        else:
            sample = decode_wav((manifest.parent / row["file"]).read_bytes())
            array, _ = features(sample)
            np.savez_compressed(cache, features=array)
            arrays[row["id"]] = array
    return rows, arrays


def dataset_digest(manifest: Path) -> str:
    return hashlib.sha256(manifest.read_bytes()).hexdigest()
