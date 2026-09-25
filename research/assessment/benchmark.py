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
import re
import sys
import wave
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = "poc-evaluator-0.1.0"
CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "curriculum.json"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
LABELS = {"correct", "incorrect", "uncertain"}
PREDICTIONS = {"pass", "retry", "uncertain"}
CLASSES = {"initial", "final", "whole-syllable", "tone", "syllable", "orthographic-letter"}
CHALLENGES = {"speech", "silence", "noise", "speaker-replay"}
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
        isinstance(manifest, dict) and manifest.get("schemaVersion") == 1,
        "manifest schemaVersion must be 1",
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
        "annotatorLabels",
        "adjudicatedLabel",
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
        labels = item.get("annotatorLabels")
        _require(
            isinstance(labels, list)
            and len(labels) == 2
            and all(label in LABELS for label in labels),
            f"two valid independent labels required for {sample_id}",
        )
        _require(
            isinstance(item.get("consentRef"), str)
            and ID_PATTERN.fullmatch(item["consentRef"]) is not None,
            f"opaque consentRef required for {sample_id}",
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
        if item["challengeClass"] in {"silence", "noise", "speaker-replay"}:
            _require(
                item["adjudicatedLabel"] == "uncertain",
                f"challenge sample must be adjudicated uncertain: {sample_id}",
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


def _rates(items: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    clear = [item for item in items if item["adjudicatedLabel"] in {"correct", "incorrect"}]
    correct = [item for item in clear if item["adjudicatedLabel"] == "correct"]
    incorrect = [item for item in clear if item["adjudicatedLabel"] == "incorrect"]
    decisions = {item["sampleId"]: predictions[item["sampleId"]]["status"] for item in items}
    accurate = sum(
        (decisions[item["sampleId"]] == "pass") == (item["adjudicatedLabel"] == "correct")
        for item in clear
        if decisions[item["sampleId"]] != "uncertain"
    )
    # Uncertain predictions remain in the accuracy denominator: they are not silently dropped.
    return {
        "clearSampleAccuracy": wilson(accurate, len(clear)),
        "falsePassOnIncorrect": wilson(
            sum(decisions[item["sampleId"]] == "pass" for item in incorrect), len(incorrect)
        ),
        "falseRetryOnCorrect": wilson(
            sum(decisions[item["sampleId"]] == "retry" for item in correct), len(correct)
        ),
        "uncertainOnClearSpeech": wilson(
            sum(decisions[item["sampleId"]] == "uncertain" for item in clear), len(clear)
        ),
        "challengeRejection": {
            challenge: wilson(
                sum(
                    decisions[item["sampleId"]] == "uncertain"
                    for item in items
                    if item["challengeClass"] == challenge
                ),
                sum(item["challengeClass"] == challenge for item in items),
            )
            for challenge in ("silence", "noise", "speaker-replay")
        },
    }


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
    overall_children = {
        item["speakerGroupId"] for item in items if item["cohort"] == "target-age-child"
    }
    classifier_rates = [
        rates["clearSampleAccuracy"]["rate"],
        rates["falsePassOnIncorrect"]["rate"],
        rates["falseRetryOnCorrect"]["rate"],
        rates["uncertainOnClearSpeech"]["rate"],
        rates["challengeRejection"]["silence"]["rate"],
        rates["challengeRejection"]["noise"]["rate"],
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
        "atLeast30TargetAgeSpeakers": len(overall_children) >= 30,
        "atLeast600AdjudicatedSamples": len(items) >= 600,
    }
    labels = [(item["annotatorLabels"][0], item["annotatorLabels"][1]) for item in test_items]
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
        "testMetrics": rates,
        "annotationAgreement": cohen_kappa(labels),
        "byTargetClass": _grouped(test_items, predicted, "targetClass"),
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
            "totalTargetAgeSpeakers": ">=30",
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
        report = evaluate(manifest, _read_json(args.predictions), args.audio_dir)
        manifest_bytes = args.manifest.read_bytes()
        prediction_bytes = args.predictions.read_bytes()
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
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (ManifestError, OSError) as exc:
        print(f"PoC evaluation unavailable: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps({"decision": report["decision"], "report": str(args.output)}, ensure_ascii=False)
    )
    return 0 if report["decision"] == "accepted" else 3


if __name__ == "__main__":
    raise SystemExit(main())
