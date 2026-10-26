"""Independent SwiftF0 pitch evidence/cache for pretrained encoder experiments.

No matcher decisions, expected targets, automatic downloads or frozen-test audio.
The existing YIN feature/cache and global experiment configuration stay separate.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import AudioRejected, decode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pitch_swift import MODEL_SHA256, SwiftPitch

PROTOCOL = ROOT / "content/pronunciation-pretrained-pitch.json"
FEATURE_VERSION = "pretrained-swift-relative32-pitch68-v2"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def load_protocol(path: Path = PROTOCOL) -> dict:
    data = json.loads(path.read_text())
    if (
        data["version"] != FEATURE_VERSION
        or data["tracker"]["modelSha256"] != MODEL_SHA256
        or data["features"]["dimensions"] != 68
        or data["features"]["contourPoints"] != 32
        or data["features"]["minimumVoicedFrames"] != 6
        or data["cache"]["allowedSplits"] != ["train", "calibration"]
    ):
        raise ValueError("PRETRAINED_PITCH_PROTOCOL_UNSUPPORTED")
    return data


def vector_from_track(track, protocol: dict | None = None) -> tuple[np.ndarray, dict]:
    """Preserve real frame positions, including unvoiced gaps, in a 68-vector."""
    cfg = (protocol or load_protocol())["features"]
    f0 = np.asarray(track.f0, dtype=np.float32)
    voiced = np.asarray(track.voiced, dtype=bool)
    seconds = np.asarray(track.seconds, dtype=np.float32)
    if (
        f0.ndim != 1
        or not len(f0)
        or voiced.shape != f0.shape
        or seconds.shape != f0.shape
        or not np.isfinite(f0).all()
        or not np.isfinite(seconds).all()
        or np.any(np.diff(seconds) <= 0)
        or np.any(f0[voiced] <= 0)
    ):
        raise ValueError("PRETRAINED_PITCH_TRACK_INVALID")
    good = np.flatnonzero(voiced)
    info = {
        "available": len(good) >= cfg["minimumVoicedFrames"],
        "flags": [] if len(good) >= cfg["minimumVoicedFrames"] else ["PITCH_INSUFFICIENT_VOICING"],
        "frames": len(f0),
        "voicedFrames": len(good),
        "featureVersion": FEATURE_VERSION,
    }
    if not info["available"]:
        return np.zeros(68, dtype=np.float32), info
    log_f0 = np.log2(f0[good])
    relative = log_f0 - np.median(log_f0)
    positions = np.linspace(seconds[good[0]], seconds[good[-1]], cfg["contourPoints"])
    contour = np.clip(
        np.interp(positions, seconds[good], relative),
        -cfg["relativeClipOctaves"],
        cfg["relativeClipOctaves"],
    )
    frame_step = float(np.median(np.diff(seconds))) if len(seconds) > 1 else 0.016
    total_extent = float(seconds[-1] - seconds[0]) + frame_step
    voiced_extent = float(seconds[good[-1]] - seconds[good[0]]) + frame_step
    median_f0 = float(np.median(f0[good]))
    vector = np.r_[
        contour,
        np.gradient(contour),
        len(good) / len(f0),
        min(float(np.ptp(relative)), cfg["rangeClipOctaves"]),
        voiced_extent / total_extent,
        min(median_f0, cfg["medianF0ClipHz"]) / cfg["medianF0DivisorHz"],
    ].astype(np.float32)
    info.update(
        {
            "medianF0": median_f0,
            "firstVoicedSeconds": float(seconds[good[0]]),
            "lastVoicedSeconds": float(seconds[good[-1]]),
        }
    )
    return vector, info


class PitchExtractor:
    def __init__(self, model: Path, *, protocol_path: Path = PROTOCOL):
        self.protocol = load_protocol(protocol_path)
        self.tracker = SwiftPitch(model)

    def vector(self, samples: np.ndarray) -> tuple[np.ndarray, dict]:
        try:
            track = self.tracker.track(samples, check=True)
        except AudioRejected as error:
            return np.zeros(68, dtype=np.float32), {
                "available": False,
                "flags": ["PITCH_AUDIO_UNASSESSABLE:" + str(error)],
                "featureVersion": FEATURE_VERSION,
            }
        return vector_from_track(track, self.protocol)


SwiftPitchVector = PitchExtractor


def cache_identity(manifest: Path, model: Path, protocol_path: Path = PROTOCOL) -> dict:
    load_protocol(protocol_path)
    if fingerprint(model) != MODEL_SHA256:
        raise ValueError("PRETRAINED_PITCH_MODEL_SHA_MISMATCH")
    license_file = model.parent / "LICENSE"
    expected_license = ROOT / "resources/licenses/SwiftF0-MIT.txt"
    if fingerprint(license_file) != fingerprint(expected_license):
        raise ValueError("PRETRAINED_PITCH_LICENSE_MISMATCH")
    return {
        "featureVersion": FEATURE_VERSION,
        "modelSha256": MODEL_SHA256,
        "licenseSha256": fingerprint(license_file),
        "pitchAdapterSha256": fingerprint(Path(__file__).with_name("pitch_swift.py")),
        "pitchTrackCodeSha256": fingerprint(Path(__file__).with_name("pitch_v2.py")),
        "audioCodeSha256": fingerprint(Path(__file__).with_name("audio.py")),
        "sourceAdapterSha256": fingerprint(Path(__file__)),
        "baseManifestSha256": fingerprint(manifest),
        "protocolSha256": fingerprint(protocol_path),
        "codeSha256": {
            name: fingerprint(Path(__file__).with_name(name))
            for name in ("pretrained_pitch.py", "pitch_swift.py", "pitch_v2.py", "audio.py")
        },
    }


def select_rows(data: dict) -> tuple[list[dict], dict]:
    rows, ignored, seen_ids = [], Counter(), set()
    tables = {
        field: {}
        for field in ("speakerId", "parentSha256", "referenceSourceId", "voiceFamilyId", "sha256")
    }
    for row in data["items"]:
        if row["id"] in seen_ids:
            raise ValueError("PRETRAINED_PITCH_DUPLICATE_ROW_ID")
        seen_ids.add(row["id"])
        if row["split"] not in {"train", "calibration", "test", "diagnostic"}:
            raise ValueError("PRETRAINED_PITCH_UNKNOWN_SPLIT")
        for field, table in tables.items():
            if field == "sha256" and row.get("placeholder"):
                continue
            if row.get(field) and table.setdefault(row[field], row["split"]) != row["split"]:
                raise ValueError("PRETRAINED_PITCH_SOURCE_LEAKAGE:" + field)
        if row["split"] not in {"train", "calibration"}:
            ignored[row["split"]] += 1
            continue
        rows.append(row)
    return rows, dict(ignored)


def prepare(
    manifest: Path,
    model: Path,
    output: Path,
    *,
    include_test: bool = False,
    protocol_path: Path = PROTOCOL,
) -> dict:
    if include_test:
        raise ValueError("PRETRAINED_PITCH_TEST_AUDIO_FORBIDDEN")
    data = json.loads(manifest.read_text())
    rows, ignored = select_rows(data)
    identity = cache_identity(manifest, model, protocol_path)
    output.mkdir(parents=True, exist_ok=True)
    identity_file = output / "identity.json"
    if identity_file.exists() and json.loads(identity_file.read_text()) != identity:
        raise ValueError("PRETRAINED_PITCH_IDENTITY_CHANGED_USE_NEW_DIRECTORY")
    if not identity_file.exists():
        if any((output / "features").glob("*.npz")):
            raise ValueError("PRETRAINED_PITCH_UNBOUND_CACHE")
        write_json(identity_file, identity)
    identity_sha = fingerprint(identity_file)
    extractor = PitchExtractor(model, protocol_path=protocol_path)
    started, records = time.perf_counter(), []
    for index, row in enumerate(rows, 1):
        audio_file = Path(row["file"])
        if not audio_file.is_absolute():
            audio_file = manifest.parent / audio_file
        path = output / "features" / (row["sha256"] + ".npz")
        sidecar_path = path.with_suffix(".json")
        if path.exists():
            meta = json.loads(sidecar_path.read_text())
            if (
                meta["identitySha256"] != identity_sha
                or meta["sha256"] != fingerprint(path)
                or meta["audioSha256"] != row["sha256"]
            ):
                raise ValueError("PRETRAINED_PITCH_CACHE_DIGEST_MISMATCH")
        else:
            if fingerprint(audio_file) != row["sha256"]:
                raise ValueError("PRETRAINED_PITCH_AUDIO_DIGEST_MISMATCH")
            try:
                samples = decode_wav(audio_file.read_bytes())
            except AudioRejected as error:
                vector = np.zeros(68, dtype=np.float32)
                info = {"available": False, "flags": ["PITCH_WAV_UNASSESSABLE:" + str(error)]}
            else:
                vector, info = extractor.vector(samples)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.with_suffix(".part").open("wb") as handle:
                np.savez_compressed(handle, pitch=vector, available=np.asarray(info["available"]))
            path.with_suffix(".part").replace(path)
            meta = {
                "identitySha256": identity_sha,
                "audioSha256": row["sha256"],
                "sha256": fingerprint(path),
                "info": info,
            }
            write_json(sidecar_path, meta)
        source_flags = row.get("numericalQualityFlags", []) + (
            ["SOURCE_PLACEHOLDER"] if row.get("placeholder") else []
        )
        info = meta["info"]
        records.append(
            {
                "id": row["id"],
                "audioSha256": row["sha256"],
                "split": row["split"],
                "speakerId": row.get("speakerId"),
                "file": str(path.relative_to(output)),
                "sha256": meta["sha256"],
                "pitchAvailable": info["available"] and not source_flags,
                "flags": info["flags"] + source_flags,
            }
        )
        if index % 500 == 0:
            print(
                json.dumps(
                    {
                        "pitchRows": index,
                        "total": len(rows),
                        "seconds": time.perf_counter() - started,
                    }
                ),
                flush=True,
            )
    result = {
        "schemaVersion": 1,
        "featureVersion": FEATURE_VERSION,
        "baseManifest": str(manifest.resolve()),
        "baseManifestSha256": fingerprint(manifest),
        "identity": identity,
        "identitySha256": identity_sha,
        "testIncluded": False,
        "ignoredSplitMetadataCounts": ignored,
        "counts": {
            "rows": len(records),
            "bySplit": dict(Counter(r["split"] for r in records)),
            "uniqueAudioSha256": len({r["audioSha256"] for r in records}),
            "available": sum(r["pitchAvailable"] for r in records),
            "flags": dict(Counter(flag for r in records for flag in r["flags"])),
        },
        "items": records,
        "elapsedSeconds": time.perf_counter() - started,
    }
    write_json(output / "manifest.json", result)
    return result


class PitchCache:
    """Load metadata once; validate each requested pitch payload before use."""

    def __init__(self, manifest: Path):
        self.path = manifest
        self.metadata = json.loads(manifest.read_text())
        if self.metadata["featureVersion"] != FEATURE_VERSION or self.metadata["testIncluded"]:
            raise ValueError("PRETRAINED_PITCH_CACHE_VERSION_OR_TEST_FORBIDDEN")
        if fingerprint(manifest.parent / "identity.json") != self.metadata["identitySha256"]:
            raise ValueError("PRETRAINED_PITCH_IDENTITY_DIGEST_MISMATCH")
        if json.loads((manifest.parent / "identity.json").read_text()) != self.metadata["identity"]:
            raise ValueError("PRETRAINED_PITCH_INLINE_IDENTITY_MISMATCH")
        self.records = {row["id"]: row for row in self.metadata["items"]}
        if len(self.records) != len(self.metadata["items"]):
            raise ValueError("PRETRAINED_PITCH_DUPLICATE_CACHE_ID")

    def read(self, row: dict) -> tuple[np.ndarray, dict]:
        if row["split"] not in {"train", "calibration"}:
            raise ValueError("PRETRAINED_PITCH_TEST_AUDIO_FORBIDDEN")
        meta = self.records[row["id"]]
        if row["sha256"] != meta["audioSha256"] or row["split"] != meta["split"]:
            raise ValueError("PRETRAINED_PITCH_ROW_IDENTITY_MISMATCH")
        path = self.path.parent / meta["file"]
        if fingerprint(path) != meta["sha256"]:
            raise ValueError("PRETRAINED_PITCH_CACHE_DIGEST_MISMATCH")
        with np.load(path, allow_pickle=False) as cache:
            vector = cache["pitch"].astype(np.float32)
        if vector.shape != (68,) or not np.isfinite(vector).all():
            raise ValueError("PRETRAINED_PITCH_VECTOR_INVALID")
        if not meta["pitchAvailable"]:
            vector = np.zeros(68, dtype=np.float32)
        return vector, {"available": meta["pitchAvailable"], "flags": meta["flags"]}


def read_cached(cache_manifest: Path | PitchCache, row: dict) -> tuple[np.ndarray, dict]:
    cache = cache_manifest if isinstance(cache_manifest, PitchCache) else PitchCache(cache_manifest)
    return cache.read(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--model", type=Path, default=ROOT / "models/matcher-pitch-swift/model.onnx"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-test", action="store_true")
    args = parser.parse_args()
    result = prepare(args.manifest, args.model, args.output, include_test=args.include_test)
    print(
        json.dumps({"output": str(args.output / "manifest.json"), **result["counts"]}), flush=True
    )


if __name__ == "__main__":
    main()
