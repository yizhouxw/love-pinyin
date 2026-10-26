"""Report predeclared sources separately when the full generation batch is incomplete.

VC plus fixed extra-syllable queries remain a complete source-specific subset.
The foreign diagnostic retains every planned slot, including unavailable TTS
generation failures. Neither report can establish acceptance of the whole batch.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import SAMPLE_RATE, decode_wav, encode_wav
from pinyin_matcher.catalog import fingerprint, load_catalog
from pinyin_matcher.controlled_generation import validate_evaluation_lock
from pinyin_matcher.evaluation_cases import (
    EXTRA_SOURCE,
    GAP_SAMPLES,
    VC_SOURCE,
    _audio,
    _check_lineage,
    _exclusions,
    _unique,
)
from pinyin_matcher.foreign_evaluation import validate_foreign_plan
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.quality import (
    LIMITS,
    PROTOCOL_SHA256,
    PROTOCOL_VERSION,
    _digest,
    _evaluation_code,
    _model_snapshot,
    assert_protocol,
    build_report,
    quality_metrics,
    validate_case_semantics,
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _base_lock(path: Path) -> dict:
    raw = _read(path)
    return validate_evaluation_lock(
        path, Path(raw["configuration"]["file"]), Path(raw["generationPlan"]["outputDirectory"])
    )


def build_vc_subset(
    evaluation_lock: Path,
    vc_manifest: Path,
    output: Path,
    *,
    exclusion_manifests: list[Path],
) -> dict:
    """Copy all 20 predeclared VC WAVs and make the same fixed 20 concatenations."""
    if output.exists():
        raise ValueError("NEW_VC_SUBSET_OUTPUT_REQUIRED")
    base = _base_lock(evaluation_lock)
    plan = base["generationPlan"]
    covered = base["model"]["coveredTargetIds"]
    if (
        len(plan["sources"]) != 5
        or len(plan["personas"]) != 4
        or len(plan["units"]) != 20
        or plan["expectedWaveforms"] != 20
        or len(covered) != 32
        or len(set(covered)) != 32
        or plan["queryPolicy"]["coveredTargetIds"] != covered
    ):
        raise ValueError("EXPLICIT_FIVE_BY_FOUR_BY_32_VC_SCOPE_REQUIRED")
    directory = Path(base["modelDirectory"])
    metadata = _read(directory / "model.json")
    catalog_path = (directory / metadata["catalogFile"]).resolve()
    if not catalog_path.is_relative_to(directory.resolve()):
        raise ValueError("VC_SUBSET_CATALOG_PATH_INVALID")
    catalog = load_catalog(catalog_path)
    targets = {r["id"]: r for r in catalog["targets"]}
    if not set(covered) <= set(catalog["pilotIds"]) or any(
        targets[key]["form"] != "whole-syllable" for key in covered
    ):
        raise ValueError("PUBLIC_VC_SUBSET_TARGETS_REQUIRED")
    exclusions, lineage, lexical = _exclusions(metadata, base, exclusion_manifests)
    data = _read(vc_manifest)
    if (
        data.get("evaluationGenerationComplete") is not True
        or data.get("evaluationLockSha256") != base["lockSha256"]
        or data.get("evaluationGenerationPlan") != plan
        or any(
            data.get(k)
            for k in ("rejected", "quarantined", "failedGenerationAttempts", "diagnostics")
        )
    ):
        raise ValueError("COMPLETE_PREDECLARED_VC_SOURCE_REQUIRED")
    rows = _unique(data["items"], plan["units"])
    sources = {r["targetId"]: r for r in plan["sources"]}
    reference_hashes = {
        p["id"]: fingerprint(Path(plan["outputDirectory"]) / "references" / (p["id"] + ".wav"))
        for p in plan["personas"]
    }
    paths = {}
    for unit in plan["units"]:
        row, source = rows[unit["id"]], sources[unit["targetId"]]
        if (
            any(
                row.get(k) != unit[k] for k in ("targetId", "voiceFamilyId", "seed", "sourceSha256")
            )
            or row.get("sourceRootId") != source["sourceRootId"]
            or row.get("split") != "test"
            or row.get("sourceAllocation") != "test"
            or row.get("sourceDeclaredAllocation") != "blind"
            or row.get("evaluationLockSha256") != base["lockSha256"]
            or row.get("referenceRootId") != row["voiceFamilyId"] + "-reference"
            or row.get("referenceSha256") != reference_hashes.get(row["voiceFamilyId"])
            or row.get("knownStandardRootNewVcFamilyValidation") is not True
            or targets[row["targetId"]]["phones"] != source["phones"]
            or targets[row["targetId"]]["tone"] != source["tone"]
            or row["targetId"] not in covered
        ):
            raise ValueError("VC_SUBSET_SOURCE_BINDING_INVALID:" + unit["id"])
        _check_lineage(row, lineage, lexical)
        paths[row["id"]] = _audio(vc_manifest, row, Path(plan["outputDirectory"]) / unit["file"])
    ordered = sorted(rows.values(), key=lambda r: (r["voiceFamilyId"], r["targetId"]))
    pairs = []
    for index, first in enumerate(ordered):
        successor = ordered[index + 1 :] + ordered[: index + 1]
        second = next(
            (
                r
                for r in successor
                if r["voiceFamilyId"] == first["voiceFamilyId"]
                and targets[r["targetId"]]["phones"] != targets[first["targetId"]]["phones"]
            ),
            None,
        )
        if second is None:
            raise ValueError("DIFFERENT_PHONE_SAME_FAMILY_PARENT_REQUIRED")
        for parent in (first, second):
            _check_lineage(parent, lineage, lexical)
        pairs.append((first, second))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name + ".building-", dir=output.parent))
    cases = []

    def record(row, key, source, case, positive, file, **extra):
        item = {
            **{
                k: row[k]
                for k in (
                    "voiceFamilyId",
                    "referenceRootId",
                    "referenceSha256",
                    "sourceRootId",
                    "sourceSha256",
                    "sourceWavSha256",
                    "labelProvenance",
                )
                if row.get(k)
            },
            "id": row["id"] + "-against-" + key,
            "unitId": row["id"],
            "source": source,
            "case": case,
            "targetId": key,
            "expectedMatch": positive,
            "clearAudio": source == VC_SOURCE,
            "file": file,
            "sha256": row["sha256"],
            "split": "test",
            "generator": "cosy",
            "generatorRevision": row.get("generatorRevision"),
            "evaluationLockSha256": base["lockSha256"],
            "actualTargetId": row["targetId"],
            "knownStandardRootNewVcFamilyValidation": True,
            "actualPhonesIndependentlyVerified": False,
            "fullBatchAcceptanceComplete": False,
            **extra,
        }
        validate_case_semantics(item)
        cases.append(item)

    try:
        for row in ordered:
            relative = "audio/vc/" + row["sha256"] + ".wav"
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(paths[row["id"]], destination)
            if fingerprint(destination) != row["sha256"]:
                raise ValueError("VC_AUDIO_CHANGED_DURING_COPY")
            actual = targets[row["targetId"]]
            for key in covered:
                target = targets[key]
                same = actual["phones"] == target["phones"]
                positive = same and actual["tone"] == target["tone"]
                case = "clean-positive" if positive else "tone" if same else "near-phoneme"
                record(
                    row,
                    key,
                    VC_SOURCE,
                    case,
                    positive,
                    relative,
                    mismatchBasis=None if positive else "tone" if same else "phoneme",
                    mismatchDescription=None
                    if positive
                    else f"Intended {actual['pinyin']} differs from requested {target['pinyin']}.",
                )
        for first, second in pairs:
            samples = np.concatenate(
                [
                    decode_wav(paths[first["id"]].read_bytes()),
                    np.zeros(GAP_SAMPLES, dtype=np.float32),
                    decode_wav(paths[second["id"]].read_bytes()),
                ]
            )
            payload = encode_wav(samples)
            digest = hashlib.sha256(payload).hexdigest()
            relative = "audio/extra/" + digest + ".wav"
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            row = {
                **first,
                "id": f"extra-{first['id']}-then-{second['id']}",
                "sha256": digest,
                "labelProvenance": "deterministic-two-intended-syllable-concatenation",
            }
            for key in covered:
                record(
                    row,
                    key,
                    EXTRA_SOURCE,
                    "extra-syllable",
                    False,
                    relative,
                    parentRootIds=[first["sourceRootId"], second["sourceRootId"]],
                    parentUnitIds=[first["id"], second["id"]],
                    parentTargetIds=[first["targetId"], second["targetId"]],
                    parentSha256=first["sha256"],
                    secondaryParentSha256=second["sha256"],
                    secondarySourceRootId=second["sourceRootId"],
                    secondarySourceSha256=second["sourceSha256"],
                    gapSamples=GAP_SAMPLES,
                    durationSeconds=len(samples) / SAMPLE_RATE,
                    mismatchBasis="syllable-count",
                    mismatchDescription="Two intended syllables for a single-syllable request.",
                )
        if len(cases) != 1280 or sum(r["expectedMatch"] for r in cases) != 20:
            raise ValueError("COMPLETE_1280_QUERY_VC_SUBSET_REQUIRED")
        _base_lock(evaluation_lock)
        result = {
            "schemaVersion": 1,
            "evaluationLockSha256": base["lockSha256"],
            "builderSha256": fingerprint(Path(__file__)),
            "inputManifest": {
                "file": str(vc_manifest.resolve()),
                "sha256": fingerprint(vc_manifest),
            },
            "exclusionManifests": exclusions,
            "completeParentLineageCheck": True,
            "acceptanceScope": "predeclared VC plus fixed extra-syllable source only",
            "fullBatchAcceptanceComplete": False,
            "sources": {
                VC_SOURCE: {
                    "usage": "unseen",
                    "requireBothClasses": True,
                    "labelProvenance": "trusted-standard-derived-VC-intended-label",
                    "unseenScope": "new VC waves/families on known standards",
                    "fullBatchAcceptanceComplete": False,
                },
                EXTRA_SOURCE: {
                    "usage": "unseen",
                    "requireBothClasses": False,
                    "labelProvenance": "fixed two-parent concatenation of new VC waves",
                    "fullBatchAcceptanceComplete": False,
                },
            },
            "coverage": {
                "publicCoveredQueryTargetIds": covered,
                "publicPositiveTargetIds": sorted(sources),
                "vcWaveforms": 20,
                "extraWaveforms": 20,
                "standardParents": 5,
                "syntheticFamilies": 4,
                "totalQueries": len(cases),
                "caseQueryCounts": dict(Counter(r["case"] for r in cases)),
                "toneNegativeQueries": sum(r["case"] == "tone" for r in cases),
            },
            "claims": {
                "standardRootsHistoricallyKnown": True,
                "realChildAccuracyEstablished": False,
                "independentHumanSpeakers": False,
                "fullBatchAcceptanceComplete": False,
                "sourcePassDoesNotEstablishFullBatchAcceptance": True,
                "wholeBatchForeignGenerationIncomplete": True,
            },
            "cases": cases,
        }
        atomic_json(staging / "manifest.json", result)
        staging.rename(output)
        return result
    except BaseException:
        shutil.rmtree(staging)
        raise


def create_foreign_diagnostic_plan(foreign_plan: Path, manifest: Path, output: Path) -> dict:
    """Freeze all 96 real/missing generation slots without inventing a missing WAV."""
    if output.exists():
        raise ValueError("NEW_FOREIGN_DIAGNOSTIC_PLAN_REQUIRED")
    assert_protocol()
    leaf = validate_foreign_plan(foreign_plan)
    generation = leaf["generationPlan"]
    units = generation["units"]
    if len(units) != 96 or sum(len(r["againstTargetIds"]) for r in units) != 96:
        raise ValueError("EXPLICIT_96_FOREIGN_QUERY_SCOPE_REQUIRED")
    data = _read(manifest)
    if data.get("foreignPlanSha256") != leaf["planSha256"] or (
        data.get("evaluationLockSha256") != leaf["evaluationLock"]["lockSha256"]
    ):
        raise ValueError("FOREIGN_DIAGNOSTIC_BINDING_MISMATCH")
    indexed = _unique(data["items"], units)
    cases, actual, missing = [], [], []
    covered = set(leaf["model"]["coveredTargetIds"])
    for unit in units:
        row = indexed[unit["id"]]
        if (
            any(row.get(k) != v for k, v in unit.items())
            or not set(row["againstTargetIds"]) <= covered
        ):
            raise ValueError("FOREIGN_DIAGNOSTIC_UNIT_CHANGED")
        path = (manifest.parent / row["file"]).resolve()
        if path != (Path(generation["outputDirectory"]) / unit["file"]).resolve() or (
            not path.is_relative_to(manifest.parent.resolve()) or Path(row["file"]).is_absolute()
        ):
            raise ValueError("FOREIGN_DIAGNOSTIC_AUDIO_PATH_INVALID")
        if row.get("sha256"):
            if row["generationStatus"] not in {"accepted-mechanically", "mechanical-failure"}:
                raise ValueError("FOREIGN_DIAGNOSTIC_RECORDED_AUDIO_NOT_TERMINAL")
            _audio(manifest, row)
            actual.append(row["id"])
        else:
            if row["generationStatus"] in {"accepted-mechanically", "mechanical-failure"}:
                raise ValueError("FOREIGN_TERMINAL_WAV_DIGEST_REQUIRED")
            if path.exists():
                raise ValueError("FOREIGN_UNRECORDED_AUDIO_REQUIRES_INVESTIGATION")
            missing.append(row["id"])
        for target in row["againstTargetIds"]:
            case = {
                **{
                    k: row[k]
                    for k in (
                        "voiceFamilyId",
                        "referenceRootId",
                        "sourceRootId",
                        "lexicalRootId",
                        "sourceText",
                        "language",
                        "contrastCategory",
                        "labelProvenance",
                        "generationStatus",
                    )
                },
                "id": row["id"] + "-against-" + target,
                "unitId": row["id"],
                "source": "incomplete-foreign-generation-diagnostic",
                "case": "cross-language-acoustic-mismatch",
                "targetId": target,
                "expectedMatch": False,
                "clearAudio": False,
                "file": str(path),
                "sha256": row.get("sha256"),
                "split": "test",
                "generator": "qwen",
                "generatorRevision": leaf["qwenInstallation"]["revision"],
                "mismatchBasis": "phoneme",
                "mismatchDescription": row["phoneticDifference"],
                "generationFailureReason": row.get("error")
                or row.get("reason")
                or ("GENERATION_" + row["generationStatus"].upper()),
                "actualPhonesIndependentlyVerified": False,
            }
            validate_case_semantics(case)
            cases.append(case)
    model = _model_snapshot(Path(leaf["modelDirectory"]))
    if model != leaf["model"]:
        raise ValueError("FOREIGN_DIAGNOSTIC_MODEL_CHANGED")
    plan = {
        "schemaVersion": 1,
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": PROTOCOL_SHA256,
        "createdUtc": datetime.now(UTC).isoformat(),
        "purpose": "diagnostic",
        "modelDirectory": leaf["modelDirectory"],
        "model": model,
        "evaluationCodeSha256": _evaluation_code(),
        "subsetRunnerCodeSha256": fingerprint(Path(__file__)),
        "sourceBindings": [
            {"file": str(p.resolve()), "sha256": fingerprint(p)} for p in (foreign_plan, manifest)
        ],
        "foreignPlanSha256": leaf["planSha256"],
        "sources": {
            "incomplete-foreign-generation-diagnostic": {
                "usage": "diagnostic",
                "requireBothClasses": False,
                "labelProvenance": "tts-intended-not-language-or-phoneme-verified",
                "fullBatchAcceptanceComplete": False,
            }
        },
        "limits": dict(LIMITS),
        "cases": cases,
        "generationCoverage": {
            "plannedWaveforms": 96,
            "actualWaveformFiles": len(actual),
            "missingWaveforms": len(missing),
            "missingUnitIds": missing,
            "plannedQueries": len(cases),
            "actualAudioQueries": sum(bool(r.get("sha256")) for r in cases),
        },
        "claims": {
            "realChildAccuracyEstablished": False,
            "independentHumanSpeakers": False,
            "fullBatchAcceptanceComplete": False,
            "missingGenerationIsNotSuccessfulAcousticRejection": True,
            "sourcePassDoesNotEstablishFullBatchAcceptance": True,
        },
    }
    plan["freezeSha256"] = _digest(plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return plan


def run_foreign_diagnostic(plan_path: Path, output: Path) -> dict:
    """CPU-match present WAVs; generation failures produce explicit unavailable slots."""
    from pinyin_matcher.inference import PinyinMatcher

    if output.exists():
        raise ValueError("NEW_FOREIGN_DIAGNOSTIC_REPORT_REQUIRED")
    plan = _read(plan_path)
    if plan.get("purpose") != "diagnostic" or any(
        s.get("usage") != "diagnostic" for s in plan["sources"].values()
    ):
        raise ValueError("FOREIGN_RUNNER_IS_DIAGNOSTIC_ONLY")
    if (
        _model_snapshot(Path(plan["modelDirectory"])) != plan["model"]
        or _evaluation_code() != plan["evaluationCodeSha256"]
        or fingerprint(Path(__file__)) != plan["subsetRunnerCodeSha256"]
        or any(fingerprint(Path(r["file"])) != r["sha256"] for r in plan["sourceBindings"])
    ):
        raise ValueError("FROZEN_FOREIGN_DIAGNOSTIC_INPUT_CHANGED")
    build_report(plan, [])  # Digest/protocol/limit validation before any inference.
    for case in plan["cases"]:
        path = Path(case["file"])
        if case.get("sha256"):
            if fingerprint(path) != case["sha256"]:
                raise ValueError("FROZEN_FOREIGN_AUDIO_CHANGED")
        elif path.exists():
            raise ValueError("UNPLANNED_REPLACEMENT_AUDIO_FORBIDDEN")
    matcher = PinyinMatcher(plan["modelDirectory"])
    results = []
    for case in plan["cases"]:
        if not case.get("sha256"):
            result = {
                "status": "unavailable",
                "reason": case["generationFailureReason"],
                "audioInferencePerformed": False,
                "generationUnavailable": True,
            }
        else:
            path = Path(case["file"])
            if fingerprint(path) != case["sha256"]:
                raise ValueError("FROZEN_FOREIGN_AUDIO_CHANGED")
            try:
                result = {
                    **matcher.match(case["targetId"], path.read_bytes(), include_evidence=True),
                    "audioInferencePerformed": True,
                }
            except (ValueError, OSError) as error:
                result = {
                    "status": "unavailable",
                    "reason": str(error),
                    "audioInferencePerformed": True,
                }
        results.append({"id": case["id"], **result})
    report = build_report(plan, results)
    observed = [r for r in report["results"] if r.get("sha256")]
    report.update(
        {
            "purpose": "diagnostic",
            "qualityPassed": False,
            "fullBatchAcceptanceComplete": False,
            "generationCoverage": plan["generationCoverage"],
            "observedAudioMetrics": quality_metrics(observed),
            "overallMetricScope": (
                "Full planned slots include unavailable generation failures; "
                "observedAudioMetrics describes actual WAV queries only."
            ),
            "actualAudioInferenceAttempts": sum(
                r.get("audioInferencePerformed", False) for r in report["results"]
            ),
        }
    )
    if plan["generationCoverage"]["missingWaveforms"]:
        report["blockers"].append("FOREIGN_GENERATION_INCOMPLETE")
    atomic_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    vc = commands.add_parser("vc")
    vc.add_argument("--evaluation-lock", type=Path, required=True)
    vc.add_argument("--vc-manifest", type=Path, required=True)
    vc.add_argument("--exclude-manifest", type=Path, action="append", required=True)
    vc.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("foreign-freeze")
    freeze.add_argument("--foreign-plan", type=Path, required=True)
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("foreign-run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "vc":
        result = build_vc_subset(
            args.evaluation_lock,
            args.vc_manifest,
            args.output,
            exclusion_manifests=args.exclude_manifest,
        )
        print(json.dumps({"manifest": str(args.output / "manifest.json"), **result["coverage"]}))
    elif args.command == "foreign-freeze":
        result = create_foreign_diagnostic_plan(args.foreign_plan, args.manifest, args.output)
        print(json.dumps({"purpose": "diagnostic", **result["generationCoverage"]}))
    else:
        result = run_foreign_diagnostic(args.plan, args.output)
        print(
            json.dumps(
                {
                    "purpose": "diagnostic",
                    "qualityPassed": False,
                    "generationCoverage": result["generationCoverage"],
                    "observedAudioMetrics": result["observedAudioMetrics"],
                }
            )
        )


if __name__ == "__main__":
    main()
