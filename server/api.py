"""Same-origin home API. Voice assessment remains unavailable until SPEC-000 passes."""

import hashlib
import ipaddress
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from server.content import load_curriculum, map_by_id
from server.domain import Event, calculate_mastery
from server.storage import connect, now_iso, public_profile, transaction

router = APIRouter(prefix="/api/v1")
local_router = APIRouter(prefix="/api/v1/local")
COOKIE = "lp_session"
CSRF_COOKIE = "lp_csrf"
SHANGHAI = ZoneInfo("Asia/Shanghai")
_failures: dict[str, deque[float]] = defaultdict(deque)
_failures_lock = threading.Lock()


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_local(request: Request) -> bool:
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    host = request.headers.get("host", "").lower()
    forwarded_host = request.headers.get("x-lp-forwarded-host")
    if forwarded_host and _is_local(request):
        host = forwarded_host.lower()
    if origin and urlparse(origin).netloc.lower() != host:
        raise HTTPException(403, detail={"code": "ORIGIN_REJECTED"})


def _get_device(raw: str | None) -> dict:
    if not raw:
        raise HTTPException(401, detail={"code": "PAIRING_REQUIRED"})
    with connect() as db:
        row = db.execute(
            """SELECT d.*,h.revision,h.content_version,h.selected_lesson_id,h.sound_enabled
               FROM devices d JOIN household h ON h.id=d.household_id
               WHERE d.token_hash=? AND d.revoked_at IS NULL""",
            (_hash(raw),),
        ).fetchone()
    if not row:
        raise HTTPException(401, detail={"code": "SESSION_EXPIRED"})
    created = datetime.fromisoformat(row["created_at"])
    if created + timedelta(days=30) <= datetime.now(UTC):
        raise HTTPException(401, detail={"code": "SESSION_EXPIRED"})
    return dict(row)


def paired(lp_session: str | None = Cookie(default=None)) -> dict:
    return _get_device(lp_session)


def mutable(
    request: Request,
    lp_session: str | None = Cookie(default=None),
    lp_csrf: str | None = Cookie(default=None),
    x_lp_csrf: str | None = Header(default=None),
) -> dict:
    _check_origin(request)
    device = _get_device(lp_session)
    if not lp_csrf:
        raise HTTPException(403, detail={"code": "CSRF_COOKIE_MISSING"})
    if not x_lp_csrf:
        raise HTTPException(403, detail={"code": "CSRF_HEADER_MISSING"})
    if not secrets.compare_digest(lp_csrf, x_lp_csrf):
        raise HTTPException(403, detail={"code": "CSRF_TOKEN_MISMATCH"})
    if not secrets.compare_digest(_hash(lp_csrf), device["csrf_hash"]):
        raise HTTPException(403, detail={"code": "CSRF_DEVICE_MISMATCH"})
    return device


def parent(device: dict = Depends(mutable)) -> dict:
    return _require_parent(device)


def parent_read(device: dict = Depends(paired)) -> dict:
    return _require_parent(device)


def _require_parent(device: dict) -> dict:
    if not device["is_parent"]:
        raise HTTPException(403, detail={"code": "PARENT_AUTH_REQUIRED"})
    return device


def _create_pairing_code() -> dict:
    code = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(8))
    with transaction() as db:
        db.execute(
            "INSERT INTO pairing_codes(code_hash,expires_at) VALUES(?,?)",
            (_hash(code), time.time() + 300),
        )
        db.execute(
            "DELETE FROM pairing_codes WHERE expires_at<? OR used_at IS NOT NULL", (time.time(),)
        )
    return {"code": code, "expiresInSeconds": 300}


@local_router.post("/pairing-code")
def local_pairing_code(request: Request) -> dict:
    if not _is_local(request):
        raise HTTPException(403, detail={"code": "LOCAL_HOST_REQUIRED"})
    return _create_pairing_code()


@router.post("/pairing-codes")
def parent_pairing_code(device: dict = Depends(parent)) -> dict:
    return _create_pairing_code()


class PairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=8, max_length=12, pattern=r"^[0-9A-Z]+$")
    label: str = Field(default="家庭设备", min_length=1, max_length=30)


