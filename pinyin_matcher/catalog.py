"""Versioned target directory. Teaching/orthography data belongs in content/."""

import hashlib
import json
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
