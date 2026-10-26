"""Collect calibration branch evidence once per raw WAV and enumerate fixed gates.

Only public covered targets contribute positive acceptance cases. Other explicitly
labelled syllables can supply counterexamples without becoming public capabilities.
This tool never loads test rows, selects test thresholds or edits model metadata.
"""

import argparse
import json
import shutil
from pathlib import Path

from pinyin_matcher.audio import AudioRejected, decode_wav, features
from pinyin_matcher.catalog import fingerprint, targets_by_id
from pinyin_matcher.data import read_manifest
from pinyin_matcher.decision_v3 import _thresholds, calibrate
from pinyin_matcher.foreign_data import read_manifest as read_foreign_manifest
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.inference import PinyinMatcher
from pinyin_matcher.quality import (
    PROTOCOL_SHA256,
    PROTOCOL_VERSION,
    _lineage,
    assert_protocol,
    coverage_metrics,
)


def training_lineage_check(metadata: dict, records: list[dict]) -> dict:
    """Check train rows only, including parents hidden behind converted waveforms."""
    provenance = metadata.get("dataProvenance", {})
    sources, missing, errors = {}, [], []
    for kind in ("synthetic", "standard"):
        path = provenance.get(kind + "ManifestPath")
        digest = provenance.get(kind + "ManifestSha256")
        if path and digest:
            sources[str(path)] = digest
        else:
            missing.append(kind + "ManifestPath/Sha256")
    for field in ("derivedManifestSha256", "foreignManifestSha256"):
        values = provenance.get(field, {})
        if not isinstance(values, dict):
            raise ValueError("MODEL_TRAINING_PROVENANCE_INVALID")
        sources.update(values)
    lineage, lexical, checked = set(), set(), {}
    for filename, expected in sources.items():
        path = Path(filename)
        if not path.is_file() or fingerprint(path) != expected:
            errors.append({"path": filename, "reason": "TRAINING_MANIFEST_MISSING_OR_CHANGED"})
            continue
        data = json.loads(path.read_text())
        # A derived input may include calibration rows; they were never trained.
        train = [row for row in data.get("items", []) if row.get("split") == "train"]
        for row in train:
            lineage.update(_lineage(row))
            if row.get("kind") == "foreign-contrast" and row.get("lexicalRootId"):
                lexical.add(row["lexicalRootId"])
        checked[filename] = {"sha256": expected, "trainRows": len(train)}
    overlaps = sorted(
        {
            row["unitId"]
            for row in records
            if _lineage(row) & lineage
            or row.get("case") == "cross-language-acoustic-mismatch"
            and row.get("lexicalRootId") in lexical
        }
    )
    return {
        "complete": not missing and not errors,
        "missing": missing,
        "errors": errors,
        "checkedManifests": checked,
        "overlapRawUnitIds": overlaps,
        "calibrationRowsInTrainingInputsWereExcluded": True,
    }


def _distance(first: list[str], second: list[str]) -> int:
    previous = list(range(len(second) + 1))
    for index, phone in enumerate(first, 1):
        current = [index]
        for other_index, other in enumerate(second, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[other_index] + 1,
                    previous[other_index - 1] + (phone != other),
                )
            )
        previous = current
    return previous[-1]


def near_targets(actual: dict, public: dict, *, limit=6) -> list[dict]:
    """Fixed target-catalogue neighbors; model predictions never choose negatives."""
    if type(limit) is not int or not 1 <= limit <= 6:
        raise ValueError("NEAR_TARGET_LIMIT_MUST_BE_ONE_TO_SIX")
    preferred = actual.get("neighbors", [])
    ordered = sorted(
        (target for target in public.values() if target["phones"] != actual["phones"]),
        key=lambda target: (
            0 if target["id"] in preferred else 1,
            preferred.index(target["id"])
            if target["id"] in preferred
            else _distance(actual["phones"], target["phones"]),
            target["id"],
        ),
    )
    selected, phones = [], set()
    for target in ordered:
        key = tuple(target["phones"])
        if key not in phones:
            selected.append(target)
            phones.add(key)
        if len(selected) == limit:
            break
    return selected


