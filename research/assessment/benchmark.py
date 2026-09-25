"""Aggregate blinded PoC predictions against adjudicated labels.

Recordings are read only from --audio-dir as <sampleId>.wav, hashed, and never
copied to the output. This evaluator cannot train/calibrate an engine or create
predictions. A metrics pass is not sufficient for product scoring acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import sys
import tempfile
import wave
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = "poc-evaluator-0.4.0"
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260926
CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "curriculum.json"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
LABELS = {"correct", "incorrect", "uncertain"}
PREDICTIONS = {"pass", "retry", "uncertain"}
CLASSES = {"initial", "final", "whole-syllable", "tone", "syllable", "orthographic-letter"}
CHALLENGES = {"speech", "silence", "too-short", "noise", "speaker-replay", "near-neighbor"}
SPLITS = {"development", "calibration", "test"}
MAX_WAV_BYTES = 512 * 1024
MAX_FRAMES = 16000 * 10


class ManifestError(ValueError):
    """Input data is incomplete, inconsistent, unsafe or unauthorized."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON input: {path.name}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def wilson(successes: int, total: int) -> dict[str, float | int | None]:
    if total == 0:
        return {"numerator": successes, "denominator": total, "rate": None, "ci95": None}
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "numerator": successes,
        "denominator": total,
        "rate": p,
        "ci95": [max(0.0, center - margin), min(1.0, center + margin)],
    }


def cohen_kappa(pairs: list[tuple[str, str]]) -> dict[str, float | int | None]:
    n = len(pairs)
    if not n:
        return {"n": 0, "observedAgreement": None, "kappa": None}
    labels = sorted(LABELS)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum(left[label] * right[label] for label in labels) / (n * n)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    return {"n": n, "observedAgreement": observed, "kappa": kappa}


