"""HTTP endpoints for sessions."""

import json
import secrets
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from server.api_dependencies import mutable, paired
from server.content import load_curriculum, map_by_id
from server.content_history import exercises_for_revision
from server.domain import (
    OPTION_ORDER_V1_PREFIX,
    PracticeCompletion,
    business_date,
    next_review,
    plan_practice,
)
from server.game_adaptation import plan_game, settings_for
from server.game_policy import GAMES
from server.game_service import clock_status
from server.learning_state import (
    _available_standard_audio,
    _current_lesson_order,
    _mastery,
    _objective_available,
    _public_exercise,
)
from server.storage import connect, now_iso, transaction

router = APIRouter()


class StartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessonId: str | None = None
    gameId: str | None = None
    gameDifficulty: Literal["auto", "gentle", "steady", "challenge"] = "auto"
    gameSpeed: Literal["auto", "slow", "normal", "fast"] = "auto"


@router.post("/reviews/{knowledge_id}/sessions")
def start_review_session(knowledge_id: str, device: dict = Depends(mutable)) -> dict:
    if device["rounds_since_break"] >= 2:
        raise HTTPException(409, detail={"code": "REST_REQUIRED"})
    content = load_curriculum()
    lessons = map_by_id("lessons")
    knowledge = map_by_id("knowledgeItems")
    if knowledge_id not in knowledge:
        raise HTTPException(404, detail={"code": "KNOWLEDGE_NOT_FOUND"})
    current_order = _current_lesson_order(lessons, device["selected_lesson_id"])
    exercise_map = map_by_id("exercises")
    audio_ids = _available_standard_audio(content)
    eligible = [
        exercise_map[exercise_id]
        for lesson in content["lessons"]
        if lesson["order"] <= current_order
        for exercise_id in lesson["exerciseIds"]
        if exercise_map[exercise_id]["primaryKnowledgeId"] == knowledge_id
        and _objective_available(exercise_map[exercise_id], audio_ids)
    ]
    eligible = list({item["id"]: item for item in eligible}.values())
    if len(eligible) < 2:
        raise HTTPException(409, detail={"code": "REVIEW_CONTENT_INSUFFICIENT"})
    day = business_date(datetime.now(UTC)).isoformat()
    session_id, now = secrets.token_urlsafe(18), now_iso()
    with transaction() as db:
        household = db.execute(
            "SELECT rounds_since_break FROM household WHERE id=?", (device["household_id"],)
        ).fetchone()
        if household["rounds_since_break"] >= 2:
            raise HTTPException(409, detail={"code": "REST_REQUIRED"})
        plan = db.execute(
            "SELECT stage,due_date FROM review_plans WHERE household_id=? AND knowledge_id=?",
            (device["household_id"], knowledge_id),
        ).fetchone()
        if not plan:
            raise HTTPException(409, detail={"code": "REVIEW_NOT_SCHEDULED"})
        if plan["due_date"] > day:
            raise HTTPException(409, detail={"code": "REVIEW_NOT_DUE", "dueDate": plan["due_date"]})
        credited = {
            row[0]
            for row in db.execute(
                """SELECT exercise_id FROM attempts WHERE household_id=? AND knowledge_id=?
                   AND business_date=? AND due_credit=1""",
                (device["household_id"], knowledge_id, day),
            )
        }
        available = [q for q in eligible if q["id"] not in credited]
        if len(available) < 2:
            raise HTTPException(409, detail={"code": "REVIEW_TODAY_EXHAUSTED"})
        tasks = []
        for q in available[:2]:
            instance_id = OPTION_ORDER_V1_PREFIX + secrets.token_urlsafe(18)
            lesson_id = next(
                lesson["id"] for lesson in content["lessons"] if q["id"] in lesson["exerciseIds"]
            )
            db.execute(
                """INSERT INTO exercise_instances(id,household_id,exercise_id,lesson_id,
                   content_version,created_at,session_id) VALUES(?,?,?,?,?,?,?)""",
                (
                    instance_id,
                    device["household_id"],
                    q["id"],
                    lesson_id,
                    content["contentVersion"],
                    now,
                    session_id,
                ),
            )
            tasks.append(
                {
                    "instanceId": instance_id,
                    "exercise": _public_exercise(q, instance_id=instance_id),
                }
            )
        db.execute(
            """INSERT INTO sessions(id,household_id,device_id,content_version,started_at,
               tasks_json,review_knowledge_id) VALUES(?,?,?,?,?,?,?)""",
            (
                session_id,
                device["household_id"],
                device["id"],
                content["contentVersion"],
                now,
                json.dumps(tasks, ensure_ascii=False),
                knowledge_id,
            ),
        )
        revision = db.execute(
            "UPDATE household SET revision=revision+1 WHERE id=? RETURNING revision",
            (device["household_id"],),
        ).fetchone()["revision"]
    return {
        "id": session_id,
        "reviewKnowledgeId": knowledge_id,
        "contentVersion": content["contentVersion"],
        "startedAt": now,
        "tasks": tasks,
        "audioAvailable": any(task["exercise"].get("audioRef") in audio_ids for task in tasks),
        "revision": revision,
    }


