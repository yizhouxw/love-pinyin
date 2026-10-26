"""Full-denominator CPU evaluations, frozen acceptance plans and latency runs."""

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import decode_wav, encode_wav
from pinyin_matcher.catalog import CATALOG, ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import read_rows, write
from pinyin_matcher.pretrained_metrics import freeze, metrics
from pinyin_matcher.pretrained_runtime import component_decision, load_matcher, signal_guard

COMPONENTS = ("onset", "rime", "tone")


def compare_targets(row, matcher, result):
    """One encoder run, then all valid, explicitly declared target comparisons."""
    true_tuple = tuple(str(row[k]) for k in COMPONENTS)
    truth = next(
        (t for t in matcher.targets.values() if tuple(str(t[k]) for k in COMPONENTS) == true_tuple),
        None,
    )
    base = {
        "audio_id": row["id"],
        "root_id": row["id"],
        "speaker_id": row["speakerId"],
        "voice_family": row.get("voiceFamilyId"),
        "reference_id": row.get("referenceSourceId"),
        "source": row["source"],
        "source_sha": row["parentSha256"],
        "split": row["split"],
        "clear": not row.get("numericalQualityFlags"),
        "labelProvenance": row["labelProvenance"],
    }
    label = {"unanimous-correct": "positive", "unanimous-error": "negative"}.get(
        row.get("expertLabel", "unanimous-correct"), "ambiguous"
    )
    if row.get("labelPolicyFlags"):
        label = "ambiguous"
    records = [
        {
            **base,
            "id": row["id"] + ":positive",
            "label": label,
            "error_type": "correct",
            "target_id": truth["id"] if truth else "pm-" + row["syllable"],
            "status": result["status"],
            "reason": result.get("reason"),
        }
    ]
    if label != "positive":
        errors = [
            k for k, v in row.get("componentExpertLabels", {}).items() if v == "unanimous-error"
        ]
        if label == "negative":
            records = [
                {
                    **records[0],
                    "id": row["id"] + ":expert_" + k,
                    "error_type": "expert_" + k,
                    "negative_origin": "expert",
                }
                for k in errors or ["unknown"]
            ]
        return records
    evidence = result.get("internalEvidence") or result.get("comparisonEvidence")
    decisions = evidence.get("targetDecisions") if evidence else None
    force_uncertain = bool(evidence and evidence.get("forceUncertain"))
    probabilities = (
        [np.asarray(evidence[k]["probabilities"]) for k in COMPONENTS]
        if evidence and decisions is None
        else None
    )
    seen = set()
    for target in matcher.targets.values():
        alternate = tuple(str(target[k]) for k in COMPONENTS)
        different = [
            i for i, (a, b) in enumerate(zip(true_tuple, alternate, strict=True)) if a != b
        ]
        if len(different) != 1 or alternate in seen:
            continue
        seen.add(alternate)
        status = result["status"]
        if force_uncertain:
            status = "uncertain"
        elif decisions is not None:
            status = decisions.get(target["id"], "uncertain")
        elif probabilities is not None:
            expected = [matcher.metadata["vocabulary"][k].index(str(target[k])) for k in COMPONENTS]
            status = component_decision(probabilities, expected, matcher.metadata["thresholds"])
        elif status in {"matched", "retry"}:
            status = "uncertain"
        records.append(
            {
                **base,
                "id": row["id"] + ":" + target["id"],
                "label": "negative",
                "error_type": COMPONENTS[different[0]],
                "negative_origin": "counterfactual",
                "target_id": target["id"],
                "status": status,
            }
        )
    return records