def _check_manifest(manifest: Any, allowed_target_ids: set[str]) -> list[dict[str, Any]]:
    _require(
        isinstance(manifest, dict) and manifest.get("schemaVersion") == 2,
        "manifest schemaVersion must be 2",
    )
    _require(
        set(manifest) == {"schemaVersion", "datasetId", "contentVersion", "items"},
        "manifest has unsupported fields",
    )
    _require(
        bool(re.fullmatch(r"[A-Za-z0-9_-]{3,64}", str(manifest.get("datasetId", "")))),
        "datasetId is invalid",
    )
    items = manifest.get("items")
    _require(isinstance(items, list) and items, "manifest items must be a non-empty list")
    ids: set[str] = set()
    speaker_splits: dict[str, set[str]] = defaultdict(set)
    required = {
        "sampleId",
        "speakerGroupId",
        "cohort",
        "targetId",
        "targetClass",
        "deviceClass",
        "environmentClass",
        "challengeClass",
        "split",
        "annotations",
        "adjudicatedLabel",
        "adjudicatorRef",
        "consentRef",
        "sha256",
    }
    for item in items:
        _require(isinstance(item, dict), "each manifest item must be an object")
        _require(
            set(item) == required,
            "manifest item is missing a required field or has an unsupported field",
        )
        sample_id, speaker_id = item.get("sampleId"), item.get("speakerGroupId")
        _require(
            isinstance(sample_id, str) and ID_PATTERN.fullmatch(sample_id) is not None,
            "sampleId must be opaque and path-safe",
        )
        _require(
            isinstance(speaker_id, str) and ID_PATTERN.fullmatch(speaker_id) is not None,
            "speakerGroupId must be opaque",
        )
        _require(sample_id not in ids, "sampleId values must be unique")
        ids.add(sample_id)
        _require(
            isinstance(item.get("cohort"), str)
            and item["cohort"] in {"target-age-child", "adult-development"},
            f"invalid cohort for {sample_id}",
        )
        _require(item.get("targetClass") in CLASSES, f"invalid targetClass for {sample_id}")
        _require(
            item.get("challengeClass") in CHALLENGES, f"invalid challengeClass for {sample_id}"
        )
        _require(item.get("split") in SPLITS, f"invalid split for {sample_id}")
        _require(
            item.get("adjudicatedLabel") in LABELS, f"invalid adjudicatedLabel for {sample_id}"
        )
        annotations = item.get("annotations")
        _require(
            isinstance(annotations, list)
            and len(annotations) == 2
            and all(
                isinstance(annotation, dict)
                and set(annotation) == {"reviewerRef", "label"}
                and isinstance(annotation["reviewerRef"], str)
                and ID_PATTERN.fullmatch(annotation["reviewerRef"]) is not None
                and annotation["label"] in LABELS
                for annotation in annotations
            ),
            f"two valid independent annotations required for {sample_id}",
        )
        reviewer_refs = [annotation["reviewerRef"] for annotation in annotations]
        _require(
            reviewer_refs[0] != reviewer_refs[1],
            f"two distinct reviewers required for {sample_id}",
        )
        _require(
            isinstance(item.get("consentRef"), str)
            and ID_PATTERN.fullmatch(item["consentRef"]) is not None,
            f"opaque consentRef required for {sample_id}",
        )
        adjudicator = item["adjudicatorRef"]
        if annotations[0]["label"] == annotations[1]["label"]:
            _require(
                item["adjudicatedLabel"] == annotations[0]["label"] and adjudicator is None,
                f"consensus labels must be retained without third-party adjudication: {sample_id}",
            )
        else:
            _require(
                isinstance(adjudicator, str)
                and ID_PATTERN.fullmatch(adjudicator) is not None
                and adjudicator not in reviewer_refs,
                f"disagreement requires a distinct opaque third adjudicator: {sample_id}",
            )
        _require(
            re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", ""))) is not None,
            f"valid SHA-256 required for {sample_id}",
        )
        _require(
            item["deviceClass"]
            in {"mac-built-in", "wired-headset", "bluetooth-headset", "tablet", "phone", "other"},
            f"invalid deviceClass for {sample_id}",
        )
        _require(
            item["environmentClass"] in {"quiet", "ordinary", "noisy"},
            f"invalid environmentClass for {sample_id}",
        )
        _require(
            isinstance(item["targetId"], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item["targetId"]) is not None,
            f"invalid targetId for {sample_id}",
        )
        _require(
            item["targetId"] == "challenge" or item["targetId"] in allowed_target_ids,
            f"targetId is not in the project curriculum: {sample_id}",
        )
        speaker_splits[speaker_id].add(item["split"])
        if item["challengeClass"] in {"silence", "too-short", "noise", "speaker-replay"}:
            _require(
                item["adjudicatedLabel"] == "uncertain",
                f"challenge sample must be adjudicated uncertain: {sample_id}",
            )
            _require(
                item["targetId"] == "challenge" and item["targetClass"] == "syllable",
                f"challenge sample must use the challenge target and syllable class: {sample_id}",
            )
        else:
            _require(
                item["targetId"] != "challenge",
                f"speech sample cannot use the challenge target: {sample_id}",
            )
            if item["challengeClass"] == "near-neighbor":
                _require(
                    item["adjudicatedLabel"] == "incorrect",
                    f"near-neighbor sample must be adjudicated incorrect: {sample_id}",
                )
    _require(
        all(len(splits) == 1 for splits in speaker_splits.values()),
        "speakerGroupId leakage across development/calibration/test splits",
    )
    return items


def _verify_audio(audio_dir: Path, items: list[dict[str, Any]]) -> None:
    root = audio_dir.resolve(strict=True)
    for item in items:
        source = root / f"{item['sampleId']}.wav"
        _require(
            not source.is_symlink(),
            f"symlinks are not accepted in the private audio directory: {item['sampleId']}",
        )
        resolved = source.resolve(strict=True)
        _require(
            resolved.parent == root,
            f"audio escaped the private audio directory: {item['sampleId']}",
        )
        _require(
            resolved.stat().st_size <= MAX_WAV_BYTES, f"audio exceeds 512 KiB: {item['sampleId']}"
        )
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        _require(digest == item["sha256"], f"SHA-256 mismatch: {item['sampleId']}")
        try:
            with wave.open(os.fspath(resolved), "rb") as wav:
                _require(wav.getnchannels() == 1, f"audio must be mono: {item['sampleId']}")
                _require(wav.getsampwidth() == 2, f"audio must be PCM16: {item['sampleId']}")
                _require(wav.getframerate() == 16000, f"audio must be 16 kHz: {item['sampleId']}")
                _require(
                    0 < wav.getnframes() <= MAX_FRAMES,
                    f"audio must be 0-10 seconds: {item['sampleId']}",
                )
        except (wave.Error, EOFError) as exc:
            raise ManifestError(f"invalid PCM WAV: {item['sampleId']}") from exc