@router.post("/sessions")
def start_session(body: StartSession, device: dict = Depends(mutable)) -> dict:
    if device["rounds_since_break"] >= 2:
        raise HTTPException(409, detail={"code": "REST_REQUIRED"})
    content = load_curriculum()
    lessons = map_by_id("lessons")
    requested_id = body.lessonId or device["selected_lesson_id"]
    if requested_id not in lessons:
        raise HTTPException(404, detail={"code": "LESSON_NOT_FOUND"})
    current_order = _current_lesson_order(lessons, device["selected_lesson_id"])
    lesson = lessons[requested_id]
    if lesson["order"] > current_order:
        raise HTTPException(403, detail={"code": "LESSON_NOT_UNLOCKED"})
    by_id = map_by_id("exercises")
    # Hearing exercises use only reviewed, present and integrity-checked standard
    # sounds. Whole-lesson recordings and Chinese instructions cannot replace them.
    audio_ids = _available_standard_audio(content)
    if body.gameId is not None and body.gameId not in GAMES:
        raise HTTPException(422, detail={"code": "GAME_NOT_FOUND"})
    eligible_lessons = (
        [item for item in content["lessons"] if item["order"] <= current_order]
        if body.gameId
        else [lesson]
    )
    question_lessons = {qid: item["id"] for item in eligible_lessons for qid in item["exerciseIds"]}
    questions = [
        by_id[qid]
        for qid in question_lessons
        if _objective_available(by_id[qid], audio_ids)
        and (
            not body.gameId
            or (
                by_id[qid]["type"] in GAMES[body.gameId]["modes"]
                and by_id[qid].get("audioRef")
                and all(
                    not o.get("pictureId") and not o.get("writing") for o in by_id[qid]["options"]
                )
            )
        )
    ]
    if not questions:
        raise HTTPException(409, detail={"code": "LESSON_NOT_READY"})
    session_id = secrets.token_urlsafe(18)
    now = now_iso()
    tasks = []
    game_settings = {}
    with transaction() as db:
        # Recheck under the same write lock as session creation. A second
        # device may have completed round two after this request's auth
        # dependency loaded its household snapshot.
        household = db.execute(
            "SELECT rounds_since_break FROM household WHERE id=?",
            (device["household_id"],),
        ).fetchone()
        if household["rounds_since_break"] >= 2:
            raise HTTPException(409, detail={"code": "REST_REQUIRED"})
        if body.gameId:
            budget = clock_status(db, device["household_id"], "heartbeat")
            if budget["reason"]:
                raise HTTPException(409, detail={"code": budget["reason"]})
            db.execute(
                "UPDATE sessions SET status='finished' WHERE household_id=? "
                "AND game_id IS NOT NULL AND status='active'",
                (device["household_id"],),
            )
        history = db.execute(
            """SELECT i.exercise_id, COALESCE(a.occurred_at,s.skipped_at) AS completed_at
               FROM exercise_instances i
               LEFT JOIN attempts a ON a.instance_id=i.id
               LEFT JOIN skipped_instances s ON s.instance_id=i.id
               WHERE i.household_id=? AND (i.lesson_id=? OR ? IS NOT NULL)
                 AND (a.id IS NOT NULL OR s.instance_id IS NOT NULL)""",
            (device["household_id"], lesson["id"], body.gameId),
        ).fetchall()
        if body.gameId:
            mastery = _mastery(db, device["household_id"])
            # Recommendations ignore knowledge beyond the school-selected lesson.
            allowed = {
                k["id"]
                for k in content["knowledgeItems"]
                if k["lessonId"] in {item["id"] for item in eligible_lessons}
            }
            mastery = {key: item for key, item in mastery.items() if key in allowed}
            game_settings = settings_for(mastery, body.gameDifficulty, body.gameSpeed)
            # Genre preference is a stable tie-break, never a filter that traps
            # later learners in lesson one's tone bank or drops current content.
            questions = sorted(questions, key=lambda q: q["type"] != GAMES[body.gameId]["mode"])
            selected_ids = plan_game(
                questions,
                [
                    PracticeCompletion(
                        row["exercise_id"], datetime.fromisoformat(row["completed_at"])
                    )
                    for row in history
                ],
                mastery,
                device["selected_lesson_id"],
            )
        else:
            selected_ids = plan_practice(
                [q["id"] for q in questions],
                [
                    PracticeCompletion(
                        row["exercise_id"], datetime.fromisoformat(row["completed_at"])
                    )
                    for row in history
                ],
            )
        question_set = [by_id[exercise_id] for exercise_id in selected_ids]
        for q in question_set:
            instance_id = OPTION_ORDER_V1_PREFIX + secrets.token_urlsafe(18)
            db.execute(
                """INSERT INTO exercise_instances(
                   id,household_id,exercise_id,lesson_id,content_version,
                   created_at,session_id) VALUES(?,?,?,?,?,?,?)""",
                (
                    instance_id,
                    device["household_id"],
                    q["id"],
                    question_lessons[q["id"]],
                    content["contentVersion"],
                    now,
                    session_id,
                ),
            )
            tasks.append(
                {
                    "instanceId": instance_id,
                    "exercise": _public_exercise(q, instance_id=instance_id),
                }
            )
        db.execute(
            """INSERT INTO sessions(id,household_id,device_id,content_version,started_at,
               tasks_json,game_id,game_settings_json) VALUES(?,?,?,?,?,?,?,?)""",
            (
                session_id,
                device["household_id"],
                device["id"],
                content["contentVersion"],
                now,
                json.dumps(tasks, ensure_ascii=False),
                body.gameId,
                json.dumps(game_settings),
            ),
        )
        revision = db.execute(
            "UPDATE household SET revision=revision+1 WHERE id=? RETURNING revision",
            (device["household_id"],),
        ).fetchone()["revision"]
    return {
        "id": session_id,
        "lessonId": lesson["id"],
        "gameId": body.gameId,
        "gameSettings": game_settings,
        "contentVersion": content["contentVersion"],
        "startedAt": now,
        "tasks": tasks,
        "audioAvailable": any(task["exercise"].get("audioRef") in audio_ids for task in tasks),
        "revision": revision,
    }


