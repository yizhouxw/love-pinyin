"""Shared learning queries and public exercise presentation."""

from datetime import date, datetime

from fastapi import HTTPException

from server import source_audio
from server.content import load_curriculum
from server.domain import (
    Event,
    calculate_mastery,
    order_options,
)


def _public_exercise(question: dict, *, instance_id: str | None = None) -> dict:
    result = {
        key: value
        for key, value in question.items()
        if key not in {"answer", "hint", "reviewStatus"}
    }
    if instance_id is not None and "options" in result:
        result["options"] = order_options(result["options"], instance_id)
    return result


def _available_standard_audio(content: dict) -> set[str]:
    assets = content.get("audioRequirements", [])
    return {
        asset["id"]
        for asset in assets
        if sum(item.get("id") == asset.get("id") for item in assets) == 1
        and source_audio.available(asset)
    }


def _objective_available(question: dict, audio_ids: set[str]) -> bool:
    if question["type"] not in {"listen-choice", "symbol-choice", "tone-choice", "blend-choice"}:
        return False
    audio_id = question.get("audioRef")
    if audio_id or question["type"] == "listen-choice":
        return audio_id in audio_ids
    return True


def _current_lesson_order(lessons: dict[str, dict], selected_lesson_id: str) -> int:
    current_lesson = lessons.get(selected_lesson_id)
    if current_lesson is None:
        raise HTTPException(409, detail={"code": "CURRENT_LESSON_REQUIRES_SELECTION"})
    return current_lesson["order"]


def _review_recommendations(
    curriculum: dict,
    selected_lesson_id: str,
    plans: list,
    credited_today: set[tuple[str, str]],
    today: date,
) -> list[dict]:
    """Return at most three due knowledge points that can start a two-question review."""
    lessons = {lesson["id"]: lesson for lesson in curriculum["lessons"]}
    current = lessons.get(selected_lesson_id)
    if current is None:
        return []
    knowledge = {item["id"]: item for item in curriculum["knowledgeItems"]}
    exercises = {item["id"]: item for item in curriculum["exercises"]}
    audio_ids = _available_standard_audio(curriculum)
    due_plans = {
        row["knowledge_id"]: row
        for row in plans
        if row["due_date"] and date.fromisoformat(row["due_date"]) <= today
    }
    candidates = []
    for knowledge_id, plan in due_plans.items():
        item = knowledge.get(knowledge_id)
        lesson = lessons.get(item["lessonId"]) if item else None
        if lesson is None or lesson["order"] > current["order"]:
            continue
        eligible = {
            exercise_id
            for lesson_id, candidate_lesson in lessons.items()
            if candidate_lesson["order"] <= current["order"]
            for exercise_id in candidate_lesson["exerciseIds"]
            if exercise_id in exercises
            and exercises[exercise_id]["primaryKnowledgeId"] == knowledge_id
            and _objective_available(exercises[exercise_id], audio_ids)
            and (knowledge_id, exercise_id) not in credited_today
        }
        if len(eligible) < 2:
            continue
        due_date = date.fromisoformat(plan["due_date"])
        candidates.append(
            {
                "knowledgeId": knowledge_id,
                "symbol": item["symbol"],
                "lessonId": lesson["id"],
                "lessonTitle": lesson["title"],
                "dueDate": plan["due_date"],
                "overdueDays": (today - due_date).days,
                "lessonOrder": lesson["order"],
            }
        )
    candidates.sort(
        key=lambda item: (-item["overdueDays"], item["lessonOrder"], item["knowledgeId"])
    )
    return [
        {key: value for key, value in item.items() if key != "lessonOrder"}
        for item in candidates[:3]
    ]


def _mastery(db, household_id: str) -> dict[str, dict]:
    content = load_curriculum()
    raw = db.execute(
        """SELECT id,knowledge_id,mode,first_try_correct,due_credit,occurred_at
           FROM attempts WHERE household_id=? ORDER BY occurred_at,id""",
        (household_id,),
    ).fetchall()
    events_by_knowledge = {item["id"]: [] for item in content["knowledgeItems"]}
    for row in raw:
        if row["knowledge_id"] in events_by_knowledge:
            events_by_knowledge[row["knowledge_id"]].append(
                Event(
                    row["id"],
                    row["mode"],
                    bool(row["first_try_correct"]),
                    datetime.fromisoformat(row["occurred_at"]),
                    bool(row["due_credit"]),
                )
            )
    result = {}
    for item in content["knowledgeItems"]:
        summary = calculate_mastery(events_by_knowledge[item["id"]], item["requiredModes"])
        result[item["id"]] = {
            "knowledgeId": item["id"],
            "status": summary.status,
            "sampleSize": summary.sample_size,
            "correctCount": summary.correct_count,
            "accuracy": summary.accuracy,
            "coveredModes": list(summary.covered_modes),
            "requiredModes": list(summary.required_modes),
        }
    return result
