"""Source-backed word practice narration; never synthesizes at request time."""

import hashlib
import json
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "content/word-practice/lessons.json"


def character_audio(text: str) -> str:
    return "word-say-" + hashlib.sha256(text.encode()).hexdigest()[:16]


def scripts() -> dict[str, str]:
    data = json.loads(CONTENT.read_text())
    result = {f"word-ui-{key.lower()}": value for key, value in data["ui"].items()}
    for lesson in data["lessons"]:
        result[lesson["audioId"]] = lesson["spokenTitle"]
        for word in lesson["read"] + lesson["write"]:
            result[word["audioId"]] = word["text"]
        for char in lesson["characters"]:
            result[character_audio(char)] = char
        for passage in lesson["passages"]:
            for paragraph in passage["paragraphs"]:
                result[paragraph["audioId"]] = paragraph["text"]
    return result
