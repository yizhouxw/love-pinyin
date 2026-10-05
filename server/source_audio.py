"""Trusted PinYinSound standard audio, served only from verified local files."""

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from server.audio_assets import _verified_file, file_audio_response

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "content" / "pinyin-source.json"
SOURCE_DIR = Path(os.environ.get("LOVE_PINYIN_SOURCE_AUDIO_DIR", ROOT / "private" / "pinyinsound"))


def target_signature(target: dict) -> str:
    descriptor = {key: target.get(key) for key in ("id", "transcript", "kind", "knowledgeIds")}
    return hashlib.sha256(
        json.dumps(descriptor, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text())
    rows = data["assets"]
    if data["version"] != 1 or len({a["id"] for a in rows}) != len(rows):
        raise ValueError("Invalid source catalog")
    for row in rows:
        if not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]):
            raise ValueError("Invalid source digest")
        if Path(row["filename"]).name != row["filename"] or "\\" in row["filename"]:
            raise ValueError("Invalid source filename")
    return data


def installed() -> bool:
    try:
        path = SOURCE_DIR / "installation.json"
        if path.stat().st_size > 16384:
            return False
        state = json.loads(path.read_text())
        source = catalog()
        return (
            state.get("version") == 1
            and state.get("enabled") is True
            and state.get("commit") == source["commit"]
            and state.get("archiveSha256") == source["archiveSha256"]
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def registered_path(target: dict) -> tuple[Path, str]:
    def unavailable():
        return HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})

    if not installed() or target.get("kind") == "instruction":
        raise unavailable()
    row = next((a for a in catalog()["assets"] if a["id"] == target["id"]), None)
    if not row or row["targetSignature"] != target_signature(target):
        raise unavailable()
    try:
        root = SOURCE_DIR.resolve()
        path = (root / "clips" / f"{row['sha256']}.mp3").resolve(strict=True)
        if root not in path.parents or not path.is_file():
            raise unavailable()
    except (OSError, RuntimeError):
        raise unavailable() from None
    return path, row["sha256"]


def available(target: dict) -> bool:
    try:
        path, digest = registered_path(target)
        handle, size = _verified_file(path, digest)
        handle.close()
        return size > 0
    except HTTPException:
        return False


def metadata(target: dict) -> dict:
    row = next(a for a in catalog()["assets"] if a["id"] == target["id"])
    return {
        "id": catalog()["id"],
        "title": catalog()["title"],
        "exampleTone": row["exampleTone"],
    }


def audio_response(target: dict, range_header: str | None = None):
    path, digest = registered_path(target)
    response = file_audio_response(path, "audio/mpeg", digest, range_header)
    response.headers["Cache-Control"] = "no-store"
    return response