@router.get("/sessions/current")
def current_session(device: dict = Depends(paired)) -> dict | None:
    with connect() as db:
        row = db.execute(
            """SELECT * FROM sessions WHERE household_id=? AND status='active'
               ORDER BY started_at DESC LIMIT 1""",
            (device["household_id"],),
        ).fetchone()
        if not row:
            return None
        attempts = db.execute(
            """SELECT i.id AS instance_id,a.id AS attempt_id,a.exercise_id,a.answer_json,
                      a.first_try_correct,a.hint_used,a.clock_pending FROM exercise_instances i
               LEFT JOIN attempts a ON a.instance_id=i.id WHERE i.session_id=?""",
            (row["id"],),
        ).fetchall()
        skipped = db.execute(
            """SELECT s.instance_id,s.skipped_at FROM skipped_instances s
               JOIN exercise_instances i ON i.id=s.instance_id
               WHERE s.household_id=? AND i.session_id=?""",
            (device["household_id"], row["id"]),
        ).fetchall()
        receipts = db.execute(
            "SELECT result_json FROM request_receipts WHERE household_id=?",
            (device["household_id"],),
        ).fetchall()
        mastery = _mastery(db, device["household_id"])
    result_by_attempt = {
        json.loads(item["result_json"]).get("attemptId"): json.loads(item["result_json"])
        for item in receipts
    }
    results = {
        item["instance_id"]: result_by_attempt[item["attempt_id"]]
        for item in attempts
        if item["attempt_id"] in result_by_attempt
    }
    exercises = exercises_for_revision(row["content_version"])
    for item in attempts:
        if item["attempt_id"] and item["instance_id"] not in results:
            exercise = exercises[item["exercise_id"]]
            answer_option_id = json.loads(item["answer_json"])["optionId"]
            results[item["instance_id"]] = {
                "attemptId": item["attempt_id"],
                "instanceId": item["instance_id"],
                "requestId": f"restored-{item['attempt_id']}",
                "answerOptionId": answer_option_id,
                "correct": answer_option_id == exercise.get("answer", {}).get("optionId"),
                "firstTryCorrect": bool(item["first_try_correct"]),
                "hintUsed": bool(item["hint_used"]),
                "clockPending": bool(item["clock_pending"]),
                "mastery": mastery.get(exercise["primaryKnowledgeId"], {}),
                "restored": True,
            }
    for item in skipped:
        results[item["instance_id"]] = {
            "instanceId": item["instance_id"],
            "skipped": True,
            "skippedAt": item["skipped_at"],
        }
    tasks = [
        {**task, "exercise": _public_exercise(task["exercise"])}
        for task in json.loads(row["tasks_json"])
    ]
    content = load_curriculum()
    audio_ids = _available_standard_audio(content)
    return {
        "id": row["id"],
        "gameId": row["game_id"],
        "gameSettings": json.loads(row["game_settings_json"]),
        "status": row["status"],
        "contentVersion": row["content_version"],
        "startedAt": row["started_at"],
        "reviewKnowledgeId": row["review_knowledge_id"],
        "lessonId": tasks[0]["exercise"]["lessonId"]
        if tasks and not row["review_knowledge_id"]
        else None,
        "tasks": tasks,
        "results": results,
        "audioAvailable": any(task["exercise"].get("audioRef") in audio_ids for task in tasks),
    }


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: str, device: dict = Depends(mutable)) -> dict:
    with transaction() as db:
        session = db.execute(
            "SELECT id,status,review_knowledge_id FROM sessions WHERE id=? AND household_id=?",
            (session_id, device["household_id"]),
        ).fetchone()
        if not session:
            raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND"})
        total = db.execute(
            "SELECT COUNT(*) FROM exercise_instances WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        complete = (
            total > 0
            and db.execute(
                """SELECT COUNT(*) FROM exercise_instances i
               LEFT JOIN attempts a ON a.instance_id=i.id
               LEFT JOIN skipped_instances s ON s.instance_id=i.id
               WHERE i.session_id=? AND (a.id IS NOT NULL OR s.instance_id IS NOT NULL)""",
                (session_id,),
            ).fetchone()[0]
            == total
        )
        cursor = db.execute(
            "UPDATE sessions SET status='finished' WHERE id=? AND household_id=? "
            "AND status='active'",
            (session_id, device["household_id"]),
        )
        if cursor.rowcount:
            if session["review_knowledge_id"]:
                review_id = session["review_knowledge_id"]
                rows = db.execute(
                    """SELECT a.first_try_correct,a.due_credit,a.business_date,i.exercise_id
                       FROM exercise_instances i JOIN attempts a ON a.instance_id=i.id
                       WHERE i.session_id=? ORDER BY i.id""",
                    (session_id,),
                ).fetchall()
                skipped_count = db.execute(
                    """SELECT COUNT(*) FROM skipped_instances s
                       JOIN exercise_instances i ON i.id=s.instance_id WHERE i.session_id=?""",
                    (session_id,),
                ).fetchone()[0]
                if (
                    len(rows) == 2
                    and not skipped_count
                    and len({r["exercise_id"] for r in rows}) == 2
                ):
                    completed_day = business_date(datetime.now(UTC))
                    passed = all(r["first_try_correct"] and r["due_credit"] for r in rows)
                    mastery = _mastery(db, device["household_id"]).get(review_id, {})
                    passed = passed and mastery.get("status") == "mastered"
                    plan = db.execute(
                        """SELECT stage,updated_at FROM review_plans
                           WHERE household_id=? AND knowledge_id=?""",
                        (device["household_id"], review_id),
                    ).fetchone()
                    if plan:
                        last_update = datetime.fromisoformat(plan["updated_at"])
                        if business_date(last_update) < completed_day:
                            stage, due = next_review(plan["stage"], completed_day, passed)
                            db.execute(
                                """UPDATE review_plans SET stage=?,due_date=?,updated_at=?
                                   WHERE household_id=? AND knowledge_id=?""",
                                (
                                    stage,
                                    due.isoformat(),
                                    now_iso(),
                                    device["household_id"],
                                    review_id,
                                ),
                            )
            if complete:
                db.execute(
                    """UPDATE household SET rounds_since_break=MIN(2,rounds_since_break+1),
                       revision=revision+1 WHERE id=?""",
                    (device["household_id"],),
                )
            else:
                db.execute(
                    "UPDATE household SET revision=revision+1 WHERE id=?",
                    (device["household_id"],),
                )
        rounds = db.execute(
            "SELECT rounds_since_break FROM household WHERE id=?",
            (device["household_id"],),
        ).fetchone()["rounds_since_break"]
    return {"finished": True, "completedRound": complete, "breakRequired": rounds >= 2}


@router.post("/rest/complete")
def complete_rest(device: dict = Depends(mutable)) -> dict:
    with transaction() as db:
        household = db.execute(
            "SELECT rounds_since_break FROM household WHERE id=?",
            (device["household_id"],),
        ).fetchone()
        completed = household["rounds_since_break"] >= 2
        if completed:
            db.execute(
                "UPDATE household SET rounds_since_break=0,revision=revision+1 WHERE id=?",
                (device["household_id"],),
            )
    return {"breakRequired": False, "breakCompleted": completed}
