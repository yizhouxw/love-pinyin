"""Explicit offline foreign phonetic contrasts; never classify by language identity.

The supplied text/contrast is a weak intended label. Generation language flags,
mechanical quality checks and TTS success do not verify the actual spoken phones.
The blind vocabulary and families are configured but deliberately inaccessible.
"""

import argparse
import hashlib
import json
import math
import os
import time
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import SAMPLE_RATE, decode_wav, encode_wav, quality_check, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog
from pinyin_matcher.generate import atomic_json, engine_qwen

CONFIG = ROOT / "content/pronunciation-foreign-contrast.json"


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split()).strip(" .!?。！？")


def configuration(path: Path | None = None) -> dict:
    config = json.loads((path or CONFIG).read_text())
    families = [
        config[key] for key in ["trainPersonaIds", "calibrationPersonaIds", "blindPersonaIds"]
    ]
    if len(set().union(*map(set, families))) != sum(map(len, families)):
        raise ValueError("VOICE_FAMILY_SPLIT_LEAK")
    lexical, texts, identifiers = {}, {}, set()
    targets = {row["id"] for row in load_catalog()["targets"]}
    for row in config["definitions"]:
        if (
            row["id"] in identifiers
            or not row["againstTargetIds"]
            or not isinstance(row.get("phoneticDifference"), str)
            or not row["phoneticDifference"].strip()
            or row.get("unknownRelativeToPilot") is not True
            or row["split"] not in {"train", "calibration", "test"}
        ):
            raise ValueError("EXPLICIT_UNIQUE_PHONETIC_CONTRAST_REQUIRED")
        identifiers.add(row["id"])
        if not set(row["againstTargetIds"]) <= targets:
            raise ValueError("UNKNOWN_CONTRAST_TARGET")
        root = row["lexicalRootId"]
        if root in lexical and lexical[root] != row["split"]:
            raise ValueError("LEXICAL_SPLIT_LEAK")
        lexical[root] = row["split"]
        text = _text(row["text"])
        if not text or texts.setdefault(text, row["split"]) != row["split"]:
            raise ValueError("TEXT_SPLIT_LEAK")
        if row["language"] not in ["English", "French"]:
            raise ValueError("UNSUPPORTED_FORMAL_FOREIGN_LANGUAGE")
    return config


def _validate_rows(rows: list[dict], config: dict):
    definitions = {row["id"]: row for row in config["definitions"]}
    lineage, texts, ids = {}, {}, set()
    for row in rows:
        if (
            row.get("kind") != "foreign-contrast"
            or row.get("unknownLabel") is not True
            or row.get("exploratoryDialect") is True
            or row.get("formalNegativeAllowed") is False
            or not row.get("againstTargetIds")
            or not isinstance(row.get("phoneticDifference"), str)
            or not row["phoneticDifference"].strip()
            or row.get("split") not in {"train", "calibration"}
            or not isinstance(row.get("id"), str)
            or not row["id"]
            or row["id"] in ids
        ):
            raise ValueError("EXPLICIT_FOREIGN_CONTRAST_REQUIRED")
        ids.add(row["id"])
        definition = definitions.get(row.get("foreignContrastId"))
        if definition is None or any(
            row.get(record_key) != definition[definition_key]
            for record_key, definition_key in (
                ("sourceText", "text"),
                ("language", "language"),
                ("locale", "locale"),
                ("lexicalRootId", "lexicalRootId"),
                ("split", "split"),
                ("contrastCategory", "contrastCategory"),
                ("againstTargetIds", "againstTargetIds"),
                ("phoneticDifference", "phoneticDifference"),
            )
        ):
            raise ValueError("FOREIGN_DEFINITION_BINDING_MISMATCH")
        allowed = (
            config["trainPersonaIds"]
            if row["split"] == "train"
            else config["calibrationPersonaIds"]
        )
        if row.get("voiceFamilyId") not in allowed:
            raise ValueError("FROZEN_SPLIT_VOICE_FAMILY_REQUIRED")
        for field in (
            "voiceFamilyId",
            "sha256",
            "lexicalRootId",
            "sourceRootId",
            "parentSha256",
            "parentRootId",
            "referenceRootId",
            "referenceSha256",
            "sourceSha256",
            "sourceWavSha256",
        ):
            if row.get(field):
                kind = (
                    "wave"
                    if field
                    in {
                        "sha256",
                        "parentSha256",
                        "referenceSha256",
                        "sourceSha256",
                        "sourceWavSha256",
                    }
                    else "root"
                    if field in {"sourceRootId", "parentRootId", "referenceRootId"}
                    else field
                )
                key = (kind, row[field])
                if lineage.setdefault(key, row["split"]) != row["split"]:
                    raise ValueError("FOREIGN_SOURCE_SPLIT_LEAK")
        text = _text(row["sourceText"])
        if texts.setdefault(text, row["split"]) != row["split"]:
            raise ValueError("FOREIGN_TEXT_SPLIT_LEAK")


