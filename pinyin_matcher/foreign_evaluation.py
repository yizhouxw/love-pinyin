"""Generate the frozen foreign holdout only after a passed model evaluation lock.

The English/French text and explicit target contrast are intended weak labels.
Neither a language instruction nor mechanical QC verifies the emitted phonemes.
Every planned attempt is retained; a missing waveform blocks a complete quality set.
"""

import argparse
import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import SAMPLE_RATE, encode_wav, quality_check
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.controlled_generation import (
    _lock_digest,
    validate_evaluation_lock,
    verify_model,
)
from pinyin_matcher.foreign_data import CONFIG, _text, configuration
from pinyin_matcher.generate import atomic_json, engine_qwen

KIND = "pinyin-matcher-foreign-evaluation-plan-v1"
LABEL = "tts-intended-not-language-or-phoneme-verified"


def _base_lock(path: Path) -> dict:
    value = json.loads(path.read_text())
    return validate_evaluation_lock(
        path,
        Path(value["configuration"]["file"]),
        Path(value["generationPlan"]["outputDirectory"]),
    )


def _code_snapshot() -> dict:
    return {
        name: fingerprint(Path(__file__).parent / name)
        for name in ("foreign_evaluation.py", "foreign_data.py")
    }


def _generation_plan(config: dict, base: dict, output: Path) -> dict:
    definitions = [row for row in config["definitions"] if row["split"] == "test"]
    voices = config["blindPersonaIds"]
    if len(definitions) != 24 or len(voices) != 4 or len(set(voices)) != 4:
        raise ValueError("FROZEN_FOREIGN_HOLDOUT_SET_REQUIRED")
    persona_rows = base["generationPlan"]["personas"]
    personas = {row["id"]: row for row in persona_rows}
    if (
        len(persona_rows) != 4
        or len(personas) != 4
        or set(personas) != set(voices)
        or any(p["split"] != "test" for p in persona_rows)
    ):
        raise ValueError("BASE_LOCK_BLIND_FAMILIES_MISMATCH")
    units = []
    for voice in voices:
        for definition in definitions:
            name = f"foreign-qwen-{voice}-{definition['id']}-0"
            persona = {
                "id": voice,
                "split": "test",
                "language": definition["language"],
                "instruction": personas[voice]["instruction"].split("标准普通话")[0]
                + f"清晰自然的{definition['language']}母语发音，"
                "只读给出的单词一次，不添加解释，不翻译为中文。",
            }
            units.append(
                {
                    "id": name,
                    "file": "qwen-locked-evaluation/" + name + ".wav",
                    "foreignContrastId": definition["id"],
                    "lexicalRootId": definition["lexicalRootId"],
                    "sourceRootId": "foreign-text-" + definition["lexicalRootId"],
                    "voiceFamilyId": voice,
                    "referenceRootId": voice + "-reference",
                    "sourceText": definition["text"],
                    "language": definition["language"],
                    "locale": definition["locale"],
                    "againstTargetIds": definition["againstTargetIds"],
                    "contrastCategory": definition["contrastCategory"],
                    "phoneticDifference": definition["phoneticDifference"],
                    "seed": config["seed"] + int(hashlib.sha256(name.encode()).hexdigest()[:7], 16),
                    "persona": persona,
                    "split": "test",
                    "labelProvenance": LABEL,
                }
            )
    return {
        "outputDirectory": str(output.resolve()),
        "expectedWaveforms": 96,
        "maximumSeconds": config["maximumSeconds"],
        "units": units,
        "allPlannedAttemptsRequired": True,
        "languageIdentityIsCorrectnessLabel": False,
        "actualPhonesIndependentlyVerified": False,
        "modelSelectionOnThisSetAllowed": False,
    }


def _vocabulary_exclusions(config: dict, source: Path) -> list[dict]:
    """Bind earlier vocabulary without reading or generating any audio."""
    bindings = []
    tests = [row for row in config["definitions"] if row["split"] == "test"]
    for excluded in config.get("heldoutVocabularyExclusions", []):
        file = (source.parent / excluded["file"]).resolve(strict=True)
        if fingerprint(file) != excluded["sha256"]:
            raise ValueError("FOREIGN_EXCLUDED_VOCABULARY_CHANGED")
        rows = configuration(file)["definitions"]
        texts = {_text(row["text"]) for row in rows}
        lexical = {row["lexicalRootId"] for row in rows}
        if any(_text(row["text"]) in texts or row["lexicalRootId"] in lexical for row in tests):
            raise ValueError("FOREIGN_HELDOUT_VOCABULARY_REUSED")
        bindings.append({"file": str(file), "sha256": excluded["sha256"]})
    return bindings


