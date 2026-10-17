"""HTTP endpoints for attempts."""

import json
import secrets
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.api_dependencies import mutable, paired
from server.content_history import exercises_for_revision
from server.domain import (
    business_date,
)
from server.learning_audio import narration_scripts
from server.learning_state import _mastery
from server.storage import connect, now_iso, transaction

router = APIRouter()


@router.post("/instances/{instance_id}/hint")
def mark_hint(instance_id: str, device: dict = Depends(mutable)) -> dict:
    with transaction() as db:
        row = db.execute(
            "SELECT * FROM exercise_instances WHERE id=? AND household_id=?",
            (instance_id, device["household_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, detail={"code": "INSTANCE_NOT_FOUND"})
        if row["answered_at"]:
            raise HTTPException(409, detail={"code": "INSTANCE_ALREADY_ANSWERED"})
        skipped = db.execute(
            "SELECT 1 FROM skipped_instances WHERE instance_id=?", (instance_id,)
        ).fetchone()
        if skipped:
            raise HTTPException(409, detail={"code": "INSTANCE_ALREADY_SKIPPED"})
        changed = not row["hint_used"]
        db.execute("UPDATE exercise_instances SET hint_used=1 WHERE id=?", (instance_id,))
        if changed:
            db.execute(
                "UPDATE household SET revision=revision+1 WHERE id=?",
                (device["household_id"],),
            )
    q = exercises_for_revision(row["content_version"])[row["exercise_id"]]
    return {
        "hintUsed": True,
        "answer": q["answer"],
        "explanation": narration_scripts()[f"hint-{q['id']}"],
    }


@router.post("/instances/{instance_id}/skip")
def skip_instance(instance_id: str, device: dict = Depends(mutable)) -> dict:
    with transaction() as db:
        instance = db.execute(
            "SELECT * FROM exercise_instances WHERE id=? AND household_id=?",
            (instance_id, device["household_id"]),
        ).fetchone()
        if not instance:
            raise HTTPException(404, detail={"code": "INSTANCE_NOT_FOUND"})
        if instance["answered_at"]:
            raise HTTPException(409, detail={"code": "INSTANCE_ALREADY_ANSWERED"})
        session = db.execute(
            "SELECT status FROM sessions WHERE id=? AND household_id=?",
            (instance["session_id"], device["household_id"]),
        ).fetchone()
        if not session or session["status"] != "active":
            raise HTTPException(409, detail={"code": "SESSION_NOT_ACTIVE"})
        skipped_at = now_iso()
        inserted = db.execute(
            """INSERT OR IGNORE INTO skipped_instances
               (instance_id,household_id,skipped_at) VALUES(?,?,?)""",
            (instance_id, device["household_id"], skipped_at),
        ).rowcount
        if inserted:
            db.execute(
                "UPDATE household SET revision=revision+1 WHERE id=?",
                (device["household_id"],),
            )
        skipped_at = db.execute(
            "SELECT skipped_at FROM skipped_instances WHERE instance_id=?", (instance_id,)
        ).fetchone()["skipped_at"]
    return {"instanceId": instance_id, "skipped": True, "skippedAt": skipped_at}


class SubmitAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=8, max_length=80)
    answerOptionId: str = Field(min_length=1, max_length=40)


@router.post("/instances/{instance_id}/answer")
def submit_answer(instance_id: str, body: SubmitAnswer, device: dict = Depends(mutable)) -> dict:
    with transaction() as db:
        receipt = db.execute(
            "SELECT result_json FROM request_receipts WHERE request_id=? AND household_id=?",
            (body.requestId, device["household_id"]),
        ).fetchone()
        if receipt:
            previous = json.loads(receipt["result_json"])
            if (
                previous.get("instanceId") != instance_id
                or previous.get("answerOptionId") != body.answerOptionId
            ):
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_KEY_REUSED"})
            return previous
        instance = db.execute(
            "SELECT * FROM exercise_instances WHERE id=? AND household_id=?",
            (instance_id, device["household_id"]),
        ).fetchone()
        if not instance:
            raise HTTPException(404, detail={"code": "INSTANCE_NOT_FOUND"})
        if instance["answered_at"]:
            raise HTTPException(409, detail={"code": "INSTANCE_ALREADY_ANSWERED"})
        if db.execute(
            "SELECT 1 FROM skipped_instances WHERE instance_id=?", (instance_id,)
        ).fetchone():
            raise HTTPException(409, detail={"code": "INSTANCE_ALREADY_SKIPPED"})
        question = exercises_for_revision(instance["content_version"]).get(instance["exercise_id"])
        if not question or question["type"] == "read-aloud":
            raise HTTPException(409, detail={"code": "EXERCISE_NOT_READY"})
        option_ids = {option["id"] for option in question["options"]}
        if body.answerOptionId not in option_ids:
            raise HTTPException(422, detail={"code": "OPTION_NOT_VALID"})
        now = datetime.now(UTC)
        day = business_date(now).isoformat()
        prior = db.execute(
            """SELECT 1 FROM attempts WHERE household_id=? AND knowledge_id=? AND exercise_id=?
               AND business_date=? AND due_credit=1 LIMIT 1""",
            (device["household_id"], question["primaryKnowledgeId"], question["id"], day),
        ).fetchone()
        clock_pending = bool(device["clock_skew_detected"])
        credit = int(prior is None and not clock_pending)
        first_correct = int(
            body.answerOptionId == question["answer"].get("optionId") and not instance["hint_used"]
        )
        attempt_id = secrets.token_urlsafe(18)
        db.execute(
            "UPDATE exercise_instances SET answered_at=? WHERE id=?",
            (now.isoformat(timespec="milliseconds"), instance_id),
        )
        db.execute(
            """INSERT INTO attempts(
               id,household_id,device_id,instance_id,exercise_id,knowledge_id,mode,
               first_try_correct,hint_used,due_credit,occurred_at,business_date,answer_json,
               clock_pending) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt_id,
                device["household_id"],
                device["id"],
                instance_id,
                question["id"],
                question["primaryKnowledgeId"],
                question["type"],
                first_correct,
                instance["hint_used"],
                credit,
                now.isoformat(timespec="milliseconds"),
                day,
                json.dumps({"optionId": body.answerOptionId}),
                int(clock_pending),
            ),
        )
        state = _mastery(db, device["household_id"])[question["primaryKnowledgeId"]]
        if state["status"] == "mastered":
            existing = db.execute(
                "SELECT 1 FROM review_plans WHERE household_id=? AND knowledge_id=?",
                (device["household_id"], question["primaryKnowledgeId"]),
            ).fetchone()
            if not existing:
                due = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
                db.execute(
                    "INSERT INTO review_plans(household_id,knowledge_id,stage,due_date,updated_at) "
                    "VALUES(?,?,0,?,?)",
                    (device["household_id"], question["primaryKnowledgeId"], due, now_iso()),
                )
        revision = db.execute(
            "UPDATE household SET revision=revision+1 WHERE id=? RETURNING revision",
            (device["household_id"],),
        ).fetchone()["revision"]
        result = {
            "attemptId": attempt_id,
            "requestId": body.requestId,
            "instanceId": instance_id,
            "answerOptionId": body.answerOptionId,
            "correctOptionId": question["answer"].get("optionId"),
            "correct": body.answerOptionId == question["answer"].get("optionId"),
            "firstTryCorrect": bool(first_correct),
            "hintUsed": bool(instance["hint_used"]),
            "creditedForMastery": bool(credit),
            "clockPending": clock_pending,
            "mastery": state,
            "revision": revision,
        }
        explanation_id = f"hint-{question['id']}"
        explanation = narration_scripts().get(explanation_id)
        if explanation:
            result.update(explanation=explanation, explanationAudioId=explanation_id)
        db.execute(
            """INSERT INTO request_receipts(request_id,household_id,status,result_json,created_at)
               VALUES(?,?,?,?,?)""",
            (body.requestId, device["household_id"], "complete", json.dumps(result), now_iso()),
        )
    return result


@router.get("/attempts/{request_id}")
def read_attempt(request_id: str, device: dict = Depends(paired)) -> dict:
    with connect() as db:
        row = db.execute(
            "SELECT result_json FROM request_receipts WHERE request_id=? AND household_id=?",
            (request_id, device["household_id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "ATTEMPT_NOT_FOUND"})
    return json.loads(row["result_json"])
