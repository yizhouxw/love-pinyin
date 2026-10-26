"""Publish compact source-hashed experiment snapshots without audio or vectors.

Only completed, explicit local result JSONs are read. Never loads a speech model,
opens frozen-test waveforms, changes labels, or runs inference. Phase-two result
publication is opt-in and requires all six fair-round model artifacts.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_metrics import GATE_LIMITS, metrics, wilson

NAMES = ("hanziflow", "sensevoice", "charsiu")
VARIANTS = ("linear", "multihead")
RESULT = ROOT / "docs/research/target-pronunciation-pretrained-results.json"


class Sources:
    def __init__(self):
        self.artifacts = {}

    def track(self, path: Path):
        relative = str(path.resolve().relative_to(ROOT))
        self.artifacts[relative] = {"sha256": fingerprint(path), "bytes": path.stat().st_size}

    def read(self, path: Path):
        self.track(path)
        return json.loads(path.read_text())


def recompute_recorded_metrics(records: list[dict], manifest: dict) -> dict:
    """Recount recorded decisions with explicit negative origins and lineage.

    Historical evaluate records encoded expert negatives with an expert_ prefix;
    plain onset/rime/tone negatives were declared counterfactual target queries.
    Only that documented origin and original manifest lineage are restored here.
    No decisions, phonetic labels or audio are changed.
    """
    inventory = {row["id"]: row for row in manifest["items"]}
    restored = []
    for original in records:
        row = dict(original)
        root = row.get("root_id") or row.get("audio_id")
        source = inventory[root]
        row["voice_family"] = source["voiceFamilyId"]
        row["reference_id"] = source["referenceSourceId"]
        if row.get("label") == "negative" and not row.get("negative_origin"):
            error = row["error_type"]
            if error.startswith(("expert-", "expert_")):
                row["negative_origin"] = "expert"
            elif error in {"onset", "rime", "tone"} or error.startswith("counterfactual-"):
                row["negative_origin"] = "counterfactual"
            else:
                raise ValueError("HISTORICAL_NEGATIVE_ORIGIN_NOT_VERIFIABLE")
        restored.append(row)
    return metrics(restored)


def _rates(counts: dict, n: int, false_accept: float | None = None) -> dict:
    result = {
        "accepted": wilson(counts.get("matched", 0), n),
        "explicitRejected": wilson(counts.get("retry", 0), n),
        "abstained": wilson(counts.get("uncertain", 0) + counts.get("unavailable", 0), n),
    }
    if false_accept is not None:
        count = round(false_accept * n)
        if abs(count - false_accept * n) > 1e-6:
            raise ValueError("SOURCE_RATE_NOT_INTEGER_COUNT")
        result["anyAlternativeFalseAccepted"] = wilson(count, n)
    return result


def _read_round(source: Sources, base: Path, prefix: str, *, choices=None) -> list[dict]:
    rows = []
    selected_choices = choices or [(name, variant) for name in NAMES for variant in VARIANTS]
    for name, variant in selected_choices:
        directory = base / (prefix + name + "-" + variant)
        metadata = source.read(directory / "model.json")
        calibration = source.read(directory / "calibration.json")
        history = source.read(directory / "training.json")
        selected = calibration["selected"]
        m = selected["metrics"]
        counts = m["positive"]
        n = m["n"]
        rows.append(
            {
                "model": name,
                "variant": variant,
                "actualVariant": metadata["variant"],
                "acousticDerivative": metadata.get("acousticDerivative"),
                "pitchOverride": metadata.get("pitchOverride"),
                "epochsActuallyRun": len(history),
                "selectedEpoch": metadata["selectedEpoch"],
                "trainRows": metadata["trainRows"],
                "trainSpeakers": metadata["trainSpeakers"],
                "calibrationRows": metadata["calibrationRows"],
                "calibrationSpeakers": metadata["calibrationSpeakers"],
                "trainingSeconds": metadata["trainingSeconds"],
                "trainingNumericalExclusions": metadata.get("trainingNumericalExclusions"),
                "manifestSha256": metadata["manifestSha256"],
                "headSha256": metadata["headSha256"],
                "headOnnxSha256": metadata.get("headOnnxSha256"),
                "thresholds": metadata["thresholds"],
                "calibration": m,
                "positiveWilson95": _rates(counts, n),
                "counterfactualWilson95": (
                    _rates(counts, n, m["falseAcceptance"])["anyAlternativeFalseAccepted"]
                    if not prefix
                    else None
                ),
                "testUsed": metadata["testUsed"],
                "qualityPassed": m["falseAcceptance"] <= 0.05
                and m["explicitRejection"] <= 0.10
                and m["abstention"] <= 0.20,
            }
        )
    return rows


def _ctc_error_breakdown(diagnostic: dict, metadata: dict) -> dict:
    """Describe actual native events without inventing replacement phone labels."""
    eligible = [
        row
        for row in diagnostic["records"]
        if row["expertLabel"] == "unanimous-correct"
        and not row["labelPolicyFlags"]
        and not row["numericalQualityFlags"]
    ]
    components = ("onset", "rime", "tone")
    reasons = {key: Counter() for key in components}
    root_reasons = Counter()
    confusion = {key: Counter() for key in components}
    by_speaker = defaultdict(Counter)
    for row in eligible:
        if not row["available"]:
            root_reasons["unavailable"] += 1
            continue
        forced, wrong = False, False
        for key in components:
            event = row["components"][key]
            best_mass = max(event["expectedSingleLabelMass"], event["bestOtherSingleLabelMass"])
            best = event["bestNativeToken"]
            if key == "onset" and best == "ZERO":
                best = ""
            if key == "tone" and best.startswith("T"):
                best = best[1:]
            native_targets = {
                metadata["nativeRimeAliases"].get(token, token) if key == "rime" else token
                for token in metadata["vocabulary"][key]
            }
            failure = {
                "blankDominates": event["emptyMass"] >= best_mass,
                "multipleDominates": event["multipleLabelMass"] >= best_mass,
                "greedyNotExactlyOne": len(event["greedyTokens"]) != 1,
                "unknownInGreedy": "<unk>" in event["greedyTokens"],
                "bestOutsideCoverage": best not in native_targets,
            }
            forced |= any(failure.values())
            reasons[key].update(name for name, found in failure.items() if found)
            if not event["expectedIsBestSingleLabel"]:
                reasons[key]["expectedNotNativeBest"] += 1
                confusion[key][(event["expectedToken"], event["bestNativeToken"])] += 1
                wrong = True
        root_reasons["forceUncertainByCompleteNativeEvents"] += forced
        root_reasons["atLeastOneExpectedComponentNotNativeBest"] += wrong
        by_speaker[row["speakerId"]].update(
            {
                "n": 1,
                "forcedUncertain": int(forced),
                "anyWrongNativeBest": int(wrong),
            }
        )
    return {
        "allCorrectRoots": len(eligible),
        "rootCounts": dict(root_reasons),
        "componentCounts": {key: dict(value) for key, value in reasons.items()},
        "topNativeBestDisagreements": {
            key: [
                {"expected": pair[0], "nativeBest": pair[1], "count": count}
                for pair, count in values.most_common(12)
            ]
            for key, values in confusion.items()
        },
        "bySpeaker": {key: dict(value) for key, value in sorted(by_speaker.items())},
        "claim": (
            "Actual expert-all-correct calibration roots; overlapping diagnostic causes, "
            "not replacement transcriptions, accuracy or threshold acceptance"
        ),
    }


def collect(
    *,
    include_phase_two=False,
    include_phase_three=False,
    include_phase_four=False,
    include_phase_five=False,
) -> dict:
    if include_phase_five:
        include_phase_four = True
    if include_phase_four:
        include_phase_two = include_phase_three = True
    source = Sources()
    base = ROOT / "private/pretrained-matcher"
    registry = source.read(ROOT / "content/pronunciation-pretrained-models.json")
    baseline = source.read(base / "baseline-comparison.json")
    old = baseline["bySource"]["original-tts-diagnostic"]["fullDenominator"]
    original = {
        "name": baseline["baseline"],
        "coveredTargets": baseline["coverageTargets"],
        "implementationSha256": baseline["inferenceCodeSha256"],
        "packageMetadataSha256": baseline["packageMetadataSha256"],
        "weightSha256": baseline["weights"],
        "diagnosticSource": baseline["sources"]["original-tts-diagnostic"],
        "reproducedOriginal370": {
            "n": old["rows"],
            "counts": old["statuses"],
            "wilson95": _rates(old["statuses"], old["rows"]),
            "exactHistoricalCountsReproduced": old["statuses"]
            == {"matched": 168, "retry": 21, "uncertain": 181},
            "scope": (
                "Historical synthetic diagnostic; already used to find errors, not a fresh test"
            ),
        },
        "supplementalCalibration": {
            key: {
                field: value[field]
                for field in (
                    "fullDenominator",
                    "commonOriginalCoverage",
                    "outsideOriginalCoverage",
                )
            }
            for key, value in baseline["bySource"].items()
            if key != "original-tts-diagnostic"
        },
    }
    candidates = {}
    for name, row in registry["models"].items():
        candidates[name] = {
            "repository": row["repository"],
            "revision": row["revision"],
            "lastModified": row["lastModified"],
            "license": row["license"],
            "licenseEvidence": row["licenseEvidence"],
            "outputs": row["outputs"],
            "trainingData": row["trainingData"],
            "weights": [
                f for f in row["files"] if f["path"].endswith((".pt", ".bin", ".safetensors"))
            ],
        }
    cpu = [
        {
            "name": "original-baseline",
            "backend": "ONNX CPU INT8 acoustic+FP32 pitch",
            "threads": baseline["benchmark"]["threads"],
            **{
                key: baseline["benchmark"].get(key)
                for key in (
                    "modelLoadMilliseconds",
                    "firstInferenceMilliseconds",
                    "processPythonCodeStartToFirstResultMilliseconds",
                    "fourSecondWarmP95Milliseconds",
                    "realTimeFactor",
                    "peakRssMiB",
                    "encoderActuallyExecuted",
                    "repeats",
                    "warmupRuns",
                )
            },
            "packageBytes": baseline["benchmark"]["weightBytes"],
            "packageSizeScope": "Two model weight files only; excludes original metadata",
            "passedLatency": baseline["benchmark"]["fourSecondWarmP95Milliseconds"] <= 400,
            "timingScope": baseline["benchmark"]["timingIncludes"],
        }
    ]
    for name in NAMES:
        benchmark = source.read(base / (name + "-full-cpu.json"))
        package = ROOT / "models/pinyin-pretrained/bundles" / (name + "-linear") / "model.json"
        model = source.read(package)
        if fingerprint(package) != benchmark["modelSha256"]:
            raise ValueError("BENCHMARK_PACKAGE_CHANGED")
        cpu.append(
            {
                "name": name,
                "backend": model["encoderBackend"],
                **{
                    key: benchmark.get(key)
                    for key in (
                        "threads",
                        "modelLoadMilliseconds",
                        "firstInferenceMilliseconds",
                        "fourSecondWarmP95Milliseconds",
                        "realTimeFactor",
                        "peakRssMiB",
                        "packageBytes",
                        "encoderActuallyExecuted",
                        "repeats",
                        "warmupRuns",
                        "passedLatency",
                        "passedMemory",
                        "modelSha256",
                    )
                },
                "packageSizeScope": "Reported bundled files; metadata bytes not included",
                "timingScope": benchmark["scope"],
                "processPythonCodeStartToFirstResultMilliseconds": None,
            }
        )
    phase_one = _read_round(source, base, "")
    raw = source.read(base / "raw-native-calibration.json")
    raw_compact = {}
    for name, report in raw.items():
        selected = report["selected"]
        raw_compact[name] = {
            "n": report["n"],
            "speakers": report["speakers"],
            "selected": selected,
            "wilson95": _rates(
                selected["counts"], report["n"], selected["rates"]["falseAcceptance"]
            ),
            "manifestSha256": report["manifestSha256"],
            "nativeCodeSha256": report["nativeCodeSha256"],
            "negativePolicy": report["negativePolicy"],
            "testRead": report["testRead"],
        }
    greedy = source.read(base / "raw-native-greedy-diagnostic.json")
    mandi = source.read(ROOT / "content/pronunciation-pretrained-data.json")
    ompal = source.read(ROOT / "content/pronunciation-ompal-data.json")
    utterances = source.read(base / "ompal/utterances-train-calibration.json")
    clips_manifest = base / "ompal-clips-v1-alias-diagnostic-manifest.json"
    if fingerprint(clips_manifest) != (
        "92f9f9469498575183335f3238a3e61d23aff48c841a7049174ff17369a6a464"
    ):
        raise ValueError("HISTORICAL_OMPAL_ALIAS_DIAGNOSTIC_MANIFEST_CHANGED")
    clips = source.read(clips_manifest)
    h_schema_path = ROOT / "models/pinyin-pretrained/hanziflow/v2_1_target_schema.json"
    h_schema = source.read(h_schema_path)
    h_final = h_schema["heads"]["final"]
    alias_defect = {
        "status": "confirmed-source-schema-semantic-error; historical metrics diagnostic only",
        "hanziflowTargetSchemaSha256": fingerprint(h_schema_path),
        "hanziflowTargetSchemaRevision": registry["models"]["hanziflow"]["revision"],
        "hanziflowActualApicalAliases": {
            "i-retroflex": h_final["apical_retroflex_final"],
            "i-dental": h_final["apical_alveolar_final"],
        },
        "charsiuActualApicalAliases": {"i-retroflex": "iii", "i-dental": "ii"},
        "historicalSharedAliases": {"i-retroflex": "iii", "i-dental": "ii"},
        "affectedArtifacts": [
            "Historical HanziFlow native probability diagnostics",
            "OMPAL v1 HanziFlow known-phone boundaries and all-three derived training clips",
        ],
        "notInferredFromModelAgreement": True,
        "historicalResultsRetained": True,
        "acceptanceUseAllowed": False,
    }
    id_map = source.read(ROOT / "content/pronunciation-ompal-detail-id-map.json")
    policy = source.read(ROOT / "content/pronunciation-ompal-policy.json")
    by_split = defaultdict(Counter)
    for utterance in utterances["utterances"]:
        group = by_split[utterance["split"]]
        group["utterances"] += 1
        for word in utterance["words"]:
            group["words"] += 1
            label = (
                "policy-unassessable" if word.get("labelPolicyFlags") else word.get("expertLabel")
            )
            group[label] += 1
    phase_two = {
        "status": "failed-alias-diagnostic; all-six-historical-artifacts-retained"
        if include_phase_two
        else "not-published-in-this-snapshot",
        "models": _read_round(source, base, "ompal-") if include_phase_two else [],
        "frozenTestEvaluation": "not-published; do not infer that model quality passed",
        "boundaryAliasDefect": alias_defect,
        "cpuEndToEndDiagnostic": [],
    }
    if include_phase_two:
        for name in NAMES:
            benchmark = source.read(base / ("ompal-" + name + "-full-cpu.json"))
            package_path = (
                ROOT / "models/pinyin-pretrained/bundles" / ("ompal-" + name) / "model.json"
            )
            package = source.read(package_path)
            if fingerprint(package_path) != benchmark["modelSha256"]:
                raise ValueError("HISTORICAL_OMPAL_BENCHMARK_PACKAGE_CHANGED")
            phase_two["cpuEndToEndDiagnostic"].append(
                {
                    "name": name,
                    "backend": package["encoderBackend"],
                    **{
                        key: value
                        for key, value in benchmark.items()
                        if key not in {"timingsMilliseconds", "statuses"}
                    },
                    "status": (
                        "historical-alias-diagnostic-head; corrected package requires retiming"
                    ),
                    "runtimeLoadedBeforeAliasConfigurationChanged": True,
                }
            )
    phase_three = {
        "status": "not-yet-published",
        "models": [],
        "nativeComparison": None,
        "cpuFullCalibration": [],
        "cpuFullCalibrationStatus": "not-published-in-this-snapshot",
        "stressCalibration": None,
        "preservedBaselineV2": None,
        "rawNativeComponentDiagnostics": None,
        "finetunedNativeComponentDiagnostics": None,
        "finetunedEncoderTraining": None,
        "finetunedNativeComparison": None,
        "swiftF0ToneExperiment": "not-published-in-this-snapshot; no quality claim",
        "encoderFinetuningStatus": "not-published-in-this-snapshot",
        "frozenTestEvaluation": "not-yet-published; no acceptance claim",
    }
    if include_phase_three:
        v2_path = base / "ompal-clips-v2/manifest.json"
        v2 = source.read(v2_path)
        expected_v2_sha = "2e1259602b83a2d1445f8a58dfba28c21d2e83213993fc6cdb3b4fbc38ceff01"
        if fingerprint(v2_path) != expected_v2_sha:
            raise ValueError("CORRECTED_ALIAS_ROUND_MANIFEST_CHANGED")
        comparison_directory = base / "ompal-v2-hanziflow-comparison"
        comparison = source.read(comparison_directory / "calibration.json")
        comparison_model = source.read(comparison_directory / "comparison.json")
        if comparison_model["manifestSha256"] != expected_v2_sha:
            raise ValueError("COMPARISON_CORRECTED_ALIAS_ROUND_MANIFEST_MISMATCH")
        phase_three.update(
            {
                "status": "corrected-alias-six-model-fair-round-completed; quality-failed",
                "manifestSha256": expected_v2_sha,
                "clipVersion": v2["version"],
                "clipCounts": v2["counts"],
                "alignmentMapping": v2["alignmentMapping"],
                "pipelineSha256AtExtraction": v2["pipelineSha256"],
                "alignerSha256": v2["alignerSha256"],
                "models": _read_round(source, base, "ompal-v2-"),
                "nativeComparison": {
                    "model": "hanziflow",
                    "variant": comparison_model["variant"],
                    "epochsActuallyRun": len(comparison["history"]),
                    "selectedEpoch": comparison["selectedEpoch"],
                    "thresholds": comparison["thresholds"],
                    "counts": comparison["counts"],
                    "fullDenominatorMetrics": comparison["fullDenominatorMetrics"],
                    "files": comparison_model["files"],
                    "finalTestRead": comparison["finalTestRead"],
                },
            }
        )
        source.track(ROOT / "pinyin_matcher/pretrained_metrics.py")
        raw_native = source.read(base / "ompal-v2-hanziflow-native-diagnostics.json")
        if raw_native["manifestSha256"] != expected_v2_sha or raw_native["finalTestRead"]:
            raise ValueError("RAW_NATIVE_DIAGNOSTICS_SCOPE_MISMATCH")
        phase_three["rawNativeComponentDiagnostics"] = {
            key: value for key, value in raw_native.items() if key != "records"
        }
        tuned_native = source.read(base / "ompal-v2-hanziflow-finetuned-native-diagnostics.json")
        if tuned_native["manifestSha256"] != expected_v2_sha or tuned_native["finalTestRead"]:
            raise ValueError("TUNED_NATIVE_DIAGNOSTICS_SCOPE_MISMATCH")
        phase_three["finetunedNativeComponentDiagnostics"] = {
            key: value for key, value in tuned_native.items() if key != "records"
        }
        fine = source.read(ROOT / "models/pinyin-pretrained/hanziflow-finetuned-v2/tuned.json")
        if fine["manifestSha256"] != expected_v2_sha or fine["finalTestRead"]:
            raise ValueError("FINETUNED_ENCODER_TRAINING_SCOPE_MISMATCH")
        phase_three["finetunedEncoderTraining"] = fine
        tuned_comparison_directory = base / "ompal-v2-hanziflow-finetuned-comparison"
        tuned_comparison = source.read(tuned_comparison_directory / "calibration.json")
        tuned_comparison_metadata = source.read(tuned_comparison_directory / "comparison.json")
        tuned_comparison_records = source.read(
            tuned_comparison_directory / "calibration-records.json"
        )
        if (
            tuned_comparison_metadata["manifestSha256"] != expected_v2_sha
            or tuned_comparison["finalTestRead"]
        ):
            raise ValueError("TUNED_COMPARISON_SCOPE_MISMATCH")
        phase_three["finetunedNativeComparison"] = {
            "model": "hanziflow-finetuned-v2",
            "variant": tuned_comparison_metadata["variant"],
            "epochsActuallyRun": len(tuned_comparison["history"]),
            "selectedEpoch": tuned_comparison["selectedEpoch"],
            "thresholds": tuned_comparison["thresholds"],
            "counts": tuned_comparison["counts"],
            "recordedFullDenominatorMetrics": tuned_comparison["fullDenominatorMetrics"],
            "fullDenominatorMetrics": recompute_recorded_metrics(tuned_comparison_records, v2),
            "acousticDerivative": tuned_comparison_metadata["acousticDerivative"],
            "files": tuned_comparison_metadata["files"],
            "finalTestRead": False,
        }
        phase_three["encoderFinetuningStatus"] = (
            "ten-actual-MPS-epochs-and120epoch-comparison-completed; quality-failed"
        )
        pitch_cache = source.read(base / "ompal-v2-swift-pitch/manifest.json")
        if pitch_cache["baseManifestSha256"] != expected_v2_sha or pitch_cache["testIncluded"]:
            raise ValueError("SWIFT_PITCH_CACHE_SCOPE_MISMATCH")
        source.track(ROOT / "content/pronunciation-pretrained-pitch.json")
        source.track(ROOT / "resources/licenses/SwiftF0-MIT.txt")
        phase_three["swiftF0ToneExperiment"] = {
            "preparation": {key: value for key, value in pitch_cache.items() if key != "items"},
            "trainingAndCpuEvaluation": (
                "Completed fit results in phaseFourOptimizedHeads; quality failed"
                if include_phase_four
                else "not-published-in-this-snapshot"
            ),
        }
        comparison_records = source.read(comparison_directory / "calibration-records.json")
        phase_three["nativeComparison"]["recordedFullDenominatorMetrics"] = comparison[
            "fullDenominatorMetrics"
        ]
        phase_three["nativeComparison"]["fullDenominatorMetrics"] = recompute_recorded_metrics(
            comparison_records, v2
        )
        stress = source.read(base / "stress-calibration-v2-summary.json")
        if stress["sourceManifestSha256"] != expected_v2_sha:
            raise ValueError("STRESS_CORRECTED_ALIAS_ROUND_MANIFEST_MISMATCH")
        for row in stress["models"].values():
            report_path = Path(row["report"])
            source.read(report_path)
            if fingerprint(report_path) != row["reportSha256"]:
                raise ValueError("STRESS_SOURCE_REPORT_CHANGED")
            row["report"] = str(report_path.relative_to(ROOT))
        phase_three["stressCalibration"] = stress
        baseline_v2 = source.read(base / "baseline-comparison-v2-repro.json")
        first_baseline_v2 = source.read(base / "baseline-comparison-v2.json")
        if baseline_v2["predictions"] != first_baseline_v2["predictions"]:
            raise ValueError("PRESERVED_BASELINE_DECISIONS_NOT_REPRODUCED")
        phase_three["preservedBaselineV2"] = {
            "implementationRevision": baseline_v2["implementationRevision"],
            "sourceFileSha256": baseline_v2["sourceFileSha256"],
            "packageMetadataSha256": baseline_v2["packageMetadataSha256"],
            "weights": baseline_v2["weights"],
            "coverageTargets": baseline_v2["coverageTargets"],
            "sources": baseline_v2["sources"],
            "bySource": baseline_v2["bySource"],
            "exactReproducedDecisions": len(baseline_v2["predictions"]),
            "benchmark": {
                key: value
                for key, value in baseline_v2["benchmark"].items()
                if key not in {"timingsMilliseconds", "statuses"}
            },
            "supersededInstrumentReading": (
                "First v2 benchmark RSS included large evaluation JSON; retained as "
                "instrument diagnostic, use reproducible isolated benchmark RSS here"
            ),
            "limitations": baseline_v2["limitations"],
        }
        cpu_paths = [base / ("ompal-v2-" + name + "-full-calibration.json") for name in NAMES]
        if all(path.is_file() for path in cpu_paths):
            for name, path in zip(NAMES, cpu_paths, strict=True):
                original_evaluation = source.read(path)
                verified_path = path.with_stem(path.stem + "-verified")
                has_verified = verified_path.is_file()
                evaluation = source.read(verified_path) if has_verified else original_evaluation
                if evaluation["manifestSha256"] != expected_v2_sha:
                    raise ValueError("CPU_CALIBRATION_CORRECTED_ALIAS_MANIFEST_MISMATCH")
                if len(evaluation["predictions"]) != evaluation["rows"]:
                    raise ValueError("CPU_CALIBRATION_PREDICTION_INVENTORY_INCOMPLETE")
                phase_three["cpuFullCalibration"].append(
                    {
                        "model": name,
                        **{
                            key: evaluation[key]
                            for key in (
                                "split",
                                "manifestSha256",
                                "modelSha256",
                                "rows",
                                "frozenPlanSha256",
                                "labelLimitation",
                            )
                        },
                        "recordedMetrics": original_evaluation["metrics"],
                        "metrics": evaluation["metrics"]
                        if has_verified
                        else recompute_recorded_metrics(evaluation["records"], v2),
                        "metricSource": "direct-verified-CPU-rerun"
                        if has_verified
                        else "recorded-decision-recomputation",
                        "originalShellExitStatus": 2 if name in {"hanziflow", "charsiu"} else 0,
                        "originalShellStatusScope": (
                            "Root observed shell source changing during execution: "
                            "HanziFlow/Charsiu evaluation atomically wrote all4202 predictions "
                            "before subsequent shell parse failure. Do not call the driver exit0."
                        ),
                        "metricRecomputation": {
                            "originalArtifactSha256": fingerprint(path),
                            "sourceManifestSha256": expected_v2_sha,
                            "metricsCodeSha256": fingerprint(
                                ROOT / "pinyin_matcher/pretrained_metrics.py"
                            ),
                            "recordedDecisionsUnchanged": True,
                            "inferenceRerun": has_verified,
                            "directVerifiedArtifactSha256": fingerprint(verified_path)
                            if has_verified
                            else None,
                        },
                    }
                )
            phase_three["cpuFullCalibrationStatus"] = "all-three-actual-runtime-results-snapshotted"
    phase_four = {
        "status": "not-yet-published",
        "models": [],
        "pendingExperiments": [
            "SenseVoice main50 encoder with new phonetic CTC heads",
            "Dedicated nonlinear acoustic/F0 tone fusion head",
        ],
        "frozenTestEvaluation": "preserved-unopened; no acceptance claim",
    }
    if include_phase_four:
        choices = [
            ("hanziflow-finetuned", "linear"),
            ("hanziflow-finetuned", "multihead"),
            ("hanziflow-finetuned", "multihead-swift"),
            ("hanziflow", "multihead-swift"),
        ]
        tone_choices = [
            ("hanziflow-finetuned", "tone-specialist"),
            ("sensevoice", "tone-specialist"),
        ]
        complete_tone = [
            (name, variant)
            for name, variant in tone_choices
            if all(
                (base / f"ompal-v2-{name}-{variant}" / filename).is_file()
                for filename in ("model.json", "training.json", "calibration.json")
            )
        ]
        choices.extend(complete_tone)
        phase_four["models"] = _read_round(
            source,
            base,
            "ompal-v2-",
            choices=choices,
        )
        if any(row["epochsActuallyRun"] != 120 for row in phase_four["models"]):
            raise ValueError("OPTIMIZED_READOUT_ROUND_INCOMPLETE")
        phase_four["status"] = "completed-actual120epoch-calibration-experiments; quality-failed"
        phase_four["allCompletedExperimentsFailedPointGates"] = not any(
            row["qualityPassed"] for row in phase_four["models"]
        )
        phase_four["completedDedicatedToneVariants"] = len(complete_tone)
        if len(complete_tone) == len(tone_choices):
            phase_four["pendingExperiments"].remove(
                "Dedicated nonlinear acoustic/F0 tone fusion head"
            )
        correct_ids = {
            row["id"]
            for row in v2["items"]
            if row["split"] == "calibration"
            and row.get("expertLabel") == "unanimous-correct"
            and not row.get("labelPolicyFlags")
        }
        available = sum(
            row["pitchAvailable"] for row in pitch_cache["items"] if row["id"] in correct_ids
        )
        phase_four["reliableSwiftF0CorrectCalibration"] = {
            "allCorrectRoots": len(correct_ids),
            "pitchAvailable": available,
            "mandatoryAbstentionRoots": len(correct_ids) - available,
            "abstentionLowerBound": 1 - available / len(correct_ids),
            "fixedAbstentionGate": 0.20,
            "voicingThresholdLowered": False,
            "scope": (
                "This experiment requires reliable F0; independent acoustic paths remain separate"
            ),
        }
    phase_five = {
        "status": "not-yet-published",
        "coverageDefect": {
            "oldObservedTargetCount": 549,
            "correctCalibrationRoots": 2239,
            "oldToneCounterfactualRoots": 1566,
            "requiredToneCounterfactualRoots": 2239,
            "resolution": (
                "Expand every observed valid training syllable base to all tones1-4; "
                "do not construct unseen onset/rime Cartesian syllables"
            ),
            "oldResultsRetained": True,
            "oldResultsAreAcceptance": False,
            "frozenTestWasUsed": False,
        },
        "models": [],
        "directCTC": [],
        "trainedSensevoiceReadouts": [],
        "sameAnchorStress": {"status": "not-published", "models": []},
        "sensevoiceInt8CTC": {"status": "not-published"},
        "completePipelineCpu": [],
        "originalPressureGuardFailure": None,
        "baselineContinuousCpu": None,
        "continuousCpuPressure": None,
        "frozenTestEvaluation": "preserved-unopened; not-enabled-after-calibration-quality-failure",
    }
    if include_phase_five:
        phase_four["pendingExperiments"] = [
            item
            for item in phase_four["pendingExperiments"]
            if item != "SenseVoice main50 encoder with new phonetic CTC heads"
        ]
        sense = source.read(ROOT / "models/pinyin-pretrained/sensevoice-finetuned-v1/tuned.json")
        if sense["finalTestRead"] or not sense["allFrozenTensorsUnchanged"]:
            raise ValueError("SENSEVOICE_DERIVATIVE_PROVENANCE_INVALID")
        phase_five["sensevoicePhoneticTraining"] = {
            key: value
            for key, value in sense.items()
            if key not in {"files", "trainableParameterNames"}
        }
        phase_five["sensevoicePhoneticTraining"]["actualTrainingEpochs"] = sum(
            entry["epoch"] > 0 for entry in sense["history"]
        )
        phase_five["sensevoicePhoneticTraining"]["weight"] = sense["files"]["tuned.safetensors"]
        diag = source.read(base / "ompal-v2-sensevoice-finetuned-native-diagnostics.json")
        phase_five["sensevoiceNewHeadDiagnostics"] = {
            key: value for key, value in diag.items() if key != "records"
        }
        isolated = source.read(base / "corpus-research-isolated/isolated-corpus-audit.json")
        phase_five["isolatedCorpusResearch"] = {
            key: isolated[key]
            for key in ("existingSplitsChanged", "reservedAudioOpened", "candidates", "conclusion")
        }
        phase_five["status"] = (
            "four-tone-coverage-repaired; actual-calibration; quality-not-accepted"
        )
        for path in (
            ROOT / "content/pronunciation-pretrained-cpu-pressure.json",
            ROOT / "content/pronunciation-pretrained-cpu-pressure-continuous.json",
            base / "cpu-pressure-exact-verified.wav.json",
        ):
            if path.is_file():
                source.track(path)
        continuous_proof = base / "cpu-pressure-continuous-verified.wav.json"
        if continuous_proof.is_file():
            phase_five["continuousCpuPressure"] = source.read(continuous_proof)
        guard_failure = base / "final-common-cpu-guard-rejected-execution.json"
        if guard_failure.is_file():
            phase_five["originalPressureGuardFailure"] = source.read(guard_failure)
            index = base / "final-common-cpu-guard-rejected-log-index.json"
            if index.is_file():
                phase_five["originalPressureGuardFailure"]["preservedLogIndex"] = source.read(index)
            for path in sorted(base.glob("ompal-v2-*-four-tones-*-failure.json")):
                source.track(path)
        stress_identity_path = base / "stress-four-tones-anchor-identity.json"
        if stress_identity_path.is_file():
            stress_identity = source.read(stress_identity_path)
            stress_summary_path = base / "stress-four-tones-summary.json"
            if stress_summary_path.is_file():
                phase_five["sameAnchorStress"]["executionSummary"] = source.read(
                    stress_summary_path
                )
            if not (
                stress_identity["same24AnchorIds"]
                and stress_identity["sameEveryCasePayloadSha256"]
                and stress_identity["sourceManifestSha256"] == expected_v2_sha
                and stress_identity["finalTestRead"] is False
            ):
                raise ValueError("FOUR_TONE_STRESS_ANCHORS_DIFFER_FROM_HISTORICAL_SCOPE")
            phase_five["sameAnchorStress"]["identity"] = stress_identity
            stress_names = (
                *NAMES,
                "hanziflow-finetuned-native-ctc",
                "hanziflow-finetuned-multihead",
                "hanziflow-finetuned-comparison",
                "sensevoice-finetuned-native-ctc",
                "sensevoice-finetuned-multihead",
            )
            for name in stress_names:
                path = base / f"stress-{name}-four-tones.json"
                if path.is_file():
                    stress_result = source.read(path)
                    if stress_result["manifestSha256"] != stress_identity["newManifestSha256"]:
                        raise ValueError("FOUR_TONE_STRESS_RESULT_IDENTITY_MISMATCH")
                    phase_five["sameAnchorStress"]["models"].append(
                        {
                            "model": name,
                            **{
                                key: value
                                for key, value in stress_result.items()
                                if key not in {"predictions", "modelInfo"}
                            },
                        }
                    )
            phase_five["sameAnchorStress"]["status"] = (
                "all-eight-actual-CPU-runs-completed; calibration-diagnostic-only"
                if len(phase_five["sameAnchorStress"]["models"]) == 8
                else "partial-artifacts-published; no complete-comparison-claim"
            )
        sense_choices = [
            ("sensevoice-finetuned", variant)
            for variant in ("linear", "multihead", "tone-specialist")
            if all(
                (base / f"ompal-v2-sensevoice-finetuned-{variant}" / filename).is_file()
                for filename in ("model.json", "training.json", "calibration.json")
            )
        ]
        if sense_choices:
            phase_five["trainedSensevoiceReadouts"] = _read_round(
                source, base, "ompal-v2-", choices=sense_choices
            )
            if any(
                row["epochsActuallyRun"] != 120 for row in phase_five["trainedSensevoiceReadouts"]
            ):
                raise ValueError("SENSEVOICE_OPTIMIZED_READOUT_ROUND_INCOMPLETE")
        for name in ("hanziflow", "sensevoice"):
            directory = base / f"ompal-v2-{name}-finetuned-native-ctc-four-tones"
            metadata = source.read(directory / "model.json")
            calibration = source.read(directory / "calibration.json")
            if metadata["testUsed"] or calibration["testUsed"]:
                raise ValueError("CTC_CALIBRATION_OPENED_FINAL_TEST")
            if len(metadata["coveredTargets"]) != 1208:
                raise ValueError("CTC_CALIBRATION_FOUR_TONE_COVERAGE_INCOMPLETE")
            row = {
                "model": name,
                "phoneticHeadOrigin": metadata["phoneticHeadOrigin"],
                "coveredTargets": len(metadata["coveredTargets"]),
                "calibrationRows": metadata["calibrationRows"],
                "thresholdCandidatesActuallyEvaluated": len(calibration["candidates"]),
                "thresholds": metadata["thresholds"],
                "metrics": calibration["selected"]["metrics"],
                "calibrationMetadataSha256": fingerprint(directory / "model.json"),
                "calibrationImplementationSha256": metadata["implementationSha256"],
                "calibrationRecordsSha256": fingerprint(directory / "calibration-records.json"),
                "acousticDerivative": metadata["acousticDerivative"],
                "fullCpuCalibration": None,
                "cpuBenchmark": None,
                "testUsed": False,
            }
            original_ctc_code = base / "pretrained_ctc_runtime-before-int8.py"
            if original_ctc_code.is_file():
                if fingerprint(original_ctc_code) != metadata["implementationSha256"]:
                    raise ValueError("NATIVE_CTC_CALIBRATION_SOURCE_SNAPSHOT_MISMATCH")
                source.track(original_ctc_code)
            native_diag = source.read(base / f"ompal-v2-{name}-finetuned-native-diagnostics.json")
            row["nativeEventErrorBreakdown"] = _ctc_error_breakdown(native_diag, metadata)
            source.track(directory / "calibration-records.json")
            full = base / f"ompal-v2-{name}-finetuned-native-ctc-four-tones-full-calibration.json"
            if full.is_file():
                measured = source.read(full)
                package_metadata = (
                    ROOT / "models/pinyin-pretrained/bundles" / directory.name / "model.json"
                )
                source.track(package_metadata)
                if (
                    measured["modelSha256"] != fingerprint(package_metadata)
                    or measured["manifestSha256"] != metadata["manifestSha256"]
                    or measured["rows"] != metadata["calibrationRows"]
                    or measured["split"] != "calibration"
                ):
                    raise ValueError("NATIVE_CTC_FULL_CPU_RESULT_IDENTITY_MISMATCH")
                row["fullCpuCalibration"] = {
                    key: value
                    for key, value in measured.items()
                    if key not in {"records", "predictions"}
                }
            cpu_path = base / f"ompal-v2-{name}-finetuned-native-ctc-four-tones-continuous-cpu.json"
            if cpu_path.is_file():
                row["cpuBenchmark"] = source.read(cpu_path)
            phase_five["directCTC"].append(row)
        for name in (
            *NAMES,
            "hanziflow-finetuned-multihead",
            "hanziflow-finetuned-comparison",
            "sensevoice-finetuned-multihead",
        ):
            full = base / f"ompal-v2-{name}-four-tones-calibration.json"
            if full.is_file():
                measured = source.read(full)
                package_metadata = (
                    ROOT
                    / "models/pinyin-pretrained/bundles"
                    / f"ompal-v2-{name}-four-tones/model.json"
                )
                package = source.read(package_metadata)
                if (
                    len(package["coveredTargets"]) != 1208
                    or package["testUsed"] is not False
                    or measured["modelSha256"] != fingerprint(package_metadata)
                    or measured["manifestSha256"] != expected_v2_sha
                    or measured["rows"] != 4202
                    or measured["split"] != "calibration"
                ):
                    raise ValueError("FOUR_TONE_CALIBRATION_RESULT_IDENTITY_MISMATCH")
                phase_five["models"].append(
                    {
                        "model": name,
                        **{
                            key: value
                            for key, value in measured.items()
                            if key not in {"records", "predictions"}
                        },
                    }
                )
        int8_package = ROOT / (
            "models/pinyin-pretrained/bundles/"
            "ompal-v2-sensevoice-finetuned-native-ctc-int8-four-tones"
        )
        if (int8_package / "model.json").is_file():
            int8_metadata = source.read(int8_package / "model.json")
            int8_source = source.read(int8_package / "encoder/tuned.json")
            if (
                int8_metadata["encoderBackend"] != "sensevoice-ctc-int8"
                or int8_metadata["thresholds"] != phase_five["directCTC"][1]["thresholds"]
                or int8_metadata["testUsed"] is not False
                or int8_source["finalTestRead"] is not False
            ):
                raise ValueError("SENSEVOICE_INT8_PARENT_PROTOCOL_MISMATCH")
            quantized = {
                "status": "actual-export-and-bundle; full-CPU-result-not-published",
                "modelSha256": fingerprint(int8_package / "model.json"),
                "encoderBackend": int8_metadata["encoderBackend"],
                "thresholds": int8_metadata["thresholds"],
                "thresholdsChanged": False,
                "packageBytes": int8_metadata["packageBytes"],
                "source": {
                    key: int8_source[key]
                    for key in (
                        "architecture",
                        "parameterCount",
                        "parentTunedMetadataSha256",
                        "parentTunedWeightSha256",
                        "exportCodeSha256",
                        "quantization",
                        "targetInput",
                        "fullCpuCalibrationRequired",
                        "qualityEstablishedByNumericalParity",
                    )
                },
                "graph": int8_source["files"]["encoder.int8.onnx"],
                "numericalParity": source.read(base / "sensevoice-finetuned-v1-int8-parity.json"),
                "fullCpuCalibration": None,
                "stressCalibration": None,
                "cpuBenchmark": None,
            }
            int8_full = base / (
                "ompal-v2-sensevoice-finetuned-native-ctc-int8-four-tones-full-calibration.json"
            )
            if int8_full.is_file():
                full = source.read(int8_full)
                if (
                    full["modelSha256"] != quantized["modelSha256"]
                    or full["manifestSha256"] != expected_v2_sha
                    or full["split"] != "calibration"
                    or full["rows"] != 4202
                ):
                    raise ValueError("SENSEVOICE_INT8_CPU_RESULT_IDENTITY_MISMATCH")
                quantized["fullCpuCalibration"] = {
                    key: value
                    for key, value in full.items()
                    if key not in {"predictions", "records"}
                }
                fp32_path = base / (
                    "ompal-v2-sensevoice-finetuned-native-ctc-four-tones-full-calibration.json"
                )
                fp32 = source.read(fp32_path)
                fp32_predictions = {row["id"]: row for row in fp32["predictions"]}
                if {row["id"] for row in full["predictions"]} != set(fp32_predictions):
                    raise ValueError("QUANTIZED_FULL_CPU_ROOT_INVENTORY_MISMATCH")
                changed = [
                    row["id"]
                    for row in full["predictions"]
                    if row["status"] != fp32_predictions[row["id"]]["status"]
                ]
                by_id = {row["id"]: row for row in v2["items"]}
                quantized["truthQueryStatusChangesFromFp32"] = len(changed)
                quantized["statusChangesByExpertLabel"] = dict(
                    Counter(
                        "policy-unassessable"
                        if by_id[root].get("labelPolicyFlags")
                        else by_id[root]["expertLabel"]
                        for root in changed
                    )
                )
                quantized["status"] = "actual-full4202-CPU-calibration-completed; quality-failed"
            int8_stress = base / "stress-sensevoice-finetuned-native-ctc-int8-four-tones.json"
            if int8_stress.is_file():
                proof = source.read(base / "stress-four-tones-int8-anchor-identity.json")
                stress_result = source.read(int8_stress)
                if not (
                    proof["same24AnchorIds"]
                    and proof["sameEveryCasePayloadSha256"]
                    and proof["newNinePackageManifestSha256"] == stress_result["manifestSha256"]
                    and stress_result["metadataSha256"] == quantized["modelSha256"]
                ):
                    raise ValueError("SENSEVOICE_INT8_STRESS_IDENTITY_MISMATCH")
                quantized["stressAnchorIdentity"] = proof
                quantized["stressCalibration"] = {
                    key: value
                    for key, value in stress_result.items()
                    if key not in {"predictions", "modelInfo"}
                }
            phase_five["sensevoiceInt8CTC"] = quantized
        cpu_names = (
            *NAMES,
            "hanziflow-finetuned-native-ctc",
            "hanziflow-finetuned-multihead",
            "hanziflow-finetuned-comparison",
            "sensevoice-finetuned-native-ctc",
            "sensevoice-finetuned-multihead",
            "sensevoice-finetuned-native-ctc-int8",
        )
        for name in cpu_names:
            warm_path = base / f"ompal-v2-{name}-four-tones-continuous-cpu.json"
            cold_path = base / f"ompal-v2-{name}-four-tones-continuous-cold.json"
            if warm_path.is_file():
                package_path = ROOT / (
                    f"models/pinyin-pretrained/bundles/ompal-v2-{name}-four-tones/model.json"
                )
                package_metadata = source.read(package_path)
                warm = source.read(warm_path)
                cold = source.read(cold_path) if cold_path.is_file() else None
                if (
                    warm["modelSha256"] != fingerprint(package_path)
                    or warm["pressureMethod"] != "supplied-exact-four-seconds"
                    or warm["threads"] != 2
                    or not warm["encoderActuallyExecuted"]
                    or warm["pressurePayloadSha256"]
                    != phase_five["continuousCpuPressure"]["payloadSha256"]
                    or (
                        cold
                        and (
                            cold["modelSha256"] != warm["modelSha256"]
                            or cold["payloadSha256"] != warm["pressurePayloadSha256"]
                            or cold["threads"] != 2
                        )
                    )
                ):
                    raise ValueError("COMPLETE_PIPELINE_CPU_IDENTITY_OR_PRESSURE_MISMATCH")
                phase_five["completePipelineCpu"].append(
                    {
                        "model": name,
                        "backend": package_metadata["encoderBackend"],
                        "warm": {
                            key: value
                            for key, value in warm.items()
                            if key not in {"timingsMilliseconds", "statuses"}
                        },
                        "cold": cold,
                    }
                )
        baseline_warm = base / "baseline-cpu-continuous.json"
        baseline_cold = base / "baseline-cpu-continuous-cold.json"
        if baseline_warm.is_file() and baseline_cold.is_file():
            document, cold = source.read(baseline_warm), source.read(baseline_cold)
            warm = document["benchmark"]
            if (
                warm["pressurePayloadSha256"] != cold["payloadSha256"]
                or warm["pressurePayloadSha256"]
                != phase_five["continuousCpuPressure"]["payloadSha256"]
                or document["implementationRevision"] != baseline_v2["implementationRevision"]
                or document["weights"] != baseline_v2["weights"]
                or warm["threads"] != 2
                or cold["threads"] != 2
            ):
                raise ValueError("PRESERVED_BASELINE_CONTINUOUS_CPU_IDENTITY_MISMATCH")
            for run in cold["runs"]:
                child = Path(run["artifact"])
                if fingerprint(child) != run["sha256"]:
                    raise ValueError("PRESERVED_BASELINE_COLD_PROCESS_ARTIFACT_CHANGED")
                source.track(child)
            phase_five["baselineContinuousCpu"] = {
                "implementationRevision": document["implementationRevision"],
                "runnerSha256": document["runnerSha256"],
                "weights": document["weights"],
                "warm": {
                    key: value
                    for key, value in warm.items()
                    if key not in {"statuses", "timingsMilliseconds"}
                },
                "cold": cold,
            }
        execution = base / "final-continuous-cpu-execution.json"
        if execution.is_file():
            phase_five["continuousCpuExecution"] = source.read(execution)
        verification_logs = (
            ("npm run verify:all", "verify-all-v8.log"),
            ("pretrained Python tool tests", "pretrained-tests-final.log"),
            ("npm run validate:release", "validate-release-pretrained-final.log"),
        )
        phase_five["engineeringVerification"] = []
        for command, filename in verification_logs:
            path = base / filename
            if path.is_file():
                source.track(path)
                phase_five["engineeringVerification"].append(
                    {
                        "command": command,
                        "logSha256": fingerprint(path),
                        "scope": "Engineering checks only; not pronunciation or child acceptance",
                    }
                )
    result = {
        "schemaVersion": 1,
        "date": "2026-10-26",
        "acceptanceIds": ["MATCH-07", "MATCH-08", "MATCH-09"],
        "overallStatus": (
            "comparison-and-listed-optimizations-actually-completed; "
            "quality-objective-incomplete; final-test-not-enabled"
        ),
        "applicationIntegrated": False,
        "realChildValidationPassed": False,
        "qualityLimits": dict(GATE_LIMITS),
        "latencyLimits": {
            "cpuThreads": 2,
            "fourSecondP95Milliseconds": 500,
            "realTimeFactor": 0.1,
            "effectiveFourSecondP95Milliseconds": 400,
        },
        "resourceBudget": {
            "maxParameters": 350000000,
            "maxWeightBytes": 1610612736,
            "maxProcessRssBytes": 3221225472,
        },
        "candidates": candidates,
        "baseline": original,
        "phaseOneManDi": {
            "status": "failed-diagnostic; source-transcription risk blocks quality interpretation",
            "nativeHeads": raw_compact,
            "nativeHanziflowAliasDefect": alias_defect,
            "trainedModels": phase_one,
            "dataConfig": {
                k: mandi[k] for k in ("datasetId", "license", "splitPolicy", "labelProvenance")
            },
            "actualCoverage": (
                "40 observed syllable-tone combinations; lexicon has44 but cai1-4 absent"
            ),
            "sourceProblem": {
                "speaker": "BEI_004_F",
                "diagnosticManifestSha256": greedy["manifestSha256"],
                "actualComponentCounts": {
                    name: data["bySpeaker"]["BEI_004_F"]
                    for name, data in greedy["aggregates"].items()
                },
                "independentEvidence": (
                    "ManDi paper section3.2 describes overwritten randomized task"
                    " transcripts; no independent corrected recording transcript "
                    "located"
                ),
                "modelAgreementRelabelled": False,
                "speakerDeleted": False,
            },
            "phaseOneMetricsLimitation": (
                "Calibration and counterfactual all-component tuples, includi"
                "ng non-lexical combinations; not a pristine test or independ"
                "ently verified phonetic accuracy"
            ),
        },
        "cpuEndToEnd": cpu,
        "cpuLimits": (
            "Model load excludes Python/runtime imports; full process col"
            "d timing only available for original baseline. Four-second r"
            "esized real speech is length pressure, not correctness evide"
            "nce. Concurrent system load was not controlled."
        ),
        "ompalData": {
            "revision": ompal["revision"],
            "license": ompal["license"],
            "citation": ompal["citation"],
            "annotationPolicy": ompal["annotationPolicy"],
            "speakerSplitPolicy": ompal["speakerSplitPolicy"],
            "sourceConfigSha256": utterances["configSha256"],
            "utterancesManifestSha256": fingerprint(
                base / "ompal/utterances-train-calibration.json"
            ),
            "clipsManifestSha256": fingerprint(clips_manifest),
            "detailIdMapSha256": utterances["detailIdMappingSha256"],
            "pinyinPolicySha256": utterances["pinyinPolicySha256"],
            "policyVersion": policy["policyVersion"],
            "uniquePromptContexts": policy["allUniquePrompts"],
            "detailedToActualMappingCount": len(id_map["mapping"]),
            "unresolvedDetailedIds": len(id_map["unresolved"]),
            "actualLearnerSpeakers": id_map["evidence"]["actualSpeakers"],
            "splitCounts": {k: dict(v) for k, v in sorted(by_split.items())},
            "clipCounts": clips["counts"],
            "boundaryPolicy": clips["boundaryPolicy"],
            "paddingPolicy": clips["paddingPolicy"],
            "pipelineSha256": clips["pipelineSha256"],
            "alignerSha256": clips["alignerSha256"],
            "frozenTestAudioIncluded": utterances["frozenTestIncluded"]
            or clips["frozenTestIncluded"],
            "reservedLearnerSpeakers": len(utterances["reservedSpeakers"]),
            "unopenedFrozenWavCountAtPreparation": sum(
                f.get("split") == "test" for f in ompal["files"]
            ),
            "labelLimits": [
                "Ratings concern last attempt and may forgive some forgotten syllables",
                "Expected context pinyin is not a realized phonetic transcription",
                "Known-phone CTC chooses candidate boundaries, never correctness labels",
                "Weak boundaries, expert disagreement and lexical policy flags remain recorded",
                (
                    "Adult French learners and connected speech do not establish "
                    "child isolated-pinyin accuracy"
                ),
            ],
        },
        "phaseTwoOmpal": phase_two,
        "phaseThreeCorrectedOmpal": phase_three,
        "phaseFourOptimizedHeads": phase_four,
        "phaseFiveFullFourToneCoverage": phase_five,
        "remainingGates": [
            "Quality objective unmet: additional validated supervision and model improvement",
            "Model/config/code freeze before opening independent final test audio",
            (
                "Frozen root-level quality metrics with error strata, abstent"
                "ions and uncertainty intervals"
            ),
            "Independent natural insertion/omission/noise truth beyond calibration stress",
            "Quality acceptance failed; Charsiu CPU real-time factor remains above0.1",
            (
                "Independent strict boundaries/phonetic truth and real child "
                "validation for broader claims"
            ),
        ],
        "reportGeneration": {
            "generatorSha256": fingerprint(Path(__file__)),
            "phaseTwoIncluded": include_phase_two,
            "phaseThreeIncluded": include_phase_three,
            "phaseFourIncluded": include_phase_four,
            "phaseFiveIncluded": include_phase_five,
            "modelInferenceOrAudioRead": False,
        },
        "sourceArtifacts": source.artifacts,
    }
    return result


def _percent(value):
    return "未定义" if value is None else f"{value * 100:.1f}%"


def markdown(report: dict) -> str:
    from textwrap import dedent

    lines = []

    def add(text):
        lines.extend(dedent(text).strip().splitlines())
        lines.append("")

    def table(headers, rows):
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)
        lines.append("")

    add("""
        # 预训练拼音匹配：实测对照与数据修复

        日期：2026-10-26。对应 SPEC-018 MATCH-07～09。
        **三款实际权重、原生头、共享探针/专用头、CPU包与原基线均已运行；
        比较和列出的优化轮次已实际完成，原质量门槛仍失败，最终测试保留未启用。**
        没有应用接入或儿童达标声明。

        本报告与JSON由 `pinyin_matcher.pretrained_report` 从实际本机结果生成。
        JSON的 `sourceArtifacts` 保存每份源结果的SHA256和大小；
        没有提交语音、训练向量或权重。旧合成实验记录保持原样，
        见[原结果](target-pronunciation-matcher-results.md)。

        ## 范围与门槛

        MATCH-07核验固定开放权重及许可；MATCH-08冻结数据谱系和完整分母；
        MATCH-09实际训练直接声学头、导出CPU包并比较。
        编码器不接收预期答案，不用汉字转写正确替代发音正确。
        线性探针和非线性头均使用真实语音预训练能力。

        原门槛保持：近邻错误放行≤5%、正确音明确误拒≤10%、
        清晰正确音拒判≤20%。拒判和不可用均保留。
        两CPU线程、四秒端到端p95≤500ms且实时率≤0.1，实际更严上限为400ms。
        预训练预算≤350M参数、≤1.5GiB权重、≤3GiB进程RSS。

        ## 实际固定模型
    """)
    model_rows = []
    for name in NAMES:
        row = report["candidates"][name]
        capability = (
            "无原生音素/四声头；比较编码器探针" if name == "sensevoice" else "原生音素/声调证据"
        )
        model_rows.append(
            [
                name,
                "`" + row["revision"] + "`",
                f"{sum(f['sizeBytes'] for f in row['weights']):,}",
                row["license"],
                capability,
            ]
        )
    table(["模型", "实际修订", "原权重字节数", "许可", "输出"], model_rows)
    add("""
        SenseVoice源码MIT与权重FunASR Model License 1.1分别保留。
        Charsiu项目MIT不能消除独立HF权重仓库未声明许可的边界。
        训练数据、维护状态与兼容代码见[核验记录](pretrained-matcher-model-audit.md)，
        固定来源和SHA见 `content/pronunciation-pretrained-models.json`。
        权重只作本地研究，不随Git再分发。

        ## 原基线实际复现
    """)
    old = report["baseline"]["reproducedOriginal370"]
    c = old["counts"]
    add(
        f"旧370段合成诊断实际复现：接受{c.get('matched', 0)}、"
        f"明确重读{c.get('retry', 0)}、拒判{c.get('uncertain', 0)}，"
        "与原记录完全一致。该集已参与研发，不能充当本轮新盲测。"
    )
    add("""
        旧模型覆盖32目标，与新训练词表不同。JSON同时保留各来源的全量及共同覆盖计数，
        不删除不可用后直接比较准确率。所有旧实现与权重保留为对照。

        ## 第一轮：ManDi同预算比较，失败保留

        固定16位训练、4位校准说话人；640个计划训练根实际使用616个，
        完整160个校准根均保留。每款都实际运行120轮，按校准损失选择检查点。
        原词典44项中只观察到40种音节声调，cai1–4没有声音。
        下表为校准诊断，不是可靠音素真值或冻结测试。
    """)
    rows = []
    for row in report["phaseOneManDi"]["trainedModels"]:
        m = row["calibration"]
        c = m["positive"]
        rows.append(
            [
                row["model"],
                row["variant"],
                f"{row['selectedEpoch']}/{row['epochsActuallyRun']}",
                c.get("matched", 0),
                c.get("retry", 0),
                c.get("uncertain", 0) + c.get("unavailable", 0),
                _percent(m["falseAcceptance"]),
            ]
        )
    table(["编码器", "读出", "选中/总轮数", "接受", "明确误拒", "拒判", "替代组合放行"], rows)
    add("全部六组均未通过原门槛。原生声学头另作诊断：")
    rows = []
    for name, row in report["phaseOneManDi"]["nativeHeads"].items():
        c = row["selected"]["counts"]
        rows.append(
            [
                name,
                row["n"],
                c.get("matched", 0),
                c.get("retry", 0),
                c.get("uncertain", 0) + c.get("unavailable", 0),
            ]
        )
    table(["原生头", "样本", "接受", "明确拒绝", "拒判"], rows)
    add("""
        SenseVoice没有原生音素/四声匹配输出，记为不适用。
        HanziFlow这份历史原生结果还使用了错误的共享舌尖韵母映射，
        后续核验确认其ii/iii与Charsiu含义相反；该原生表只保留作失败诊断。
        本轮最难反例为任何替代音素组合，含非词汇组合；
        不能直接等同于最终静态合法近邻评测。Wilson区间在JSON逐项保留。

        BEI_004_F上两个独立原生头的声母、韵母仅6/40与源标签一致。
        作者论文§3.2独立披露过任务随机转录被覆盖、与录音不符的问题，
        没有找到可核实的纠正顺序。全部声音及失败结果保留；
        没有用模型一致改标或删除该说话人。
        此风险促使下一轮转向独立专家错误标签，
        详见[数据审计](target-pronunciation-pretrained-data-audit.md)。

        ## 实际CPU端到端测量

        Mac Studio M2 Ultra，固定两推理线程；三次暖机、30次计时。
        包含WAV解码、特征、编码器、读出头和目标比较。
        四秒重复真实波形用于长度压力，不能作正确发音样本。
    """)
    rows = []
    for row in report["cpuEndToEnd"]:
        rows.append(
            [
                row["name"],
                row["backend"],
                f"{row['fourSecondWarmP95Milliseconds']:.2f}",
                f"{row['realTimeFactor']:.4f}",
                f"{row['modelLoadMilliseconds']:.1f}",
                f"{row['firstInferenceMilliseconds']:.1f}",
                f"{row['peakRssMiB']:.1f}",
                f"{row['packageBytes'] / 1024**2:.2f}",
                "通过" if row["passedLatency"] else "未通过",
            ]
        )
    table(
        ["包", "后端", "p95 ms", "实时率", "加载ms", "首推ms", "RSS MiB", "大小MiB", "延迟"], rows
    )
    add("""
        模型加载从Python和运行库已导入后开始，不能当完整命令冷启动。
        完整进程代码启动至首次结果只有旧基线实测1654.2ms，
        其他三包仍需补齐独立的完整冷启动。三预训练包均低于3GiB进程RSS；
        Charsiu当前CPU包未通过延迟。

        旧大小只计两个权重，新包计登记文件，范围不同已明示。
        各包后端不同，不能把延迟差异全部归因于编码器架构；
        量化与准确率的配对比较仍须独立报告。并发系统负载未控制。

        ## 第二轮：OMPAL专家数据与真实错误（旧边界诊断）
    """)
    ompal = report["ompalData"]
    add(f"固定版本 `{ompal['revision']}`，CC BY 4.0。")
    defect = report["phaseTwoOmpal"]["boundaryAliasDefect"]
    add(
        "**此轮边界存在已证实的模型标签语义缺陷，所有下列成绩仅作诊断。**"
        "HanziFlow上游明确定义舌尖后元音为ii、舌尖前元音为iii，"
        "Charsiu官方处理器恰好相反。旧共享映射误将Charsiu规则用于HanziFlow，"
        "影响OMPAL候选边界及三款编码器使用的共同片段。"
        "此结论来自固定上游schema，不是模型一致性推断。"
        "旧成绩完整保留；修正映射后必须重建边界、缓存并重新训练，不能用于验收。"
        f"实际HanziFlow schema SHA256：`{defect['hanziflowTargetSchemaSha256']}`。"
        "详见[标签语义核验](pretrained-matcher-model-audit.md)。"
    )
    add(
        f"已准备{ompal['clipCounts']['utterances']:,}段句子、"
        f"{ompal['clipCounts']['words']:,}个字片段。"
        "实际46位学习者按28训练、8校准、10最终预留划分，"
        "另3位母语参考只诊断。"
        f"最终{ompal['unopenedFrozenWavCountAtPreparation']}份WAV在本准备记录中未打开。"
    )
    rows = []
    for split in ("train", "calibration", "diagnostic"):
        c = ompal["splitCounts"].get(split, {})
        rows.append(
            [
                split,
                c.get("utterances", 0),
                c.get("words", 0),
                c.get("unanimous-correct", 0),
                c.get("unanimous-error", 0),
                c.get("ambiguous", 0),
                c.get("policy-unassessable", 0),
                c.get("native-reference-aggregate", 0),
            ]
        )
    table(
        ["集合", "句子", "全字记录", "一致正确", "一致错误", "专家分歧", "政策范围外", "母语参考"],
        rows,
    )
    add("""
        母语aggregate参考不冒称三位专家一致正确。
        公开detailed的65个旧篇章块经完整元数据精确匹配恢复到实际46人，
        1768条映射全部唯一。多数票只用于身份连接，正确性使用原始专家票。
        84个词汇上下文单独冻结；一/不、三声、轻声、儿化、文字备选和地区变体
        保留不可评估标记。

        字边界由同一HanziFlow已知音素CTC流程产生，三模型使用相同片段；
        它只提供候选边界，不能证明发音正确。
    """)
    add(
        f"当前{ompal['clipCounts']['weakAlignmentWords']:,}项有弱边界记录、"
        f"{ompal['clipCounts']['numericallyFlagged']}项有数值旗标，均未悄悄删除。"
    )
    add("""
        专家只评最后一次尝试，并可能宽容个别遗忘性漏字。
        这仍是成人句中语音代理任务；不能以对齐成功证明没有漏读，
        也不能证明儿童孤立拼音准确率。

        来源摘要：
    """)
    for name, key in [
        ("数据配置", "sourceConfigSha256"),
        ("句子清单", "utterancesManifestSha256"),
        ("字片段清单", "clipsManifestSha256"),
        ("评分ID映射", "detailIdMapSha256"),
        ("词汇政策v2", "pinyinPolicySha256"),
    ]:
        lines.append(f"- {name}：`{ompal[key]}`")
    lines.append("")
    if report["phaseTwoOmpal"]["models"]:
        add("""
            三编码器各自的线性和非线性读出都已实际运行120轮，
            使用同一专家部分监督数据和校准流程。六组均未通过原质量门槛，
            本报告后文记录已完成的追加优化；最终测试没有启用作验收。
            专家标错只降低目标分量概率，不为真实错音编造替代音素。
        """)
    else:
        add("""
            本快照尚未发布第二轮三编码器的专家部分监督训练及后续优化。
            完整同预算结果由生成器显式 `--include-phase-two` 后追加，
            未完成模型不填推测数字。专家标错只降低目标分量概率，
            不为真实错音编造替代音素。
        """)
    if report["phaseTwoOmpal"]["models"]:
        rows = []
        for row in report["phaseTwoOmpal"]["models"]:
            m, c = row["calibration"], row["calibration"]["positive"]
            rows.append(
                [
                    row["model"],
                    row["variant"],
                    row["epochsActuallyRun"],
                    c.get("matched", 0),
                    c.get("retry", 0),
                    c.get("uncertain", 0) + c.get("unavailable", 0),
                    _percent(m["falseAcceptance"]),
                ]
            )
        table(["编码器", "读出", "实际轮数", "校准接受", "明确误拒", "拒判", "最难错误放行"], rows)
    if report["phaseTwoOmpal"]["cpuEndToEndDiagnostic"]:
        add("旧边界诊断头的完整CPU包也已实际运行；以下运行时在别名配置修正前加载：")
        rows = []
        for row in report["phaseTwoOmpal"]["cpuEndToEndDiagnostic"]:
            rows.append(
                [
                    row["name"],
                    row["backend"],
                    f"{row['fourSecondWarmP95Milliseconds']:.2f}",
                    f"{row['realTimeFactor']:.4f}",
                    f"{row['modelLoadMilliseconds']:.1f}",
                    f"{row['firstInferenceMilliseconds']:.1f}",
                    f"{row['peakRssMiB']:.1f}",
                    f"{row['packageBytes'] / 1024**2:.2f}",
                ]
            )
        table(
            ["诊断包", "后端", "p95 ms", "实时率", "加载ms", "首推ms", "RSS MiB", "大小MiB"],
            rows,
        )
        add("修正边界后的模型及进一步优化包仍须重新测量，此表不证明最终效果或性能达标。")
    phase_three = report["phaseThreeCorrectedOmpal"]
    if phase_three["models"]:
        add("""
            ## 第三轮：修正标签映射后重建并重新训练

            HanziFlow舌尖后ii/舌尖前iii已按固定上游schema修正。
            统一重建边界与缓存后，三编码器的线性和非线性头各实际运行120轮，
            六组仍未通过原质量门槛。此处不使用旧边界结果作模型优劣结论。
        """)
        add(f"新片段清单SHA256：`{phase_three['manifestSha256']}`。")
        rows = []
        for row in phase_three["models"]:
            m, c = row["calibration"], row["calibration"]["positive"]
            rows.append(
                [
                    row["model"],
                    row["variant"],
                    row["epochsActuallyRun"],
                    c.get("matched", 0),
                    c.get("retry", 0),
                    c.get("uncertain", 0) + c.get("unavailable", 0),
                    _percent(m["falseAcceptance"]),
                ]
            )
        table(["编码器", "读出", "实际轮数", "校准接受", "明确误拒", "拒判", "最难错误放行"], rows)
        comparison = phase_three["nativeComparison"]
        c = comparison["counts"]
        add(
            f"HanziFlow另实际训练{comparison['epochsActuallyRun']}轮157维原生声学比较头，"
            "使用完整原生CTC声学证据及F0，目标仅在编码后进入比较。"
            f"校准正确音接受/明确误拒/拒判为{c['positive']['matched']}/"
            f"{c['positive']['explicitReject']}/{c['positive']['abstention']}；"
            f"任一近邻目标放行为{c['errorStrata']['counterfactual-any']['falseAccept']}/"
            f"{c['errorStrata']['counterfactual-any']['n']}，"
            f"专家实际错音放行为{c['errorStrata']['expert-any']['falseAccept']}/"
            f"{c['errorStrata']['expert-any']['n']}。仍未达标。"
        )
        stress = phase_three["stressCalibration"]
        raw_native = phase_three["rawNativeComponentDiagnostics"]
        if raw_native:
            unavailable = raw_native["allCalibrationRows"] - raw_native["availableRows"]
            add(
                "HanziFlow原始三头也在完整4202个校准字上实际诊断；"
                f"{raw_native['availableRows']}项可计算、"
                f"{unavailable}项预先标为不可评估。"
                "专家分量正确且可计算者，原生单标签最大质量与期待类一致："
                "声母2103/2991、韵母1838/3041、声调1470/2345。"
                "这里保留可用性分母及所有专家分歧，不把可计算子集的一致率称为完整质量准确率。"
            )
        fine = phase_three["finetunedEncoderTraining"]
        if fine:
            selected = next(row for row in fine["history"] if row["epoch"] == fine["selectedEpoch"])
            add(
                "后续对HanziFlow最后两个编码层与三原生头完成10轮真实MPS微调，"
                f"耗时{fine['history'][-1]['elapsedSeconds']:.1f}秒，按校准signed CTC选第"
                f"{fine['selectedEpoch']}轮：损失从{fine['history'][0]['balancedSignedCtcLoss']:.3f}"
                f"至{selected['balancedSignedCtcLoss']:.3f}。"
                f"{fine['changedTrainableTensors']}个可训练张量实际改变，冻结张量逐项完全相同。"
                "这些是训练及模型选择证据，不能代替接受/误拒/拒判质量门槛；"
                "微调模型的最终CPU包效果仍待验证。"
            )
        tuned_native = phase_three["finetunedNativeComponentDiagnostics"]
        if raw_native and tuned_native:
            rows = []
            for component in ("onset", "rime", "tone"):
                raw_component = raw_native["components"][component]["unanimous-correct"]
                tuned_component = tuned_native["components"][component]["unanimous-correct"]
                if raw_component["available"] != tuned_component["available"]:
                    raise ValueError("NATIVE_DIAGNOSTICS_DENOMINATORS_CHANGED")
                rows.append(
                    [
                        component,
                        raw_component["allExpertRows"],
                        raw_component["available"],
                        raw_component["expectedIsBestSingleLabel"],
                        tuned_component["expectedIsBestSingleLabel"],
                        raw_component["unassessable"],
                    ]
                )
            add("相同4202个校准字的原生声学分量诊断已重跑，微调后仍有1057项不可评估：")
            table(
                [
                    "分量",
                    "专家正确全分母",
                    "可计算",
                    "原始期待类最大",
                    "微调期待类最大",
                    "不可评估",
                ],
                rows,
            )
            add("这是同一校准集上的声学诊断改善；没有阈值接受/拒绝判定，不代表完整质量门槛通过。")
        tuned_comparison = phase_three["finetunedNativeComparison"]
        if tuned_comparison:
            c = tuned_comparison["counts"]
            add(
                f"微调后又实际训练{tuned_comparison['epochsActuallyRun']}轮原生比较头，"
                f"选第{tuned_comparison['selectedEpoch']}轮。2239正确音为"
                f"{c['positive']['matched']}接受、{c['positive']['explicitReject']}明确误拒、"
                f"{c['positive']['abstention']}拒判；"
                f"任一近邻放行{c['errorStrata']['counterfactual-any']['falseAccept']}/2239，"
                f"专家实际错音放行{c['errorStrata']['expert-any']['falseAccept']}/188。"
                "接受覆盖改善，但近邻错误放行、明确误拒和拒判仍未通过原门槛，"
                "因此继续保留失败，不能称优化模型已经达标。"
            )
        swift = phase_three["swiftF0ToneExperiment"]
        if isinstance(swift, dict):
            prepared = swift["preparation"]
            add(
                "另已实际完成固定MIT SwiftF0图的真实语音特征准备："
                f"{prepared['counts']['rows']}个训练/校准字根完整保留，"
                f"{prepared['counts']['available']}项有可用F0特征，弱voicing及静音等旗标保留。"
                "未读取诊断或最终音频；尚无完成的声调头比较，不能宣称改善。"
            )
        if stress:
            add("""
                同轮另用24段真实专家一致正确校准片段、8位说话人进行输入挑战。
                三款包共享同24段；72个双音节波形由这些声音拼接，
                重复目标查询按实际波形去重，仍非72个独立说话根。
            """)
            rows = []
            for name in NAMES:
                c = stress["models"][name]["overallByExpectedBehavior"]
                control, double, invalid = c["accept"], c["do-not-match"], c["abstain"]
                rows.append(
                    [
                        name,
                        control["matchedUnits"]["count"],
                        control["explicitRetryUnits"]["count"],
                        control["abstentionUnits"]["count"],
                        f"{double['matchedUnits']['count']}/{double['actualPayloadUnits']}",
                        f"{invalid['abstentionUnits']['count']}/{invalid['actualPayloadUnits']}",
                    ]
                )
            table(
                ["CPU包", "正确音接受/24", "明确误拒/24", "拒判/24", "双音节放行", "不可评估拒判"],
                rows,
            )
            add("""
                三款对170个去重的不可评估波形均拒判，没有明确判错。
                SenseVoice双音节3/72放行虽为4.17%，Wilson95%上界约11.55%；
                HanziFlow/Charsiu的0/72上界也约5.07%。样本来自24个相关源根，
                这只是校准挑战，不能据点估计宣布多读/漏读通过。
                完整类型、分母、选择排除与区间保留在JSON。
            """)
        baseline_v2 = phase_three["preservedBaselineV2"]
        if baseline_v2:
            b = baseline_v2["benchmark"]
            add(
                f"保留旧基线在三来源4732个原决策上逐项重现。"
                f"隔离测量四秒CPU p95 {b['fourSecondWarmP95Milliseconds']:.2f}ms、"
                f"RSS {b['peakRssMiB']:.2f}MiB，权重2,730,431字节。"
                "首份v2测量混入大评测JSON的RSS保留作仪器诊断，采用-repro记录。"
                "它仅覆盖当前4202个校准字中的218个：2239个专家正确音为"
                "21接受、7明确误拒、126拒判、2085不可用；188个专家错音"
                "为0接受、8拒判、180不可用。不能将狭窄覆盖下的0放行视为达标。"
            )
        if phase_three["cpuFullCalibration"]:
            add("三款最终CPU路径在完整4202个校准字记录上实际运行，包含不可评估记录：")
            rows = []
            for row in phase_three["cpuFullCalibration"]:
                m = row["metrics"]
                rows.append(
                    [
                        row["model"],
                        row["rows"],
                        m["positive"]["n"],
                        m["positive"]["accepted"]["count"],
                        m["positive"]["explicitReject"]["count"],
                        m["positive"]["abstention"]["count"],
                        f"{m['negativeOriginStrata']['counterfactual']['falseAccept']['count']}/"
                        f"{m['negativeOriginStrata']['counterfactual']['n']}",
                        f"{m['negativeOriginStrata']['expert']['falseAccept']['count']}/"
                        f"{m['negativeOriginStrata']['expert']['n']}",
                        m["ambiguous"]["roots"],
                    ]
                )
            table(
                [
                    "CPU模型",
                    "全字",
                    "正确音分母",
                    "接受",
                    "明确误拒",
                    "拒判",
                    "近邻任一放行",
                    "专家错音放行",
                    "含糊",
                ],
                rows,
            )
            add(
                "近邻与专家实际错音分别完整记账，各自按原根的任一目标放行计失败，"
                "并逐类检查门槛，不把不同来源混合稀释。完整分层Wilson区间、"
                "说话人bootstrap与样本量门禁保留在JSON；本表仍是校准诊断。"
                "本轮只从原实际records重算分母及补回清单音色/参考谱系，"
                "原SHA、原统计及所有决策均保留，没有更改发音标签。"
                "原HanziFlow/Charsiu评测已原子写完4202条结果，随后驱动shell因执行期间"
                "源文件改变出现解析错误，退出2，不能称其整条命令成功退出。"
                "新增直接Python验证产物按-verified单独保留，JSON逐模型标注是否已采用。"
            )
        else:
            add("三个CPU包的完整校准推理尚未全部结束；在齐备前不填部分或推测比较表。")
        add("""
            本报告列出的比较与优化轮次已实际运行，其校准质量仍失败。
            中间训练损失不代替匹配质量；保留的最终测试没有启用作验收。
        """)
    phase_four = report["phaseFourOptimizedHeads"]
    if phase_four["models"]:
        add("""
            ## 第四轮：微调读出与独立声调特征继续优化

            下列各组均实际训练120轮，使用相同修正边界的训练/校准根。
            HanziFlow微调后的线性/非线性读出，与原始/微调编码器加SwiftF0的读出，
            单独作为追加优化记录；不能冒称原始三款获得同样追加预算。
        """)
        rows = []
        for row in phase_four["models"]:
            m, c = row["calibration"], row["calibration"]["positive"]
            rows.append(
                [
                    row["model"],
                    row["variant"],
                    row["selectedEpoch"],
                    c.get("matched", 0),
                    c.get("retry", 0),
                    c.get("uncertain", 0) + c.get("unavailable", 0),
                    _percent(m["falseAcceptance"]),
                ]
            )
        table(["编码器", "追加读出", "选中轮次", "接受", "明确误拒", "拒判", "最难错误放行"], rows)
        if phase_four["allCompletedExperimentsFailedPointGates"]:
            add("本轮所有已完成模型仍未通过原质量点估计门槛，失败完整保留。")
        swift = phase_four["reliableSwiftF0CorrectCalibration"]
        add(
            f"要求可靠F0的Swift实验，在{swift['allCorrectRoots']}个正确校准根中仅"
            f"{swift['pitchAvailable']}个有可用证据，强制拒判下界"
            f"{_percent(swift['abstentionLowerBound'])}已超过20%。"
            "未据此调低voicing标准，这个版本不能作为达到拒判门槛的候选。"
            "其他直接声学路径分别保留；更可靠的F0不能自动视为更好的声调判断。"
        )
        if not report["reportGeneration"]["phaseFiveIncluded"]:
            add("本快照尚未发布SenseVoice主50层新音素头及其CPU验证结果，不预填数值。")
    phase_five = report["phaseFiveFullFourToneCoverage"]
    if report["reportGeneration"]["phaseFiveIncluded"]:
        add("""
            ## 第五轮：补齐同音节四声目标，实测直接CTC与新音素头

            冻结之前发现目标覆盖缺口：旧549目标只包含观察到的声调及小目录，
            在2239个正确校准根中，仅1566个根实际测过同音节不同声调。
            旧各轮数据与结果完整保留为诊断，不据此验收四声近邻能力。
            新协议将训练中出现的合法音节base各扩为1—4声，共1208目标，
            声调近邻覆盖全部2239个正确根；不任意组合未见过的声母/韵母。
            门槛没有降低，最终测试没有用于修补或选择。
        """)
        trained = phase_five["sensevoicePhoneticTraining"]
        add(
            "SenseVoice追加优化实际保留主干50层，省去20个任务层；冻结前44层，"
            "训练末6层、归一化及新随机初始化的声母/韵母/声调CTC头。"
            f"共{trained['actualTrainingEpochs']}轮（2轮仅头部预热及10轮尾层微调），"
            f"选中第{trained['selectedEpoch']}轮。"
            f"共有{trained['parameterCount']:,}个参数；全部冻结张量与源权重逐个相同，"
            f"实际改变{trained['changedEncoderTensors']}个编码器张量及"
            f"{trained['changedPhoneticHeadTensors']}个新头张量。"
            "这是本项目训练的新音素头，原始SenseVoice依然没有原生音素/声调输出；"
            "损失下降和分量诊断不等于发音匹配质量达标。"
        )
        add("""
            直接CTC匹配不再训练下游读出：声学输出计算全部原生类别的单标签事件，
            保留空白、未知、多读及目录外概率质量，不按已知目标重新归一化。
            从15个预先声明的概率/间隔组合中，仅在校准集选择参数。
            下表保留全部正确音分母，错误按同一音频任一近邻放行计一次失败；
            专家实际错音与正确音反事实目标分别报告，不能互相稀释。
        """)
        rows = []
        for row in phase_five["directCTC"]:
            m = row["metrics"]
            p = m["positive"]
            cf = m["negativeOriginStrata"]["counterfactual"]["falseAccept"]
            expert = m["negativeOriginStrata"]["expert"]["falseAccept"]
            rows.append(
                [
                    row["model"],
                    row["coveredTargets"],
                    p["accepted"]["count"],
                    p["explicitReject"]["count"],
                    p["abstention"]["count"],
                    f"{cf['count']}/{cf['n']} ({_percent(cf['rate'])})",
                    f"{expert['count']}/{expert['n']} ({_percent(expert['rate'])})",
                    "通过" if m["gates"]["passesPointEstimates"] else "失败",
                ]
            )
        table(
            [
                "直接CTC编码器",
                "目标数",
                "正确接受/2239",
                "明确误拒/2239",
                "拒判/2239",
                "任一近邻错误放行",
                "专家实际错音放行",
                "原质量点门槛",
            ],
            rows,
        )
        if phase_five["models"]:
            rows = []
            for row in phase_five["models"]:
                m = row["metrics"]
                p = m["positive"]
                cf = m["negativeOriginStrata"]["counterfactual"]["falseAccept"]
                expert = m["negativeOriginStrata"]["expert"]["falseAccept"]
                rows.append(
                    [
                        row["model"],
                        p["accepted"]["count"],
                        p["explicitReject"]["count"],
                        p["abstention"]["count"],
                        f"{cf['count']}/{cf['n']}",
                        f"{expert['count']}/{expert['n']}",
                        "重新比较已有CPU概率"
                        if row.get("encoderAndHeadReexecuted") is False
                        else "完整CPU波形推理",
                    ]
                )
            add(
                "四声目标更新后的三款原编码器与优化包严格根分母如下；原始模型资源和阈值保持原记录："
            )
            table(
                [
                    "版本",
                    "接受/2239",
                    "明确误拒/2239",
                    "拒判/2239",
                    "任一近邻放行",
                    "实际专家错误放行",
                    "执行证据",
                ],
                rows,
            )
        if phase_five["trainedSensevoiceReadouts"]:
            rows = []
            for row in phase_five["trainedSensevoiceReadouts"]:
                m = row["calibration"]
                p = m["positive"]
                rows.append(
                    [
                        row["variant"],
                        row["epochsActuallyRun"],
                        p.get("matched", 0),
                        p.get("retry", 0),
                        p.get("uncertain", 0) + p.get("unavailable", 0),
                        _percent(m["falseAcceptance"]),
                    ]
                )
            add("SenseVoice50新音素头之后，追加同训练/校准集合的三种120轮读出实测：")
            table(
                [
                    "追加读出",
                    "实际轮数",
                    "接受/2239",
                    "明确误拒/2239",
                    "拒判/2239",
                    "最难错误类型放行",
                ],
                rows,
            )
            add("三个新增读出均仍未达到全部质量门槛；完整CPU管线数据另报。")
        add(
            "两个直接CTC版本仍未通过：同音节四声补齐后，声调近邻及整体近邻放行暴露更多错误，"
            "正确音误拒和拒判也超过限制。Wilson区间、说话人bootstrap、各错误类型、"
            "1775个原始不明确/不可评估标签根的状态均保留在JSON。"
            "完整CPU波形评测与共同四秒计时分别记录，未完成的项目不预填结果。"
        )
        for row in phase_five["directCTC"]:
            errors = row["nativeEventErrorBreakdown"]
            causes = errors["rootCounts"]
            add(
                f"{row['model']}的{errors['allCorrectRoots']}个专家全对校准根中，"
                f"{causes['atLeastOneExpectedComponentNotNativeBest']}个至少有一分量"
                "原生单标签best与预期不同；"
                f"{causes['forceUncertainByCompleteNativeEvents']}个被空白、多标签或未知等"
                "完整事件保护强制拒判。原因可重叠，逐音素/声调混淆与说话人计数见JSON；"
                "不能仅降低阈值解决。"
            )
        stress = phase_five["sameAnchorStress"]
        if len(stress["models"]) == 8:
            add("""
                ### 原始与优化后八包的同音频压力对照

                八包均实际单独进程、CPU两线程运行。24个正确控制锚ID与旧轮完全相同，
                全部312个病例的payload SHA逐个相同，没有加入新独立样本。
                二词拼接按72个原始波形任一构成目标被接受记一次放行；
                噪声、静音漏读、坏格式等按170个去重不可评估输入分别记录。
            """)
            rows = []
            for row in stress["models"]:
                counts = row["overallByExpectedBehavior"]
                good = counts["accept"]
                multi = counts["do-not-match"]["matchedUnits"]
                bad = counts["abstain"]
                rows.append(
                    [
                        row["model"],
                        good["matchedUnits"]["count"],
                        good["explicitRetryUnits"]["count"],
                        good["abstentionUnits"]["count"],
                        f"{multi['count']}/{multi['denominator']}",
                        bad["matchedUnits"]["count"],
                        bad["explicitRetryUnits"]["count"],
                    ]
                )
            table(
                [
                    "包",
                    "正确接受/24",
                    "明确误拒/24",
                    "拒判/24",
                    "二词放行",
                    "不可评估被接受/170",
                    "不可评估被明确判错/170",
                ],
                rows,
            )
            add(
                "HanziFlow微调比较头二词放行13/72，且把3个不可评估输入明确判错；"
                "SenseVoice50直接CTC也将1个不可评估输入明确判错。失败完整保留。"
                "0/72的Wilson95上界仍为5.07%，这些相关病例也不能证明人群错误放行率≤5%。"
                "这轮属于校准压力诊断，既非自然多读/漏读发音真值，也非冻结或儿童验收。"
            )
        isolated = phase_five["isolatedCorpusResearch"]
        add(
            "公开孤立四声数据源的追加核验尚未找到同时具备多说话人、自然孤立音、"
            "独立音素正确性检查、明确音频许可和固定可下载文件的验收语料。"
            "HVPT公开仓库仅行为数据；另有逐调清晰语音只承诺按请求提供；"
            "896条孤立WAV来源缺少明确音频许可；Shtooka两名原录音者素材有许可，"
            "但没有独立分量正确性评级，仅可作补充诊断。"
            "本轮调查没有改变训练/校准/测试划分，也没有打开保留测试音频。"
        )
        if isolated["existingSplitsChanged"] or isolated["reservedAudioOpened"]:
            raise ValueError("ISOLATED_CORPUS_AUDIT_CHANGED_RESERVED_SCOPE")
        quantized = phase_five["sensevoiceInt8CTC"]
        if quantized.get("fullCpuCalibration"):
            measured = quantized["fullCpuCalibration"]["metrics"]
            p = measured["positive"]
            cf = measured["negativeOriginStrata"]["counterfactual"]["falseAccept"]
            actual = measured["negativeOriginStrata"]["expert"]["falseAccept"]
            add("""
                ### SenseVoice50完整CTC图的实际INT8量化

                实际导出50层编码器和三个新CTC头，ORT只使用本机CPU两线程。
                原FP32父模型与阈值保持不变，量化包绑定父元数据/权重SHA、词表和许可。
                小规模数值对照中单标签CTC事件概率最大差约0.0291，不能推断匹配质量保持。
                因此另行实际运行全部4202校准根及相同压力音频。
            """)
            add(
                f"量化CPU包为{quantized['packageBytes']:,}字节；正确音"
                f"{p['accepted']['count']}接受、{p['explicitReject']['count']}明确误拒、"
                f"{p['abstention']['count']}拒判，分母始终2239。"
                f"任一近邻错误放行{cf['count']}/{cf['n']}（{_percent(cf['rate'])}），"
                f"专家实际错音放行{actual['count']}/{actual['n']}（{_percent(actual['rate'])}）。"
                f"4202个原目标查询有{quantized['truthQueryStatusChangesFromFp32']}个状态与"
                "FP32不同；质量门槛仍失败，不能宣称量化保持全部判定或已达标。"
            )
            if quantized.get("stressCalibration"):
                counts = quantized["stressCalibration"]["overallByExpectedBehavior"]
                good, multi, bad = (counts[key] for key in ("accept", "do-not-match", "abstain"))
                add(
                    f"INT8另用包含第9包的新压力清单，仍与原8包的24锚及全部312病例"
                    "payload SHA逐个相同，旧清单与旧结果保持原样。"
                    f"正确控制{good['matchedUnits']['count']}/24接受、"
                    f"{good['explicitRetryUnits']['count']}/24误拒、"
                    f"{good['abstentionUnits']['count']}/24拒判；二词"
                    f"{multi['matchedUnits']['count']}/72放行；170不可评估输入"
                    f"{bad['matchedUnits']['count']}被接受、"
                    f"{bad['explicitRetryUnits']['count']}被明确判错。"
                    "不可评估误判仍须保留为失败。"
                )
        cpu_round = phase_five["completePipelineCpu"]
        if cpu_round:
            if phase_five["originalPressureGuardFailure"]:
                add("""
                    原先与旧基线共用的重复词压力 `f0f4fa64…00e69`，被当前完整运行时的
                    `MULTIPLE_SEPARATED_SPEECH_REGIONS` 保护提前拒判。
                    九包暖机/冷启动共18组命令全部真实失败，日志和失败JSON保留，
                    没有把绕过编码器的耗时当性能。没有关闭guard或修改超时限制。
                    改用自然连续校准父句的原PCM四秒窗，单纯按数值guard选取，未查看识别结果：
                    OMPAL `ompal-00200706` 原帧 `[28000,92000)`，无重采样或重复，
                    新payload SHA
                    `6d2ecbfa74b82a45326b7de100395406283db5ea35f1e5ce50b92197018f1cfc`。
                    原32目标基线也实际重跑完全相同的新bytes。
                """)
            add("""
                ### 统一四秒原始bytes的完整CPU性能

                等训练与完整评测结束后，逐包顺序运行。所有新包使用同一固定四秒WAV原始bytes，
                CPU两线程；3次暖机后计30次，覆盖解码、前端、编码器、读出和目标比较。
                每次计时断言实际进入编码器。冷启动另启5个独立Python进程，包含导入、
                资源完整性核验、模型加载、完整推理和CLI退出；未清空操作系统文件缓存。
                暖机p95≤500ms与实时率≤0.1同时要求四秒p95≤400ms。
            """)
            rows = []
            baseline_cpu = phase_five["baselineContinuousCpu"]["warm"]
            baseline_cold = phase_five["baselineContinuousCpu"]["cold"]
            rows.append(
                [
                    "保留原32目标基线",
                    f"{baseline_cpu['fourSecondWarmP95Milliseconds']:.2f}",
                    f"{baseline_cpu['realTimeFactor']:.4f}",
                    f"{baseline_cold['freshProcessWallP95Milliseconds']:.1f}",
                    f"{baseline_cpu['peakRssMiB']:.1f}",
                    f"{baseline_cpu['weightBytes'] / 1024**2:.2f}",
                    "通过",
                ]
            )
            for row in cpu_round:
                warm, cold = row["warm"], row["cold"]
                rows.append(
                    [
                        row["model"],
                        f"{warm['fourSecondWarmP95Milliseconds']:.2f}",
                        f"{warm['realTimeFactor']:.4f}",
                        f"{cold['freshProcessWallP95Milliseconds']:.1f}" if cold else "未发布",
                        f"{warm['peakRssMiB']:.1f}",
                        f"{warm['packageBytes'] / 1024**2:.2f}",
                        "通过" if warm["passedLatency"] else "失败",
                    ]
                )
            table(
                [
                    "CPU包",
                    "暖机p95 ms",
                    "实时率",
                    "独立进程冷启动p95 ms",
                    "峰值RSS MiB",
                    "资源MiB",
                    "联合延迟门槛",
                ],
                rows,
            )
            add(
                "加载与首推耗时、30次原始计时、5个独立进程明细及所有权重/元数据SHA见JSON和"
                "绑定的本地结果。此处只证明固定压力音频的性能；连续四秒真实语音没有发音正确性标签，"
                "性能达标不改变上述匹配质量失败和儿童验证缺口。"
            )
    add("""
        ## 剩余门禁与复现

        比较与本报告列出的优化轮次已实际完成，原质量门槛仍失败，
        整体质量目标尚未完成。最终测试保留未启用，不能称冻结验收通过。
        后续需要有独立发音真值的数据与进一步模型改进；符合条件后再冻结模型、
        参数、代码和测试清单，报告近邻完整分母、区间、真实多读/漏读与噪声挑战。
        CPU冷启动、延迟与内存已实际报告；Charsiu仍未达到实时率门槛。
        没有独立儿童验证时不宣称儿童达标。

        安装、准备、训练、导出、CPU CLI及冻结评测见
        [工具文档](../engineering/pretrained-pronunciation-matcher.md)。
        重建本报告：

        ```sh
        ./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_report
        # 六个第二轮训练产物完成后才加入其真实校准表
        ./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_report \\
          --include-phase-two
        # 修正边界后三款同预算模型和原生比较头完成后追加真实第三轮
        ./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_report \\
          --include-phase-three
        # 微调读出与独立声调特征的已完成优化轮次
        ./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_report \\
          --include-phase-four
        # 完整四声目标与新SenseVoice音素头、直接CTC真实校准
        ./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_report \\
          --include-phase-five
        ```
    """)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-phase-two", action="store_true")
    parser.add_argument("--include-phase-three", action="store_true")
    parser.add_argument("--include-phase-four", action="store_true")
    parser.add_argument("--include-phase-five", action="store_true")
    parser.add_argument("--output-json", type=Path, default=RESULT)
    parser.add_argument("--output-markdown", type=Path, default=RESULT.with_suffix(".md"))
    args = parser.parse_args()
    report = collect(
        include_phase_two=args.include_phase_two or args.include_phase_three,
        include_phase_three=args.include_phase_three,
        include_phase_four=args.include_phase_four,
        include_phase_five=args.include_phase_five,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    args.output_markdown.write_text(markdown(report))
    print(
        json.dumps(
            {
                "json": str(args.output_json),
                "markdown": str(args.output_markdown),
                "sourceArtifacts": len(report["sourceArtifacts"]),
                "phaseTwoIncluded": report["reportGeneration"]["phaseTwoIncluded"],
                "phaseThreeIncluded": report["reportGeneration"]["phaseThreeIncluded"],
                "phaseFourIncluded": report["reportGeneration"]["phaseFourIncluded"],
                "phaseFiveIncluded": report["reportGeneration"]["phaseFiveIncluded"],
            }
        )
    )


if __name__ == "__main__":
    main()