def _rows(manifest: Path, kind: str) -> list[dict]:
    data = json.loads(manifest.read_text())
    if kind == "speech":
        # Validate all lineage metadata without opening any test WAVs.
        rows = [
            row
            for row in read_manifest(manifest, verify_audio=False)
            if row["split"] == "calibration"
        ]
    elif kind == "foreign":
        if any(row.get("split") != "calibration" for row in data["items"]):
            raise ValueError("FOREIGN_CALIBRATION_ONLY_NO_TRAIN_OR_TEST")
        rows = read_foreign_manifest(manifest)
    else:
        rows = data["items"]
        if any(
            row.get("split") != "calibration"
            or row.get("expectedMatch") is not False
            or row.get("case") != "non-speech"
            for row in rows
        ):
            raise ValueError("NON_SPEECH_CALIBRATION_CONTRACT_REQUIRED")
    if not rows:
        raise ValueError("CALIBRATION_ROWS_REQUIRED")
    selected = []
    for row in rows:
        path = (manifest.parent / row["file"]).resolve()
        if not path.is_relative_to(manifest.parent.resolve()) or fingerprint(path) != row["sha256"]:
            raise ValueError("CALIBRATION_AUDIO_DIGEST_MISMATCH")
        selected.append(
            {
                **row,
                "path": str(path),
                "manifest": str(manifest),
                "manifestLabelProvenance": data.get("labelProvenance"),
            }
        )
    return selected


def collect_records(
    matcher, inputs: list[tuple[Path, str]], *, near_limit=6
) -> tuple[list[dict], dict]:
    public = {key: matcher.targets[key] for key in matcher.metadata["coveredTargetIds"]}
    if not public:
        raise ValueError("PUBLIC_TARGETS_REQUIRED")
    targets = {**targets_by_id(), **matcher.targets}
    initial_target = sorted(public)[0]
    cache, seen, records, input_counts, exclusions = {}, set(), [], {}, []

    def measured(row):
        if row["sha256"] not in cache:
            try:
                samples = decode_wav(Path(row["path"]).read_bytes())
                acoustic, quality = features(samples)
                evidence = matcher._branch_evidence(acoustic, samples, initial_target)
                cache[row["sha256"]] = {**evidence, "legacyFeatureQuality": quality}
            except AudioRejected as error:
                cache[row["sha256"]] = {
                    "available": True,
                    "predictedPhones": [],
                    "predictedTone": None,
                    "pitchReliable": False,
                    "toneProbability": 0.0,
                    "contentMargin": 0.0,
                    "freeCtcAdvantage": 0.0,
                    "audioRejectionReason": str(error),
                }
            except Exception as error:
                cache[row["sha256"]] = {
                    "available": False,
                    "evidenceError": type(error).__name__ + ": " + str(error)[:500],
                }
        return cache[row["sha256"]]

    def record(row, evidence, target, case, expected, source, *, suffix=None, **extra):
        lineage = {
            key: row[key]
            for key in (
                "voiceFamilyId",
                "referenceRootId",
                "referenceSha256",
                "sourceRootId",
                "parentRootId",
                "parentSha256",
                "sourceSha256",
                "sourceWavSha256",
                "sourcePhoneticGroup",
                "generationMode",
                "generator",
                "generatorRevision",
                "labelProvenance",
                "derivedFromStandard",
                "lexicalRootId",
                "language",
                "contrastCategory",
                "phoneticDifference",
            )
            if key in row
        }
        records.append(
            {
                **evidence,
                **lineage,
                "id": row["id"] + "::" + case + "::" + (suffix or target["id"]),
                "unitId": row["id"],
                "rawAudioId": row["id"],
                "sha256": row["sha256"],
                "source": source,
                "case": case,
                "split": "calibration",
                "targetId": target["id"],
                "targetPhones": target["phones"],
                "targetTone": target["tone"],
                "targetPubliclyCovered": target["id"] in public,
                "expectedMatch": expected,
                "clearAudio": bool(row.get("clearAudio", source != "mechanical-non-speech")),
                "sourceManifest": row["manifest"],
                "sourceLabelProvenance": row.get("manifestLabelProvenance"),
                **extra,
            }
        )

    for manifest, kind in inputs:
        rows = _rows(manifest, kind)
        input_counts[str(manifest)] = len(rows)
        for row in rows:
            identity = (row["id"], row["sha256"])
            if identity in seen:
                continue
            seen.add(identity)
            evidence = measured(row)
            if kind == "non-speech":
                for target in public.values():
                    record(
                        row,
                        evidence,
                        target,
                        "non-speech",
                        False,
                        "mechanical-non-speech",
                        unitId="mechanical-wave:" + row["sha256"],
                        sourceRootId="mechanical-wave:" + row["sha256"],
                        declaredSourceRootId=row.get("sourceRootId"),
                    )
                continue
            if kind == "foreign":
                for key in row["againstTargetIds"]:
                    if key not in public:
                        exclusions.append(
                            {
                                "sampleId": row["id"],
                                "targetId": key,
                                "reason": "FOREIGN_PAIR_OUTSIDE_PUBLIC_COVERAGE",
                            }
                        )
                        continue
                    record(
                        row,
                        evidence,
                        public[key],
                        "cross-language-acoustic-mismatch",
                        False,
                        "foreign-" + row["generator"],
                        mismatchBasis="phoneme",
                        mismatchDescription=row["phoneticDifference"],
                    )
                continue
            actual = targets.get(row["targetId"])
            if (
                not actual
                or actual["form"] != "whole-syllable"
                or actual["tone"] not in {1, 2, 3, 4}
            ):
                raise ValueError("EXPLICIT_FULL_SYLLABLE_LABEL_REQUIRED")
            source = (
                "licensed-standard-vc"
                if row.get("derivedFromStandard")
                else "synthetic-" + row["generator"]
            )
            row = {"lexicalRootId": actual["id"], **row}
            if row["targetId"] in public:
                record(
                    row,
                    evidence,
                    actual,
                    "clean-positive",
                    True,
                    source,
                    actualTargetId=row["targetId"],
                    contentCorrect=evidence.get("predictedPhones") == actual["phones"],
                )
                for tone in range(1, 5):
                    if tone != actual["tone"]:
                        counter = next(
                            (
                                target
                                for target in public.values()
                                if target["phones"] == actual["phones"] and target["tone"] == tone
                            ),
                            {**actual, "id": f"countertone:{actual['id']}:{tone}", "tone": tone},
                        )
                        record(
                            row,
                            evidence,
                            counter,
                            "tone",
                            False,
                            source,
                            actualTargetId=row["targetId"],
                        )
            else:
                # An unsupported actual label is never called a public positive.
                for target in public.values():
                    if target["phones"] == actual["phones"] and target["tone"] != actual["tone"]:
                        record(
                            row,
                            evidence,
                            target,
                            "tone",
                            False,
                            source,
                            actualTargetId=row["targetId"],
                        )
            for target in near_targets(actual, public, limit=near_limit):
                record(
                    row,
                    evidence,
                    target,
                    "near-phoneme",
                    False,
                    source,
                    actualTargetId=row["targetId"],
                )
    return records, {
        "inputRows": input_counts,
        "uniqueRawWaveformsInferred": len(cache),
        "deduplicatedRawRows": len(seen),
        "publicCoveredTargetIds": sorted(public),
        "publicPositiveTargetIds": sorted(
            {r["actualTargetId"] for r in records if r["expectedMatch"]}
        ),
        "coverage": coverage_metrics(records),
        "excludedPairs": exclusions,
        "countertoneIdsArePublicCapabilities": False,
        "realChildAccuracyEstablished": False,
    }