def create_foreign_plan(
    evaluation_lock: Path, foreign_configuration: Path, output: Path, plan_path: Path
) -> dict:
    """Freeze metadata only. Does not import TTS, read held-out audio or generate it."""
    if plan_path.exists() or output.exists():
        raise ValueError("FOREIGN_PLAN_AND_OUTPUT_MUST_BE_NEW")
    base = _base_lock(evaluation_lock)
    config = configuration(foreign_configuration)
    exclusions = _vocabulary_exclusions(config, foreign_configuration.resolve())
    generation = _generation_plan(config, base, output)
    frozen = plan_path.with_suffix(".configuration.frozen.json").resolve()
    if frozen.exists():
        raise ValueError("FOREIGN_FROZEN_CONFIGURATION_ALREADY_EXISTS")
    registry = json.loads(Path(base["generatorRegistry"]["file"]).read_text())
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
        "model": base["model"],
        "modelDirectory": base["modelDirectory"],
        "calibrationReport": base["calibrationReport"],
        "calibrationCollection": base["calibrationCollection"],
        "configuration": {
            "file": str(frozen),
            "sourceFile": str(foreign_configuration.resolve()),
            "sha256": fingerprint(foreign_configuration),
        },
        "generatorRegistry": base["generatorRegistry"],
        "qwenInstallation": registry["generators"]["qwen"],
        "vocabularyExclusions": exclusions,
        "codeSha256": _code_snapshot(),
        "generationPlan": generation,
    }
    plan["planSha256"] = _lock_digest(plan)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with frozen.open("xb") as stream:
        stream.write(foreign_configuration.read_bytes())
    with plan_path.open("x") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return plan


def validate_foreign_plan(plan_path: Path) -> dict:
    if not plan_path.is_file() or plan_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("FOREIGN_EVALUATION_PLAN_REQUIRED")
    plan = json.loads(plan_path.read_text())
    digest = plan.pop("planSha256", None)
    if plan.get("kind") != KIND or plan.get("schemaVersion") != 1 or digest != _lock_digest(plan):
        raise ValueError("FOREIGN_EVALUATION_PLAN_INVALID")
    plan["planSha256"] = digest
    binding = plan["evaluationLock"]
    if fingerprint(Path(binding["file"])) != binding["sha256"]:
        raise ValueError("FOREIGN_BASE_EVALUATION_LOCK_CHANGED")
    base = _base_lock(Path(binding["file"]))
    if binding["lockSha256"] != base["lockSha256"] or any(
        plan[key] != base[key]
        for key in (
            "model",
            "modelDirectory",
            "calibrationReport",
            "calibrationCollection",
            "generatorRegistry",
        )
    ):
        raise ValueError("FOREIGN_MODEL_OR_CALIBRATION_BINDING_CHANGED")
    config = plan["configuration"]
    if any(fingerprint(Path(config[key])) != config["sha256"] for key in ("file", "sourceFile")):
        raise ValueError("FROZEN_FOREIGN_CONFIGURATION_CHANGED")
    frozen_configuration = configuration(Path(config["file"]))
    if plan.get("vocabularyExclusions", []) != _vocabulary_exclusions(
        frozen_configuration, Path(config["sourceFile"])
    ):
        raise ValueError("FOREIGN_EXCLUSION_BINDING_CHANGED")
    registry = json.loads(Path(base["generatorRegistry"]["file"]).read_text())
    if plan["qwenInstallation"] != registry["generators"]["qwen"]:
        raise ValueError("FOREIGN_GENERATOR_BINDING_CHANGED")
    if plan["codeSha256"] != _code_snapshot():
        raise ValueError("FROZEN_FOREIGN_CODE_CHANGED")
    if plan["generationPlan"] != _generation_plan(
        frozen_configuration, base, Path(plan["generationPlan"]["outputDirectory"])
    ):
        raise ValueError("FROZEN_FOREIGN_GENERATION_PLAN_CHANGED")
    return plan