def evaluate(
    manifest: Path,
    package: Path,
    output: Path,
    *,
    split="calibration",
    frozen_plan: Path | None = None,
):
    if split == "test":
        from pinyin_matcher.pretrained_freeze import verify_test_manifest

        verify_test_manifest(manifest, frozen_plan, package=package)
    rows = [r for r in read_rows(manifest, verify_splits=(split,)) if r["split"] == split]
    matcher = load_matcher(package)
    if matcher.session is None:
        raise ValueError(matcher.problem)
    records, predictions = [], []
    for index, row in enumerate(rows):
        match_options = {"evidence": True}
        if getattr(matcher, "supports_target_comparison_batch", False):
            true_tuple = tuple(str(row[key]) for key in COMPONENTS)
            match_options["comparison_target_ids"] = [
                target["id"]
                for target in matcher.targets.values()
                if sum(
                    str(target[key]) != expected
                    for key, expected in zip(COMPONENTS, true_tuple, strict=True)
                )
                == 1
            ]
        result = matcher.match(
            "pm-" + row["syllable"], Path(row["file"]).read_bytes(), **match_options
        )
        if result.get("reason") == "TARGET_NOT_TRAINED" and matcher.targets:
            alternate = next(iter(matcher.targets))
            comparison = matcher.match(alternate, Path(row["file"]).read_bytes(), **match_options)
            if comparison.get("internalEvidence"):
                result["comparisonEvidence"] = comparison["internalEvidence"]
        if row.get("numericalQualityFlags"):
            result = {**result, "status": "uncertain", "reason": "PREDECLARED_DATA_QUALITY_FLAG"}
            result.pop("internalEvidence", None)
            result.pop("comparisonEvidence", None)
        records.extend(compare_targets(row, matcher, result))
        predictions.append({"id": row["id"], "syllable": row["syllable"], **result})
        if (index + 1) % 50 == 0:
            print(
                json.dumps(
                    {"evaluated": index + 1, "total": len(rows), "model": matcher.metadata["model"]}
                ),
                flush=True,
            )
    report = {
        "schemaVersion": 1,
        "split": split,
        "manifestSha256": fingerprint(manifest),
        "modelSha256": fingerprint(package / "model.json"),
        "rows": len(rows),
        "metrics": metrics(records),
        "records": records,
        "predictions": predictions,
        "frozenPlanSha256": fingerprint(frozen_plan) if frozen_plan else None,
        "labelLimitation": (
            "Corpus readings lack fine phonetic verification; OMPAL uses recorded expert votes "
            "with lexical-policy and missing-word caveats."
        ),
    }
    write(output, report)
    return {k: report[k] for k in ("split", "rows", "manifestSha256", "modelSha256", "metrics")}