def _fit(matcher, records: list[dict], output: Path, *, fixed_thresholds: dict | None = None):
    lineage_check = training_lineage_check(matcher.metadata, records)
    atomic_json(output / "training-lineage-check.json", lineage_check)
    if lineage_check["overlapRawUnitIds"]:
        raise ValueError("CALIBRATION_TRAINING_LINEAGE_LEAKAGE")
    if lineage_check["errors"]:
        raise ValueError("MODEL_TRAINING_MANIFEST_MISSING_OR_CHANGED")
    policies = {
        source: {
            "requireBothClasses": not (
                source.startswith("foreign-") or source == "mechanical-non-speech"
            )
        }
        for source in {r["source"] for r in records}
    }
    if fixed_thresholds is not None:
        _thresholds(fixed_thresholds)
    grid = {key: [value] for key, value in fixed_thresholds.items()} if fixed_thresholds else None
    report = calibrate(records, grid=grid, source_policies=policies)
    report["thresholdSelectionMode"] = (
        "predeclared-single-setting" if fixed_thresholds else "calibration-grid"
    )
    if fixed_thresholds is not None:
        report["predeclaredThresholds"] = fixed_thresholds
    report["trainingLineageCheck"] = lineage_check
    if not lineage_check["complete"]:
        report["calibrationPassed"] = False
        report["thresholds"] = None
        report["blockers"].append("TRAINING_LINEAGE_PROVENANCE_INCOMPLETE")
    atomic_json(output / "calibration.json", report)
    return report


