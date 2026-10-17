"""HTTP endpoints for progress."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from server.api_dependencies import _observe_clock, paired
from server.content import load_curriculum, map_by_id
from server.domain import (
    business_date,
)
from server.learning_state import _mastery, _review_recommendations
from server.storage import connect

router = APIRouter()


@router.get("/profiles/progress")
def progress(device: dict = Depends(paired)) -> dict:
    _observe_clock(device)
    today = business_date(datetime.now(UTC))
    with connect() as db:
        mastery = _mastery(db, device["household_id"])
        completed_sessions = db.execute(
            """SELECT COUNT(*)
               FROM sessions s
               WHERE s.household_id=? AND s.status='finished'
                 AND EXISTS (
                   SELECT 1 FROM exercise_instances i WHERE i.session_id=s.id
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM exercise_instances i
                   LEFT JOIN attempts a ON a.instance_id=i.id
                   LEFT JOIN skipped_instances sk ON sk.instance_id=i.id
                   WHERE i.session_id=s.id AND a.id IS NULL AND sk.instance_id IS NULL
                 )""",
            (device["household_id"],),
        ).fetchone()[0]
        attempts = db.execute(
            """SELECT id,exercise_id,knowledge_id,mode,first_try_correct,hint_used,due_credit,
               clock_pending,
               occurred_at,business_date FROM attempts WHERE household_id=?
               ORDER BY occurred_at DESC,id DESC LIMIT 1000""",
            (device["household_id"],),
        ).fetchall()
        attempt_count = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE household_id=?",
            (device["household_id"],),
        ).fetchone()[0]
        plans = db.execute(
            "SELECT knowledge_id,stage,due_date FROM review_plans WHERE household_id=?",
            (device["household_id"],),
        ).fetchall()
        credited_today = {
            (row["knowledge_id"], row["exercise_id"])
            for row in db.execute(
                """SELECT DISTINCT knowledge_id,exercise_id FROM attempts
                   WHERE household_id=? AND business_date=? AND due_credit=1""",
                (device["household_id"], today.isoformat()),
            ).fetchall()
        }
        pending_clock_count = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE household_id=? AND clock_pending=1",
            (device["household_id"],),
        ).fetchone()[0]
    by_knowledge = {row["knowledge_id"]: row for row in plans}
    for key, value in mastery.items():
        plan = by_knowledge.get(key)
        due = plan["due_date"] if plan else None
        value["reviewDueDate"] = due
        value["reviewDue"] = bool(due and date.fromisoformat(due) <= today)
        value["reviewStage"] = plan["stage"] if plan else None
    recommendations = _review_recommendations(
        load_curriculum(), device["selected_lesson_id"], plans, credited_today, today
    )
    return {
        "schemaVersion": 2,
        "contentVersion": device["content_version"],
        "profileId": device["household_id"],
        "revision": device["revision"],
        "selectedLessonId": device["selected_lesson_id"],
        "masteryRuleVersion": "mastery-v1",
        "completedSessions": completed_sessions,
        "attemptCount": attempt_count,
        "clockSkewDetected": bool(device["clock_skew_detected"]),
        "pendingClockAttempts": pending_clock_count,
        "settings": {
            "soundEnabled": bool(device["sound_enabled"]),
            "reducedMotion": bool(device["reduced_motion"]),
            "playbackGapSeconds": device["playback_gap_tenths"] / 10,
        },
        "mastery": list(mastery.values()),
        "reviewRecommendations": recommendations,
        "attempts": [dict(row) for row in attempts],
    }


@router.get("/profiles/knowledge/{knowledge_id}/attempts")
def knowledge_attempt_history(
    knowledge_id: str,
    cursor: str | None = None,
    limit: int = Query(default=8, ge=1, le=50),
    device: dict = Depends(paired),
) -> dict:
    if knowledge_id not in map_by_id("knowledgeItems"):
        raise HTTPException(404, detail={"code": "KNOWLEDGE_NOT_FOUND"})
    with connect() as db:
        cursor_row = None
        if cursor is not None:
            cursor_row = db.execute(
                """SELECT id,knowledge_id,occurred_at FROM attempts
                   WHERE id=? AND household_id=?""",
                (cursor, device["household_id"]),
            ).fetchone()
            if cursor_row is None or cursor_row["knowledge_id"] != knowledge_id:
                raise HTTPException(404, detail={"code": "ATTEMPT_CURSOR_NOT_FOUND"})
        if cursor_row is None:
            rows = db.execute(
                """SELECT id,mode,first_try_correct,hint_used,due_credit,clock_pending,occurred_at
                   FROM attempts WHERE household_id=? AND knowledge_id=?
                   ORDER BY occurred_at DESC,id DESC LIMIT ?""",
                (device["household_id"], knowledge_id, limit + 1),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT id,mode,first_try_correct,hint_used,due_credit,clock_pending,occurred_at
                   FROM attempts WHERE household_id=? AND knowledge_id=?
                     AND (occurred_at,id) < (?,?)
                   ORDER BY occurred_at DESC,id DESC LIMIT ?""",
                (
                    device["household_id"],
                    knowledge_id,
                    cursor_row["occurred_at"],
                    cursor_row["id"],
                    limit + 1,
                ),
            ).fetchall()
    has_more = len(rows) > limit
    visible = rows[:limit]
    return {
        "knowledgeId": knowledge_id,
        "items": [
            {
                "id": row["id"],
                "mode": row["mode"],
                "firstTryCorrect": bool(row["first_try_correct"]),
                "hintUsed": bool(row["hint_used"]),
                "dueCredit": bool(row["due_credit"]),
                "clockPending": bool(row["clock_pending"]),
                "occurredAt": row["occurred_at"],
            }
            for row in visible
        ],
        "nextCursor": visible[-1]["id"] if has_more and visible else None,
        "hasMore": has_more,
    }
