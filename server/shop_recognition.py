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
    targets = {key: pictures[key] for key in rules["targetIds"]}
    targets.update({f"shop-sentence-{item['id']}": item for item in rules["sentences"]})
    return targets, rules["readingTolerance"]


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
    expected = target["pinyin"].removesuffix(".").split()
    match = match_transcript({"syllables": expected}, result["transcript"])
    observed = match["recognizedPinyin"].split()
    matched = (
        match["status"] != "uncertain"
        and len(observed) == len(expected)
        and all(
            game_form(actual, tolerance) == game_form(wanted, tolerance)
            for actual, wanted in zip(observed, expected, strict=True)
        )
    )
    return {
        "status": "matched" if matched else "uncertain",
        "reason": None if matched else "insufficient-evidence",
        "recognizedPinyin": match["recognizedPinyin"] if matched else None,
        "toneAssessed": False,
        "evidence": "acoustic" if matched else "none",
    }