def _quality_manifest(data: dict, plan: dict) -> dict:
    cases = []
    for row in data["items"]:
        completed = row["generationStatus"] in {"accepted-mechanically", "mechanical-failure"}
        for target in row["againstTargetIds"]:
            cases.append(
                {
                    **{
                        key: row[key]
                        for key in (
                            "voiceFamilyId",
                            "referenceRootId",
                            "sourceRootId",
                            "lexicalRootId",
                            "split",
                            "labelProvenance",
                        )
                    },
                    "id": row["id"] + "-against-" + target,
                    "source": "foreign-unseen-qwen",
                    "case": "cross-language-acoustic-mismatch",
                    "unitId": row["id"],
                    "targetId": target,
                    "expectedMatch": False,
                    "clearAudio": False,
                    "file": row.get("file"),
                    # Interrupted output is preserved for diagnosis, never a complete case.
                    "sha256": row.get("sha256") if completed else None,
                    "mismatchBasis": "phoneme",
                    "mismatchDescription": row["phoneticDifference"],
                    "sourceText": row["sourceText"],
                    "language": row["language"],
                    "actualPhonesIndependentlyVerified": False,
                    "generationStatus": row["generationStatus"],
                }
            )
    ready = len(data["items"]) == plan["generationPlan"]["expectedWaveforms"] and all(
        row.get("sha256")
        and row["generationStatus"] in {"accepted-mechanically", "mechanical-failure"}
        for row in data["items"]
    )
    return {
        "schemaVersion": 1,
        "foreignPlanSha256": plan["planSha256"],
        "qualityManifestReady": bool(ready),
        "expectedWaveforms": plan["generationPlan"]["expectedWaveforms"],
        "allPlannedAttemptsRequired": True,
        "sources": {
            "foreign-unseen-qwen": {
                "usage": "unseen",
                "labelProvenance": LABEL,
                "requireBothClasses": False,
            }
        },
        "cases": cases,
    }