def _check_predictions(
    predictions: Any, test_items: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    _require(
        isinstance(predictions, dict) and predictions.get("schemaVersion") == 1,
        "prediction schemaVersion must be 1",
    )
    _require(
        set(predictions)
        == {
            "schemaVersion",
            "datasetId",
            "contentVersion",
            "split",
            "engineId",
            "engineVersion",
            "items",
        },
        "predictions have unsupported fields",
    )
    _require(
        isinstance(predictions.get("engineId"), str) and predictions["engineId"],
        "engineId required",
    )
    _require(
        isinstance(predictions.get("engineVersion"), str) and predictions["engineVersion"],
        "engineVersion required",
    )
    rows = predictions.get("items")
    _require(isinstance(rows, list), "predictions items must be a list")
    allowed = {item["sampleId"] for item in test_items}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        _require(
            isinstance(row, dict) and set(row) <= {"sampleId", "status"},
            "prediction rows may contain only sampleId and status",
        )
        sample_id = row.get("sampleId")
        _require(sample_id in allowed, "predictions may include test split rows only")
        _require(sample_id not in result, f"duplicate prediction: {sample_id}")
        _require(
            isinstance(row.get("status"), str) and row["status"] in PREDICTIONS,
            f"invalid prediction status for {sample_id}",
        )
        result[sample_id] = row
    _require(set(result) == allowed, "every test sample must have exactly one prediction")
    return result


def _metric_counts(
    items: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]
) -> dict[str, tuple[int, int]]:
    clear = [item for item in items if item["adjudicatedLabel"] in {"correct", "incorrect"}]
    correct = [item for item in clear if item["adjudicatedLabel"] == "correct"]
    incorrect = [item for item in clear if item["adjudicatedLabel"] == "incorrect"]
    decisions = {item["sampleId"]: predictions[item["sampleId"]]["status"] for item in items}
    # Uncertain predictions remain in the accuracy denominator as incorrect.
    counts = {
        "clearSampleAccuracy": (
            sum(
                decisions[item["sampleId"]] != "uncertain"
                and (decisions[item["sampleId"]] == "pass")
                == (item["adjudicatedLabel"] == "correct")
                for item in clear
            ),
            len(clear),
        ),
        "falsePassOnIncorrect": (
            sum(decisions[item["sampleId"]] == "pass" for item in incorrect),
            len(incorrect),
        ),
        "falseRetryOnCorrect": (
            sum(decisions[item["sampleId"]] == "retry" for item in correct),
            len(correct),
        ),
        "uncertainOnClearSpeech": (
            sum(decisions[item["sampleId"]] == "uncertain" for item in clear),
            len(clear),
        ),
    }
    for challenge in ("silence", "too-short", "noise", "speaker-replay"):
        rows = [item for item in items if item["challengeClass"] == challenge]
        counts[f"challengeRejection:{challenge}"] = (
            sum(decisions[item["sampleId"]] == "uncertain" for item in rows),
            len(rows),
        )
    return counts


