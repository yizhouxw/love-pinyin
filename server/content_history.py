"""Local, explicitly registered teaching revisions; never infer an unknown version."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from server import content

HISTORY_DIR = Path(__file__).resolve().parents[1] / "content" / "history"


@lru_cache(maxsize=1)
def revision_index() -> list[dict]:
    data = json.loads((HISTORY_DIR / "index.json").read_text())
    rows = data["revisions"]
    if data["version"] != 1 or len({r["contentVersion"] for r in rows}) != len(rows):
        raise ValueError("Invalid content history index")
    for row in rows:
        if Path(row["file"]).name != row["file"] or "\\" in row["file"]:
            raise ValueError("Invalid history filename")
    return rows


def revision_order(version: object) -> int | None:
    if not isinstance(version, str):
        return None
    for index, row in enumerate(revision_index()):
        if row["contentVersion"] == version:
            return index
    # The running curriculum is authoritative, including isolated test revisions.
    if version == content.load_curriculum()["contentVersion"]:
        return len(revision_index())
    return None


def compatible_revision(version: object, container_version: object) -> bool:
    child, parent = revision_order(version), revision_order(container_version)
    return child is not None and parent is not None and child <= parent


@lru_cache(maxsize=32)
def archived_exercises(version: str) -> dict[str, dict]:
    row = next((r for r in revision_index() if r["contentVersion"] == version), None)
    if row is None:
        raise ValueError("Unknown content revision")
    raw = (HISTORY_DIR / row["file"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("Content history digest mismatch")
    data = json.loads(raw)
    questions = data["exercises"]
    if data["contentVersion"] != version or len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Invalid content history")
    return {q["id"]: q for q in questions}


def exercises_for_revision(version: str) -> dict[str, dict]:
    if version == content.load_curriculum()["contentVersion"]:
        return content.map_by_id("exercises")
    return archived_exercises(version)
