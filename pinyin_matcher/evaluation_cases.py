"""Build frozen-model quality queries without running inference or selecting cases.

Every planned VC waveform is queried against every public covered target. Foreign
speech retains only the authored target contrasts, never a language-wide negative
label. The extra-syllable set uses a fixed same-family, different-phone successor.
Known standard parents and synthetic family dependence remain explicit.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import SAMPLE_RATE, decode_wav, encode_wav
from pinyin_matcher.catalog import fingerprint, load_catalog
from pinyin_matcher.controlled_generation import validate_evaluation_lock
from pinyin_matcher.foreign_evaluation import validate_foreign_plan
from pinyin_matcher.quality import _lineage, validate_case_semantics

VC_SOURCE = "known-standard-new-vc-families"
EXTRA_SOURCE = "known-standard-new-vc-extra-syllable"
FOREIGN_SOURCE = "new-family-foreign-intended-contrasts"
GAP_SAMPLES = 2400


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _audio(manifest: Path, row: dict, expected: Path | None = None) -> Path:
    relative = Path(row.get("file") or "")
    path = (manifest.parent / relative).resolve()
    if (
        not row.get("file")
        or relative.is_absolute()
        or not path.is_relative_to(manifest.parent.resolve())
        or expected is not None
        and path != expected.resolve()
    ):
        raise ValueError("EVALUATION_INPUT_AUDIO_PATH_INVALID")
    if not row.get("sha256") or not path.is_file():
        raise ValueError("PLANNED_EVALUATION_WAVEFORM_MISSING:" + row["id"])
    if fingerprint(path) != row["sha256"]:
        raise ValueError("EVALUATION_INPUT_AUDIO_CHANGED:" + row["id"])
    return path


def _unique(rows: list[dict], planned: list[dict]) -> dict[str, dict]:
    indexed = {row["id"]: row for row in rows}
    if len(indexed) != len(rows) or set(indexed) != {row["id"] for row in planned}:
        raise ValueError("COMPLETE_PLANNED_EVALUATION_SET_REQUIRED")
    return indexed


def _exclusions(model: dict, base: dict, extra: list[Path]) -> tuple[list[dict], set, set]:
    """Bind all acoustic train/cal inputs, plus explicitly supplied pitch anchors."""
    provenance = model.get("dataProvenance", {})
    bindings = {}
    for kind in ("synthetic", "standard"):
        path = provenance.get(kind + "ManifestPath")
        digest = provenance.get(kind + "ManifestSha256")
        if not path or not digest:
            raise ValueError("MODEL_TRAINING_PROVENANCE_REQUIRED")
        bindings[Path(path).resolve()] = digest
    for field in ("derivedManifestSha256", "foreignManifestSha256"):
        bindings.update({Path(p).resolve(): d for p, d in provenance.get(field, {}).items()})
    collection = _read(Path(base["calibrationCollection"]["file"]))
    inputs = collection.get("inputManifestSha256", {})
    if not inputs:
        raise ValueError("CALIBRATION_INPUT_PROVENANCE_REQUIRED")
    bindings.update({Path(p).resolve(): d for p, d in inputs.items()})
    if not extra:
        raise ValueError("EXPLICIT_PITCH_ANCHOR_EXCLUSION_REQUIRED")
    for path in extra:
        path = path.resolve()
        bindings.setdefault(path, fingerprint(path))
    records, lineage, lexical = [], set(), set()
    for path, digest in sorted(bindings.items()):
        if fingerprint(path) != digest:
            raise ValueError("EXCLUSION_MANIFEST_CHANGED:" + str(path))
        data = _read(path)
        rows = [r for r in data.get("items", data.get("cases", [])) if r.get("split") != "test"]
        if not rows:
            raise ValueError("EXCLUSION_MANIFEST_HAS_NO_USED_ROWS:" + str(path))
        for row in rows:
            lineage.update(_lineage(row))
            if row.get("lexicalRootId"):
                lexical.add(row["lexicalRootId"])
        records.append({"path": str(path), "sha256": digest, "usedRows": len(rows)})
    return records, lineage, lexical


def _check_lineage(row: dict, lineage: set, lexical: set):
    if _lineage(row) & lineage or row.get("lexicalRootId") in lexical:
        raise ValueError("EVALUATION_TRAIN_OR_CALIBRATION_LINEAGE_LEAKAGE:" + row["id"])


def build_cases(
    evaluation_lock: Path,
    vc_manifest: Path,
    foreign_plan: Path,
    foreign_manifest: Path,
    output: Path,
    *,
    exclusion_manifests: list[Path],
) -> dict:
    """Copy all audio and build cases; never instantiate a matcher or run inference.

    ``exclusion_manifests`` must include the pitch head's original raw anchor
    manifest. Acoustic model provenance and actual calibration inputs are added
    automatically. Both parents are checked before any extra-syllable WAV is made.
    The returned manifest has relative paths accepted by ``quality.freeze_plan``.
    """
    if output.exists():
        raise ValueError("EVALUATION_CASE_OUTPUT_MUST_BE_NEW")
    raw_lock = _read(evaluation_lock)
    base = validate_evaluation_lock(
        evaluation_lock,
        Path(raw_lock["configuration"]["file"]),
        Path(raw_lock["generationPlan"]["outputDirectory"]),
    )
    leaf = validate_foreign_plan(foreign_plan)
    if leaf["evaluationLock"]["lockSha256"] != base["lockSha256"]:
        raise ValueError("FOREIGN_AND_VC_EVALUATION_LOCK_MISMATCH")
    model_dir = Path(base["modelDirectory"])
    metadata = _read(model_dir / "model.json")
    catalog_path = (model_dir / metadata["catalogFile"]).resolve()
    if not catalog_path.is_relative_to(model_dir.resolve()):
        raise ValueError("EVALUATION_CATALOG_PATH_INVALID")
    catalog = load_catalog(catalog_path)
    targets = {r["id"]: r for r in catalog["targets"]}
    covered = base["model"]["coveredTargetIds"]
    if (
        not covered
        or len(set(covered)) != len(covered)
        or not set(covered) <= set(catalog["pilotIds"])
        or covered != base["generationPlan"]["queryPolicy"]["coveredTargetIds"]
        or any(targets[k]["form"] != "whole-syllable" for k in covered)
    ):
        raise ValueError("PUBLIC_COVERED_WHOLE_SYLLABLE_TARGETS_REQUIRED")
    exclusions, lineage, lexical = _exclusions(metadata, base, exclusion_manifests)
    vc = _read(vc_manifest)
    plan = base["generationPlan"]
    if (
        vc.get("evaluationGenerationComplete") is not True
        or vc.get("evaluationLockSha256") != base["lockSha256"]
        or vc.get("evaluationGenerationPlan") != plan
        or vc.get("rejected")
        or vc.get("quarantined")
        or vc.get("failedGenerationAttempts")
        or vc.get("diagnostics")
    ):
        raise ValueError("COMPLETE_LOCKED_VC_MANIFEST_REQUIRED")
    vc_rows = _unique(vc["items"], plan["units"])
    sources = {r["targetId"]: r for r in plan["sources"]}
    reference_hashes = {
        persona["id"]: fingerprint(
            Path(plan["outputDirectory"]) / "references" / (persona["id"] + ".wav")
        )
        for persona in plan["personas"]
    }
    audio_paths = {}
    for unit in plan["units"]:
        row = vc_rows[unit["id"]]
        source = sources[unit["targetId"]]
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
        ):
            raise ValueError("VC_EVALUATION_ROW_PROVENANCE_INVALID:" + unit["id"])
        _check_lineage(row, lineage, lexical)
        audio_paths[row["id"]] = _audio(
            vc_manifest, row, Path(plan["outputDirectory"]) / unit["file"]
        )
    foreign = _read(foreign_manifest)
    foreign_generation = leaf["generationPlan"]
    if (
        foreign.get("foreignPlanSha256") != leaf["planSha256"]
        or foreign.get("evaluationLockSha256") != base["lockSha256"]
        or foreign.get("qualityManifestReady") is not True
    ):
        raise ValueError("COMPLETE_LOCKED_FOREIGN_MANIFEST_REQUIRED")
    foreign_rows = _unique(foreign["items"], foreign_generation["units"])
    for unit in foreign_generation["units"]:
        row = foreign_rows[unit["id"]]
        if (
            any(row.get(k) != v for k, v in unit.items())
            or row.get("generationStatus") not in {"accepted-mechanically", "mechanical-failure"}
            or not set(row["againstTargetIds"]) <= set(covered)
            or len(set(row["againstTargetIds"])) != len(row["againstTargetIds"])
            or not row["againstTargetIds"]
        ):
            raise ValueError("FOREIGN_EVALUATION_ROW_PROVENANCE_INVALID:" + unit["id"])
        _check_lineage(row, lineage, lexical)
        audio_paths[row["id"]] = _audio(
            foreign_manifest, row, Path(foreign_generation["outputDirectory"]) / unit["file"]
        )
    ordered_vc = sorted(vc_rows.values(), key=lambda r: (r["voiceFamilyId"], r["targetId"]))
    pairs = []
    for index, first in enumerate(ordered_vc):
        successor = ordered_vc[index + 1 :] + ordered_vc[: index + 1]
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
            raise ValueError("DIFFERENT_PHONE_SAME_FAMILY_EXTRA_SYLLABLE_PARENT_REQUIRED")
        # Do not rely on quality._lineage recognizing secondary-parent fields.
        for parent in (first, second):
            _check_lineage(parent, lineage, lexical)
        pairs.append((first, second))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name + ".building-", dir=output.parent))
    cases = []

    def copy_audio(row: dict, category: str) -> str:
        relative = f"audio/{category}/{row['sha256']}.wav"
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(audio_paths[row["id"]], destination)
        if fingerprint(destination) != row["sha256"]:
            raise ValueError("EVALUATION_INPUT_AUDIO_CHANGED_DURING_COPY")
        return relative

    def record(row: dict, target: str, source: str, case: str, positive: bool, file: str, **extra):
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
                    "lexicalRootId",
                    "labelProvenance",
                )
                if row.get(k)
            },
            "id": f"{row['id']}-against-{target}",
            "unitId": row["id"],
            "source": source,
            "case": case,
            "targetId": target,
            "expectedMatch": positive,
            "clearAudio": source == VC_SOURCE,
            "file": file,
            "sha256": row["sha256"],
            "split": "test",
            "generator": "qwen" if source == FOREIGN_SOURCE else "cosy",
            "generatorRevision": row.get("generatorRevision")
            or (leaf["qwenInstallation"]["revision"] if source == FOREIGN_SOURCE else None),
            "evaluationLockSha256": base["lockSha256"],
            "actualPhonesIndependentlyVerified": False,
            **extra,
        }
        validate_case_semantics(item)
        cases.append(item)

    try:
        for row in ordered_vc:
            relative = copy_audio(row, "vc")
            actual = targets[row["targetId"]]
            for key in covered:
                target = targets[key]
                same_phones = actual["phones"] == target["phones"]
                positive = same_phones and actual["tone"] == target["tone"]
                case = "clean-positive" if positive else "tone" if same_phones else "near-phoneme"
                record(
                    row,
                    key,
                    VC_SOURCE,
                    case,
                    positive,
                    relative,
                    actualTargetId=row["targetId"],
                    knownStandardRootNewVcFamilyValidation=True,
                    mismatchBasis=None if positive else "tone" if same_phones else "phoneme",
                    mismatchDescription=None
                    if positive
                    else f"Intended {actual['pinyin']} differs from requested {target['pinyin']}.",
                )
        for first, second in pairs:
            samples = np.concatenate(
                [
                    decode_wav(audio_paths[first["id"]].read_bytes()),
                    np.zeros(GAP_SAMPLES, dtype=np.float32),
                    decode_wav(audio_paths[second["id"]].read_bytes()),
                ]
            )
            payload = encode_wav(samples)
            digest = hashlib.sha256(payload).hexdigest()
            name = f"extra-{first['id']}-then-{second['id']}"
            relative = f"audio/extra/{digest}.wav"
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            row = {
                **first,
                "id": name,
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
                    parentSha256=first["sha256"],
                    secondaryParentSha256=second["sha256"],
                    secondarySourceRootId=second["sourceRootId"],
                    secondarySourceSha256=second["sourceSha256"],
                    parentTargetIds=[first["targetId"], second["targetId"]],
                    durationSeconds=len(samples) / SAMPLE_RATE,
                    gapSamples=GAP_SAMPLES,
                    mismatchBasis="syllable-count",
                    mismatchDescription=(
                        "Two intended spoken syllables for a single-syllable request."
                    ),
                    knownStandardRootNewVcFamilyValidation=True,
                )
        for unit in foreign_generation["units"]:
            row = foreign_rows[unit["id"]]
            relative = copy_audio(row, "foreign")
            for key in row["againstTargetIds"]:
                record(
                    row,
                    key,
                    FOREIGN_SOURCE,
                    "cross-language-acoustic-mismatch",
                    False,
                    relative,
                    mismatchBasis="phoneme",
                    mismatchDescription=row["phoneticDifference"],
                    language=row["language"],
                    contrastCategory=row["contrastCategory"],
                    sourceText=row["sourceText"],
                    generationStatus=row["generationStatus"],
                    foreignPlanSha256=leaf["planSha256"],
                )
        result = {
            "schemaVersion": 1,
            "evaluationLockSha256": base["lockSha256"],
            "foreignPlanSha256": leaf["planSha256"],
            "builderSha256": fingerprint(Path(__file__)),
            "inputManifests": {
                str(p.resolve()): fingerprint(p) for p in (vc_manifest, foreign_manifest)
            },
            "exclusionManifests": exclusions,
            "completeParentLineageCheck": True,
            "sources": {
                VC_SOURCE: {
                    "usage": "unseen",
                    "requireBothClasses": True,
                    "labelProvenance": "trusted-standard-derived-VC-intended-label",
                    "unseenScope": (
                        "new VC waveforms and synthetic families; known standard parents"
                    ),
                },
                EXTRA_SOURCE: {
                    "usage": "unseen",
                    "requireBothClasses": False,
                    "labelProvenance": "fixed two-parent concatenation of new VC waveforms",
                },
                FOREIGN_SOURCE: {
                    "usage": "unseen",
                    "requireBothClasses": False,
                    "labelProvenance": "tts-intended-not-language-or-phoneme-verified",
                },
            },
            "queryPolicy": {
                "vcAndExtra": "all public covered targets, with no result-based omissions",
                "foreign": "only frozen authored target contrasts",
                "extraPairing": "next sorted same-family different-phone source, cyclic; 150ms gap",
            },
            "coverage": {
                "publicCoveredTargetIds": covered,
                "publicPositiveTargetIds": sorted(
                    {r["targetId"] for r in cases if r["expectedMatch"]}
                ),
                "vcWaveforms": len(vc_rows),
                "vcStandardRoots": len(sources),
                "extraWaveforms": len(pairs),
                "foreignWaveforms": len(foreign_rows),
                "caseQueryCounts": dict(Counter(r["case"] for r in cases)),
                "positiveQueries": sum(r["expectedMatch"] for r in cases),
                "totalQueries": len(cases),
            },
            "claims": {
                "standardRootsHistoricallyKnown": True,
                "independentHumanSpeakers": False,
                "realChildAccuracyEstablished": False,
                "allCoveredTargetsHavePositiveValidation": False,
                "newVoiceFamiliesAreIndependentRealSpeakers": False,
                "modelInferencePerformedByBuilder": False,
            },
            "cases": cases,
        }
        (staging / "manifest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        staging.rename(output)
        return result
    except BaseException:
        shutil.rmtree(staging)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-lock", type=Path, required=True)
    parser.add_argument("--vc-manifest", type=Path, required=True)
    parser.add_argument("--foreign-plan", type=Path, required=True)
    parser.add_argument("--foreign-manifest", type=Path, required=True)
    parser.add_argument("--exclude-manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_cases(
        args.evaluation_lock,
        args.vc_manifest,
        args.foreign_plan,
        args.foreign_manifest,
        args.output,
        exclusion_manifests=args.exclude_manifest,
    )
    print(
        json.dumps(
            {"manifest": str((args.output / "manifest.json").resolve()), **result["coverage"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