def read_manifest(manifest: Path) -> list[dict]:
    data = json.loads(manifest.read_text())
    if (
        data.get("version") != 1
        or data.get("cohort") != "synthetic-explicit-foreign-phonetic-contrasts"
        or data.get("languageIdentityIsCorrectnessLabel") is not False
    ):
        raise ValueError("FOREIGN_MANIFEST_REQUIRED")
    candidates = [
        CONFIG,
        *[
            CONFIG.with_name(f"pronunciation-foreign-contrast-v{version}.json")
            for version in (1, 2)
        ],
    ]
    source = next(
        (
            path
            for path in candidates
            if path.exists()
            and fingerprint(path)
            == data.get("vocabularyConfigurationSha256", data.get("configurationSha256"))
        ),
        None,
    )
    if source is None:
        raise ValueError("FOREIGN_MANIFEST_CONFIGURATION_UNKNOWN")
    config = configuration(source)
    _validate_rows(data["items"], config)
    for row in data["items"]:
        file = (manifest.parent / row["file"]).resolve()
        if not file.is_relative_to(manifest.parent.resolve()) or fingerprint(file) != row["sha256"]:
            raise ValueError("FOREIGN_SOURCE_DIGEST_MISMATCH")
        decode_wav(file.read_bytes())
    return data["items"]


def lineage_counts(rows: list[dict]) -> dict:
    """Count original utterance roots, not derivatives or wrong-target pairings."""
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for row in rows:
        identities = [("root", row.get("sourceRootId", row["id"]))]
        identities += [
            ("wave", row[field])
            for field in ("sha256", "parentSha256", "sourceSha256", "sourceWavSha256")
            if row.get(field)
        ]
        if row.get("parentRootId"):
            identities.append(("root", row["parentRootId"]))
        first = find(identities[0])
        for identity in identities[1:]:
            parent[find(identity)] = first
    roots = {find(("root", row.get("sourceRootId", row["id"]))) for row in rows}
    return {
        "records": len(rows),
        "rawAudioUnits": len(roots),
        "distinctWaveforms": len({row["sha256"] for row in rows}),
        "sourceUtteranceRoots": len(roots),
        "parentRootIds": sorted(str(root[1]) for root in roots),
        "uniqueLexicalRoots": len({row["lexicalRootId"] for row in rows}),
        "voiceFamilies": len({row["voiceFamilyId"] for row in rows}),
        "independentRealSpeakers": 0,
        "wrongTargetPairs": sum(len(row.get("againstTargetIds", [])) for row in rows),
    }


def audit_manifests(manifests: list[Path]) -> dict:
    rows = [row for manifest in manifests for row in read_manifest(manifest)]
    _validate_rows(rows, configuration())
    return {
        "configurationSha256": fingerprint(CONFIG),
        "manifestSha256": {str(path): fingerprint(path) for path in manifests},
        "overall": lineage_counts(rows),
        "bySplit": {
            split: lineage_counts([row for row in rows if row["split"] == split])
            for split in sorted({row["split"] for row in rows})
        },
        "byLanguage": dict(Counter(row["language"] for row in rows)),
        "byLanguageAndContrastCategory": {
            f"{language}/{category}": lineage_counts(
                [
                    row
                    for row in rows
                    if row["language"] == language and row["contrastCategory"] == category
                ]
            )
            for language, category in sorted(
                {(row["language"], row["contrastCategory"]) for row in rows}
            )
        },
        "bySplitLanguageAndContrastCategory": {
            f"{split}/{language}/{category}": lineage_counts(
                [
                    row
                    for row in rows
                    if row["split"] == split
                    and row["language"] == language
                    and row["contrastCategory"] == category
                ]
            )
            for split, language, category in sorted(
                {(row["split"], row["language"], row["contrastCategory"]) for row in rows}
            )
        },
        "labelProvenance": "tts-intended-not-language-or-phoneme-verified",
        "languageIdentityIsCorrectnessLabel": False,
        "realForeignSpeakerValidation": False,
        "blindGenerationEnabled": False,
        "independentTrialsEstablished": False,
        "minimumIndependentZeroErrorTrialsForWilson95UpperAtMostFivePercent": 73,
    }


