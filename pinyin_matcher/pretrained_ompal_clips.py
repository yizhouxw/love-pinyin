"""Offline OMPAL word clips: expert labels retained, model supplies boundaries.

No recognition output becomes a correctness label. Every annotated word is
retained, including failed alignments and ambiguous lexical/expert judgments.
Frozen-test speech is excluded unless both the explicit flag and plan are given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_align import align_components
from pinyin_matcher.pretrained_data import read_recording

SAMPLE_RATE = 16000
VERSION = "ompal-three-head-midpoint-v2-model-specific-apical"


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def _selection(
    data: dict, include_frozen_test: bool, frozen_plan: Path | None
) -> tuple[list, dict]:
    plan = {}
    if include_frozen_test:
        from pinyin_matcher.pretrained_freeze import verify_plan, verify_source_manifest

        plan = verify_plan(frozen_plan)
        verify_source_manifest(data, frozen_plan, plan)
    selected = []
    for utterance in data["utterances"]:
        if utterance["split"] not in {"train", "calibration", "diagnostic", "test"}:
            raise ValueError("OMPAL_SPLIT_INVALID")
        if utterance["split"] != "test" or include_frozen_test:
            selected.append(utterance)
    ids = [word["id"] for utterance in selected for word in utterance["words"]]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", x) for x in ids):
        raise ValueError("OMPAL_WORD_ID_INVALID_OR_DUPLICATED")
    return selected, plan


def _read_audio(path: Path) -> np.ndarray:
    samples, rate = read_recording(path)
    if not 8000 <= rate <= 192000 or not 400 <= len(samples) <= rate * 120:
        raise ValueError("UTTERANCE_DURATION_OR_RATE_INVALID")
    if rate != SAMPLE_RATE:
        divisor = math.gcd(rate, SAMPLE_RATE)
        samples = resample_poly(samples, SAMPLE_RATE // divisor, rate // divisor)
    samples = np.asarray(samples, dtype=np.float32)
    if not np.isfinite(samples).all():
        raise ValueError("UTTERANCE_NONFINITE")
    return samples


def word_audio(
    samples: np.ndarray, bounds: list[dict], index: int
) -> tuple[np.ndarray, dict, list]:
    """Preserve CTC blank partitions; cap 40ms outer context at neighbor cuts."""
    item = bounds[index]
    if not item["available"]:
        return (
            np.zeros(4000, dtype=np.float32),
            {
                "startSample": None,
                "endSample": None,
                "originalDurationSeconds": None,
                "zeroPadLeftSamples": 0,
                "zeroPadRightSamples": 0,
                "placeholder": True,
            },
            ["ALIGNMENT_UNAVAILABLE", *item["flags"]],
        )
    previous_cut = bounds[index - 1]["endSeconds"] if index else 0
    following_cut = (
        bounds[index + 1]["startSeconds"] if index + 1 < len(bounds) else len(samples) / SAMPLE_RATE
    )
    start = round(max(previous_cut, item["startSeconds"] - 0.04, 0) * SAMPLE_RATE)
    end = round(
        min(following_cut, item["endSeconds"] + 0.04, len(samples) / SAMPLE_RATE) * SAMPLE_RATE
    )
    flags = []
    if not 0 <= start < end <= len(samples):
        failed = [dict(x, available=False, flags=["CLIP_BOUNDARY_INVALID"]) for x in bounds]
        return word_audio(samples, failed, index)
    clip = samples[start:end].copy()
    count = len(clip)
    if count < 1280:
        flags.append("ACOUSTIC_CONTENT_UNDER_80MS")
    if count > SAMPLE_RATE * 4:
        flags.append("WORD_CLIP_OVER_FOUR_SECONDS")
    rms = float(np.sqrt(np.mean(clip * clip)))
    if rms < 1e-5:
        flags.append("NO_AUDIO_ENERGY")
    if float(np.mean(np.abs(clip) >= 0.99)) > 0.05:
        flags.append("CLIPPED_AUDIO")
    padding = max(0, 2400 - count)
    left = padding // 2
    right = padding - left
    if padding:
        clip = np.pad(clip, (left, right))
    metadata = {
        "startSample": start,
        "endSample": end,
        "startSeconds": start / SAMPLE_RATE,
        "endSeconds": end / SAMPLE_RATE,
        "originalDurationSeconds": count / SAMPLE_RATE,
        "zeroPadLeftSamples": left,
        "zeroPadRightSamples": right,
        "placeholder": False,
        "rms": rms,
    }
    return clip, metadata, flags


def _load_native(path: Path, metadata: dict) -> dict | None:
    sidecar = path.with_suffix(".json")
    if not path.exists() or not sidecar.exists():
        return None
    saved = json.loads(sidecar.read_text())
    if saved.get("provenance") != metadata or fingerprint(path) != saved.get("sha256"):
        raise ValueError("OMPAL_NATIVE_CACHE_INTEGRITY_MISMATCH")
    with np.load(path, allow_pickle=False) as cached:
        return {head: cached[head].copy() for head in ("initial", "final", "tone")}


def _save_native(path: Path, native: dict, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".npz.part")
    with temporary.open("wb") as output:
        np.savez_compressed(
            output, **{key: np.asarray(value, dtype=np.float32) for key, value in native.items()}
        )
    temporary.replace(path)
    _write(path.with_suffix(".json"), {"sha256": fingerprint(path), "provenance": metadata})


def prepare_clips(
    utterances: Path,
    output: Path,
    *,
    model_path: Path = ROOT / "models/pinyin-pretrained/hanziflow",
    device: str = "cpu",
    batch_size: int = 4,
    include_frozen_test: bool = False,
    frozen_plan: Path | None = None,
    provider=None,
) -> dict:
    """Prepare every selected word, with resumable native-logit caching."""
    if device not in {"cpu", "mps"} or not 1 <= batch_size <= 4:
        raise ValueError("OMPAL_PREPARATION_DEVICE_OR_BATCH_INVALID")
    data = json.loads(utterances.read_text())
    selected, plan = _selection(data, include_frozen_test, frozen_plan)
    if include_frozen_test and provider is not None:
        raise ValueError("FROZEN_TEST_NUMERIC_PROVIDER_FORBIDDEN")
    output.mkdir(parents=True, exist_ok=True)
    model_record = json.loads((ROOT / "content/pronunciation-pretrained-models.json").read_text())[
        "models"
    ]["hanziflow"]
    from pinyin_matcher.pretrained_native import native_rime_aliases

    aliases = native_rime_aliases("hanziflow")
    schema_entry = next(
        item for item in model_record["files"] if item["path"] == "v2_1_target_schema.json"
    )
    if provider is None:
        schema_path = model_path / "v2_1_target_schema.json"
        if fingerprint(schema_path) != schema_entry["sha256"]:
            raise ValueError("OMPAL_NATIVE_TARGET_SCHEMA_MISMATCH")
    mapping = {
        "model": "hanziflow",
        "aliases": aliases,
        "aliasesSha256": hashlib.sha256(
            json.dumps(aliases, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "upstreamTargetSchemaSha256": schema_entry["sha256"],
        "aliasConfigurationSha256": fingerprint(
            ROOT / "content/pronunciation-pretrained-experiment.json"
        ),
    }
    model_identity = {
        "model": "hanziflow",
        "revision": model_record["revision"],
        "sourceWeights": {
            x["path"]: x["sha256"]
            for x in model_record["files"]
            if x["path"].endswith(".safetensors")
        },
        "implementationSha256": fingerprint(Path(__file__).with_name("pretrained_wav2vec.py")),
        "device": device,
        "batchSize": batch_size,
        "normalization": "utterance-mean-variance-v1",
        "decoderSha256": fingerprint(Path(__file__).with_name("pretrained_data.py")),
    }
    rows, pending = [], []
    started = time.perf_counter()

    def emit(utterance: dict, samples: np.ndarray | None, native: dict | None, error=None):
        if native is None:
            bounds = [
                {"index": index, "available": False, "flags": [error or "NATIVE_UNAVAILABLE"]}
                for index in range(len(utterance["words"]))
            ]
            audio = np.zeros(4000, dtype=np.float32)
        else:
            audio = samples
            bounds = align_components(
                native,
                utterance["words"],
                len(audio) / SAMPLE_RATE,
                directory=model_path,
                aliases=aliases,
            )
        for index, word in enumerate(utterance["words"]):
            clip, window, flags = word_audio(audio, bounds, index)
            file = Path("clips") / (word["id"] + ".wav")
            path = output / file
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = encode_wav(clip)
            if not path.exists() or path.read_bytes() != payload:
                temporary = path.with_suffix(".wav.part")
                temporary.write_bytes(payload)
                temporary.replace(path)
            rows.append(
                {
                    **word,
                    "id": word["id"],
                    "file": str(file),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "split": utterance["split"],
                    "speakerId": utterance["speakerId"],
                    "voiceFamilyId": utterance.get("voiceFamilyId", utterance["speakerId"]),
                    "referenceSourceId": utterance.get("referenceSourceId", utterance["speakerId"]),
                    "source": utterance.get("source", "ompal-v1"),
                    "labelProvenance": utterance.get("labelProvenance"),
                    "sourceUtteranceId": utterance["id"],
                    "sourcePath": utterance.get("sourcePath"),
                    "sourceGitBlobSha1": utterance.get("sourceGitBlobSha1"),
                    "parentSha256": utterance["sha256"],
                    "parentFile": utterance["file"],
                    "syllable": word.get("expectedPinyin"),
                    "onset": word.get("onset"),
                    "rime": word.get("rime"),
                    "tone": word.get("tone"),
                    "alignment": bounds[index],
                    "alignmentFlags": bounds[index]["flags"],
                    "numericalQualityFlags": sorted(set(flags)),
                    "bounds": window,
                    "placeholder": window["placeholder"],
                    "sampleRate": SAMPLE_RATE,
                    "durationSeconds": len(clip) / SAMPLE_RATE,
                    "alignmentIsCorrectnessEvidence": False,
                }
            )

    def flush():
        nonlocal provider
        if not pending:
            return
        if provider is None:
            from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

            provider = Wav2VecEvidence("hanziflow", model_path, device=device, threads=2)
        try:
            evidence = provider.evidence_batch([entry[1] for entry in pending])
            if len(evidence) != len(pending):
                raise ValueError("NATIVE_BATCH_SIZE_MISMATCH")
        except (RuntimeError, ValueError) as error:
            for utterance, _, _, _ in pending:
                emit(utterance, None, None, "NATIVE_MODEL_ERROR:" + type(error).__name__)
        else:
            for (utterance, samples, cache_path, cache_meta), result in zip(
                pending, evidence, strict=True
            ):
                native = result["native"]
                _save_native(cache_path, native, cache_meta)
                emit(utterance, samples, native)
        pending.clear()

    for index, utterance in enumerate(selected):
        path = Path(utterance["file"])
        if not path.is_absolute():
            path = utterances.parent / path
        if fingerprint(path) != utterance["sha256"]:
            raise ValueError("OMPAL_PARENT_SHA256_MISMATCH:" + utterance["id"])
        try:
            samples = _read_audio(path)
        except (OSError, ValueError) as error:
            emit(utterance, None, None, "PARENT_AUDIO_INVALID:" + type(error).__name__)
            continue
        cache_meta = {
            **model_identity,
            "parentSha256": utterance["sha256"],
            "samplesSha256": hashlib.sha256(samples.tobytes()).hexdigest(),
        }
        key = hashlib.sha256(json.dumps(cache_meta, sort_keys=True).encode()).hexdigest()
        cache_path = output / "native-cache" / (key + ".npz")
        cached = _load_native(cache_path, cache_meta)
        if cached is not None:
            emit(utterance, samples, cached)
        else:
            pending.append((utterance, samples, cache_path, cache_meta))
            if len(pending) >= batch_size:
                flush()
        if index % 20 == 0:
            print(
                json.dumps(
                    {
                        "utterances": index + 1,
                        "total": len(selected),
                        "wordRows": len(rows),
                        "seconds": time.perf_counter() - started,
                    }
                ),
                flush=True,
            )
    flush()
    order = {
        word["id"]: index
        for index, word in enumerate(word for utterance in selected for word in utterance["words"])
    }
    rows.sort(key=lambda row: order[row["id"]])
    result = {
        "schemaVersion": 1,
        "datasetId": "ompal-word-clips-v1",
        "version": VERSION,
        "license": data.get("license"),
        "citation": data.get("citation"),
        "utterancesManifestSha256": fingerprint(utterances),
        "utterancesManifestPath": str(utterances.resolve()),
        "utterancesConfigSha256": data.get("configSha256"),
        "pipelineSha256": fingerprint(Path(__file__)),
        "alignerSha256": fingerprint(Path(__file__).with_name("pretrained_align.py")),
        "alignmentMapping": mapping,
        "model": model_identity,
        "frozenTestIncluded": include_frozen_test,
        "frozenPlanSha256": fingerprint(frozen_plan) if frozen_plan is not None and plan else None,
        "placeholderPolicy": (
            "250ms silence, explicit placeholder+numerical flags; "
            "retained in all denominators and excluded from training."
        ),
        "boundaryPolicy": (
            "Three independent known-phone CTC paths; union supports; shared midpoint cuts; "
            "40ms context bounded by neighbors; no model-derived correctness."
        ),
        "paddingPolicy": (
            "Short clips zero-padded symmetrically to150ms; original duration/padding logged; "
            "under80ms acoustic content flagged."
        ),
        "counts": {
            "utterances": len(selected),
            "words": len(rows),
            "bySplit": dict(Counter(row["split"] for row in rows)),
            "byExpertLabel": dict(Counter(row.get("expertLabel", "missing") for row in rows)),
            "alignmentUnavailable": sum(row["placeholder"] for row in rows),
            "weakAlignmentWords": sum(
                any(flag.startswith("WEAK_CTC_SUPPORT:") for flag in row["alignmentFlags"])
                for row in rows
            ),
            "numericallyFlagged": sum(bool(row["numericalQualityFlags"]) for row in rows),
            "policyFlagged": sum(bool(row.get("labelPolicyFlags")) for row in rows),
            "padded": sum(
                row["bounds"]["zeroPadLeftSamples"] + row["bounds"]["zeroPadRightSamples"] > 0
                for row in rows
            ),
            "excludedFrozenUtterances": sum(
                utterance["split"] == "test" for utterance in data["utterances"]
            )
            if not include_frozen_test
            else 0,
        },
        "elapsedSeconds": time.perf_counter() - started,
        "items": rows,
    }
    _write(output / "manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utterances", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=ROOT / "models/pinyin-pretrained/hanziflow")
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--include-frozen-test", action="store_true")
    parser.add_argument("--frozen-plan", type=Path)
    args = parser.parse_args()
    result = prepare_clips(
        args.utterances,
        args.output,
        model_path=args.model,
        device=args.device,
        batch_size=args.batch_size,
        include_frozen_test=args.include_frozen_test,
        frozen_plan=args.frozen_plan,
    )
    print(json.dumps(result["counts"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
