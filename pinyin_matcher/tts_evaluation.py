"""Freeze and generate a public-character TTS evaluation without scoring audio.

The 32 targets by four synthetic families by two generators are intended weak
labels. A generated word, mechanical QC or a language instruction does not verify
its actual phonemes or tone. No standard recording supplies the spoken content.
Each planned seed is attempted at most once; missing audio retains its full query
placeholder and prevents a complete quality freeze.
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import SAMPLE_RATE, encode_wav, quality_check
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog
from pinyin_matcher.controlled_generation import (
    _evaluation_reference_record,
    _lock_digest,
    validate_evaluation_lock,
    verify_model,
)
from pinyin_matcher.generate import atomic_json, engine_cosy, engine_qwen
from pinyin_matcher.quality import validate_case_semantics

KIND = "pinyin-matcher-public-character-tts-plan-v1"
LABEL = "tts-character-intent-actual-phones-and-tone-unverified"
ENGINES = ("qwen", "cosy")
TERMINAL = {"accepted-mechanically", "mechanical-failure", "tts-failure", "interrupted-attempt"}
CLAIMS = {
    "actualPhonesAndTonesIndependentlyVerified": False,
    "independentHumanSpeakers": False,
    "realChildAccuracyEstablished": False,
    "standardRecordingContentUsed": False,
    "sharedFamilyLabelsDoNotCreateIndependentRealSpeakers": True,
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _base_lock(path: Path) -> dict:
    value = _read(path)
    return validate_evaluation_lock(
        path,
        Path(value["configuration"]["file"]),
        Path(value["generationPlan"]["outputDirectory"]),
    )


def _generation_plan(base: dict, output: Path) -> dict:
    directory = Path(base["modelDirectory"])
    metadata = _read(directory / "model.json")
    catalog_file = (directory / metadata["catalogFile"]).resolve()
    if not catalog_file.is_relative_to(directory.resolve()):
        raise ValueError("TTS_EVALUATION_CATALOG_PATH_INVALID")
    catalog = load_catalog(catalog_file)
    targets = {row["id"]: row for row in catalog["targets"]}
    covered = base["model"]["coveredTargetIds"]
    if (
        len(covered) != 32
        or len(set(covered)) != 32
        or not set(covered) <= set(catalog["pilotIds"])
        or any(
            targets[key]["form"] != "whole-syllable"
            or targets[key]["tone"] not in {1, 2, 3, 4}
            or not isinstance(targets[key].get("ttsText"), str)
            or not targets[key]["ttsText"].strip()
            for key in covered
        )
    ):
        raise ValueError("EXACT_PUBLIC_32_CHARACTER_TARGETS_REQUIRED")
    ma = [targets.get(f"pm-ma{i}") for i in range(1, 5)]
    if (
        not {f"pm-ma{i}" for i in range(1, 5)} <= set(covered)
        or any(not row or row["tone"] != index for index, row in enumerate(ma, 1))
        or len({tuple(row["phones"]) for row in ma}) != 1
    ):
        raise ValueError("PUBLIC_MA_FOUR_TONE_CONTRAST_REQUIRED")
    personas = base["generationPlan"]["personas"]
    if (
        len(personas) != 4
        or len({p["id"] for p in personas}) != 4
        or any(p["split"] != "test" for p in personas)
    ):
        raise ValueError("FOUR_FROZEN_TEST_FAMILIES_REQUIRED")
    labels = [
        {key: targets[target][key] for key in ("id", "pinyin", "phones", "tone", "ttsText")}
        for target in covered
    ]
    units = []
    for engine in ENGINES:
        for voice in personas:
            persona = {
                k: v for k, v in voice.items() if k not in {"referenceSeed", "referenceFile"}
            }
            for label in labels:
                name = f"public-tts-{engine}-{voice['id']}-{label['id']}-0"
                units.append(
                    {
                        "id": name,
                        "file": f"{engine}-character/{name}.wav",
                        "generator": engine,
                        "actualTargetId": label["id"],
                        "intendedPinyin": label["pinyin"],
                        "intendedTone": label["tone"],
                        "sourceText": label["ttsText"] + "。",
                        "sourceRootId": "tts-text-" + label["id"],
                        "lexicalRootId": label["id"],
                        "voiceFamilyId": voice["id"],
                        "referenceRootId": voice["id"] + "-reference",
                        "sharedReferenceFile": str(
                            Path(base["generationPlan"]["outputDirectory"])
                            / "references"
                            / (voice["id"] + ".wav")
                        ),
                        "referenceConditioning": (
                            "shared-description-family; Qwen VoiceDesign does not condition "
                            "on the reference WAV"
                        )
                        if engine == "qwen"
                        else "main-lock-Qwen-reference-zero-shot",
                        "persona": persona,
                        "seed": int(
                            hashlib.sha256(
                                (base["lockSha256"] + ":public-character-v1:" + name).encode()
                            ).hexdigest()[:8],
                            16,
                        ),
                        "split": "test",
                        "labelProvenance": LABEL,
                    }
                )
    return {
        "outputDirectory": str(output.resolve()),
        "targets": labels,
        "units": units,
        "expectedWaveforms": 256,
        "expectedQueries": 8192,
        "expectedWaveformsPerEngine": 128,
        "coveredTargetIds": covered,
        "allTargetsQueriedForEveryWaveform": True,
        "oneSeedOneAttempt": True,
        "mechanicalFailureAudioMustBeRetained": True,
        "actualPhonesAndTonesIndependentlyVerified": False,
        "modelSelectionOnThisSetAllowed": False,
        "generation": {"threads": 4, "device": "mps", "maximumSeconds": 8},
    }


def create_tts_plan(evaluation_lock: Path, output: Path, plan_path: Path) -> dict:
    """Freeze metadata/text only; never read a reference or generate any speech."""
    if output.exists() or plan_path.exists():
        raise ValueError("TTS_PLAN_AND_OUTPUT_MUST_BE_NEW")
    base = _base_lock(evaluation_lock)
    registry = _read(Path(base["generatorRegistry"]["file"]))
    plan = {
        "schemaVersion": 1,
        "kind": KIND,
        "stage": "before-audio-generation",
        "createdUtc": datetime.now(UTC).isoformat(),
        "evaluationLock": {
            "file": str(evaluation_lock.resolve()),
            "sha256": fingerprint(evaluation_lock),
            "lockSha256": base["lockSha256"],
        },
        **{
            k: base[k]
            for k in (
                "model",
                "modelDirectory",
                "calibrationReport",
                "calibrationCollection",
                "generatorRegistry",
            )
        },
        "generatorInstallations": {engine: registry["generators"][engine] for engine in ENGINES},
        "cosySource": registry["cosySource"],
        "leafCodeSha256": fingerprint(Path(__file__)),
        "generationPlan": _generation_plan(base, output),
        "claims": dict(CLAIMS),
    }
    plan["planSha256"] = _lock_digest(plan)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with plan_path.open("x") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return plan


def validate_tts_plan(plan_path: Path) -> dict:
    if not plan_path.is_file() or plan_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("TTS_EVALUATION_PLAN_REQUIRED")
    plan = _read(plan_path)
    digest = plan.pop("planSha256", None)
    if plan.get("schemaVersion") != 1 or plan.get("kind") != KIND or digest != _lock_digest(plan):
        raise ValueError("TTS_EVALUATION_PLAN_INVALID")
    plan["planSha256"] = digest
    if plan.get("claims") != CLAIMS:
        raise ValueError("TTS_WEAK_LABEL_CLAIMS_CHANGED")
    binding = plan["evaluationLock"]
    if fingerprint(Path(binding["file"])) != binding["sha256"]:
        raise ValueError("TTS_BASE_LOCK_CHANGED")
    base = _base_lock(Path(binding["file"]))
    if binding["lockSha256"] != base["lockSha256"] or any(
        plan[k] != base[k]
        for k in (
            "model",
            "modelDirectory",
            "calibrationReport",
            "calibrationCollection",
            "generatorRegistry",
        )
    ):
        raise ValueError("TTS_MODEL_OR_CALIBRATION_BINDING_CHANGED")
    registry = _read(Path(base["generatorRegistry"]["file"]))
    if plan["generatorInstallations"] != {e: registry["generators"][e] for e in ENGINES} or (
        plan["cosySource"] != registry["cosySource"]
    ):
        raise ValueError("TTS_INSTALLATION_BINDING_CHANGED")
    if plan["leafCodeSha256"] != fingerprint(Path(__file__)):
        raise ValueError("TTS_EVALUATION_CODE_CHANGED")
    if plan["generationPlan"] != _generation_plan(
        base, Path(plan["generationPlan"]["outputDirectory"])
    ):
        raise ValueError("TTS_FROZEN_GENERATION_PLAN_CHANGED")
    return plan


def _validate_data(data: dict, plan: dict, *, verify_audio=True):
    units = plan["generationPlan"]["units"]
    if data.get("ttsPlanSha256") != plan["planSha256"] or len(data.get("items", [])) != len(units):
        raise ValueError("TTS_COMPLETE_PLACEHOLDER_SET_REQUIRED")
    root = Path(plan["generationPlan"]["outputDirectory"])
    for row, unit in zip(data["items"], units, strict=True):
        if any(row.get(k) != v for k, v in unit.items()) or row.get("generationStatus") not in (
            TERMINAL | {"pending", "attempt-started"}
        ):
            raise ValueError("TTS_PLANNED_UNIT_CHANGED")
        path = (root / row["file"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("TTS_AUDIO_PATH_INVALID")
        if verify_audio:
            if row.get("sha256"):
                if fingerprint(path) != row["sha256"]:
                    raise ValueError("TTS_EXISTING_AUDIO_CHANGED")
            elif path.exists():
                raise ValueError("TTS_UNRECORDED_AUDIO_FORBIDS_RETRY")


def _quality_manifest(data: dict, plan: dict) -> dict:
    targets = plan["generationPlan"]["targets"]
    labels = {r["id"]: r for r in targets}
    cases = []
    for row in data["items"]:
        actual = labels[row["actualTargetId"]]
        for target in targets:
            positive = target["id"] == actual["id"]
            tone = actual["phones"] == target["phones"] and not positive
            case = "clean-positive" if positive else "tone" if tone else "near-phoneme"
            cases.append(
                {
                    **{
                        k: row[k]
                        for k in (
                            "voiceFamilyId",
                            "referenceRootId",
                            "sourceRootId",
                            "lexicalRootId",
                            "generator",
                            "actualTargetId",
                            "sourceText",
                            "labelProvenance",
                            "referenceConditioning",
                            "generationStatus",
                        )
                    },
                    "id": row["id"] + "-against-" + target["id"],
                    "unitId": row["id"],
                    "source": "pure-tts-new-family-" + row["generator"],
                    "case": case,
                    "targetId": target["id"],
                    "expectedMatch": positive,
                    "clearAudio": True,
                    "file": row["file"],
                    "sha256": row.get("sha256"),
                    "split": "test",
                    "referenceSha256": row.get("referenceSha256"),
                    "generatorRevision": plan["generatorInstallations"][row["generator"]][
                        "revision"
                    ],
                    "contrastCategory": "public-target-positive"
                    if positive
                    else "same-syllable-tone"
                    if tone
                    else "phoneme-mismatch",
                    "language": "Mandarin",
                    "ttsPlanSha256": plan["planSha256"],
                    "mismatchBasis": None if positive else "tone" if tone else "phoneme",
                    "mismatchDescription": None
                    if positive
                    else f"Intended {actual['pinyin']} differs from requested {target['pinyin']}.",
                    "actualPhonesAndToneIndependentlyVerified": False,
                }
            )
    ready = _ready(data)
    return {
        "schemaVersion": 1,
        "ttsPlanSha256": plan["planSha256"],
        "evaluationLockSha256": plan["evaluationLock"]["lockSha256"],
        "qualityManifestReady": bool(ready),
        "expectedWaveforms": 256,
        "expectedQueries": 8192,
        "allPlannedAttemptsRequired": True,
        "clearAudioIsPredeclaredIntentNotAcceptanceFiltering": True,
        "sources": {
            "pure-tts-new-family-" + engine: {
                "usage": "unseen",
                "requireBothClasses": True,
                "labelProvenance": LABEL,
                "unseenScope": (
                    "new synthetic utterances and family descriptions; reused target text "
                    "is not an independent human source"
                ),
                "actualPhonesAndTonesIndependentlyVerified": False,
            }
            for engine in ENGINES
        },
        "coverage": {
            "publicIntendedPositiveTargetIds": plan["generationPlan"]["coveredTargetIds"],
            "intendedPositiveWaveforms": 256,
            "maToneContrastWaveforms": 32,
            "expectedQueries": len(cases),
            "missingWaveforms": sum(not row.get("sha256") for row in data["items"]),
        },
        "claims": plan["claims"],
        "cases": cases,
    }


def _ready(data: dict) -> bool:
    return len(data["items"]) == 256 and all(
        row.get("sha256")
        and row["generationStatus"] in {"accepted-mechanically", "mechanical-failure"}
        for row in data["items"]
    )


def _reference_digest(row: dict, plan: dict) -> str:
    reference = Path(row["sharedReferenceFile"])
    if not reference.is_file():
        raise ValueError("MAIN_LOCK_SHARED_REFERENCE_REQUIRED")
    _evaluation_reference_record(
        reference, row["persona"], {"lockSha256": plan["evaluationLock"]["lockSha256"]}
    )
    return fingerprint(reference)


@contextmanager
def _generation_guard(output: Path):
    guard = output / ".generation.lock"
    try:
        with guard.open("x") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as error:
        raise ValueError(
            "TTS_ENGINE_ALREADY_RUNNING_OR_INTERRUPTED_LOCK_REQUIRES_INVESTIGATION"
        ) from error
    try:
        yield
    finally:
        guard.unlink()


def generate_tts_evaluation(
    plan_path: Path, engine: str, model: Path, *, source: Path | None = None
) -> dict:
    """Run just one frozen engine. Never redraw a failed or interrupted utterance."""
    if engine not in ENGINES:
        raise ValueError("ONE_FIXED_TTS_ENGINE_REQUIRED")
    plan = validate_tts_plan(plan_path)
    if verify_model(engine, model.resolve(strict=True)) != plan["generatorInstallations"][engine]:
        raise ValueError("TTS_ENGINE_INSTALLATION_CHANGED")
    output = Path(plan["generationPlan"]["outputDirectory"])
    manifest = output / "manifest.json"
    if output.exists() and not manifest.is_file():
        raise ValueError("TTS_OUTPUT_WITHOUT_MANIFEST_FORBIDDEN")
    output.mkdir(parents=True, exist_ok=True)
    with _generation_guard(output):
        data = (
            _read(manifest)
            if manifest.exists()
            else {
                "version": 1,
                "cohort": "locked-public-character-tts-weak-label-evaluation",
                "ttsPlanSha256": plan["planSha256"],
                "evaluationLockSha256": plan["evaluationLock"]["lockSha256"],
                "expectedWaveforms": 256,
                "sharedReferences": {},
                "items": [
                    {
                        **unit,
                        "generationStatus": "pending",
                        "generatorRevision": plan["generatorInstallations"][unit["generator"]][
                            "revision"
                        ],
                    }
                    for unit in plan["generationPlan"]["units"]
                ],
            }
        )
        _validate_data(data, plan)

        def save(*, quality=False):
            data["qualityManifestReady"] = bool(_ready(data))
            atomic_json(manifest, data)
            if quality:
                atomic_json(output / "quality-manifest.json", _quality_manifest(data, plan))

        for row in data["items"]:
            if row["generationStatus"] == "attempt-started":
                row.update(
                    generationStatus="interrupted-attempt",
                    error="Previous attempt did not finish; never resample.",
                )
        save(quality=True)
        pending = [
            r
            for r in data["items"]
            if r["generator"] == engine and r["generationStatus"] == "pending"
        ]
        if not pending:
            return data
        # References are supplied by the main lock's own one-time generation.
        # Qwen uses their family description, while Cosy actually conditions on WAV.
        for row in pending:
            digest = _reference_digest(row, plan)
            if data["sharedReferences"].setdefault(row["voiceFamilyId"], digest) != digest:
                raise ValueError("TTS_SHARED_REFERENCE_CHANGED")
            row["referenceSha256"] = digest
        save()
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            settings = plan["generationPlan"]["generation"]
            synthesize = (
                engine_qwen(model)
                if engine == "qwen"
                else engine_cosy(
                    model,
                    (source or ROOT / "private/matcher-cosy-source").resolve(strict=True),
                    settings["threads"],
                    settings["device"],
                )
            )
        except Exception as error:
            for row in pending:
                row.update(
                    generationStatus="tts-failure", error=str(error), errorType=type(error).__name__
                )
            save(quality=True)
            return data
        for row in pending:
            validate_tts_plan(plan_path)
            if _reference_digest(row, plan) != row["referenceSha256"]:
                raise ValueError("TTS_SHARED_REFERENCE_CHANGED")
            row["generationStatus"] = "attempt-started"
            save()
            started = time.perf_counter()
            try:
                samples, rate = synthesize(
                    row["sourceText"], row["persona"], row["seed"], Path(row["sharedReferenceFile"])
                )
                samples = np.asarray(samples, dtype=np.float32)
                if (
                    samples.ndim != 1
                    or not np.isfinite(samples).all()
                    or type(rate) is not int
                    or rate <= 0
                ):
                    raise ValueError("TTS_INVALID_OUTPUT")
                divisor = math.gcd(rate, SAMPLE_RATE)
                samples = resample_poly(samples, SAMPLE_RATE // divisor, rate // divisor).astype(
                    np.float32
                )
                validate_tts_plan(plan_path)
                if _reference_digest(row, plan) != row["referenceSha256"]:
                    raise ValueError("TTS_SHARED_REFERENCE_CHANGED")
                path = output / row["file"]
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(encode_wav(samples))
                row["sha256"] = fingerprint(path)
                row["durationSeconds"] = len(samples) / SAMPLE_RATE
                row["generationStatus"] = "mechanical-failure"
                row["quality"] = quality_check(samples)
                row["generationStatus"] = "accepted-mechanically"
            except Exception as error:
                row.update(
                    generationStatus="mechanical-failure" if row.get("sha256") else "tts-failure",
                    error=str(error),
                    errorType=type(error).__name__,
                )
            row["generationSeconds"] = round(time.perf_counter() - started, 4)
            save()
        validate_tts_plan(plan_path)
        _validate_data(data, plan)
        save(quality=True)
        return data


def merge_quality_manifests(manifests: list[Path], output: Path, *, tts_plan: Path) -> dict:
    """Copy every input query/WAV into a new safe root; no inference or filtering."""
    if output.exists() or not manifests:
        raise ValueError("NEW_MERGED_OUTPUT_AND_NONEMPTY_MANIFESTS_REQUIRED")
    plan = validate_tts_plan(tts_plan)
    tts_root = Path(plan["generationPlan"]["outputDirectory"])
    tts_manifest = tts_root / "manifest.json"
    tts_manifest_sha = fingerprint(tts_manifest)
    tts_data = _read(tts_manifest)
    _validate_data(tts_data, plan)
    canonical_tts = _quality_manifest(tts_data, plan)
    if not canonical_tts["qualityManifestReady"]:
        raise ValueError("ALL_256_TTS_WAVEFORMS_REQUIRED_NO_MISSING_ATTEMPTS")
    cases, sources, exclusions, inputs = [], {}, {}, []
    identifiers, files, tts_seen = set(), {}, False
    for manifest in manifests:
        input_sha = fingerprint(manifest)
        data = _read(manifest)
        if data.get("evaluationLockSha256") != plan["evaluationLock"]["lockSha256"]:
            raise ValueError("MERGED_EVALUATION_LOCK_MISMATCH")
        if data.get("qualityManifestReady", True) is not True:
            raise ValueError("INCOMPLETE_QUALITY_INPUT_FORBIDDEN")
        is_tts_input = bool(data.get("ttsPlanSha256"))
        if is_tts_input:
            if data != canonical_tts:
                raise ValueError("COMPLETE_CANONICAL_TTS_QUERY_SET_REQUIRED")
            tts_seen = True
        if data.get("schemaVersion") != 1 or not data.get("sources") or not data.get("cases"):
            raise ValueError("QUALITY_MERGE_INPUT_INVALID")
        for name, policy in data["sources"].items():
            if name.startswith("pure-tts-new-family-") and not is_tts_input:
                raise ValueError("TTS_SOURCE_NAMES_RESERVED_FOR_COMPLETE_CANONICAL_INPUT")
            if name in sources and sources[name] != policy:
                raise ValueError("QUALITY_SOURCE_POLICY_COLLISION")
            sources[name] = policy
        for item in data.get("exclusionManifests", []):
            if fingerprint(Path(item["path"])) != item["sha256"]:
                raise ValueError("QUALITY_EXCLUSION_MANIFEST_CHANGED")
            exclusions[item["path"]] = item
        for row in data["cases"]:
            if row["id"] in identifiers or row["source"] not in data["sources"]:
                raise ValueError("QUALITY_DUPLICATE_OR_UNDECLARED_QUERY")
            identifiers.add(row["id"])
            validate_case_semantics(row)
            path = (manifest.parent / (row.get("file") or "")).resolve()
            if (
                not row.get("file")
                or Path(row["file"]).is_absolute()
                or not path.is_relative_to(manifest.parent.resolve())
            ):
                raise ValueError("QUALITY_MERGE_AUDIO_PATH_INVALID")
            if not row.get("sha256") or fingerprint(path) != row["sha256"]:
                raise ValueError("QUALITY_MERGE_AUDIO_MISSING_OR_CHANGED")
            files.setdefault(row["sha256"], path)
            cases.append({**row, "file": "audio/" + row["sha256"] + ".wav"})
        inputs.append(
            {
                "file": str(manifest.resolve()),
                "sha256": input_sha,
                "queries": len(data["cases"]),
                "coverage": data.get("coverage", {}),
            }
        )
    if not tts_seen:
        raise ValueError("CANONICAL_TTS_QUALITY_INPUT_REQUIRED")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name + ".building-", dir=output.parent))
    try:
        (staging / "audio").mkdir()
        for digest, path in files.items():
            destination = staging / "audio" / (digest + ".wav")
            shutil.copyfile(path, destination)
            if fingerprint(destination) != digest:
                raise ValueError("QUALITY_MERGE_AUDIO_CHANGED_DURING_COPY")
        validate_tts_plan(tts_plan)
        if fingerprint(tts_manifest) != tts_manifest_sha or any(
            fingerprint(Path(item["file"])) != item["sha256"] for item in inputs
        ):
            raise ValueError("QUALITY_INPUT_CHANGED_DURING_MERGE")
        result = {
            "schemaVersion": 1,
            "evaluationLockSha256": plan["evaluationLock"]["lockSha256"],
            "sources": sources,
            "cases": cases,
            "inputManifests": inputs,
            "ttsGenerationManifest": {"file": str(tts_manifest), "sha256": tts_manifest_sha},
            "exclusionManifests": list(exclusions.values()),
            "coverage": {
                "totalQueries": len(cases),
                "distinctWaveforms": len(files),
                "queryCountsBySource": dict(Counter(r["source"] for r in cases)),
                "positiveTargetsBySource": {
                    source: sorted(
                        {
                            r["targetId"]
                            for r in cases
                            if r["source"] == source and r["expectedMatch"]
                        }
                    )
                    for source in sources
                },
            },
            "claims": {
                "realChildAccuracyEstablished": False,
                "independentHumanSpeakers": False,
                "ttsActualPhonesAndTonesIndependentlyVerified": False,
                "sourceAndGeneratorAndCategoryPoliciesPreserved": True,
                "modelInferencePerformedByMerger": False,
            },
        }
        atomic_json(staging / "manifest.json", result)
        staging.rename(output)
        return result
    except BaseException:
        shutil.rmtree(staging)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--evaluation-lock", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--plan", type=Path, required=True)
    check = commands.add_parser("check")
    check.add_argument("--plan", type=Path, required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--plan", type=Path, required=True)
    generate.add_argument("--engine", choices=ENGINES, required=True)
    generate.add_argument("--model", type=Path, required=True)
    generate.add_argument("--source", type=Path)
    merge = commands.add_parser("merge")
    merge.add_argument("--tts-plan", type=Path, required=True)
    merge.add_argument("--manifest", type=Path, action="append", required=True)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        result = create_tts_plan(args.evaluation_lock, args.output, args.plan)
        print(
            json.dumps(
                {
                    "planSha256": result["planSha256"],
                    "expectedWaveforms": 256,
                    "audioGenerated": False,
                }
            )
        )
    elif args.command == "check":
        print(json.dumps({"planSha256": validate_tts_plan(args.plan)["planSha256"]}))
    elif args.command == "generate":
        result = generate_tts_evaluation(args.plan, args.engine, args.model, source=args.source)
        print(
            json.dumps(
                {
                    "items": len(result["items"]),
                    "qualityManifestReady": result["qualityManifestReady"],
                    "statuses": dict(
                        Counter(
                            r["generationStatus"]
                            for r in result["items"]
                            if r["generator"] == args.engine
                        )
                    ),
                }
            )
        )
    else:
        result = merge_quality_manifests(args.manifest, args.output, tts_plan=args.tts_plan)
        print(json.dumps({"manifest": str(args.output / "manifest.json"), **result["coverage"]}))


if __name__ == "__main__":
    main()
