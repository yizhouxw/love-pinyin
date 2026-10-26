"""Run the preserved original matcher without importing the current matcher tree.

The source revision, original model and old TTS diagnostic cohort are pinned.
ManDi/OMPAL input manifests are calibration-only; frozen test audio is not read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BASELINE_REVISION = "335a09d2782891c2858b8e248c471793ada14ecc"
MODEL_METADATA_SHA256 = "3f3e7816d7ce6267a78a8bff694e13956e38744913743e192ec9232b500f0ced"
ORIGINAL_TTS_SHA256 = "d4163d8e3b090ec1219b5bbe2e9c3b3f9dac0499150820d3935c7311e0986e7c"
WEIGHT_SHA256 = {
    "acoustic.int8.onnx": "f3516ad9f833934f2f8875c2145bd8b87edb4d207bc938ac6c4e97881acf2f81",
    "pitch.onnx": "cb1d2ec33fc6ea4a3e7fe279bfec03a8e7939d1152483feb93a1a18cb51805aa",
}


def fingerprint(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_snapshot(repository: Path, snapshot: Path) -> dict:
    """Compare archived Python/content bytes directly with the fixed Git commit."""
    resolved = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", BASELINE_REVISION],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if resolved != BASELINE_REVISION:
        raise ValueError("PRESERVED_BASELINE_REVISION_MISMATCH")
    paths = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "ls-tree",
            "-r",
            "--name-only",
            BASELINE_REVISION,
            "pinyin_matcher",
            "content/pronunciation-targets.json",
            "content/pronunciation-rules.json",
            "content/pronunciation-training.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    records = {}
    for relative in paths:
        if not relative.endswith((".py", ".json")):
            continue
        expected = subprocess.run(
            ["git", "-C", str(repository), "show", f"{BASELINE_REVISION}:{relative}"],
            check=True,
            capture_output=True,
        ).stdout
        actual = snapshot / relative
        digest = hashlib.sha256(expected).hexdigest()
        if not actual.is_file() or fingerprint(actual) != digest:
            raise ValueError("PRESERVED_BASELINE_SOURCE_MISMATCH:" + relative)
        records[relative] = digest
    if "pinyin_matcher/inference.py" not in records:
        raise ValueError("PRESERVED_BASELINE_INFERENCE_MISSING")
    return records


def assert_import_roots(snapshot: Path) -> dict:
    paths = {}
    for name, module in list(sys.modules.items()):
        if name == "pinyin_matcher" or name.startswith("pinyin_matcher."):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(snapshot.resolve()):
                raise ValueError("CURRENT_MATCHER_IMPORT_FORBIDDEN:" + name)
            paths[name] = str(path)
    return paths


def wilson(count: int, denominator: int) -> dict:
    if not denominator:
        return {"count": count, "denominator": 0, "rate": None, "wilson95": None}
    z = 1.959963984540054
    rate = count / denominator
    center = (rate + z * z / (2 * denominator)) / (1 + z * z / denominator)
    half = (
        z
        * math.sqrt(rate * (1 - rate) / denominator + z * z / (4 * denominator**2))
        / (1 + z * z / denominator)
    )
    return {
        "count": count,
        "denominator": denominator,
        "rate": rate,
        "wilson95": [center - half, center + half],
    }


def summarize(rows: list[dict]) -> dict:
    positive = [r for r in rows if r["expectedMatch"] is True]
    negative = [r for r in rows if r["expectedMatch"] is False]
    unclear = [r for r in rows if r["expectedMatch"] is None]
    return {
        "rows": len(rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "positiveRows": len(positive),
        "positiveStatuses": dict(Counter(r["status"] for r in positive)),
        "negativeRows": len(negative),
        "negativeStatuses": dict(Counter(r["status"] for r in negative)),
        "unassessableRows": len(unclear),
        "unassessableStatuses": dict(Counter(r["status"] for r in unclear)),
        "positiveAcceptance": wilson(
            sum(r["status"] == "matched" for r in positive), len(positive)
        ),
        "positiveExplicitRejection": wilson(
            sum(r["status"] == "retry" for r in positive), len(positive)
        ),
        "positiveAbstentionIncludingUnavailable": wilson(
            sum(r["status"] in {"uncertain", "unavailable"} for r in positive), len(positive)
        ),
        "negativeFalseAcceptance": wilson(
            sum(r["status"] == "matched" for r in negative), len(negative)
        ),
        "reasons": dict(Counter(r["reason"] for r in rows if r["reason"])),
    }


def run(args) -> dict:
    started = time.perf_counter()
    if args.output.exists():
        raise ValueError("PRESERVED_BASELINE_OUTPUT_ALREADY_EXISTS")
    source_files = verify_snapshot(args.repository_root, args.snapshot)
    if fingerprint(args.model / "model.json") != MODEL_METADATA_SHA256:
        raise ValueError("PRESERVED_ORIGINAL_MODEL_METADATA_MISMATCH")
    for name, expected in WEIGHT_SHA256.items():
        if fingerprint(args.model / name) != expected:
            raise ValueError("PRESERVED_ORIGINAL_WEIGHT_MISMATCH:" + name)
    if fingerprint(args.tts_manifest) != ORIGINAL_TTS_SHA256:
        raise ValueError("PRESERVED_ORIGINAL_TTS_DIAGNOSTIC_MANIFEST_MISMATCH")
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "2"
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
    os.chdir(args.snapshot)
    sys.path.insert(0, str(args.snapshot))
    import numpy as np
    import onnxruntime as ort

    from pinyin_matcher.audio import decode_wav, encode_wav
    from pinyin_matcher.inference import PinyinMatcher

    imported = assert_import_roots(args.snapshot)
    load_started = time.perf_counter()
    matcher = PinyinMatcher(args.model, threads=2)
    load_ms = (time.perf_counter() - load_started) * 1000
    if matcher.session is None or matcher.session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("PRESERVED_BASELINE_CPU_LOAD_FAILED:" + matcher.problem)
    metadata = json.loads((args.model / "model.json").read_text())
    covered = set(metadata["coveredTargetIds"])
    catalog = json.loads((args.model / "targets.json").read_text())
    target_map = {}
    for target in catalog["targets"]:
        if target["form"] == "whole-syllable":
            key = tuple(str(target[k]) for k in ("onset", "rime", "tone"))
            if key not in target_map or target["id"] in covered:
                target_map[key] = target["id"]
    mandi = json.loads(args.mandi_manifest.read_text())
    if mandi.get("frozenTestIncluded"):
        raise ValueError("PRESERVED_BASELINE_CALIBRATION_MUST_NOT_OPEN_FROZEN_TEST_MANIFEST")
    if args.pressure_wav:
        payload = args.pressure_wav.read_bytes()
        if (
            hashlib.sha256(payload).hexdigest() != args.pressure_sha256
            or len(decode_wav(payload)) != 64000
        ):
            raise ValueError("PRESERVED_BASELINE_PRESSURE_BYTES_OR_DURATION_MISMATCH")
        pressure_row = {"id": str(args.pressure_wav), "sha256": args.pressure_sha256}
        pressure_method = "supplied-exact-four-seconds; same bytes as all pretrained candidates"
    else:
        pressure_row = next(
            r
            for r in mandi["items"]
            if r["split"] == "calibration" and r["speakerId"] == "CHD_012_F"
        )
        path = Path(pressure_row["file"])
        if not path.is_absolute():
            path = args.mandi_manifest.parent / path
        unit = decode_wav(path.read_bytes())
        payload = encode_wav(np.resize(unit, 64000))
        pressure_method = "numpy.resize(CHD_012_F first calibration word,64000)+PCM16WAVencode"
    begin = time.perf_counter()
    first = matcher.match("pm-ba1", payload, include_evidence=True)
    first_ms = (time.perf_counter() - begin) * 1000
    if "candidateId" not in first:
        raise ValueError("PRESERVED_BASELINE_BENCHMARK_SKIPPED_ENCODER")
    startup_ms = (time.perf_counter() - started) * 1000
    for _ in range(0 if args.cold_only else 3):
        matcher.match("pm-ba1", payload)
    timings, statuses = [], []
    for _ in range(0 if args.cold_only else 30):
        begin = time.perf_counter()
        result = matcher.match("pm-ba1", payload)
        timings.append((time.perf_counter() - begin) * 1000)
        statuses.append(result["status"])
    benchmark = {
        "device": "Mac Studio M2 Ultra CPU",
        "threads": 2,
        "provider": "CPUExecutionProvider",
        "modelLoadMilliseconds": load_ms,
        "pythonModulesAlreadyImportedAtLoadStart": True,
        "firstInferenceMilliseconds": first_ms,
        "sourceVerificationAndImportsToFirstResultMilliseconds": startup_ms,
        "firstStatus": first["status"],
        "encoderActuallyExecuted": "candidateId" in first,
        "pressureSourceId": pressure_row["id"],
        "pressureSourceSha256": pressure_row["sha256"],
        "pressurePayloadSha256": hashlib.sha256(payload).hexdigest(),
        "pressureMethod": pressure_method,
        "warmupRuns": 0 if args.cold_only else 3,
        "repeats": len(timings),
        "timingsMilliseconds": timings,
        "statuses": statuses,
        "fourSecondWarmP95Milliseconds": float(np.percentile(timings, 95)) if timings else None,
        "realTimeFactor": float(np.percentile(timings, 95)) / 4000 if timings else None,
        "peakRssMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if sys.platform == "darwin" else 1024),
        "memoryScope": (
            "matcher plus small ManDi pressure-source metadata; "
            "before OMPAL evaluation metadata is loaded"
        ),
        "weightBytes": sum((args.model / name).stat().st_size for name in WEIGHT_SHA256),
        "timingIncludes": (
            "WAV decode, acoustic/pitch features, both ONNX models and target/candidate comparison"
        ),
        "simultaneousSystemLoadNotControlled": True,
    }
    sources, predictions = {}, []
    cohorts = (
        ()
        if args.benchmark_only
        else (
            ("original-tts-diagnostic", args.tts_manifest, "test"),
            ("mandi-calibration", args.mandi_manifest, "calibration"),
            ("ompal-calibration", args.ompal_manifest, "calibration"),
        )
    )
    for cohort, manifest, split in cohorts:
        data = json.loads(manifest.read_text())
        if cohort != "original-tts-diagnostic" and data.get("frozenTestIncluded"):
            raise ValueError("PRESERVED_BASELINE_CALIBRATION_MUST_NOT_OPEN_FROZEN_TEST_MANIFEST")
        rows = [r for r in data["items"] if r["split"] == split]
        sources[cohort] = {
            "manifest": str(manifest),
            "sha256": fingerprint(manifest),
            "rows": len(rows),
            "split": split,
        }
        for row in rows:
            if cohort == "original-tts-diagnostic":
                target, expected, scope = row["targetId"], True, "tts-intended-positive-diagnostic"
            else:
                key = tuple(str(row[k]) for k in ("onset", "rime", "tone"))
                target = target_map.get(
                    key,
                    "pm-" + str(row.get("syllable") or row.get("expectedPinyin")).replace("ü", "v"),
                )
                expected, scope = True, "corpus-intended-adult-positive-diagnostic"
                if cohort == "ompal-calibration":
                    if row.get("labelPolicyFlags") or row["expertLabel"] == "ambiguous":
                        expected, scope = None, "unassessable-policy-or-expert-disagreement"
                    elif row["expertLabel"] == "unanimous-correct":
                        expected, scope = True, "expert-unanimous-positive"
                    elif row["expertLabel"] == "unanimous-error":
                        expected, scope = False, "expert-any-component-unanimous-error"
                    else:
                        expected, scope = None, "unassessable-expert-status"
            audio_file = Path(row["file"])
            if not audio_file.is_absolute():
                audio_file = manifest.parent / audio_file
            audio = audio_file.read_bytes()
            if hashlib.sha256(audio).hexdigest() != row["sha256"]:
                raise ValueError("PRESERVED_BASELINE_INPUT_SHA256_MISMATCH:" + row["id"])
            result = matcher.match(target, audio)
            predictions.append(
                {
                    "id": row["id"],
                    "source": cohort,
                    "speakerId": row.get("speakerId", row.get("voiceFamilyId")),
                    "targetId": target,
                    "withinOriginalCoverage": target in covered,
                    "expectedMatch": expected,
                    "truthScope": scope,
                    "expertLabel": row.get("expertLabel"),
                    "policyFlags": row.get("labelPolicyFlags", []),
                    "numericalQualityFlags": row.get("numericalQualityFlags", []),
                    "status": result["status"],
                    "reason": result.get("reason"),
                }
            )
        print(json.dumps({"baselineSourceEvaluated": cohort, "rows": len(rows)}), flush=True)
    assert_import_roots(args.snapshot)
    report = {
        "schemaVersion": 2,
        "benchmarkOnly": args.benchmark_only,
        "coldOnly": args.cold_only,
        "baseline": "original-preserved-synthetic-32-targets",
        "implementationRevision": BASELINE_REVISION,
        "runnerSha256": fingerprint(Path(__file__).resolve()),
        "archivedImplementation": str(args.snapshot),
        "importedImplementationModules": imported,
        "sourceFileSha256": source_files,
        "package": str(args.model),
        "packageMetadataSha256": MODEL_METADATA_SHA256,
        "weights": WEIGHT_SHA256,
        "coveredTargetIds": sorted(covered),
        "coverageTargets": len(covered),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "onnxruntime": ort.__version__,
            "executable": sys.executable,
        },
        "benchmark": benchmark,
        "evaluationProcessPeakRssMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if sys.platform == "darwin" else 1024),
        "sources": sources,
        "allSources": summarize(predictions),
        "bySource": {
            cohort: {
                "fullDenominator": summarize([r for r in predictions if r["source"] == cohort]),
                "commonOriginalCoverage": summarize(
                    [
                        r
                        for r in predictions
                        if r["source"] == cohort and r["withinOriginalCoverage"]
                    ]
                ),
                "outsideOriginalCoverage": summarize(
                    [
                        r
                        for r in predictions
                        if r["source"] == cohort and not r["withinOriginalCoverage"]
                    ]
                ),
            }
            for cohort in sources
        },
        "limitations": [
            "All inputs here are historical diagnostics or calibration, never frozen test.",
            "TTS labels are intended readings; ManDi annotation-order risk remains.",
            "Policy/expert ambiguous OMPAL words remain unassessable in full counts.",
            "Original baseline decisions are unchanged; new-model guards are not substituted.",
            "Canonical known-error target checks are not exhaustive all-neighbor evaluation.",
            "Wilson intervals do not remove speaker correlation or establish child accuracy.",
        ],
        "predictions": predictions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "repository-root",
        "snapshot",
        "model",
        "mandi-manifest",
        "ompal-manifest",
        "tts-manifest",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--benchmark-only", action="store_true")
    parser.add_argument("--cold-only", action="store_true")
    parser.add_argument("--pressure-wav", type=Path)
    parser.add_argument("--pressure-sha256")
    args = parser.parse_args()
    if bool(args.pressure_wav) != bool(args.pressure_sha256):
        parser.error("--pressure-wav and --pressure-sha256 must be supplied together")
    if args.benchmark_only and not args.pressure_wav:
        parser.error("--benchmark-only requires explicit --pressure-wav")
    if args.cold_only and not args.benchmark_only:
        parser.error("--cold-only requires --benchmark-only")
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    data = run(args)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(data["predictions"]),
                "p95Milliseconds": data["benchmark"]["fourSecondWarmP95Milliseconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