def freeze_experiment(manifest: Path, packages: list[Path], output: Path):
    from pinyin_matcher.pretrained_freeze import pipeline_files, protocol_files, verify_plan

    manifest, output = manifest.resolve(), output.resolve()
    packages = [path.resolve() for path in packages]
    if output.exists():
        raise ValueError("FROZEN_PLAN_ALREADY_EXISTS")
    manifest_data = json.loads(manifest.read_text())
    rows = manifest_data["items"]
    if (
        not rows
        or manifest_data.get("frozenTestIncluded")
        or any(r["split"] == "test" for r in rows)
    ):
        raise ValueError("FREEZE_REQUIRES_UNOPENED_TEST_TRAIN_CALIBRATION_MANIFEST")
    # Validate all training/calibration waveform hashes and lineage before
    # recording a plan. This does not open any reserved waveform.
    read_rows(manifest)
    ompal = any(r.get("source") == "ompal-v1" for r in rows)
    source_config = ROOT / (
        "content/pronunciation-ompal-data.json"
        if ompal
        else "content/pronunciation-pretrained-data.json"
    )
    source_data = json.loads(source_config.read_text())
    reserved = source_data["files"] if ompal else source_data["recordings"]
    annotation_inventory, annotation_files = [], []
    if ompal:
        from pinyin_matcher.pretrained_ompal import frozen_annotations

        raw = Path(rows[0]["parentFile"]).parents[2]
        annotation_inventory, annotation_files = frozen_annotations(source_data, raw)
    else:
        from pinyin_matcher.pretrained_data import frozen_annotations

        annotation_inventory, annotation_files = frozen_annotations(
            source_data, manifest.parent / "raw"
        )
    metadata_rows = [
        {
            **{k: v for k, v in r.items() if not (k == "sha256" and r.get("placeholder"))},
            "root_id": r["id"],
        }
        for r in rows
    ]
    metadata_rows += [
        {
            "id": r["speakerId"] + ":reserved-recording",
            "root_id": r["gitBlobSha1"] if ompal else r["wav"]["sha256"],
            "speakerId": r["speakerId"],
            "source": "ompal-v1" if ompal else "mandi-cmn-wl1",
            "parentSha256": ("git-blob-sha1:" + r["gitBlobSha1"]) if ompal else r["wav"]["sha256"],
            "split": "test",
        }
        for r in reserved
        if r.get("split") == "test"
    ]
    package_resources = []
    for package in packages:
        package = package.resolve()
        metadata_path = package / "model.json"
        metadata = json.loads(metadata_path.read_text())
        if (
            metadata.get("manifestSha256") != fingerprint(manifest)
            or metadata.get("testUsed") is not False
        ):
            raise ValueError("MODEL_TRAINING_MANIFEST_NOT_FROZEN")
        if not metadata.get("packageFiles"):
            raise ValueError("FROZEN_MODEL_PACKAGE_FILES_REQUIRED")
        package_resources.append(metadata_path)
        for relative, record in metadata["packageFiles"].items():
            resource = (package / relative).resolve()
            if not resource.is_relative_to(package) or fingerprint(resource) != record["sha256"]:
                raise ValueError("FROZEN_MODEL_PACKAGE_CHANGED")
            package_resources.append(resource)
    plan = freeze(
        metadata_rows,
        files=sorted(
            {
                manifest,
                source_config,
                ROOT / "content/pronunciation-pretrained-models.json",
                ROOT / "content/pronunciation-pretrained-experiment.json",
                CATALOG,
                ROOT / "tools/pinyin-pretrained/uv.lock",
                ROOT / "tools/pinyin-pretrained/pyproject.toml",
                *[
                    path
                    for path in (
                        ROOT / "content/pronunciation-pretrained-pitch.json",
                        ROOT / "resources/licenses/SwiftF0-MIT.txt",
                    )
                    if path.is_file()
                ],
                *annotation_files,
                *protocol_files(),
                *(
                    [
                        ROOT / "content/pronunciation-ompal-policy.json",
                        ROOT / "content/pronunciation-ompal-detail-id-map.json",
                    ]
                    if ompal
                    else []
                ),
            }
        ),
        model_files=package_resources,
        code_files=pipeline_files(),
        config={
            "packages": [str(p.resolve()) for p in packages],
            "sourceConfigPath": str(source_config.resolve()),
            "trainingManifestPath": str(manifest.resolve()),
            "reservedAnnotationInventory": annotation_inventory,
            "thresholdsFrozen": True,
            "testAudioNotOpened": True,
            "testCorpusLabelLimitationAcknowledged": True,
        },
    )
    write(output, plan)
    try:
        verify_plan(output)
    except Exception:
        output.unlink()
        raise
    return plan


