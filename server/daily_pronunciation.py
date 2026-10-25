"""Authored tone policy and locally derived first tones; never substitute another tone."""

import hashlib
import json
import re
from pathlib import Path

from fastapi import HTTPException

from server import source_audio

POLICY = Path(__file__).resolve().parents[1] / "content" / "daily-reading-policy.json"


def policy() -> dict:
    return json.loads(POLICY.read_text())


def signature(recipe: dict) -> str:
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def registered(asset_id: str) -> tuple[Path, str]:
    """The installation manifest binds the local output to its pinned source and recipe."""
    try:
        recipe = policy()["derivedFirstTones"][asset_id]
        if not source_audio.installed():
            raise ValueError("Source disabled")
        manifest = json.loads((source_audio.SOURCE_DIR / "daily-first-tones.json").read_text())
        entry = manifest[asset_id]
        digest = entry["sha256"]
        if entry["recipeSha256"] != signature(recipe) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Stale derived recording")
        return source_audio.SOURCE_DIR / "clips" / f"{digest}.wav", digest
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(404, detail={"code": "DAILY_AUDIO_NOT_FOUND"}) from None