def _percentile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _speaker_cluster_interval(
    items: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    metric: str,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    groups = _group_speakers(items)
    eligible = []
    for _, group in sorted(groups.items()):
        counts = _metric_counts(group, predictions)[metric]
        if counts[1] > 0:
            eligible.append(counts)
    if len(eligible) < 2:
        return {
            "method": "speaker-cluster percentile bootstrap",
            "ci95": None,
            "speakerClusters": len(eligible),
            "replicates": 0,
            "reason": "at least two eligible speaker clusters are required",
        }
    rng = random.Random(seed)
    estimates = []
    for _ in range(replicates):
        selected = [rng.randrange(len(eligible)) for _ in eligible]
        numerator = sum(eligible[index][0] for index in selected)
        denominator = sum(eligible[index][1] for index in selected)
        if denominator:
            estimates.append(numerator / denominator)
    estimates.sort()
    if len(estimates) < replicates * 0.95:
        return {
            "method": "speaker-cluster percentile bootstrap",
            "ci95": None,
            "speakerClusters": len(eligible),
            "replicates": len(estimates),
            "reason": "too many resamples had an empty metric denominator",
        }
    return {
        "method": "speaker-cluster percentile bootstrap",
        "ci95": [
            _percentile(estimates, 0.025),
            _percentile(estimates, 0.975),
        ],
        "speakerClusters": len(eligible),
        "replicates": len(estimates),
    }


def _rates(items: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts = _metric_counts(items, predictions)
    metrics = {}
    for name, (numerator, denominator) in counts.items():
        sample_interval = wilson(numerator, denominator)
        metrics[name] = {
            "numerator": numerator,
            "denominator": denominator,
            "rate": sample_interval["rate"],
            "sampleWilsonCi95": sample_interval["ci95"],
            "speakerClusterCi95": _speaker_cluster_interval(items, predictions, name),
        }
    challenge = {
        name.partition(":")[2]: metrics.pop(name)
        for name in list(metrics)
        if name.startswith("challengeRejection:")
    }
    return {**metrics, "challengeRejection": challenge}


def _grouped(
    items: list[dict[str, Any]], predictions: dict[str, dict[str, Any]], field: str
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[item[field]].append(item)
    return {key: _rates(group, predictions) for key, group in sorted(groups.items())}


def evaluate(manifest: Any, predictions: Any, audio_dir: Path) -> dict[str, Any]:
    _require(isinstance(manifest, dict), "manifest root must be an object")
    _require(isinstance(predictions, dict), "predictions root must be an object")
    try:
        content = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError("project curriculum content is unavailable or invalid") from exc
    _require(
        manifest.get("contentVersion") == content.get("contentVersion"),
        "manifest contentVersion does not match the checked-in curriculum",
    )
    allowed_target_ids = {item["id"] for item in content["readingTargets"]}
    items = _check_manifest(manifest, allowed_target_ids)
    _require(
        predictions.get("datasetId") == manifest["datasetId"],
        "predictions belong to a different dataset",
    )
    _require(
        predictions.get("contentVersion") == manifest["contentVersion"],
        "predictions belong to a different content version",
    )
    _require(
        predictions.get("split") == "test", "only a held-out test prediction file may be evaluated"
    )
    _verify_audio(audio_dir, items)
    test_items = [item for item in items if item["split"] == "test"]
    _require(test_items, "manifest must include a held-out test split")
    predicted = _check_predictions(predictions, test_items)
    target_children = {
        item["speakerGroupId"] for item in test_items if item["cohort"] == "target-age-child"
    }
    rates = _rates(test_items, predicted)
    child_test_items = [item for item in test_items if item["cohort"] == "target-age-child"]
    child_rates = _rates(child_test_items, predicted)
    overall_children = {
        item["speakerGroupId"] for item in items if item["cohort"] == "target-age-child"
    }
    classifier_rates = [
        child_rates["clearSampleAccuracy"]["rate"],
        child_rates["falsePassOnIncorrect"]["rate"],
        child_rates["falseRetryOnCorrect"]["rate"],
        child_rates["uncertainOnClearSpeech"]["rate"],
        child_rates["challengeRejection"]["silence"]["rate"],
        child_rates["challengeRejection"]["noise"]["rate"],
    ]
    gates = {
        "clearSampleAccuracyAtLeast90Percent": classifier_rates[0] is not None
        and classifier_rates[0] >= 0.90,
        "falsePassAtMost5Percent": classifier_rates[1] is not None and classifier_rates[1] <= 0.05,
        "falseRetryAtMost10Percent": classifier_rates[2] is not None
        and classifier_rates[2] <= 0.10,
        "uncertainAtMost20Percent": classifier_rates[3] is not None and classifier_rates[3] <= 0.20,
        "silenceRejectionAtLeast95Percent": classifier_rates[4] is not None
        and classifier_rates[4] >= 0.95,
        "noiseRejectionAtLeast95Percent": classifier_rates[5] is not None
        and classifier_rates[5] >= 0.95,
        "atLeast30HeldOutTargetAgeSpeakers": len(target_children) >= 30,
        "atLeast600AdjudicatedSamples": len(items) >= 600,
    }
    labels = [
        tuple(annotation["label"] for annotation in item["annotations"]) for item in test_items
    ]
    return {
        "reportVersion": VERSION,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "dataset": {
            "datasetId": manifest["datasetId"],
            "contentVersion": manifest["contentVersion"],
            "totalManifestSamples": len(items),
            "totalTargetAgeSpeakers": len(overall_children),
            "testSamples": len(test_items),
            "testTargetAgeSpeakers": len(target_children),
            "speakerHoldoutValid": True,
        },
        "engine": {
            "engineId": predictions["engineId"],
            "engineVersion": predictions["engineVersion"],
        },
        "confidenceIntervals": {
            "primary": "speaker-cluster percentile bootstrap, 95%, 2000 resamples",
            "seed": BOOTSTRAP_SEED,
            "sampleWilsonCi95": (
                "descriptive row-level interval only; repeated samples per speaker are correlated"
            ),
            "insufficientClusters": "cluster interval is null when fewer than 2 eligible speakers",
        },
        "testMetrics": rates,
        "targetAgeChildTestMetrics": child_rates,
        "annotationAgreement": cohen_kappa(labels),
        "byTargetClass": _grouped(test_items, predicted, "targetClass"),
        # Target IDs map to curriculum items, not people. Per-target reporting
        # prevents a weak syllable/tone target from disappearing in class means.
        "byTargetId": _grouped(test_items, predicted, "targetId"),
        "byChallengeClass": _grouped(test_items, predicted, "challengeClass"),
        "byDeviceClass": _grouped(test_items, predicted, "deviceClass"),
        "byEnvironmentClass": _grouped(test_items, predicted, "environmentClass"),
        "byCohort": _grouped(test_items, predicted, "cohort"),
        "speakerDistribution": {
            "perSpeakerClearAccuracy": sorted(
                _rates(group, predicted)["clearSampleAccuracy"]["rate"]
                for speaker, group in _group_speakers(test_items).items()
                if any(item["adjudicatedLabel"] in {"correct", "incorrect"} for item in group)
            ),
        },
        "classifierMetricGates": gates,
        "classifierMetricsAllPass": all(gates.values()),
        "lockedThresholds": {
            "clearSampleAccuracy": ">=0.90",
            "falsePassOnIncorrect": "<=0.05",
            "falseRetryOnCorrect": "<=0.10",
            "uncertainOnClearSpeech": "<=0.20",
            "silenceAndNoiseRejection": ">=0.95",
            "heldOutTestTargetAgeSpeakers": ">=30",
            "totalAdjudicatedSamples": ">=600",
        },
        "scoreCalibration": "not-measured: this tool evaluates categorical judgments only",
        "decision": "continue-research",
        "acceptanceBlockers": [
            "The evaluator does not establish calibrated 0-100 score meaning or score stability.",
            "SPEC-000 also requires a locked study plan and qualified educator approval "
            "of thresholds.",
            "A metrics pass is not product acceptance; review subgroup confidence "
            "intervals and errors.",
        ],
    }


def _group_speakers(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[item["speakerGroupId"]].append(item)
    return groups


def _write_private_report(output_path: Path, report: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".assessment-report-", dir=output_path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output_path)
        os.chmod(output_path, 0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, required=True, help="private manifest JSON; never commit it"
    )
    parser.add_argument(
        "--predictions", type=Path, required=True, help="blinded test predictions JSON"
    )
    parser.add_argument(
        "--audio-dir", type=Path, required=True, help="private directory with <sampleId>.wav files"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="aggregate report JSON destination"
    )
    args = parser.parse_args()
    try:
        manifest = _read_json(args.manifest)
        predictions = _read_json(args.predictions)
        audio_root = args.audio_dir.resolve(strict=True)
        output_path = args.output.resolve()
        manifest_path = args.manifest.resolve(strict=True)
        predictions_path = args.predictions.resolve(strict=True)
        _require(
            output_path not in {manifest_path, predictions_path}
            and not output_path.is_relative_to(audio_root),
            "output path must not replace a research input or be inside "
            "the private audio directory",
        )
        if args.output.exists():
            _require(
                not os.path.samefile(args.output, manifest_path)
                and not os.path.samefile(args.output, predictions_path),
                "output path must not replace a research input",
            )
        report = evaluate(manifest, predictions, audio_root)
        manifest_bytes = manifest_path.read_bytes()
        prediction_bytes = predictions_path.read_bytes()
        report["inputDigests"] = {
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "predictionsSha256": hashlib.sha256(prediction_bytes).hexdigest(),
            "wavSetSha256": hashlib.sha256(
                "\n".join(
                    sorted(
                        f"{item['sampleId']}:{item['sha256']}"
                        for item in _check_manifest(
                            manifest,
                            {
                                item["id"]
                                for item in json.loads(CONTENT_PATH.read_text(encoding="utf-8"))[
                                    "readingTargets"
                                ]
                            },
                        )
                    )
                ).encode()
            ).hexdigest(),
        }
        _write_private_report(args.output, report)
    except (ManifestError, OSError) as exc:
        print(f"PoC evaluation unavailable: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps({"decision": report["decision"], "report": str(args.output)}, ensure_ascii=False)
    )
    return 0 if report["decision"] == "accepted" else 3


if __name__ == "__main__":
    raise SystemExit(main())
