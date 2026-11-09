"""Target-independent Qwen recognition with game-only pronunciation tolerance."""

import json
from functools import lru_cache
from pathlib import Path

from server import qwen_recognition as qwen
from server.reading_recognition import base_syllable, match_transcript

CONTENT = Path(__file__).resolve().parents[1] / "content"


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, dict]:
    rules = json.loads((CONTENT / "pinyin-shop.json").read_text())
    pictures = json.loads((CONTENT / "illustrations.json").read_text())["items"]
    return {key: pictures[key] for key in rules["targetIds"]}, rules["readingTolerance"]


def game_form(syllable: str, tolerance: dict) -> str:
    value = base_syllable(syllable)
    value = tolerance["isolatedVowels"].get(value, value)
    for plain, retroflex in tolerance["initialPairs"]:
        if value.startswith(retroflex):
            value = plain + value[len(retroflex) :]
            break
    for front, back in tolerance["finalPairs"]:
        if value.endswith(back):
            value = value[: -len(back)] + front
            break
    return value


def evaluate(target: dict, payload: bytes) -> dict:
    result = qwen.transcribe(payload, maximum_frames=80_000, tokens=24)
    if "transcript" not in result:
        return {
            "status": result["status"],
            "reason": "model-unavailable"
            if result["status"] == "unavailable"
            else "insufficient-evidence",
            "recognizedPinyin": None,
            "toneAssessed": False,
            "evidence": "none",
        }
    _, tolerance = catalog()
    expected = game_form(target["pinyin"], tolerance)
    match = match_transcript({"syllables": [target["pinyin"]]}, result["transcript"])
    observed = match["recognizedPinyin"].split()
    matched = (
        match["status"] != "uncertain"
        and len(observed) == 1
        and game_form(observed[0], tolerance) == expected
    )
    return {
        "status": "matched" if matched else "uncertain",
        "reason": None if matched else "insufficient-evidence",
        "recognizedPinyin": observed[0] if matched else None,
        "toneAssessed": False,
        "evidence": "acoustic" if matched else "none",
    }