def benchmark(
    package: Path, wav: Path, target: str, output: Path, *, repeats=30, exact_four_seconds=False
):
    started = time.perf_counter()
    matcher = load_matcher(package)
    loaded = time.perf_counter()
    if matcher.session is None:
        raise ValueError(matcher.problem)
    if target not in matcher.targets:
        raise ValueError("BENCHMARK_TARGET_UNSUPPORTED")
    samples = decode_wav(wav.read_bytes())
    if exact_four_seconds:
        if len(samples) != 64000:
            raise ValueError("BENCHMARK_REQUIRES_EXACTLY_FOUR_SECONDS")
        four_seconds = samples
        payload = wav.read_bytes()
    else:
        # Length pressure from real speech; not a correctness or child trial.
        active = np.flatnonzero(np.abs(samples) > max(float(np.abs(samples).max()) * 0.03, 0.002))
        if not len(active):
            raise ValueError("BENCHMARK_SPEECH_REQUIRED")
        unit = samples[active[0] : active[-1] + 1]
        four_seconds = np.resize(unit, 64000)
        payload = encode_wav(four_seconds)
    reason = signal_guard(four_seconds)
    if reason:
        raise ValueError("BENCHMARK_WOULD_SKIP_ENCODER: " + reason)
    first_start = time.perf_counter()
    first = matcher.match(target, payload, evidence=True)
    if "internalEvidence" not in first:
        raise ValueError("BENCHMARK_DID_NOT_EXECUTE_ENCODER")
    first_ms = (time.perf_counter() - first_start) * 1000
    for _ in range(3):
        matcher.match(target, payload)
    timings = []
    statuses = []
    for _ in range(repeats):
        t = time.perf_counter()
        result = matcher.match(target, payload)
        if "elapsedMilliseconds" not in result or result["status"] == "unavailable":
            raise ValueError("BENCHMARK_TIMED_RUN_SKIPPED_ENCODER")
        timings.append((time.perf_counter() - t) * 1000)
        statuses.append(result["status"])
    p95 = float(np.percentile(timings, 95))
    report = {
        "schemaVersion": 1,
        "device": "Mac Studio M2 Ultra CPU",
        "threads": 2,
        "sourceWavSha256": fingerprint(wav),
        "pressurePayloadSha256": hashlib.sha256(payload).hexdigest(),
        "pressureMethod": (
            "supplied-exact-four-seconds" if exact_four_seconds else "crop-and-repeat"
        ),
        "pythonModulesAlreadyImportedAtLoadStart": True,
        "modelLoadMilliseconds": (loaded - started) * 1000,
        "firstInferenceMilliseconds": first_ms,
        "firstStatus": first["status"],
        "encoderActuallyExecuted": "internalEvidence" in first,
        "fourSecondWarmP95Milliseconds": p95,
        "realTimeFactor": p95 / 4000,
        "repeats": repeats,
        "warmupRuns": 3,
        "timingsMilliseconds": timings,
        "statuses": statuses,
        "peakRssMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2,
        "packageBytes": matcher.metadata.get("packageBytes"),
        "passedLatency": p95 <= 500 and p95 / 4000 <= 0.1,
        "passedMemory": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= 3 * 1024**3,
        "modelSha256": fingerprint(package / "model.json"),
        "scope": (
            "WAV decode, guards, features, encoder, heads and target comparison; no HTTP/LAN."
        ),
    }
    write(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--manifest", type=Path, required=True)
    evaluate_parser.add_argument("--model", type=Path, required=True)
    evaluate_parser.add_argument(
        "--split", choices=["calibration", "test", "diagnostic"], default="calibration"
    )
    evaluate_parser.add_argument("--freeze", type=Path)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--manifest", type=Path, required=True)
    freeze_parser.add_argument("--model", type=Path, action="append", required=True)
    freeze_parser.add_argument("--output", type=Path, required=True)
    bench_parser = sub.add_parser("benchmark")
    bench_parser.add_argument("--model", type=Path, required=True)
    bench_parser.add_argument("--wav", type=Path, required=True)
    bench_parser.add_argument("--target", required=True)
    bench_parser.add_argument("--output", type=Path, required=True)
    bench_parser.add_argument("--exact-four-seconds", action="store_true")
    args = parser.parse_args()
    if args.action == "evaluate":
        result = evaluate(
            args.manifest, args.model, args.output, split=args.split, frozen_plan=args.freeze
        )
    elif args.action == "freeze":
        result = freeze_experiment(args.manifest, args.model, args.output)
    else:
        result = benchmark(
            args.model,
            args.wav,
            args.target,
            args.output,
            exact_four_seconds=args.exact_four_seconds,
        )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