@router.post("/pair")
def pair(body: PairInput, request: Request, response: Response) -> dict:
    _check_origin(request)
    address = request.client.host if request.client else "unknown"
    now = time.time()
    with _failures_lock:
        queue = _failures[address]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= 5:
            raise HTTPException(429, detail={"code": "PAIRING_COOLDOWN", "retryAfter": 60})

    with transaction() as db:
        record = db.execute(
            "SELECT * FROM pairing_codes WHERE code_hash=? AND used_at IS NULL AND expires_at>=?",
            (_hash(body.code), now),
        ).fetchone()
        if not record:
            with _failures_lock:
                _failures[address].append(now)
            raise HTTPException(401, detail={"code": "PAIRING_CODE_INVALID"})
        household = db.execute("SELECT * FROM household ORDER BY created_at LIMIT 1").fetchone()
        if not household:
            raise HTTPException(503, detail={"code": "HOUSEHOLD_NOT_READY"})
        already_parent = bool(
            db.execute(
                "SELECT 1 FROM devices WHERE household_id=? AND is_parent=1 AND revoked_at IS NULL",
                (household["id"],),
            ).fetchone()
        )
        session_value = secrets.token_urlsafe(36)
        csrf = secrets.token_urlsafe(24)
        device_id = secrets.token_urlsafe(14)
        db.execute(
            """INSERT INTO devices(id,household_id,token_hash,csrf_hash,label,is_parent,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                device_id,
                household["id"],
                _hash(session_value),
                _hash(csrf),
                body.label.strip(),
                int(not already_parent),
                now_iso(),
            ),
        )
        db.execute(
            "UPDATE pairing_codes SET used_at=? WHERE code_hash=?", (now_iso(), _hash(body.code))
        )

    secure = request.url.scheme == "https"
    for name, value, http_only in [(COOKIE, session_value, True), (CSRF_COOKIE, csrf, False)]:
        response.set_cookie(
            name,
            value,
            httponly=http_only,
            secure=secure,
            samesite="strict",
            max_age=2592000,
            path="/",
        )
    with _failures_lock:
        _failures[address].clear()
    return {"paired": True, "isParent": not already_parent, "deviceId": device_id}


@router.delete("/session", status_code=204)
def unpair(request: Request, device: dict = Depends(mutable)) -> Response:
    with transaction() as db:
        db.execute("UPDATE devices SET revoked_at=? WHERE id=?", (now_iso(), device["id"]))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@router.get("/devices")
def list_devices(device: dict = Depends(parent_read)) -> dict:
    with connect() as db:
        rows = db.execute(
            """SELECT id,label,created_at FROM devices
               WHERE household_id=? AND revoked_at IS NULL ORDER BY created_at,id""",
            (device["household_id"],),
        ).fetchall()
    return {
        "devices": [
            {
                "id": row["id"],
                "label": row["label"],
                "createdAt": row["created_at"],
                "current": row["id"] == device["id"],
            }
            for row in rows
        ]
    }


@router.delete("/devices/{device_id}")
def revoke_device(device_id: str, device: dict = Depends(parent)) -> dict:
    if device_id == device["id"]:
        raise HTTPException(409, detail={"code": "CANNOT_REVOKE_CURRENT_DEVICE"})
    with transaction() as db:
        cursor = db.execute(
            """UPDATE devices SET revoked_at=? WHERE id=? AND household_id=?
               AND revoked_at IS NULL""",
            (now_iso(), device_id, device["household_id"]),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, detail={"code": "DEVICE_NOT_FOUND"})
        revision = db.execute(
            "UPDATE household SET revision=revision+1 WHERE id=? RETURNING revision",
            (device["household_id"],),
        ).fetchone()["revision"]
    return {"revoked": True, "revision": revision}


@router.get("/health")
def health() -> dict:
    data = load_curriculum()
    return {"status": "ok", "contentVersion": data["contentVersion"], "storage": "sqlite"}


@router.get("/capabilities")
def capabilities() -> dict:
    return {
        "assessment": {"available": False, "reason": "pending-local-poc"},
        "audio": {"available": False, "reason": "assets-not-recorded"},
        "contentReview": "draft",
        "externalAudioTransfer": False,
    }


@router.get("/bootstrap")
def bootstrap(request: Request, lp_session: str | None = Cookie(default=None)) -> dict:
    if not lp_session:
        return {
            "paired": False,
            "isLocalHost": _is_local(request),
            "contentVersion": load_curriculum()["contentVersion"],
        }
    device = _get_device(lp_session)
    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE household_id=?", (device["household_id"],)
        ).fetchone()[0]
    return {
        "paired": True,
        "device": {
            "id": device["id"],
            "label": device["label"],
            "isParent": bool(device["is_parent"]),
        },
        "profile": public_profile(device),
        "attemptCount": count,
    }


@router.get("/curriculum")
def curriculum(device: dict = Depends(paired)) -> dict:
    data = load_curriculum()
    return {
        key: data[key]
        for key in (
            "id",
            "contentVersion",
            "edition",
            "inventory",
            "lessons",
            "knowledgeItems",
            "exercises",
            "readingTargets",
            "audioRequirements",
            "reviewStatus",
        )
    }


class LessonChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessonId: str
    expectedRevision: int = Field(ge=0)


@router.put("/household/current-lesson")
def select_lesson(body: LessonChoice, device: dict = Depends(parent)) -> dict:
    if body.lessonId not in map_by_id("lessons"):
        raise HTTPException(404, detail={"code": "LESSON_NOT_FOUND"})
    with transaction() as db:
        household = db.execute(
            "SELECT * FROM household WHERE id=?", (device["household_id"],)
        ).fetchone()
        if household["revision"] != body.expectedRevision:
            raise HTTPException(409, detail={"code": "REVISION_CONFLICT"})
        db.execute(
            "UPDATE household SET selected_lesson_id=?,revision=revision+1 WHERE id=?",
            (body.lessonId, device["household_id"]),
        )
        household = db.execute(
            "SELECT * FROM household WHERE id=?", (device["household_id"],)
        ).fetchone()
    return public_profile(household)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    soundEnabled: bool


@router.put("/household/settings")
def settings(body: Settings, device: dict = Depends(parent)) -> dict:
    with transaction() as db:
        db.execute(
            "UPDATE household SET sound_enabled=?,revision=revision+1 WHERE id=?",
            (int(body.soundEnabled), device["household_id"]),
        )
        row = db.execute("SELECT * FROM household WHERE id=?", (device["household_id"],)).fetchone()
    return public_profile(row)


@router.get("/profiles/export")
def export_profile(device: dict = Depends(parent_read)) -> dict:
    with connect() as db:
        household = db.execute(
            "SELECT * FROM household WHERE id=?", (device["household_id"],)
        ).fetchone()
        attempts = db.execute(
            """SELECT id,exercise_id,knowledge_id,mode,first_try_correct,hint_used,due_credit,
               occurred_at,business_date,answer_json FROM attempts WHERE household_id=?
               ORDER BY occurred_at,id""",
            (device["household_id"],),
        ).fetchall()
        reviews = db.execute(
            "SELECT knowledge_id,stage,due_date,updated_at FROM review_plans WHERE household_id=?",
            (device["household_id"],),
        ).fetchall()
        sessions = db.execute(
            """SELECT id,content_version AS contentVersion,started_at AS startedAt,status
               FROM sessions WHERE household_id=? ORDER BY started_at,id""",
            (device["household_id"],),
        ).fetchall()
        skipped = db.execute(
            """SELECT s.instance_id AS instanceId,i.session_id AS sessionId,
               s.skipped_at AS skippedAt FROM skipped_instances s
               JOIN exercise_instances i ON i.id=s.instance_id
               WHERE s.household_id=? ORDER BY s.skipped_at,s.instance_id""",
            (device["household_id"],),
        ).fetchall()
    return {
        "schemaVersion": 1,
        "exportedAt": now_iso(),
        "profile": public_profile(household),
        "attempts": [dict(row) for row in attempts],
        "sessions": [dict(row) for row in sessions],
        "skippedInstances": [dict(row) for row in skipped],
        "reviewPlans": [dict(row) for row in reviews],
        "note": "不包含会话凭据、设备信息或录音。",
    }


class DeleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=1, max_length=40)


@router.delete("/profiles/data")
def delete_profile_data(body: DeleteData, device: dict = Depends(parent)) -> dict:
    if body.confirmation != "删除我的学习记录":
        raise HTTPException(422, detail={"code": "CONFIRMATION_REQUIRED"})
    with transaction() as db:
        household_id = device["household_id"]
        db.execute("DELETE FROM request_receipts WHERE household_id=?", (household_id,))
        db.execute("DELETE FROM attempts WHERE household_id=?", (household_id,))
        db.execute("DELETE FROM exercise_instances WHERE household_id=?", (household_id,))
        db.execute("DELETE FROM sessions WHERE household_id=?", (household_id,))
        db.execute("DELETE FROM review_plans WHERE household_id=?", (household_id,))
        db.execute(
            "UPDATE household SET selected_lesson_id='lesson-01',revision=revision+1 WHERE id=?",
            (household_id,),
        )
        row = db.execute("SELECT * FROM household WHERE id=?", (household_id,)).fetchone()
    return {"deleted": True, "profile": public_profile(row)}


class StartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessonId: str | None = None


@router.post("/sessions")
def start_session(body: StartSession, device: dict = Depends(mutable)) -> dict:
    content = load_curriculum()
    lessons = map_by_id("lessons")
    requested_id = body.lessonId or device["selected_lesson_id"]
    if requested_id not in lessons:
        raise HTTPException(404, detail={"code": "LESSON_NOT_FOUND"})
    current_order = lessons[device["selected_lesson_id"]]["order"]
    lesson = lessons[requested_id]
    if lesson["order"] > current_order:
        raise HTTPException(403, detail={"code": "LESSON_NOT_UNLOCKED"})
    by_id = map_by_id("exercises")
    # Do not expose listening tasks until approved audio assets exist. Browser
    # speech synthesis is not a substitute for reviewed Mandarin exemplars.
    questions = [
        by_id[qid]
        for qid in lesson["exerciseIds"]
        if by_id[qid]["type"] in {"symbol-choice", "tone-choice", "blend-choice"}
    ]
    if not questions:
        raise HTTPException(409, detail={"code": "LESSON_NOT_READY"})
    question_set = questions[:6]
    if not question_set:
        raise HTTPException(409, detail={"code": "LESSON_NOT_READY"})
    session_id = secrets.token_urlsafe(18)
    now = now_iso()
    tasks = []
    with transaction() as db:
        for q in question_set:
            instance_id = secrets.token_urlsafe(18)
            db.execute(
                """INSERT INTO exercise_instances(
                   id,household_id,exercise_id,lesson_id,content_version,
                   created_at,session_id) VALUES(?,?,?,?,?,?,?)""",
                (
                    instance_id,
                    device["household_id"],
                    q["id"],
                    lesson["id"],
                    content["contentVersion"],
                    now,
                    session_id,
                ),
            )
            tasks.append({"instanceId": instance_id, "exercise": q})
        db.execute(
            """INSERT INTO sessions(id,household_id,device_id,content_version,started_at,tasks_json)
               VALUES(?,?,?,?,?,?)""",
            (
                session_id,
                device["household_id"],
                device["id"],
                content["contentVersion"],
                now,
                json.dumps(tasks, ensure_ascii=False),
            ),
        )
    return {
        "id": session_id,
        "lessonId": lesson["id"],
        "contentVersion": content["contentVersion"],
        "startedAt": now,
        "tasks": tasks,
        "draftContent": content["reviewStatus"] != "approved",
        "audioAvailable": False,
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
            """SELECT i.id AS instance_id,a.id AS attempt_id FROM exercise_instances i
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
    result_by_attempt = {
        json.loads(item["result_json"]).get("attemptId"): json.loads(item["result_json"])
        for item in receipts
    }
    results = {
        item["instance_id"]: result_by_attempt[item["attempt_id"]]
        for item in attempts
        if item["attempt_id"] in result_by_attempt
    }
    for item in skipped:
        results[item["instance_id"]] = {
            "instanceId": item["instance_id"],
            "skipped": True,
            "skippedAt": item["skipped_at"],
        }
    return {**dict(row), "tasks": json.loads(row["tasks_json"]), "results": results}


@router.post("/sessions/{session_id}/finish", status_code=204)
def finish_session(session_id: str, device: dict = Depends(mutable)) -> Response:
    with transaction() as db:
        cursor = db.execute(
            "UPDATE sessions SET status='finished' WHERE id=? AND household_id=? "
            "AND status='active'",
            (session_id, device["household_id"]),
        )
        if cursor.rowcount == 0:
            row = db.execute(
                "SELECT id FROM sessions WHERE id=? AND household_id=?",
                (session_id, device["household_id"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND"})
    return Response(status_code=204)


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
        db.execute("UPDATE exercise_instances SET hint_used=1 WHERE id=?", (instance_id,))
    q = map_by_id("exercises")[row["exercise_id"]]
    return {
        "hintUsed": True,
        "answer": q["answer"],
        "explanation": q.get("hint") or "先看清问题，再观察卡片上的拼音。",
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
        db.execute(
            """INSERT OR IGNORE INTO skipped_instances
               (instance_id,household_id,skipped_at) VALUES(?,?,?)""",
            (instance_id, device["household_id"], skipped_at),
        )
        skipped_at = db.execute(
            "SELECT skipped_at FROM skipped_instances WHERE instance_id=?", (instance_id,)
        ).fetchone()["skipped_at"]
    return {"instanceId": instance_id, "skipped": True, "skippedAt": skipped_at}


class SubmitAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=8, max_length=80)
    answerOptionId: str = Field(min_length=1, max_length=40)


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
        question = map_by_id("exercises").get(instance["exercise_id"])
        if not question or question["type"] == "read-aloud":
            raise HTTPException(409, detail={"code": "EXERCISE_NOT_READY"})
        option_ids = {option["id"] for option in question["options"]}
        if body.answerOptionId not in option_ids:
            raise HTTPException(422, detail={"code": "OPTION_NOT_VALID"})
        now = datetime.now(UTC)
        day = now.astimezone(SHANGHAI).date().isoformat()
        prior = db.execute(
            """SELECT 1 FROM attempts WHERE household_id=? AND knowledge_id=? AND exercise_id=?
               AND business_date=? AND due_credit=1 LIMIT 1""",
            (device["household_id"], question["primaryKnowledgeId"], question["id"], day),
        ).fetchone()
        credit = int(prior is None)
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
               first_try_correct,hint_used,due_credit,occurred_at,business_date,answer_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            "correct": body.answerOptionId == question["answer"].get("optionId"),
            "firstTryCorrect": bool(first_correct),
            "hintUsed": bool(instance["hint_used"]),
            "creditedForMastery": bool(credit),
            "mastery": state,
            "revision": revision,
        }
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


@router.get("/profiles/progress")
def progress(device: dict = Depends(paired)) -> dict:
    with connect() as db:
        mastery = _mastery(db, device["household_id"])
        attempts = db.execute(
            """SELECT id,exercise_id,knowledge_id,mode,first_try_correct,hint_used,due_credit,
               occurred_at,business_date FROM attempts WHERE household_id=?
               ORDER BY occurred_at DESC,id DESC LIMIT 1000""",
            (device["household_id"],),
        ).fetchall()
        plans = db.execute(
            "SELECT knowledge_id,stage,due_date FROM review_plans WHERE household_id=?",
            (device["household_id"],),
        ).fetchall()
    by_knowledge = {row["knowledge_id"]: row for row in plans}
    today = datetime.now(UTC).astimezone(SHANGHAI).date()
    for key, value in mastery.items():
        plan = by_knowledge.get(key)
        due = plan["due_date"] if plan else None
        value["reviewDueDate"] = due
        value["reviewDue"] = bool(due and date.fromisoformat(due) <= today)
        value["reviewStage"] = plan["stage"] if plan else None
    return {
        "schemaVersion": 1,
        "contentVersion": device["content_version"],
        "profileId": device["household_id"],
        "revision": device["revision"],
        "selectedLessonId": device["selected_lesson_id"],
        "masteryRuleVersion": "mastery-v1",
        "mastery": list(mastery.values()),
        "attempts": [dict(row) for row in attempts],
    }


@router.post("/assessments", status_code=503)
def assessment_unavailable(response: Response, device: dict = Depends(mutable)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {
        "error": {
            "code": "ASSESSMENT_NOT_READY",
            "status": "unavailable",
            "externalAudioTransfer": False,
        }
    }


@router.get("/assessments/{request_id}")
def assessment_status(request_id: str, device: dict = Depends(paired)) -> dict:
    with connect() as db:
        row = db.execute(
            "SELECT summary_json FROM assessment_summaries WHERE request_id=? AND household_id=?",
            (request_id, device["household_id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "ASSESSMENT_NOT_FOUND"})
    return json.loads(row["summary_json"])
