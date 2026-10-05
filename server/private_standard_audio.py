"""Private household clips explicitly confirmed in the local authoring tool."""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from server.audio_assets import _verified_file, file_audio_response

ROOT = Path(__file__).resolve().parents[1]
STANDARD_DIR = (
    Path(os.environ.get("LOVE_PINYIN_STANDARD_AUDIO_DIR", ROOT / "private" / "standard-audio"))
    .expanduser()
    .resolve()
)


def target_signature(target: dict) -> str:
    descriptor = {key: target.get(key) for key in ("id", "transcript", "kind", "knowledgeIds")}
    return hashlib.sha256(
        json.dumps(descriptor, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def read_assets() -> dict:
    try:
        path = STANDARD_DIR / "manifest.json"
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}
        data = json.loads(path.read_text())
        assets = data["assets"]
        result = {asset["id"]: asset for asset in assets}
        return result if data["version"] == 1 and len(result) == len(assets) else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def reviewed_path(target: dict) -> tuple[Path, str]:
    def unavailable():
        return HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})

    asset = read_assets().get(target["id"], {})
    if (
        target.get("kind") == "instruction"
        or asset.get("targetSignature") != target_signature(target)
        or asset.get("usage") != "private-household"
        or asset.get("distribution") != "not-for-redistribution"
    ):
        raise unavailable()
    try:
        reviews = asset["reviews"]
        if len(reviews) != 2 or {row["role"] for row in reviews} != {"teaching", "quality"}:
            raise ValueError()
        names = {row["reviewer"].strip().casefold() for row in reviews}
        if len(names) != 2 or "" in names:
            raise ValueError()
        for row in reviews:
            if row["confirmed"] is not True or datetime.fromisoformat(row["at"]).tzinfo is None:
                raise ValueError()
        digest = asset["sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError()
        if asset["file"] != f"clips/{digest}.wav":
            raise ValueError()
        path = (STANDARD_DIR / asset["file"]).resolve(strict=True)
        if STANDARD_DIR.resolve() not in path.parents or not path.is_file():
            raise ValueError()
    except (KeyError, TypeError, ValueError, OSError, AttributeError, RuntimeError):
        raise unavailable() from None
    return path, digest


def available(target: dict) -> bool:
    try:
        path, digest = reviewed_path(target)
        handle, size = _verified_file(path, digest)
        handle.close()
        return size > 0
    except HTTPException:
        return False


def audio_response(target: dict, range_header: str | None):
    path, digest = reviewed_path(target)
    return file_audio_response(path, "audio/wav", digest, range_header)
