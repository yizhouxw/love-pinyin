"""Read-only repository for the versioned curriculum shipped with this server."""

import json
from functools import lru_cache
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "curriculum.json"


@lru_cache(maxsize=1)
def load_curriculum() -> dict:
    content = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    lessons = content["lessons"]
    if len({row["id"] for row in lessons}) != len(lessons):
        raise ValueError("duplicate lesson ID in curriculum")
    if len({row["order"] for row in lessons}) != len(lessons):
        raise ValueError("duplicate lesson order in curriculum")
    knowledge = {row["id"] for row in content["knowledgeItems"]}
    exercises = {row["id"] for row in content["exercises"]}
    targets = {row["id"] for row in content["readingTargets"]}
    for row in lessons:
        if not set(row["knowledgeIds"]) <= knowledge:
            raise ValueError(f"unknown knowledge ID in {row['id']}")
        if not set(row["exerciseIds"]) <= exercises:
            raise ValueError(f"unknown exercise ID in {row['id']}")
        if not set(row["readingTargetIds"]) <= targets:
            raise ValueError(f"unknown reading target ID in {row['id']}")
    return content


def map_by_id(collection: str) -> dict[str, dict]:
    return {row["id"]: row for row in load_curriculum()[collection]}


@lru_cache(maxsize=1)
def load_writing() -> dict:
    return json.loads((CONTENT_PATH.parent / "writing.json").read_text(encoding="utf-8"))