def run(
    model: Path,
    inputs: list[tuple[Path, str]],
    output: Path,
    *,
    fixed_thresholds: dict | None = None,
):
    if output.exists():
        raise ValueError("CALIBRATION_OUTPUT_ALREADY_EXISTS")
    if not inputs:
        raise ValueError("CALIBRATION_INPUTS_REQUIRED")
    if fixed_thresholds is not None:
        _thresholds(fixed_thresholds)
    assert_protocol()
    matcher = PinyinMatcher(model)
    if matcher.session is None or matcher.metadata.get("decisionVersion") != 3:
        raise ValueError(matcher.problem or "V3_MODEL_REQUIRED")
    records, collection = collect_records(matcher, inputs)
    output.mkdir(parents=True)
    atomic_json(output / "records.json", records)
    atomic_json(
        output / "collection.json",
        {
            **collection,
            "protocolVersion": PROTOCOL_VERSION,
            "protocolSha256": PROTOCOL_SHA256,
            "modelMetadataSha256": fingerprint(model / "model.json"),
            "collectionCodeSha256": fingerprint(Path(__file__)),
            "inputManifestSha256": {str(path): fingerprint(path) for path, kind in inputs},
            "predeclaredThresholds": fixed_thresholds,
        },
    )
    return _fit(matcher, records, output, fixed_thresholds=fixed_thresholds)


def recalibrate(
    model: Path, records_path: Path, output: Path, *, fixed_thresholds: dict | None = None
):
    """Apply the amended protocol to identical stored evidence in a new directory."""
    if output.exists():
        raise ValueError("CALIBRATION_OUTPUT_ALREADY_EXISTS")
    assert_protocol()
    original = json.loads((records_path.parent / "collection.json").read_text())
    if original["modelMetadataSha256"] != fingerprint(model / "model.json"):
        raise ValueError("STORED_EVIDENCE_MODEL_METADATA_CHANGED")
    matcher = PinyinMatcher(model)
    if matcher.session is None or matcher.metadata.get("decisionVersion") != 3:
        raise ValueError(matcher.problem or "V3_MODEL_REQUIRED")
    records = json.loads(records_path.read_text())
    original_report = records_path.parent / "calibration.json"
    output.mkdir(parents=True)
    shutil.copyfile(records_path, output / "records.json")
    atomic_json(
        output / "collection.json",
        {
            **original,
            "protocolVersion": PROTOCOL_VERSION,
            "protocolSha256": PROTOCOL_SHA256,
            "recalibrationSourceRecords": str(records_path),
            "recalibrationSourceRecordsFileSha256": fingerprint(records_path),
            "coverage": coverage_metrics(records),
            "inferenceRerun": False,
            "sourceProtocolVersion": original.get("protocolVersion", 1),
            "predeclaredThresholds": fixed_thresholds,
            "legacyCalibrationReportSha256": fingerprint(original_report)
            if original_report.exists()
            else None,
        },
    )
    report = _fit(matcher, records, output, fixed_thresholds=fixed_thresholds)
    report["recalibrationSourceRecordsFileSha256"] = fingerprint(records_path)
    report["legacyCalibrationReportSha256"] = (
        fingerprint(original_report) if original_report.exists() else None
    )
    atomic_json(output / "calibration.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--foreign", type=Path, action="append", default=[])
    parser.add_argument("--non-speech", type=Path, action="append", default=[])
    parser.add_argument(
        "--records",
        type=Path,
        help="Recalibrate identical stored evidence into a new output directory.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fixed-thresholds",
        type=Path,
        help="Validate exactly one predeclared setting; never search or relax thresholds.",
    )
    args = parser.parse_args()
    inputs = [
        (path, kind)
        for kind, paths in [
            ("speech", args.manifest),
            ("foreign", args.foreign),
            ("non-speech", args.non_speech),
        ]
        for path in paths
    ]
    if args.records and inputs:
        raise ValueError("RECALIBRATION_RECORDS_CANNOT_MIX_NEW_INPUTS")
    fixed = None
    if args.fixed_thresholds is not None:
        fixed = json.loads(args.fixed_thresholds.read_text())
        if not isinstance(fixed, dict):
            raise ValueError("EXPLICIT_FIXED_THRESHOLDS_OBJECT_REQUIRED")
        _thresholds(fixed)
    report = (
        recalibrate(args.model, args.records, args.output, fixed_thresholds=fixed)
        if args.records
        else run(args.model, inputs, args.output, fixed_thresholds=fixed)
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("calibrationPassed", "thresholds", "feasibleCombinations", "blockers")
            }
        )
    )


if __name__ == "__main__":
    main()