def generate_foreign_evaluation(plan_path: Path, model_dir: Path) -> dict:
    """Consume a frozen plan. A failed attempt is terminal and remains in its denominator."""
    plan = validate_foreign_plan(plan_path)
    model_dir = model_dir.resolve(strict=True)
    if verify_model("qwen", model_dir) != plan["qwenInstallation"]:
        raise ValueError("FOREIGN_QWEN_INSTALLATION_CHANGED")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    output = Path(plan["generationPlan"]["outputDirectory"])
    manifest = output / "manifest.json"
    units = plan["generationPlan"]["units"]
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if data.get("foreignPlanSha256") != plan["planSha256"] or len(data.get("items", [])) != len(
            units
        ):
            raise ValueError("FOREIGN_EXISTING_MANIFEST_BINDING_MISMATCH")
        for row, unit in zip(data["items"], units, strict=True):
            if any(row.get(key) != value for key, value in unit.items()):
                raise ValueError("FOREIGN_EXISTING_UNIT_CHANGED")
            audio = output / row["file"]
            if row["generationStatus"] == "in-progress":
                row.update(
                    generationStatus="tts-failure",
                    error="PREVIOUS_ATTEMPT_INTERRUPTED",
                    errorType="InterruptedAttempt",
                )
                if audio.exists() and not row.get("sha256"):
                    row["sha256"] = fingerprint(audio)
                    row["interruptedOutputRetained"] = True
            if row.get("sha256"):
                if fingerprint(audio) != row["sha256"]:
                    raise ValueError("FOREIGN_EXISTING_AUDIO_CHANGED")
            elif audio.exists():
                raise ValueError("FOREIGN_UNRECORDED_OUTPUT_REQUIRES_INVESTIGATION")
    else:
        if output.exists():
            raise ValueError("FOREIGN_OUTPUT_WITHOUT_MANIFEST_FORBIDDEN")
        output.mkdir(parents=True)
        data = {
            "version": 1,
            "cohort": "locked-synthetic-foreign-evaluation",
            "foreignPlanSha256": plan["planSha256"],
            "evaluationLockSha256": plan["evaluationLock"]["lockSha256"],
            "languageIdentityIsCorrectnessLabel": False,
            "actualPhonesIndependentlyVerified": False,
            "expectedWaveforms": 96,
            "generatorInstallation": plan["qwenInstallation"],
            "items": [
                {
                    **unit,
                    "generator": "qwen",
                    "generationMode": "generate_voice_design",
                    "generatorRevision": plan["qwenInstallation"]["revision"],
                    "generatorWeightsSha256": {
                        row["path"]: row["sha256"]
                        for row in plan["qwenInstallation"]["files"]
                        if row["path"].endswith(".safetensors")
                    },
                    "generationStatus": "pending",
                }
                for unit in units
            ],
        }

    def save():
        quality = _quality_manifest(data, plan)
        data["qualityManifestReady"] = quality["qualityManifestReady"]
        atomic_json(manifest, data)
        atomic_json(output / "quality-manifest.json", quality)

    save()
    if not any(row["generationStatus"] == "pending" for row in data["items"]):
        return data
    # Failures to initialize also retain all 96 explicit records.
    try:
        synthesize = engine_qwen(model_dir)
    except Exception as error:
        for row in data["items"]:
            if row["generationStatus"] == "pending":
                row.update(
                    generationStatus="tts-failure", error=str(error), errorType=type(error).__name__
                )
        save()
        return data
    for row in data["items"]:
        if row["generationStatus"] != "pending":
            continue
        validate_foreign_plan(plan_path)
        row["generationStatus"] = "in-progress"
        row["attemptStartedUtc"] = datetime.now(UTC).isoformat()
        save()
        started = time.perf_counter()
        try:
            samples, rate = synthesize(row["sourceText"], row["persona"], row["seed"])
            samples = np.asarray(samples, dtype=np.float32)
            if (
                samples.ndim != 1
                or not np.isfinite(samples).all()
                or not isinstance(rate, int)
                or rate <= 0
            ):
                raise ValueError("TTS_INVALID_OUTPUT")
            divisor = math.gcd(rate, SAMPLE_RATE)
            samples = resample_poly(samples, SAMPLE_RATE // divisor, rate // divisor).astype(
                np.float32
            )
            validate_foreign_plan(plan_path)
            audio = output / row["file"]
            audio.parent.mkdir(parents=True, exist_ok=True)
            with audio.open("xb") as stream:
                stream.write(encode_wav(samples))
            row["sha256"] = fingerprint(audio)
            row["durationSeconds"] = len(samples) / SAMPLE_RATE
            # Keep the actual WAV even when mechanical quality fails; no model-based filtering.
            row["generationStatus"] = "mechanical-failure"
            row["quality"] = quality_check(samples)
            if len(samples) / SAMPLE_RATE > plan["generationPlan"]["maximumSeconds"]:
                raise ValueError("FOREIGN_MAXIMUM_DURATION_EXCEEDED")
            row["generationStatus"] = "accepted-mechanically"
        except Exception as error:
            row.update(
                generationStatus="mechanical-failure" if row.get("sha256") else "tts-failure",
                error=str(error),
                errorType=type(error).__name__,
            )
        row["generationSeconds"] = round(time.perf_counter() - started, 4)
        save()
    validate_foreign_plan(plan_path)
    if verify_model("qwen", model_dir) != plan["qwenInstallation"]:
        raise ValueError("FOREIGN_QWEN_INSTALLATION_CHANGED")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--evaluation-lock", type=Path, required=True)
    create.add_argument("--configuration", type=Path, default=CONFIG)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--plan", type=Path, required=True)
    check = commands.add_parser("check")
    check.add_argument("--plan", type=Path, required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--plan", type=Path, required=True)
    generate.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        result = create_foreign_plan(
            args.evaluation_lock, args.configuration, args.output, args.plan
        )
        print(json.dumps({"planSha256": result["planSha256"], "expectedWaveforms": 96}))
    elif args.command == "check":
        print(json.dumps({"planSha256": validate_foreign_plan(args.plan)["planSha256"]}))
    else:
        result = generate_foreign_evaluation(args.plan, args.model)
        print(
            json.dumps(
                {
                    "items": len(result["items"]),
                    "qualityManifestReady": result["qualityManifestReady"],
                }
            )
        )
        if not result["qualityManifestReady"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
