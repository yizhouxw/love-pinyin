"""Versioned target directory. Teaching/orthography data belongs in content/."""

import hashlib
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "content/pronunciation-targets.json"


def load_catalog(path: Path = CATALOG) -> dict:
    data = json.loads(path.read_text())
    if data.get("version") != 1 or not data.get("targets"):
        raise ValueError("TARGET_CATALOG_INVALID")
    ids = set()
    vocabulary = data["tokens"]
    if vocabulary[0] != "<blank>" or len(set(vocabulary)) != len(vocabulary):
        raise ValueError("TOKEN_VOCABULARY_INVALID")
    for item in data["targets"]:
        if item["id"] in ids or not item["phones"] or item["tone"] not in range(6):
            raise ValueError("TARGET_CATALOG_INVALID")
        if any(token not in vocabulary[1:] for token in item["phones"]):
            raise ValueError("TARGET_PHONES_INVALID")
        ids.add(item["id"])
    return data


def fingerprint(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def targets_by_id(catalog: dict | None = None) -> dict[str, dict]:
    return {item["id"]: item for item in (catalog or load_catalog())["targets"]}


def training_catalog(extensions_path: Path | None = None) -> dict:
    """Add declared standard anchors without changing public targets or phone heads.

    Extension labels clone an existing syllable's phonemes; they cannot invent a
    new phoneme, broaden the public pilot set, or silently mutate the base catalog.
    The resulting complete catalog is copied into the trained model bundle.
    """
    data = load_catalog()
    if extensions_path is None:
        return data
    extension = json.loads(extensions_path.read_text())
    if (
        extension.get("version") != 1
        or extension.get("baseCatalogSha256") != fingerprint(CATALOG)
        or extension.get("publicCoverageChanges") is not False
        or not extension.get("targets")
    ):
        raise ValueError("TRAINING_CATALOG_EXTENSION_INVALID")
    known = targets_by_id(data)
    for label in extension["targets"]:
        prototype = known.get(label.get("prototypeId"))
        if (
            prototype is None
            or prototype["form"] != "whole-syllable"
            or not isinstance(label.get("id"), str)
            or not label["id"].startswith("pm-")
            or label["id"] in known
            or type(label.get("tone")) is not int
            or label["tone"] not in {1, 2, 3, 4}
            or not isinstance(label.get("pinyin"), str)
            or not label["pinyin"]
            or unicodedata.normalize("NFC", label["pinyin"]) != label["pinyin"]
            or not isinstance(label.get("standardAudioId"), str)
            or not label["standardAudioId"]
            or label.get("trainingOnly") is not True
        ):
            raise ValueError("TRAINING_CATALOG_EXTENSION_TARGET_INVALID")
        target = {
            **prototype,
            **{key: label[key] for key in ("id", "pinyin", "tone", "standardAudioId")},
            "pilot": False,
            "trainingOnly": True,
            "ttsText": None,
            "sourceItemId": None,
        }
        known[target["id"]] = target
        data["targets"].append(target)
    data["trainingExtension"] = {
        "baseCatalogSha256": extension["baseCatalogSha256"],
        "configurationSha256": fingerprint(extensions_path),
        "publicCoverageChanges": False,
    }
    return data
