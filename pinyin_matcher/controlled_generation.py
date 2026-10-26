"""Offline balanced phoneme/character TTS experiments; all labels remain weak."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import (
    SAMPLE_RATE,
    decode_wav,
    encode_wav,
    features,
    quality_check,
    trim_silence,
)
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.generate import atomic_json, engine_cosy, engine_qwen

CONFIG = ROOT / "content/pronunciation-contrast-training.json"


EVALUATION_LOCK_KIND = "pinyin-matcher-model-and-generation-plan-v1"
EVALUATION_SUFFIX = "-locked-evaluation"


def _lock_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _generation_code_snapshot() -> dict[str, str]:
    from pinyin_matcher.quality import _evaluation_code

    return _evaluation_code() | {
        name: fingerprint(Path(__file__).parent / name)
        for name in ["controlled_generation.py", "generate.py"]
    }


def _evaluation_model_snapshot(model: Path, *, require_usable: bool = False) -> dict:
    from pinyin_matcher.quality import _model_snapshot

    snapshot = _model_snapshot(model)
    metadata = json.loads((model / "model.json").read_text())
    if metadata.get("calibrationPassed") is not True or not metadata.get("pitchTone"):
        raise ValueError("PASSED_CALIBRATION_AND_INDEPENDENT_TONE_REQUIRED")
    if snapshot["files"].get(metadata.get("file")) != metadata.get("sha256"):
        raise ValueError("EVALUATION_ACOUSTIC_MODEL_DIGEST_MISMATCH")
    if snapshot["files"].get(metadata.get("catalogFile")) != metadata.get("catalogSha256"):
        raise ValueError("EVALUATION_CATALOG_DIGEST_MISMATCH")
    if snapshot["files"].get(metadata["pitchTone"]["file"]) != metadata["pitchTone"]["sha256"]:
        raise ValueError("EVALUATION_TONE_MODEL_DIGEST_MISMATCH")
    if require_usable:
        from pinyin_matcher.inference import PinyinMatcher

        matcher = PinyinMatcher(model)
        if matcher.session is None:
            raise ValueError(matcher.problem or "EVALUATION_MODEL_UNAVAILABLE")
    return snapshot


def _evaluation_generation_plan(configuration: dict, model: dict, output: Path) -> dict:
    source_rows = [
        row
        for row in configuration["definitions"]
        if (row.get("standardSource") or {}).get("allocation") == "blind"
    ]
    voice_ids = configuration["blindTestPersonaIds"]
    personas = {row["id"]: row for row in configuration["additionalPersonas"]}
    if len(source_rows) != 13 or voice_ids != [f"voice-{i}" for i in range(32, 36)]:
        raise ValueError("FROZEN_EVALUATION_SOURCE_OR_FAMILY_SET_INVALID")
    voices = []
    for key in voice_ids:
        persona = personas[key]
        if persona["split"] != "test":
            raise ValueError("EVALUATION_FAMILIES_MUST_HAVE_TEST_SPLIT")
        voices.append(
            {
                **persona,
                "referenceSeed": configuration["seed"] + int(key[-2:]),
                "referenceFile": "references/" + key + ".wav",
            }
        )
    sources = [
        {
            "targetId": row["id"],
            "pinyin": row["pinyin"],
            "phones": row["phones"],
            "tone": row["tone"],
            "sourceSha256": row["standardSource"]["sourceSha256"],
            "sourceRootId": "pinyinsound-" + row["standardSource"]["sourceSha256"],
            "phoneticGroup": row["standardSource"]["phoneticGroup"],
            "sourceHistory": "Known standards with benchmark history; not new human speakers.",
        }
        for row in source_rows
    ]
    units = []
    for persona in voices:
        for source in sources:
            sample_id = "-".join(
                ["controlled", "cosy", persona["id"], source["targetId"], "vc", "0"]
            )
            seed = (
                configuration["seed"]
                + int.from_bytes(hashlib.sha256(sample_id.encode()).digest()[:4], "little")
                % 1_000_000
            )
            units.append(
                {
                    "id": sample_id,
                    "voiceFamilyId": persona["id"],
                    "targetId": source["targetId"],
                    "sourceSha256": source["sourceSha256"],
                    "seed": seed,
                    "file": "cosy" + EVALUATION_SUFFIX + "/" + sample_id + ".wav",
                }
            )
    return {
        "outputDirectory": str(output.resolve()),
        "sourcePool": "locked-evaluation",
        "outputSuffix": EVALUATION_SUFFIX,
        "ttsDevice": "mps",
        "threads": 4,
        "repetitions": 1,
        "sources": sources,
        "personas": voices,
        "units": units,
        "expectedWaveforms": 52,
        "expectedStandardRoots": 13,
        "expectedSyntheticReferenceFamilies": 4,
        "queryPolicy": {
            "coveredTargetIds": model["coveredTargetIds"],
            "allPlannedWaveformsRequired": True,
            "rule": "Query every planned wave against all covered targets; never omit failures.",
        },
        "claimScope": "New VC voices on known standards; no independent human/child validation.",
    }


def create_evaluation_lock(
    model: Path,
    configuration: Path,
    calibration_report: Path,
    output: Path,
    lock_path: Path,
    *,
    calibration_model: Path | None = None,
) -> dict:
    """Freeze model and generation plan only. Never read or generate source audio."""
    if lock_path.exists():
        raise ValueError("EVALUATION_LOCK_ALREADY_EXISTS")
    configuration_bytes = configuration.read_bytes()
    config = json.loads(configuration_bytes)
    snapshot = _evaluation_model_snapshot(model.resolve(strict=True), require_usable=True)
    report = json.loads(calibration_report.read_text())
    lineage = report.get("trainingLineageCheck", {})
    if (
        report.get("calibrationPassed") is not True
        or report.get("thresholds") != snapshot["thresholds"]
        or lineage.get("complete") is not True
        or lineage.get("overlapRawUnitIds")
        or lineage.get("errors")
    ):
        raise ValueError("PASSED_MATCHING_CALIBRATION_REPORT_REQUIRED")
    from pinyin_matcher.quality import _model_snapshot

    calibrated_model = (calibration_model or model).resolve(strict=True)
    collection_file = calibration_report.parent / "collection.json"
    collection = json.loads(collection_file.read_text())
    calibrated_snapshot = _model_snapshot(calibrated_model)
    if collection.get("modelMetadataSha256") != calibrated_snapshot["files"]["model.json"]:
        raise ValueError("CALIBRATION_MODEL_METADATA_MISMATCH")
    final_files = {
        name: digest for name, digest in snapshot["files"].items() if name != "model.json"
    }
    calibrated_files = {
        name: digest
        for name, digest in calibrated_snapshot["files"].items()
        if name != "model.json"
    }
    if (
        final_files != calibrated_files
        or snapshot["coveredTargetIds"] != calibrated_snapshot["coveredTargetIds"]
    ):
        raise ValueError("CALIBRATION_MODEL_WEIGHTS_OR_CATALOG_MISMATCH")
    plan = _evaluation_generation_plan(config, snapshot, output)
    managed = [
        output / "references",
        ROOT / "private/matcher-data/references",
        ROOT / "private/matcher-v2-controlled/references",
        ROOT / "private/matcher-v4-acoustic/references",
    ]
    for persona in plan["personas"]:
        if any((directory / (persona["id"] + ".wav")).exists() for directory in managed):
            raise ValueError("EVALUATION_REFERENCE_ALREADY_EXISTS_BEFORE_LOCK")
    if (output / ("cosy" + EVALUATION_SUFFIX)).exists():
        raise ValueError("EVALUATION_OUTPUT_ALREADY_EXISTS_BEFORE_LOCK")
    frozen = lock_path.with_suffix(".configuration.frozen.json")
    if frozen.exists():
        raise ValueError("FROZEN_EVALUATION_CONFIGURATION_ALREADY_EXISTS")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with frozen.open("xb") as stream:
        stream.write(configuration_bytes)
    registry = ROOT / "content/pronunciation-models.json"
    lock = {
        "schemaVersion": 1,
        "createdUtc": datetime.now(UTC).isoformat(),
        "kind": EVALUATION_LOCK_KIND,
        "stage": "before-audio-generation",
        "modelDirectory": str(model.resolve()),
        "model": snapshot,
        "configuration": {"file": str(frozen.resolve()), "sha256": fingerprint(frozen)},
        "calibrationModelDirectory": str(calibrated_model),
        "calibrationModel": calibrated_snapshot,
        "calibrationCollection": {
            "file": str(collection_file.resolve()),
            "sha256": fingerprint(collection_file),
        },
        "calibrationReport": {
            "file": str(calibration_report.resolve()),
            "sha256": fingerprint(calibration_report),
        },
        "generatorRegistry": {"file": str(registry.resolve()), "sha256": fingerprint(registry)},
        "codeSha256": _generation_code_snapshot(),
        "generationPlan": plan,
        "claims": {
            "newIndependentHumanSpeakers": False,
            "realChildAccuracyEstablished": False,
            "standardRootsHistoricallyKnown": True,
            "newWaveformsAndFamiliesNotGeneratedBeforeLock": True,
            "isQualityFreeze": False,
        },
    }
    lock["lockSha256"] = _lock_digest(lock)
    with lock_path.open("x") as stream:
        stream.write(json.dumps(lock, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return lock


def validate_evaluation_lock(lock_path: Path, configuration: Path, output: Path) -> dict:
    """Fail before source access when weights, thresholds, code or plan changed."""
    if not lock_path.is_file() or lock_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("EVALUATION_LOCK_REQUIRED")
    lock = json.loads(lock_path.read_text())
    digest = lock.pop("lockSha256", None)
    if (
        lock.get("schemaVersion") != 1
        or lock.get("kind") != EVALUATION_LOCK_KIND
        or digest != _lock_digest(lock)
    ):
        raise ValueError("EVALUATION_LOCK_INVALID")
    lock["lockSha256"] = digest
    frozen = Path(lock["configuration"]["file"])
    if (
        fingerprint(frozen) != lock["configuration"]["sha256"]
        or fingerprint(configuration) != lock["configuration"]["sha256"]
    ):
        raise ValueError("FROZEN_EVALUATION_CONFIGURATION_CHANGED")
    for key in ["calibrationReport", "calibrationCollection", "generatorRegistry"]:
        resource = lock[key]
        if fingerprint(Path(resource["file"])) != resource["sha256"]:
            raise ValueError("FROZEN_EVALUATION_INPUT_CHANGED")
    if lock["generatorRegistry"]["file"] != str(
        (ROOT / "content/pronunciation-models.json").resolve()
    ):
        raise ValueError("EVALUATION_GENERATOR_REGISTRY_INVALID")
    if _generation_code_snapshot() != lock["codeSha256"]:
        raise ValueError("FROZEN_EVALUATION_CODE_CHANGED")
    if _evaluation_model_snapshot(Path(lock["modelDirectory"])) != lock["model"]:
        raise ValueError("FROZEN_EVALUATION_MODEL_CHANGED")
    from pinyin_matcher.quality import _model_snapshot

    if _model_snapshot(Path(lock["calibrationModelDirectory"])) != lock["calibrationModel"]:
        raise ValueError("FROZEN_CALIBRATION_MODEL_CHANGED")
    plan = _evaluation_generation_plan(json.loads(frozen.read_text()), lock["model"], output)
    if plan != lock["generationPlan"]:
        raise ValueError("FROZEN_EVALUATION_GENERATION_PLAN_CHANGED")
    return lock


def _evaluation_reference_record(reference: Path, persona: dict, lock: dict):
    if not reference.exists():
        return
    metadata = reference.with_suffix(".json")
    if not metadata.is_file():
        raise ValueError("EVALUATION_REFERENCE_PROVENANCE_REQUIRED")
    record = json.loads(metadata.read_text())
    if (
        record.get("evaluationLockSha256") != lock["lockSha256"]
        or record.get("sha256") != fingerprint(reference)
        or record.get("persona") != persona
    ):
        raise ValueError("EVALUATION_REFERENCE_PROVENANCE_MISMATCH")


def pitch_evidence(samples: np.ndarray) -> dict:
    """Measurements only. No expected tone is passed and no truth label is inferred."""
    acoustic, info = features(samples)
    indices = np.flatnonzero(acoustic[:, 67] > 0.5)
    result = {**info, "measurement": "Legacy YIN diagnosis only; may drop changing/creaky tails"}
    if len(indices) < 8:
        result["reliableContour"] = False
        return result
    pitch = acoustic[indices, 64]
    semitones = (pitch - np.median(pitch)) * 12
    bins = np.interp(np.linspace(0, len(pitch) - 1, 9), np.arange(len(pitch)), semitones)
    result.update(
        {
            "reliableContour": True,
            "voicedSeconds": len(indices) * 0.01,
            "relativeSemitone9": [round(float(value), 3) for value in bins],
            "f0HzQuantiles": [
                round(float(value), 2) for value in np.quantile(220 * 2**pitch, [0.1, 0.5, 0.9])
            ],
            "endMinusStartSemitones": round(
                float(np.median(semitones[-5:]) - np.median(semitones[:5])), 3
            ),
            "minimumLocation": round(float(np.argmin(semitones) / max(1, len(semitones) - 1)), 3),
        }
    )
    return result


def verify_model(engine: str, model_dir: Path) -> dict:
    expected = json.loads((ROOT / "content/pronunciation-models.json").read_text())["generators"][
        engine
    ]
    actual = json.loads((model_dir / "installation.json").read_text())
    if actual != expected:
        raise ValueError("TTS_INSTALLATION_VERSION_MISMATCH")
    for row in expected["files"]:
        resource = (model_dir / row["path"]).resolve()
        if (
            not resource.is_relative_to(model_dir)
            or resource.stat().st_size != row["bytes"]
            or fingerprint(resource) != row["sha256"]
        ):
            raise ValueError("TTS_MODEL_DIGEST_MISMATCH")
    return expected


def standard_source(
    definition: dict,
    output: Path,
    *,
    evaluation_lock: Path | None = None,
    configuration: Path | None = None,
) -> Path:
    source = definition.get("standardSource")
    if not source:
        raise ValueError("NO_LICENSED_STANDARD_SOURCE")
    if source.get("allocation") == "blind":
        if evaluation_lock is None or configuration is None:
            raise ValueError("BLIND_STANDARD_SOURCE_ACCESS_FORBIDDEN")
        lock = validate_evaluation_lock(evaluation_lock, configuration, output)
        if not any(
            row["targetId"] == definition["id"] and row["sourceSha256"] == source["sourceSha256"]
            for row in lock["generationPlan"]["sources"]
        ):
            raise ValueError("BLIND_SOURCE_NOT_IN_FROZEN_GENERATION_PLAN")
    original = ROOT / "private/pinyinsound/clips" / (source["sourceSha256"] + ".mp3")
    if fingerprint(original) != source["sourceSha256"]:
        raise ValueError("STANDARD_SOURCE_DIGEST_MISMATCH")
    directory = output / "standard-sources"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (source["sourceSha256"] + ".wav")
    if not destination.exists():
        temporary = destination.with_name(destination.stem + f".{os.getpid()}.tmp.wav")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(original),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ],
            check=True,
        )
        temporary.replace(destination)
    return destination


def convert_voice(synthesize, source: Path, reference: Path, seed: int):
    """Only the exact official loaded generator; source and reference stay explicit."""
    import torch

    model = getattr(synthesize, "model", None)
    if model is None:
        raise ValueError("EXPLICIT_OFFLINE_COSY_MODEL_REQUIRED")
    torch.manual_seed(seed)
    try:
        reference_cache = getattr(model, "controlled_reference_cache", {})
        source_cache = getattr(model, "controlled_source_cache", {})
        model.controlled_reference_cache = reference_cache
        model.controlled_source_cache = source_cache
        if reference not in reference_cache:
            conditioning = model.frontend.frontend_vc(
                str(source), str(reference), model.sample_rate
            )
            reference_cache[reference] = {
                key: value
                for key, value in conditioning.items()
                if key not in {"source_speech_token", "source_speech_token_len"}
            }
            source_cache[source] = (
                conditioning["source_speech_token"],
                conditioning["source_speech_token_len"],
            )
        if source not in source_cache:
            source_cache[source] = model.frontend._extract_speech_token(str(source))
        tokens, length = source_cache[source]
        conditioning = {
            **reference_cache[reference],
            "source_speech_token": tokens,
            "source_speech_token_len": length,
        }
        # Exact upstream frontend/model boundary, with immutable conditioning
        # cached instead of recomputing identical reference encoders per clip.
        chunks = list(model.model.tts(**conditioning, stream=False))
    finally:
        for name in ("tts_speech_token_dict", "llm_end_dict", "hift_cache_dict"):
            getattr(model.model, name).clear()
    samples = np.concatenate([chunk["tts_speech"].cpu().numpy().reshape(-1) for chunk in chunks])
    return samples, model.sample_rate


def anchor_training_definitions(configuration: dict) -> list[dict]:
    from pinyin_matcher.catalog import targets_by_id

    lock = configuration["standardAnchorSourceManifest"]
    path = (ROOT / lock["path"]).resolve(strict=True)
    if fingerprint(path) != lock["sha256"]:
        raise ValueError("STANDARD_ANCHOR_MANIFEST_DIGEST_MISMATCH")
    manifest = json.loads(path.read_text())
    if manifest["cohort"] != lock["cohort"]:
        raise ValueError("STANDARD_ANCHOR_COHORT_MISMATCH")
    train_hashes = set(lock["trainSourceSha256s"])
    forbidden = set(lock["heldoutCalibrationSourceSha256s"]) | {
        row["standardSource"]["sourceSha256"]
        for row in configuration["definitions"]
        if row.get("standardSource")
    }
    if train_hashes & forbidden:
        raise ValueError("STANDARD_SOURCE_SPLIT_LEAKAGE")
    targets = targets_by_id()
    tone_marks = json.loads((ROOT / "content/pronunciation-rules.json").read_text())[
        "toneCombiningMarks"
    ]
    definitions = []
    for row in manifest["items"]:
        if row["split"] != "train":
            continue
        if row["sourceSha256"] not in train_hashes or row["targetId"] not in targets:
            raise ValueError("STANDARD_ANCHOR_SOURCE_REFERENCE_INVALID")
        target = targets[row["targetId"]]
        definitions.append(
            {
                "id": target["id"],
                "pinyin": target["pinyin"],
                "base": unicodedata.normalize(
                    "NFC",
                    "".join(
                        ch
                        for ch in unicodedata.normalize("NFD", target["pinyin"])
                        if ch not in tone_marks
                    ),
                ),
                "tone": target["tone"],
                "phones": target["phones"],
                "ttsText": None,
                "cosyPhonemes": "",
                "standardSource": {
                    "assetId": row["id"],
                    "sourceSha256": row["sourceSha256"],
                    "allocation": "train",
                    "phoneticGroup": ":".join(target["phones"]),
                    "source": "https://github.com/cmguo/PinYinSound",
                },
            }
        )
    if {row["standardSource"]["sourceSha256"] for row in definitions} != train_hashes:
        raise ValueError("STANDARD_ANCHOR_SOURCE_COVERAGE_MISMATCH")
    return definitions


def acoustic_extension_definitions(configuration: dict) -> list[dict]:
    """Explicit category-coverage migration only; all older allocations stay frozen."""
    from pinyin_matcher.catalog import load_catalog, targets_by_id

    migration = configuration["acousticOnlyExtensionV4"]
    original = {row["id"]: row for row in configuration["definitions"]}
    public = set(load_catalog()["pilotIds"])
    known = targets_by_id()
    expected = {
        key
        for key in migration["candidateTargetIds"]
        if original[key].get("standardSource") and key not in public
    }
    if {row["targetId"] for row in migration["selectedSources"]} != expected:
        raise ValueError("ACOUSTIC_EXTENSION_CATEGORY_SELECTION_MISMATCH")
    previous_cal = migration["originalCalibrationRetirement"]
    previous_path = (ROOT / previous_cal["manifest"]).resolve(strict=True)
    if fingerprint(previous_path) != previous_cal["manifestSha256"]:
        raise ValueError("ORIGINAL_CALIBRATION_MANIFEST_CHANGED")
    blind = {
        row["standardSource"]["sourceSha256"]
        for row in original.values()
        if (row.get("standardSource") or {}).get("allocation") == "blind"
    }
    definitions = []
    for selected in migration["selectedSources"]:
        key = selected["targetId"]
        row = json.loads(json.dumps(original[key]))
        source = row["standardSource"]
        if (
            key in public
            or key not in known
            or source["allocation"] != "calibration"
            or source["sourceSha256"] != selected["sourceSha256"]
            or source["sourceSha256"] in blind
        ):
            raise ValueError("ACOUSTIC_EXTENSION_SOURCE_REFERENCE_INVALID")
        source["allocation"] = "train"
        source["originalAcousticAllocation"] = "calibration-v1"
        source["acousticOnlyExtension"] = True
        row["phoneticCoverageExtension"] = True
        definitions.append(row)
    return definitions


def generate(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    config_payload = args.configuration.read_bytes()
    configuration = json.loads(config_payload)
    configuration_sha = hashlib.sha256(config_payload).hexdigest()
    definitions = configuration["definitions"]
    evaluation = None
    if args.source_pool == "locked-evaluation":
        if args.evaluation_lock is None:
            raise ValueError("EVALUATION_LOCK_REQUIRED")
        evaluation = validate_evaluation_lock(args.evaluation_lock, args.configuration, args.output)
        plan = evaluation["generationPlan"]
        if (
            args.bases
            or args.limit
            or args.repetitions != 1
            or args.suffix != plan["outputSuffix"]
            or args.threads != plan["threads"]
            or args.tts_device != plan["ttsDevice"]
        ):
            raise ValueError("FROZEN_EVALUATION_GENERATION_ARGUMENTS_CHANGED")
        if not (
            args.engine == "qwen"
            and args.references_only
            and args.modes == ["character"]
            or args.engine == "cosy"
            and not args.references_only
            and args.modes == ["vc"]
        ):
            raise ValueError("LOCKED_EVALUATION_REQUIRES_QWEN_REFERENCES_OR_COSY_VC")
        definitions = [
            row
            for row in definitions
            if (row.get("standardSource") or {}).get("allocation") == "blind"
        ]
    elif args.evaluation_lock is not None:
        raise ValueError("EVALUATION_LOCK_ONLY_FOR_LOCKED_SOURCE_POOL")
    training_pool = args.source_pool in {"anchor-training", "acoustic-v4-extension"}
    if args.source_pool == "anchor-training":
        if args.engine != "cosy" or args.modes != ["vc"]:
            raise ValueError("ANCHOR_TRAINING_POOL_REQUIRES_COSY_VC")
        definitions = anchor_training_definitions(configuration)
    elif args.source_pool == "acoustic-v4-extension":
        if args.engine != "cosy" or args.modes != ["vc"]:
            raise ValueError("ACOUSTIC_EXTENSION_REQUIRES_COSY_VC")
        definitions = acoustic_extension_definitions(configuration)
    if args.engine != "cosy" and set(args.modes) & {"vc", "phonemes"}:
        raise ValueError("PHONEME_AND_VC_MODES_COSY_ONLY")
    if args.engine != "qwen" and "carrier" in args.modes:
        raise ValueError("CARRIER_MODE_QWEN_ONLY")
    definitions = [row for row in definitions if not args.bases or row["base"] in args.bases]
    if not definitions or any(
        base not in {row["base"] for row in definitions} for base in args.bases or []
    ):
        raise ValueError("UNKNOWN_EXPLICIT_BASE")
    source_personas = json.loads((ROOT / "content/pronunciation-training.json").read_text())[
        "personas"
    ]
    personas = {
        row["id"]: row for row in source_personas + configuration.get("additionalPersonas", [])
    }
    requested = args.persona_ids or (
        configuration["blindTestPersonaIds"]
        if evaluation
        else (
            configuration["standardAnchorSourceManifest"]["trainPersonaIds"]
            if training_pool
            else configuration["trainPersonaIds"]
        )
    )
    allowed = set(
        configuration["blindTestPersonaIds"]
        if evaluation
        else configuration["trainPersonaIds"] + configuration["calibrationPersonaIds"]
    )
    if not set(requested) <= allowed:
        raise ValueError("TRAIN_OR_CALIBRATION_FAMILIES_ONLY")
    if evaluation and (
        len(requested) != 4 or set(requested) != set(configuration["blindTestPersonaIds"])
    ):
        raise ValueError("FROZEN_EVALUATION_FAMILY_SET_CHANGED")
    selected = [personas[key] for key in requested]
    if training_pool and not set(requested) <= set(
        configuration["standardAnchorSourceManifest"]["trainPersonaIds"]
    ):
        raise ValueError("ANCHOR_TRAINING_VOICES_NOT_ALLOCATED")
    if args.modes == ["vc"]:
        allocation = "blind" if evaluation else "train" if training_pool else "calibration"
        if not any(
            row.get("standardSource", {}).get("allocation") == allocation
            for row in definitions
            if row.get("standardSource")
        ):
            raise ValueError("NO_ELIGIBLE_STANDARD_SOURCES")
    model_dir = args.model.resolve(strict=True)
    install = verify_model(args.engine, model_dir)
    synthesize = (
        engine_qwen(model_dir)
        if args.engine == "qwen"
        else engine_cosy(model_dir, args.source.resolve(strict=True), args.threads, args.tts_device)
    )
    # Register special-token spellings are checked against the exact locked source.
    tokenizer_source = (args.source / "cosyvoice/tokenizer/tokenizer.py").read_text()
    registered = set(re.findall(r'\[[^\[\]"\s]+\]', tokenizer_source))
    output = args.output.resolve() / (args.engine + args.suffix)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"
    data = (
        json.loads(manifest.read_text())
        if manifest.exists()
        else {
            "version": 1,
            "cohort": "synthetic",
            "labelProvenance": "tts-intended-not-human-adjudicated",
            "configurationSha256": configuration_sha,
            "configuration": configuration,
            "items": [],
            "diagnostics": [],
            "quarantined": [],
            "rejected": [],
        }
    )
    if data["configurationSha256"] != configuration_sha:
        raise ValueError("CONFIG_CHANGED_USE_NEW_OUTPUT_SUFFIX")
    if evaluation:
        if manifest.exists() and data.get("evaluationLockSha256") != evaluation["lockSha256"]:
            raise ValueError("EVALUATION_MANIFEST_LOCK_MISMATCH")
        data.setdefault("failedGenerationAttempts", []).extend(data["rejected"])
        data["rejected"] = []
        data.update(
            {
                "evaluationLockSha256": evaluation["lockSha256"],
                "evaluationGenerationPlan": evaluation["generationPlan"],
                "knownStandardRootNewVcFamilyValidation": True,
                "realChildAccuracyEstablished": False,
            }
        )
    seen = {
        row["id"]
        for group in (data["items"], data["diagnostics"], data["quarantined"], data["rejected"])
        for row in group
    }
    count = 0
    references = args.output.resolve() / "references"
    references.mkdir(exist_ok=True)
    for persona in selected:
        if evaluation:
            validate_evaluation_lock(args.evaluation_lock, args.configuration, args.output)
        reference = references / (persona["id"] + ".wav")
        if evaluation:
            _evaluation_reference_record(reference, persona, evaluation)
        if not reference.exists():
            existing = ROOT / "private/matcher-data/references" / reference.name
            if existing.exists() and not evaluation:
                reference.write_bytes(existing.read_bytes())
            elif args.engine == "qwen":
                samples, rate = synthesize(
                    persona["referenceText"],
                    persona,
                    configuration["seed"] + int(persona["id"][-2:]),
                )
                if evaluation:
                    validate_evaluation_lock(args.evaluation_lock, args.configuration, args.output)
                reference.write_bytes(
                    encode_wav(resample_poly(samples, SAMPLE_RATE, rate).astype(np.float32))
                )
            else:
                raise ValueError("EXPLICIT_SYNTHETIC_REFERENCE_REQUIRED")
        reference_hash = fingerprint(reference)
        atomic_json(
            references / (persona["id"] + ".json"),
            {
                "evaluationLockSha256": evaluation["lockSha256"] if evaluation else None,
                "voiceFamilyId": persona["id"],
                "sha256": reference_hash,
                "source": "existing synthetic Qwen reference"
                if (ROOT / "private/matcher-data/references" / reference.name).exists()
                else "new synthetic Qwen reference",
                "persona": persona,
                "seed": (
                    json.loads((ROOT / "content/pronunciation-training.json").read_text())["seed"]
                    if (ROOT / "private/matcher-data/references" / reference.name).exists()
                    else configuration["seed"]
                )
                + int(persona["id"][-2:]),
                "generatorRevision": json.loads(
                    (ROOT / "content/pronunciation-models.json").read_text()
                )["generators"]["qwen"]["revision"],
            },
        )
        if args.references_only:
            print(json.dumps({"reference": persona["id"], "sha256": reference_hash}), flush=True)
            continue
        for definition in definitions:
            for mode in args.modes:
                if mode == "phonemes" and args.engine != "cosy":
                    raise ValueError("PHONEMES_MODE_COSY_ONLY")
                if mode in {"character", "carrier"} and not definition["ttsText"]:
                    continue
                tokens = re.findall(r"\[[^\]]+\]", definition["cosyPhonemes"])
                if mode == "phonemes" and not set(tokens) <= registered:
                    unsupported_id = "-".join(
                        [args.engine, persona["id"], definition["id"], mode, "unsupported"]
                    )
                    if unsupported_id not in seen:
                        data["rejected"].append(
                            {
                                "id": unsupported_id,
                                "reason": "UNREGISTERED_PHONEME_TOKEN",
                                "tokens": sorted(set(tokens) - registered),
                            }
                        )
                        seen.add(unsupported_id)
                        atomic_json(manifest, data)
                    continue
                if mode == "vc":
                    if not definition.get("standardSource") or definition["standardSource"].get(
                        "allocation"
                    ) != ("blind" if evaluation else "train" if training_pool else "calibration"):
                        continue
                    if persona["split"] != (
                        "test" if evaluation else definition["standardSource"]["allocation"]
                    ):
                        raise ValueError("STANDARD_SOURCE_SPLIT_MISMATCH")
                template = configuration["generationModes"][args.engine + "-" + mode]
                text = template.format(**definition)
                for repeat in range(args.repetitions):
                    item_id = "-".join(
                        [
                            "controlled",
                            args.engine,
                            persona["id"],
                            definition["id"],
                            mode,
                            str(repeat),
                        ]
                    )
                    if item_id in seen:
                        continue
                    if evaluation:
                        validate_evaluation_lock(
                            args.evaluation_lock, args.configuration, args.output
                        )
                    seed = (
                        configuration["seed"]
                        + int.from_bytes(hashlib.sha256(item_id.encode()).digest()[:4], "little")
                        % 1_000_000
                    )
                    started = time.monotonic()
                    try:
                        if mode == "vc":
                            source_audio = standard_source(
                                definition,
                                args.output.resolve(),
                                evaluation_lock=args.evaluation_lock if evaluation else None,
                                configuration=args.configuration if evaluation else None,
                            )
                            samples, rate = convert_voice(synthesize, source_audio, reference, seed)
                        else:
                            samples, rate = synthesize(text, persona, seed, reference)
                        if evaluation:
                            validate_evaluation_lock(
                                args.evaluation_lock, args.configuration, args.output
                            )
                        samples = trim_silence(
                            resample_poly(samples, SAMPLE_RATE, rate).astype(np.float32)
                        )
                        quality_check(samples)
                        evidence = pitch_evidence(samples)
                        filename = item_id + ".wav"
                        path = output / filename
                        path.write_bytes(encode_wav(samples))
                        row = {
                            "id": item_id,
                            "targetId": definition["id"],
                            "voiceFamilyId": persona["id"],
                            "referenceRootId": persona["id"] + "-reference",
                            "referenceSha256": reference_hash,
                            "generator": args.engine,
                            "generatorRevision": install["revision"],
                            "modelSha256": next(
                                row["sha256"]
                                for row in install["files"]
                                if row["path"] in {"model.safetensors", "llm.pt"}
                            ),
                            "generationDevice": "metal-mlx"
                            if args.engine == "qwen"
                            else args.tts_device + "+cpu-vocoder",
                            "split": persona["split"],
                            "text": text,
                            "seed": seed,
                            "file": filename,
                            "sha256": fingerprint(path),
                            "labelProvenance": "tts-intended-not-human-adjudicated",
                            "durationSeconds": evidence["durationSeconds"],
                            "intendedPinyin": definition["pinyin"],
                            "intendedTone": definition["tone"],
                            "tone": definition["tone"],
                            "generationMode": mode,
                            "f0Evidence": evidence,
                        }
                        if mode == "vc":
                            row.update(
                                {
                                    "sourceRootId": "pinyinsound-"
                                    + definition["standardSource"]["sourceSha256"],
                                    "sourceSha256": definition["standardSource"]["sourceSha256"],
                                    "sourceWavSha256": fingerprint(source_audio),
                                    "sourceLicenseStatus": "retain original source license",
                                    "derivedFromStandard": True,
                                    "sourceAllocation": definition["standardSource"]["allocation"],
                                    "sourcePhoneticGroup": definition["standardSource"][
                                        "phoneticGroup"
                                    ],
                                    "independentRoot": False,
                                }
                            )
                        if evaluation:
                            row.update(
                                {
                                    "evaluationLockSha256": evaluation["lockSha256"],
                                    "sourceAllocation": "test",
                                    "sourceDeclaredAllocation": "blind",
                                    "knownStandardRootNewVcFamilyValidation": True,
                                    "independentHumanSpeaker": False,
                                    "realChildAccuracyEstablished": False,
                                }
                            )
                        if args.source_pool == "acoustic-v4-extension":
                            row.update(
                                {
                                    "phoneticCoverageExtension": True,
                                    "acousticOnlyExtension": True,
                                    "pitchTrainingEligible": False,
                                    "acousticAllocationVersion": 4,
                                }
                            )
                        reason = (
                            "NOT_ISOLATED_SYLLABLE"
                            if mode == "carrier"
                            else "DURATION_OVER_2_SECONDS"
                            if len(samples) > 2 * SAMPLE_RATE
                            else None
                        )
                        if reason:
                            row["reason"] = reason
                        data[
                            "diagnostics"
                            if mode == "carrier"
                            else "quarantined"
                            if reason
                            else "items"
                        ].append(row)
                        print(
                            json.dumps(
                                {
                                    "generated": item_id,
                                    "group": "diagnostic"
                                    if mode == "carrier"
                                    else "quarantined"
                                    if reason
                                    else "items",
                                    "duration": evidence["durationSeconds"],
                                    "contour": evidence.get("relativeSemitone9"),
                                    "elapsed": round(time.monotonic() - started, 2),
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                    except (ValueError, RuntimeError) as error:
                        if evaluation:
                            validate_evaluation_lock(
                                args.evaluation_lock, args.configuration, args.output
                            )
                        data["rejected"].append({"id": item_id, "reason": str(error)})
                        print(
                            json.dumps(
                                {"rejected": item_id, "reason": str(error)}, ensure_ascii=False
                            ),
                            flush=True,
                        )
                    seen.add(item_id)
                    atomic_json(manifest, data)
                    count += 1
                    if args.limit and count >= args.limit:
                        return

    if evaluation and args.engine == "cosy":
        expected = {row["id"]: row for row in evaluation["generationPlan"]["units"]}
        if (
            data["rejected"]
            or data["quarantined"]
            or {row["id"] for row in data["items"]} != set(expected)
        ):
            raise ValueError("FROZEN_EVALUATION_GENERATION_INCOMPLETE")
        for row in data["items"]:
            planned = expected[row["id"]]
            if (
                row.get("evaluationLockSha256") != evaluation["lockSha256"]
                or row["sourceSha256"] != planned["sourceSha256"]
                or row["targetId"] != planned["targetId"]
                or row["voiceFamilyId"] != planned["voiceFamilyId"]
                or row["seed"] != planned["seed"]
                or row["split"] != "test"
                or fingerprint(output / row["file"]) != row["sha256"]
            ):
                raise ValueError("FROZEN_EVALUATION_GENERATION_PROVENANCE_INVALID")
        validate_evaluation_lock(args.evaluation_lock, args.configuration, args.output)
        data["evaluationGenerationComplete"] = True
        atomic_json(manifest, data)


def inspect_manifest(manifest: Path, output: Path):
    """Independent pYIN evidence with an explicit voiced-probability mask, no tone oracle."""
    import librosa

    source = json.loads(manifest.read_text())
    results = []
    for group in ["items", "quarantined", "diagnostics"]:
        for row in source.get(group, []):
            samples = decode_wav((manifest.parent / row["file"]).read_bytes())
            f0, voiced, probability = librosa.pyin(
                samples,
                fmin=65,
                fmax=900,
                sr=SAMPLE_RATE,
                frame_length=1024,
                hop_length=160,
                fill_na=np.nan,
            )
            reliable = voiced & np.isfinite(f0) & (probability >= 0.5)
            values = f0[reliable]
            relative = 12 * np.log2(values / np.median(values)) if len(values) else np.array([])
            evidence = {
                "algorithm": "librosa.pyin 1.0.0; 1024-frame; 65-900 Hz; probability >= 0.5",
                "reliableFrames": int(reliable.sum()),
                "voicingProbabilityMedian": float(np.median(probability[voiced]))
                if voiced.any()
                else None,
                "f0HzQuantiles": [float(v) for v in np.quantile(values, [0.1, 0.5, 0.9])]
                if len(values)
                else None,
                "relativeSemitone9": [
                    float(v)
                    for v in np.interp(
                        np.linspace(0, len(values) - 1, 9), np.arange(len(values)), relative
                    )
                ]
                if len(values) >= 8
                else None,
                "endMinusStartSemitones": float(np.median(relative[-5:]) - np.median(relative[:5]))
                if len(values) >= 8
                else None,
            }
            results.append(
                {
                    "id": row["id"],
                    "intendedPinyin": row["intendedPinyin"],
                    "intendedTone": row["intendedTone"],
                    "voiceFamilyId": row["voiceFamilyId"],
                    "generationMode": row["generationMode"],
                    "durationSeconds": row["durationSeconds"],
                    "sourceGroup": group,
                    "evidence": evidence,
                }
            )
    report = {
        "sourceManifestSha256": fingerprint(manifest),
        "labelProvenance": "tts-intended-not-human-adjudicated",
        "statement": "F0 measures contour only; no syllable or pronunciation truth is inferred.",
        "results": results,
    }
    atomic_json(output, report)
    print(json.dumps({"output": str(output), "samples": len(results)}))


def inspect_swift_manifest(manifest: Path, output: Path, model: Path):
    """Preserve complete physical tracks, including irregular low-pitch tails."""
    from pinyin_matcher.pitch_swift import MODEL_SHA256, SwiftPitch

    tracker = SwiftPitch(model)
    source = json.loads(manifest.read_text())
    results = []
    for group in ["items", "quarantined", "diagnostics"]:
        for row in source.get(group, []):
            samples = decode_wav((manifest.parent / row["file"]).read_bytes())
            pitch = tracker.track(samples)
            good = np.flatnonzero(pitch.voiced)
            values = pitch.f0[good]
            summary = pitch.summary()
            if len(values) >= 6:
                relative = 12 * np.log2(values / np.median(values))
                width = max(2, len(values) // 8)
                early = relative[: max(width, int(len(values) * 0.6))]
                summary.update(
                    {
                        "relativeSemitone9": [
                            float(v)
                            for v in np.interp(np.linspace(good[0], good[-1], 9), good, relative)
                        ],
                        "f0Hz9": [
                            float(v)
                            for v in np.interp(np.linspace(good[0], good[-1], 9), good, values)
                        ],
                        "endMinusStartSemitones": float(
                            np.median(relative[-width:]) - np.median(relative[:width])
                        ),
                        "earlyPeakMinusEndSemitones": float(
                            np.max(early) - np.median(relative[-width:])
                        ),
                        "minimumTimeFraction": float(
                            (good[np.argmin(relative)] - good[0]) / max(1, good[-1] - good[0])
                        ),
                        "endMinusMinimumSemitones": float(
                            np.median(relative[-width:]) - np.min(relative)
                        ),
                    }
                )
            results.append(
                {
                    "id": row["id"],
                    "targetId": row.get("targetId"),
                    "intendedPinyin": row.get("intendedPinyin"),
                    "intendedTone": row.get("intendedTone", row.get("tone")),
                    "voiceFamilyId": row.get("voiceFamilyId"),
                    "generationMode": row.get("generationMode"),
                    "durationSeconds": len(samples) / SAMPLE_RATE,
                    "sourceGroup": group,
                    "sourceRootId": row.get("sourceRootId"),
                    "evidence": summary,
                    "track": {
                        "f0Hz": pitch.f0.tolist(),
                        "confidence": pitch.confidence.tolist(),
                        "voiced": pitch.voiced.tolist(),
                        "seconds": pitch.seconds.tolist(),
                    },
                }
            )
    report = {
        "sourceManifestSha256": fingerprint(manifest),
        "trackerModelSha256": MODEL_SHA256,
        "statement": "Physical F0 only; not verified pronunciation labels or child accuracy.",
        "results": results,
    }
    atomic_json(output, report)
    print(json.dumps({"output": str(output), "samples": len(results)}))


def formant_warp(samples: np.ndarray, factor: float) -> np.ndarray:
    """Warp only the smooth cepstral envelope; harmonic frequencies stay in place."""
    import librosa

    spectrum = librosa.stft(samples, n_fft=1024, hop_length=160)
    log_magnitude = np.log(np.maximum(np.abs(spectrum), 1e-6))
    cepstrum = np.fft.irfft(log_magnitude, n=1024, axis=0)
    cepstrum[20:-19] = 0
    envelope = np.fft.rfft(cepstrum, n=1024, axis=0).real
    frequencies = np.arange(len(envelope))
    warped = np.stack(
        [
            np.interp(frequencies / factor, frequencies, envelope[:, index])
            for index in range(envelope.shape[1])
        ],
        axis=1,
    )
    filtered = spectrum * np.exp(np.clip(warped - envelope, -2, 2))
    return librosa.istft(filtered, hop_length=160, length=len(samples)).astype(np.float32)


def augment_standards(args):
    """Licensed source-derived control data; never new independent speaker roots."""
    import librosa

    configuration = json.loads(args.configuration.read_text())
    output = args.output.resolve() / "standard-signal-augmented"
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"
    report = {
        "version": 1,
        "cohort": "licensed-standard-derived-not-independent-speakers",
        "configurationSha256": fingerprint(args.configuration),
        "items": [],
        "quarantined": [],
    }
    for definition in configuration["definitions"]:
        if (
            not definition.get("standardSource")
            or definition["standardSource"].get("allocation") != "calibration"
            or (args.bases and definition["base"] not in args.bases)
        ):
            continue
        source = standard_source(definition, args.output.resolve())
        original = decode_wav(source.read_bytes())
        for parameters in configuration["standardSignalVariants"]:
            samples = formant_warp(original, parameters["formantScale"])
            if parameters["pitchSemitones"]:
                samples = librosa.effects.pitch_shift(
                    samples,
                    sr=SAMPLE_RATE,
                    n_steps=parameters["pitchSemitones"],
                    n_fft=1024,
                    hop_length=160,
                )
            if parameters["timeStretchRate"] != 1:
                samples = librosa.effects.time_stretch(
                    samples, rate=parameters["timeStretchRate"], n_fft=1024, hop_length=160
                )
            samples = trim_silence(samples.astype(np.float32))
            peak = float(np.max(np.abs(samples)))
            if peak > 0.95:
                samples *= 0.95 / peak
            sample_id = "standard-derived-" + definition["id"] + "-" + parameters["id"]
            destination = output / (sample_id + ".wav")
            destination.write_bytes(encode_wav(samples))
            row = {
                "id": sample_id,
                "targetId": definition["id"],
                "intendedPinyin": definition["pinyin"],
                "intendedTone": definition["tone"],
                "tone": definition["tone"],
                "split": "calibration",
                "voiceFamilyId": "pinyinsound-source",
                "referenceRootId": "pinyinsound-" + definition["standardSource"]["sourceSha256"],
                "sourceRootId": "pinyinsound-" + definition["standardSource"]["sourceSha256"],
                "sourceSha256": definition["standardSource"]["sourceSha256"],
                "sourceWavSha256": fingerprint(source),
                "sha256": fingerprint(destination),
                "file": destination.name,
                "parameters": parameters,
                "labelProvenance": "trusted-standard-with-recorded-signal-transform",
                "generationMode": "signal-derived-control",
                "f0Evidence": pitch_evidence(samples),
                "durationSeconds": len(samples) / SAMPLE_RATE,
                "generator": "standard-signal-augmentation",
                "independentRoot": False,
            }
            try:
                quality_check(samples)
                report["items"].append(row)
            except ValueError as error:
                row["reason"] = str(error)
                report["quarantined"].append(row)
            atomic_json(manifest, report)
    print(
        json.dumps(
            {
                "output": str(manifest),
                "items": len(report["items"]),
                "quarantined": len(report["quarantined"]),
                "independentRoots": len({r["sourceSha256"] for r in report["items"]}),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["qwen", "cosy"])
    parser.add_argument("--model", type=Path)
    parser.add_argument("--augment-standards", action="store_true")
    parser.add_argument("--references-only", action="store_true")
    parser.add_argument("--evaluation-lock", type=Path)
    parser.add_argument("--create-evaluation-lock", action="store_true")
    parser.add_argument("--check-evaluation-lock", action="store_true")
    parser.add_argument("--evaluation-model", type=Path)
    parser.add_argument("--calibration-report", type=Path)
    parser.add_argument("--calibration-model", type=Path)
    parser.add_argument("--inspect-swift", action="store_true")
    parser.add_argument(
        "--pitch-model", type=Path, default=ROOT / "models/matcher-pitch-swift/model.onnx"
    )
    parser.add_argument("--inspect-manifest", type=Path)
    parser.add_argument("--inspect-output", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT / "private/matcher-cosy-source")
    parser.add_argument("--output", type=Path, default=ROOT / "private/matcher-v2-controlled")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["phonemes", "character", "carrier", "vc"],
        default=["phonemes"],
    )
    parser.add_argument("--bases", nargs="+")
    parser.add_argument("--persona-ids", nargs="+")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--configuration", type=Path, default=CONFIG)
    parser.add_argument(
        "--source-pool",
        choices=["pilot", "anchor-training", "acoustic-v4-extension", "locked-evaluation"],
        default="pilot",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--tts-device", choices=["cpu", "mps"], default="mps")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.create_evaluation_lock:
        if not args.evaluation_lock or not args.evaluation_model or not args.calibration_report:
            parser.error("--evaluation-lock, --evaluation-model and --calibration-report required")
        lock = create_evaluation_lock(
            args.evaluation_model,
            args.configuration,
            args.calibration_report,
            args.output,
            args.evaluation_lock,
            calibration_model=args.calibration_model,
        )
        print(
            json.dumps(
                {
                    "lock": str(args.evaluation_lock),
                    "lockSha256": lock["lockSha256"],
                    "configuration": lock["configuration"]["file"],
                    "plannedWaveforms": 52,
                    "audioGenerated": False,
                }
            )
        )
        return
    if args.check_evaluation_lock:
        if not args.evaluation_lock:
            parser.error("--evaluation-lock required")
        lock = validate_evaluation_lock(args.evaluation_lock, args.configuration, args.output)
        print(
            json.dumps(
                {
                    "valid": True,
                    "lockSha256": lock["lockSha256"],
                    "plannedWaveforms": 52,
                    "audioGenerated": False,
                }
            )
        )
        return
    if args.augment_standards:
        augment_standards(args)
        return
    if args.inspect_manifest:
        if not args.inspect_output:
            parser.error("--inspect-output required for inspection")
        if args.inspect_swift:
            inspect_swift_manifest(args.inspect_manifest, args.inspect_output, args.pitch_model)
        else:
            inspect_manifest(args.inspect_manifest, args.inspect_output)
        return
    if not args.engine or not args.model:
        parser.error("--engine and --model required for generation")
    if not 1 <= args.repetitions <= 20:
        parser.error("repetitions must be 1..20")
    generate(args)


if __name__ == "__main__":
    main()
