"""Scene settings and progress-based planning; no motor performance enters mastery."""

from server.domain import plan_practice
from server.game_policy import CATALOG


def recommend(mastery: dict) -> dict:
    rules = CATALOG["adaptation"]
    samples = sum(item.get("sampleSize", 0) for item in mastery.values())
    correct = sum(item.get("correctCount", 0) for item in mastery.values())
    mastered = sum(item.get("status") == "mastered" for item in mastery.values())
    accuracy = correct / samples if samples else 0
    level, speed = "gentle", "slow"
    if samples >= rules["steadySamples"] and accuracy >= rules["steadyAccuracy"]:
        level, speed = "steady", "normal"
    if (
        samples >= rules["challengeSamples"]
        and accuracy >= rules["challengeAccuracy"]
        and mastered >= rules["challengeMastered"]
    ):
        level = "challenge"
    return {
        "level": level,
        "speed": speed,
        "sampleSize": samples,
        "correctCount": correct,
        "masteredCount": mastered,
    }


def settings_for(mastery: dict, difficulty: str, speed: str) -> dict:
    match = recommend(mastery)
    return {
        "version": 1,
        "level": match["level"] if difficulty == "auto" else difficulty,
        "speed": match["speed"] if speed == "auto" else speed,
        "requestedDifficulty": difficulty,
        "requestedSpeed": speed,
        "recommendation": match,
    }


def valid_settings(value: object) -> bool:
    if value == {}:
        return True  # Legacy sessions.
    if not isinstance(value, dict) or set(value) != {
        "version",
        "level",
        "speed",
        "requestedDifficulty",
        "requestedSpeed",
        "recommendation",
    }:
        return False
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["level"], str)
        or value["level"] not in CATALOG["levels"]
        or not isinstance(value["speed"], str)
        or value["speed"] not in CATALOG["speeds"]
        or value["requestedDifficulty"] not in ["auto", *CATALOG["levels"]]
        or value["requestedSpeed"] not in ["auto", *CATALOG["speeds"]]
    ):
        return False
    match = value["recommendation"]
    return (
        isinstance(match, dict)
        and set(match) == {"level", "speed", "sampleSize", "correctCount", "masteredCount"}
        and isinstance(match["level"], str)
        and match["level"] in CATALOG["levels"]
        and isinstance(match["speed"], str)
        and match["speed"] in CATALOG["speeds"]
        and all(
            type(match[key]) is int and 0 <= match[key] <= 100000
            for key in ("sampleSize", "correctCount", "masteredCount")
        )
        and match["correctCount"] <= match["sampleSize"]
    )


def plan_game(questions: list[dict], completions: list, mastery: dict, lesson_id: str) -> list[str]:
    """Two weak spots, then current lesson, then historical rotation; no repeats."""
    weak = [
        q["id"]
        for q in questions
        if mastery.get(q["primaryKnowledgeId"], {}).get("status") == "practicing"
    ]
    chosen = plan_practice(weak, completions, limit=CATALOG["adaptation"]["weakSlots"])
    current = [q["id"] for q in questions if q["lessonId"] == lesson_id and q["id"] not in chosen]
    chosen += plan_practice(current, completions, limit=6 - len(chosen))
    remaining = [q["id"] for q in questions if q["id"] not in chosen]
    return (
        chosen
        if len(chosen) == 6
        else chosen + plan_practice(remaining, completions, limit=6 - len(chosen))
    )