def generate(args) -> dict:
    if args.split not in {"train", "calibration"}:
        raise ValueError("BLIND_FOREIGN_GENERATION_DISABLED")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    config_path = getattr(args, "configuration", None) or CONFIG
    allowed_configs = [
        CONFIG,
        *[
            CONFIG.with_name(f"pronunciation-foreign-contrast-v{version}.json")
            for version in (1, 2)
        ],
    ]
    if config_path.resolve() not in {path.resolve() for path in allowed_configs}:
        raise ValueError("REGISTERED_GENERATION_CONFIGURATION_REQUIRED")
    config = configuration(config_path)
    install = json.loads((args.model / "installation.json").read_text())
    expected = json.loads((ROOT / "content/pronunciation-models.json").read_text())["generators"][
        "qwen"
    ]
    if install != expected:
        raise ValueError("TTS_INSTALLATION_VERSION_MISMATCH")
    for row in install["files"]:
        file = (args.model / row["path"]).resolve()
        if not file.is_relative_to(args.model.resolve()) or fingerprint(file) != row["sha256"]:
            raise ValueError("TTS_MODEL_DIGEST_MISMATCH")
    source = json.loads((ROOT / "content/pronunciation-training.json").read_text())["personas"]
    additional = json.loads(
        (ROOT / "content/pronunciation-contrast-training.json").read_text()
    ).get("additionalPersonas", [])
    personas = {row["id"]: row for row in source + additional}
    allowed = (
        config["trainPersonaIds"] if args.split == "train" else config["calibrationPersonaIds"]
    )
    requested = args.persona_ids or allowed
    if not set(requested) <= set(allowed) or any(key not in personas for key in requested):
        raise ValueError("FROZEN_SPLIT_VOICE_FAMILY_REQUIRED")
    definitions = [row for row in config["definitions"] if row["split"] == args.split]
    output = args.output.resolve() / ("qwen-" + args.split)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"
    data = (
        json.loads(manifest.read_text())
        if manifest.exists()
        else {
            "version": 1,
            "cohort": "synthetic-explicit-foreign-phonetic-contrasts",
            "configurationSha256": fingerprint(config_path),
            "labelProvenance": "tts-intended-not-language-or-phoneme-verified",
            "languageIdentityIsCorrectnessLabel": False,
            "realForeignSpeakerValidation": False,
            "items": [],
            "quarantined": [],
            "rejected": [],
        }
    )
    if data["configurationSha256"] != fingerprint(config_path):
        raise ValueError("CONFIG_CHANGED_USE_NEW_OUTPUT_DIRECTORY")
    seen = {row["id"] for key in ["items", "quarantined", "rejected"] for row in data[key]}
    synthesize = engine_qwen(args.model)
    completed = 0
    for persona_id in requested:
        for definition in definitions:
            sample_id = f"foreign-qwen-{persona_id}-{definition['id']}-0"
            if sample_id in seen:
                continue
            seed = config["seed"] + int(hashlib.sha256(sample_id.encode()).hexdigest()[:7], 16)
            persona = dict(personas[persona_id])
            language = definition["language"]
            persona["language"] = language
            persona["instruction"] = (
                persona["instruction"].split("标准普通话")[0]
                + f"清晰自然的{language}母语发音，只读给出的单词一次，不添加解释，不翻译为中文。"
            )
            row = {
                "id": sample_id,
                "kind": "foreign-contrast",
                "unknownLabel": True,
                "foreignContrastId": definition["id"],
                "lexicalRootId": definition["lexicalRootId"],
                "language": language,
                "locale": definition["locale"],
                "sourceText": definition["text"],
                "text": definition["text"] + ".",
                "contrastCategory": definition["contrastCategory"],
                "againstTargetIds": definition["againstTargetIds"],
                "phoneticDifference": definition["phoneticDifference"],
                "voiceFamilyId": persona_id,
                "referenceRootId": persona_id + "-reference",
                "sourceRootId": sample_id,
                "split": args.split,
                "seed": seed,
                "generator": "qwen",
                "generatorRevision": install["revision"],
                "modelSha256": next(
                    x["sha256"] for x in install["files"] if x["path"].endswith(".safetensors")
                ),
                "labelProvenance": "tts-intended-not-language-or-phoneme-verified",
            }
            started = time.perf_counter()
            try:
                samples, rate = synthesize(row["text"], persona, seed)
                divisor = math.gcd(int(rate), SAMPLE_RATE)
                samples = resample_poly(samples, SAMPLE_RATE // divisor, int(rate) // divisor)
                samples = trim_silence(np.asarray(samples, dtype=np.float32))
                quality = quality_check(samples)
                file = output / (sample_id + ".wav")
                file.write_bytes(encode_wav(samples))
                row.update({"file": file.name, "sha256": fingerprint(file), **quality})
                if quality["durationSeconds"] > config["maximumSeconds"]:
                    row["reason"] = "SHORT_WORD_OUTPUT_TOO_LONG"
                    data["quarantined"].append(row)
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
    read_manifest(manifest)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("models/matcher-qwen"))
    parser.add_argument("--output", type=Path, default=Path("private/matcher-v2-foreign"))
    parser.add_argument("--split", choices=["train", "calibration"], default="train")
    parser.add_argument("--persona-ids", nargs="+")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--configuration",
        type=Path,
        help="Registered active or immutable v1/v2 plan; use the original plan to resume.",
    )
    args = parser.parse_args()
    result = generate(args)
    print(json.dumps({key: len(result[key]) for key in ["items", "quarantined", "rejected"]}))
