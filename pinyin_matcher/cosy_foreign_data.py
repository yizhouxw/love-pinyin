"""Fixed local CosyVoice3 instruct2 foreign/dialect contrast pilot.

Dialect outputs remain exploratory until actual phones have independent evidence;
the instruction string is never used as evidence of generation success.
"""

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import SAMPLE_RATE, encode_wav, quality_check, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.controlled_generation import verify_model
from pinyin_matcher.generate import atomic_json, engine_cosy

CONFIG = ROOT / "content/pronunciation-cosy-foreign-pilot.json"


def generate(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    config = json.loads(CONFIG.read_text())
    foreign_config = ROOT / "content/pronunciation-foreign-contrast.json"
    if args.mode == "pilot":
        if args.split != "train":
            raise ValueError("PILOT_VOCABULARY_IS_TRAIN_ONLY")
        definitions = config["definitions"]
    else:
        definitions = [
            row
            for row in json.loads(foreign_config.read_text())["definitions"]
            if row["split"] == args.split
        ]
    allowed = (
        config["trainPersonaIds"] if args.split == "train" else config["calibrationPersonaIds"]
    )
    personas = args.persona_ids or allowed
    if not set(personas) <= set(allowed):
        raise ValueError("FROZEN_TRAIN_OR_CALIBRATION_FAMILIES_REQUIRED")
    model_dir = args.model.resolve(strict=True)
    install = verify_model("cosy", model_dir)
    synthesize = engine_cosy(
        model_dir, args.source.resolve(strict=True), args.threads, args.tts_device
    )
    model = synthesize.model
    output = args.output.resolve() / ("cosy-" + args.mode + "-" + args.split)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"

    def freeze_configuration(source: Path, name: str) -> str:
        frozen = output / name
        if frozen.exists():
            if json.loads(frozen.read_text()) != json.loads(source.read_text()):
                raise ValueError("CONFIG_CHANGED_USE_NEW_OUTPUT_DIRECTORY")
        else:
            frozen.write_bytes(source.read_bytes())
        return fingerprint(frozen)

    config_digest = freeze_configuration(CONFIG, "configuration.json")
    vocabulary_digest = (
        freeze_configuration(foreign_config, "vocabulary.json")
        if args.mode == "full"
        else config_digest
    )
    data = (
        json.loads(manifest.read_text())
        if manifest.exists()
        else {
            "version": 1,
            "cohort": "synthetic-explicit-foreign-phonetic-contrasts",
            "configurationSha256": config_digest,
            "vocabularyConfigurationSha256": vocabulary_digest,
            "labelProvenance": "tts-intended-not-language-dialect-or-phoneme-verified",
            "languageIdentityIsCorrectnessLabel": False,
            "realForeignSpeakerValidation": False,
            "items": [],
            "exploratoryDialect": [],
            "quarantined": [],
            "rejected": [],
        }
    )
    if (
        data["configurationSha256"] != config_digest
        or data["vocabularyConfigurationSha256"] != vocabulary_digest
    ):
        raise ValueError("CONFIG_CHANGED_USE_NEW_OUTPUT_DIRECTORY")
    pilot_manifest = args.output.resolve() / "cosy-pilot-train/manifest.json"
    if (
        args.mode == "full"
        and args.split == "train"
        and not data["items"]
        and pilot_manifest.exists()
    ):
        import shutil

        pilot = json.loads(pilot_manifest.read_text())
        allowed_ids = {row["id"] for row in definitions}
        for row in pilot["items"]:
            if row["foreignContrastId"] not in allowed_ids or row["voiceFamilyId"] not in personas:
                continue
            original = pilot_manifest.parent / row["file"]
            if fingerprint(original) != row["sha256"]:
                raise ValueError("PILOT_AUDIO_DIGEST_MISMATCH")
            copied = dict(row)
            copied["reusedPilotManifestSha256"] = fingerprint(pilot_manifest)
            shutil.copyfile(original, output / copied["file"])
            data["items"].append(copied)
        atomic_json(manifest, data)
    seen = {
        row["id"]
        for group in ["items", "exploratoryDialect", "quarantined", "rejected"]
        for row in data[group]
    }
    import torch

    completed = 0
    for persona in personas:
        reference = ROOT / "private/matcher-data/references" / (persona + ".wav")
        if not reference.exists():
            reference = ROOT / "private/matcher-v2-controlled/references" / reference.name
        if not reference.is_file():
            raise ValueError("EXPLICIT_SYNTHETIC_REFERENCE_REQUIRED")
        for definition in definitions:
            sample_id = f"foreign-cosy-{persona}-{definition['id']}-0"
            if sample_id in seen:
                continue
            seed = config["seed"] + int(hashlib.sha256(sample_id.encode()).hexdigest()[:7], 16)
            row = {
                "id": sample_id,
                "kind": "foreign-contrast",
                "unknownLabel": not definition.get("exploratoryDialect", False),
                "foreignContrastId": definition["id"],
                "lexicalRootId": definition["lexicalRootId"],
                "language": definition["language"],
                "locale": definition["locale"],
                "sourceText": definition["text"],
                "text": definition["text"]
                + ("。" if definition["language"] == "Cantonese" else "."),
                "againstTargetIds": definition["againstTargetIds"],
                "contrastCategory": definition["contrastCategory"],
                "phoneticDifference": definition["phoneticDifference"],
                "voiceFamilyId": persona,
                "referenceRootId": persona + "-reference",
                "referenceSha256": fingerprint(reference),
                "sourceRootId": sample_id,
                "split": args.split,
                "seed": seed,
                "generator": "cosy",
                "generationMode": "inference_instruct2",
                "generatorRevision": install["revision"],
                "modelSha256": next(x["sha256"] for x in install["files"] if x["path"] == "llm.pt"),
                "labelProvenance": "tts-intended-not-language-dialect-or-phoneme-verified",
            }
            if definition.get("exploratoryDialect"):
                row.update(
                    {
                        key: definition[key]
                        for key in [
                            "intendedJyutping",
                            "intendedFinalStop",
                            "exploratoryDialect",
                            "formalNegativeAllowed",
                        ]
                    }
                )
            started = time.perf_counter()
            try:
                torch.manual_seed(seed)
                try:
                    chunks = list(
                        model.inference_instruct2(
                            row["text"],
                            config["instructions"][definition["language"]],
                            str(reference),
                            stream=False,
                            text_frontend=False,
                        )
                    )
                finally:
                    for name in ["tts_speech_token_dict", "llm_end_dict", "hift_cache_dict"]:
                        getattr(model.model, name).clear()
                if not chunks:
                    raise ValueError("TTS_EMPTY")
                samples = np.concatenate(
                    [part["tts_speech"].cpu().numpy().reshape(-1) for part in chunks]
                )
                divisor = math.gcd(model.sample_rate, SAMPLE_RATE)
                samples = resample_poly(
                    samples, SAMPLE_RATE // divisor, model.sample_rate // divisor
                )
                samples = trim_silence(np.asarray(samples, dtype=np.float32))
                quality = quality_check(samples)
                file = output / (sample_id + ".wav")
                file.write_bytes(encode_wav(samples))
                row.update({"file": file.name, "sha256": fingerprint(file), **quality})
                if quality["durationSeconds"] > config["maximumSeconds"]:
                    row["reason"] = "SHORT_WORD_OUTPUT_TOO_LONG"
                    data["quarantined"].append(row)
                elif row.get("exploratoryDialect"):
                    data["exploratoryDialect"].append(row)
                else:
                    data["items"].append(row)
            except (ValueError, RuntimeError) as error:
                row["reason"] = str(error)[:500]
                data["rejected"].append(row)
            row["generationSeconds"] = time.perf_counter() - started
            atomic_json(manifest, data)
            print(
                json.dumps(
                    {
                        "id": sample_id,
                        "seconds": row["generationSeconds"],
                        "reason": row.get("reason"),
                    }
                ),
                flush=True,
            )
            completed += 1
            if args.limit and completed >= args.limit:
                return data
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("models/matcher-cosy"))
    parser.add_argument("--source", type=Path, default=Path("private/matcher-cosy-source"))
    parser.add_argument("--output", type=Path, default=Path("private/matcher-v2-foreign"))
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--split", choices=["train", "calibration"], default="train")
    parser.add_argument("--persona-ids", nargs="+")
    parser.add_argument("--tts-device", choices=["cpu", "mps"], default="mps")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--limit", type=int)
    result = generate(parser.parse_args())
    print(
        json.dumps(
            {
                key: len(result[key])
                for key in ["items", "exploratoryDialect", "quarantined", "rejected"]
            }
        )
    )
