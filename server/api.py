"""Same-origin home API. The first release does not expose voice recording or assessment."""

import hashlib
import ipaddress
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from server import source_audio
from server.content import load_curriculum, load_illustrations, load_writing, map_by_id
from server.content_history import compatible_revision, exercises_for_revision
from server.domain import (
    OPTION_ORDER_V1_PREFIX,
    Event,
    PracticeCompletion,
    business_date,
    calculate_mastery,
    next_review,
    order_options,
    plan_practice,
)
from server.learning_audio import learning_audio_response, learning_audio_status, narration_scripts
from server.playback_settings import GAP, gap_tenths
from server.storage import connect, now_iso, public_profile, transaction

router = APIRouter(prefix="/api/v1")
local_router = APIRouter(prefix="/api/v1/local")
COOKIE = "lp_session"
CSRF_COOKIE = "lp_csrf"
_failures: dict[str, deque[float]] = defaultdict(deque)
_failures_lock = threading.Lock()
_import_previews: dict[str, tuple[str, str, int, float, dict]] = {}
_import_previews_lock = threading.Lock()
IMPORT_MAX_BYTES = 1_048_576
IMPORT_MAX_ATTEMPTS = 50_000
IMPORT_PREVIEW_TTL = 300
IMPORT_MAX_ACTIVE_PREVIEWS = 8


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


def _get_device(raw: str | None, request: Request) -> dict:
    if not raw:
        raise HTTPException(401, detail={"code": "PAIRING_REQUIRED"})
    with connect() as db:
        row = db.execute(
            """SELECT d.*,h.id AS profile_id,h.revision,h.content_version,
                      h.selected_lesson_id,h.sound_enabled,h.reduced_motion,h.playback_gap_tenths,h.rounds_since_break,
                      h.last_observed_at,h.clock_skew_detected
               FROM devices d JOIN household h ON h.id=d.household_id
               WHERE d.token_hash=? AND d.revoked_at IS NULL""",
            (_hash(raw),),
        ).fetchone()
    if not row:
        raise HTTPException(401, detail={"code": "SESSION_EXPIRED"})
    created = datetime.fromisoformat(row["created_at"])
    if created + timedelta(days=30) <= datetime.now(UTC):
        raise HTTPException(401, detail={"code": "SESSION_EXPIRED"})
    observed_at = now_iso()
    suggested_model = unquote(request.headers.get("x-lp-device-model", "")[:1000]).strip()[:80]
    if any(ord(char) < 32 or ord(char) == 127 for char in suggested_model):
        suggested_model = ""
    with transaction() as db:
        db.execute(
            "UPDATE devices SET last_connected_at=?,model=COALESCE(NULLIF(model,''),NULLIF(?,'')) "
            "WHERE id=? AND revoked_at IS NULL",
            (observed_at, suggested_model, row["id"]),
        )
    return {**dict(row), "last_connected_at": observed_at}


def paired(request: Request, lp_session: str | None = Cookie(default=None)) -> dict:
    return _get_device(lp_session, request)


def _observe_clock(device: dict) -> bool:
    now = datetime.now(UTC)
    with transaction() as db:
        household = db.execute(
            "SELECT last_observed_at,clock_skew_detected FROM household WHERE id=?",
            (device["household_id"],),
        ).fetchone()
        last = (
            datetime.fromisoformat(household["last_observed_at"])
            if household["last_observed_at"]
            else None
        )
        skewed = last is not None and now < last - timedelta(minutes=5)
        previously_skewed = bool(household["clock_skew_detected"])
        if not skewed and (last is None or now > last):
            db.execute(
                "UPDATE household SET last_observed_at=? WHERE id=?",
                (now.isoformat(timespec="milliseconds"), device["household_id"]),
            )
        if skewed != previously_skewed:
            db.execute(
                "UPDATE household SET clock_skew_detected=?,revision=revision+1 WHERE id=?",
                (int(skewed), device["household_id"]),
            )
            device["revision"] += 1
    device["clock_skew_detected"] = int(skewed)
    return skewed


def mutable(
    request: Request,
    lp_session: str | None = Cookie(default=None),
    lp_csrf: str | None = Cookie(default=None),
    x_lp_csrf: str | None = Header(default=None),
) -> dict:
    _check_origin(request)
    device = _get_device(lp_session, request)
    if not lp_csrf:
        raise HTTPException(403, detail={"code": "CSRF_COOKIE_MISSING"})
    if not x_lp_csrf:
        raise HTTPException(403, detail={"code": "CSRF_HEADER_MISSING"})
    if not secrets.compare_digest(lp_csrf, x_lp_csrf):
        raise HTTPException(403, detail={"code": "CSRF_TOKEN_MISMATCH"})
    if not secrets.compare_digest(_hash(lp_csrf), device["csrf_hash"]):
        raise HTTPException(403, detail={"code": "CSRF_DEVICE_MISMATCH"})
    _observe_clock(device)
    return device


def parent(device: dict = Depends(mutable)) -> dict:
    return _require_parent(device)


def parent_read(device: dict = Depends(paired)) -> dict:
    return _require_parent(device)


def _require_parent(device: dict) -> dict:
    if not device["is_parent"]:
        raise HTTPException(403, detail={"code": "PARENT_AUTH_REQUIRED"})
    return device


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
    model: str = Field(default="", max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")


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
            """INSERT INTO devices(id,household_id,token_hash,csrf_hash,label,is_parent,
                                  created_at,model,pairing_code,last_connected_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                device_id,
                household["id"],
                _hash(session_value),
                _hash(csrf),
                body.label.strip(),
                int(not already_parent),
                now_iso(),
                body.model.strip() or None,
                body.code,
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
            """SELECT id,label,created_at,model,pairing_code,last_connected_at FROM devices
               WHERE household_id=? AND revoked_at IS NULL ORDER BY created_at,id""",
            (device["household_id"],),
        ).fetchall()
    return {
        "devices": [
            {
                "id": row["id"],
                "label": row["label"],
                "createdAt": row["created_at"],
                "model": row["model"],
                "pairingCode": row["pairing_code"],
                "lastConnectedAt": row["last_connected_at"],
                "current": row["id"] == device["id"],
            }
            for row in rows
        ]
    }


class DeviceModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model: str = Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")


@router.put("/devices/{device_id}")
def update_device_model(
    device_id: str, body: DeviceModelInput, device: dict = Depends(parent)
) -> dict:
    with transaction() as db:
        updated = db.execute(
            "UPDATE devices SET model=? WHERE id=? AND household_id=? AND revoked_at IS NULL",
            (body.model, device_id, device["household_id"]),
        )
        if not updated.rowcount:
            raise HTTPException(404, detail={"code": "DEVICE_NOT_FOUND"})
    return {"updated": True}


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
    content = load_curriculum()
    standard_ids = _available_standard_audio(content)
    learning = learning_audio_status()
    return {
        "audio": {
            "available": bool(standard_ids),
            "reason": "ready" if standard_ids else "assets-not-recorded",
            "availableIds": sorted(standard_ids),
        },
        "learningAudio": {
            "narrationReady": sum(learning["narration"].values()),
            "narrationTotal": len(learning["narration"]),
            "lessonRecordingsReady": sum(
                item["available"] for item in learning["lessons"].values()
            ),
        },
    }


@router.get("/bootstrap")
def bootstrap(request: Request, lp_session: str | None = Cookie(default=None)) -> dict:
    try:
        device = _get_device(lp_session, request)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return {
            "paired": False,
            "isLocalHost": _is_local(request),
            "contentVersion": load_curriculum()["contentVersion"],
        }
    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE household_id=?", (device["household_id"],)
        ).fetchone()[0]
    return {
        "paired": True,
        "isLocalHost": _is_local(request),
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
    result = {
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
        )
    }
    result["writing"] = load_writing()
    result["illustrations"] = load_illustrations()
    result["exercises"] = [_public_exercise(item) for item in data["exercises"]]
    audio_ids = _available_standard_audio(data)
    result["audioRequirements"] = [
        {
            **asset,
            "available": asset["id"] in audio_ids,
            "standardSource": source_audio.metadata(asset) if asset["id"] in audio_ids else None,
        }
        for asset in data["audioRequirements"]
    ]
    return result


@router.get("/audio/{asset_id}")
def get_audio_asset(
    asset_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    device: dict = Depends(paired),
) -> Response:
    matches = [a for a in load_curriculum()["audioRequirements"] if a["id"] == asset_id]
    if len(matches) != 1:
        raise HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})
    return source_audio.audio_response(matches[0], range_header)


@router.get("/learning-audio")
def get_learning_audio(device: dict = Depends(paired)) -> dict:
    return learning_audio_status()


@router.get("/voice/{asset_id}")
def get_learning_voice(
    asset_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    device: dict = Depends(paired),
) -> Response:
    return learning_audio_response(asset_id, range_header)


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
    reducedMotion: bool | None = None
    playbackGapSeconds: float | None = Field(
        default=None,
        strict=True,
        ge=GAP["minSeconds"],
        le=GAP["maxSeconds"],
        multiple_of=GAP["stepSeconds"],
        allow_inf_nan=False,
    )


@router.put("/household/settings")
def settings(body: Settings, device: dict = Depends(parent)) -> dict:
    with transaction() as db:
        db.execute(
            """UPDATE household SET sound_enabled=?,
               reduced_motion=COALESCE(?,reduced_motion),
               playback_gap_tenths=COALESCE(?,playback_gap_tenths),
               revision=revision+1 WHERE id=?""",
            (
                int(body.soundEnabled),
                int(body.reducedMotion) if body.reducedMotion is not None else None,
                gap_tenths(body.playbackGapSeconds)
                if body.playbackGapSeconds is not None
                else None,
                device["household_id"],
            ),
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
            """SELECT id,instance_id,exercise_id,knowledge_id,mode,first_try_correct,
               hint_used,due_credit,clock_pending,
               occurred_at,business_date,answer_json FROM attempts WHERE household_id=?
               ORDER BY occurred_at,id""",
            (device["household_id"],),
        ).fetchall()
        reviews = db.execute(
            "SELECT knowledge_id,stage,due_date,updated_at FROM review_plans WHERE household_id=?",
            (device["household_id"],),
        ).fetchall()
        sessions = db.execute(
            """SELECT id,content_version AS contentVersion,started_at AS startedAt,
                      status,tasks_json,
                      review_knowledge_id AS reviewKnowledgeId
               FROM sessions WHERE household_id=? ORDER BY started_at,id""",
            (device["household_id"],),
        ).fetchall()
        task_positions = {
            task["instanceId"]: index
            for session in sessions
            for index, task in enumerate(json.loads(session["tasks_json"]))
        }
        skipped = db.execute(
            """SELECT s.instance_id AS instanceId,i.session_id AS sessionId,
               s.skipped_at AS skippedAt FROM skipped_instances s
               JOIN exercise_instances i ON i.id=s.instance_id
               WHERE s.household_id=? ORDER BY s.skipped_at,s.instance_id""",
            (device["household_id"],),
        ).fetchall()
        instances = db.execute(
            """SELECT id,exercise_id,lesson_id,content_version,created_at,session_id,
               hint_used,answered_at FROM exercise_instances WHERE household_id=?
               ORDER BY created_at,id""",
            (device["household_id"],),
        ).fetchall()
        assessments = db.execute(
            """SELECT target_id,status,summary_json,engine_version,created_at
               FROM assessment_summaries WHERE household_id=? ORDER BY created_at,request_id""",
            (device["household_id"],),
        ).fetchall()
    return {
        "schemaVersion": 5,
        "contentVersion": household["content_version"],
        "masteryRuleVersion": 1,
        "exportedAt": now_iso(),
        "profile": public_profile(household),
        "attempts": [dict(row) for row in attempts],
        "sessions": [
            {
                key: row[key]
                for key in ("id", "contentVersion", "startedAt", "status", "reviewKnowledgeId")
            }
            for row in sessions
        ],
        "skippedInstances": [dict(row) for row in skipped],
        "reviewPlans": [dict(row) for row in reviews],
        "exerciseInstances": [
            {**dict(row), "position": task_positions.get(row["id"], -1)} for row in instances
        ],
        "assessmentSummaries": [
            {
                "targetId": row["target_id"],
                "status": row["status"],
                "summary": {
                    key: value
                    for key, value in json.loads(row["summary_json"]).items()
                    if key in {"score", "confidence", "dimensions", "reason", "calibrationVersion"}
                },
                "engineVersion": row["engine_version"],
                "createdAt": row["created_at"],
                "model": row["model"],
                "pairingCode": row["pairing_code"],
                "lastConnectedAt": row["last_connected_at"],
            }
            for row in assessments
        ],
        "note": "不包含会话凭据、设备信息或录音。",
    }


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise HTTPException(422, detail={"code": code})


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


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _parse_datetime(value: object, code: str) -> datetime:
    _require(isinstance(value, str), code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, detail={"code": code}) from None
    _require(parsed.tzinfo is not None, code)
    return parsed


def _validate_backup(value: object) -> dict:
    _require(isinstance(value, dict), "BACKUP_INVALID")
    migrated_from = value.get("schemaVersion")
    backup = (
        _migrate_v2_backup(value)
        if migrated_from == 2
        else _migrate_v3_backup(value)
        if migrated_from == 3
        else _migrate_v4_backup(value)
        if migrated_from == 4
        else value
    )
    required = {
        "schemaVersion",
        "contentVersion",
        "masteryRuleVersion",
        "exportedAt",
        "profile",
        "attempts",
        "sessions",
        "skippedInstances",
        "reviewPlans",
        "exerciseInstances",
        "assessmentSummaries",
        "note",
    }
    _require(set(backup) == required, "BACKUP_FIELDS_INVALID")
    _require(backup["schemaVersion"] == 5, "BACKUP_VERSION_UNSUPPORTED")
    curriculum = load_curriculum()
    _require(
        compatible_revision(backup["contentVersion"], curriculum["contentVersion"]),
        "CONTENT_VERSION_UNSUPPORTED",
    )
    _require(backup["masteryRuleVersion"] == 1, "MASTERY_RULE_VERSION_UNSUPPORTED")
    _parse_datetime(backup["exportedAt"], "BACKUP_TIME_INVALID")
    _require(isinstance(backup["note"], str) and len(backup["note"]) <= 160, "BACKUP_INVALID")

    profile = backup["profile"]
    _require(
        isinstance(profile, dict)
        and set(profile)
        == {
            "id",
            "selectedLessonId",
            "contentVersion",
            "revision",
            "roundsSinceBreak",
            "settings",
        },
        "BACKUP_PROFILE_INVALID",
    )
    _require(profile["contentVersion"] == backup["contentVersion"], "BACKUP_PROFILE_INVALID")
    _require(profile["selectedLessonId"] in map_by_id("lessons"), "BACKUP_REFERENCE_INVALID")
    _require(
        type(profile["revision"]) is int and profile["revision"] >= 0, "BACKUP_PROFILE_INVALID"
    )
    _require(
        type(profile["roundsSinceBreak"]) is int and 0 <= profile["roundsSinceBreak"] <= 2,
        "BACKUP_PROFILE_INVALID",
    )
    settings_value = profile["settings"]
    _require(
        isinstance(settings_value, dict)
        and set(settings_value)
        in (
            {"soundEnabled", "reducedMotion"},
            {"soundEnabled", "reducedMotion", "playbackGapSeconds"},
        ),
        "BACKUP_PROFILE_INVALID",
    )
    _require(
        all(type(settings_value[key]) is bool for key in ("soundEnabled", "reducedMotion")),
        "BACKUP_PROFILE_INVALID",
    )
    try:
        gap_tenths(settings_value.get("playbackGapSeconds", GAP["defaultSeconds"]))
    except ValueError:
        _require(False, "BACKUP_PROFILE_INVALID")

    arrays = (
        "attempts",
        "sessions",
        "skippedInstances",
        "reviewPlans",
        "exerciseInstances",
        "assessmentSummaries",
    )
    _require(all(isinstance(backup[key], list) for key in arrays), "BACKUP_INVALID")
    _require(len(backup["attempts"]) <= IMPORT_MAX_ATTEMPTS, "BACKUP_TOO_MANY_ATTEMPTS")
    sessions = {}
    for row in backup["sessions"]:
        _require(
            isinstance(row, dict)
            and set(row) == {"id", "contentVersion", "startedAt", "status", "reviewKnowledgeId"},
            "BACKUP_SESSION_INVALID",
        )
        _require(
            isinstance(row["id"], str) and 8 <= len(row["id"]) <= 100 and row["id"] not in sessions,
            "BACKUP_DUPLICATE_ID",
        )
        _require(
            compatible_revision(row["contentVersion"], backup["contentVersion"])
            and row["status"] in {"active", "finished"},
            "BACKUP_SESSION_INVALID",
        )
        _parse_datetime(row["startedAt"], "BACKUP_TIME_INVALID")
        _require(
            row["reviewKnowledgeId"] is None
            or row["reviewKnowledgeId"] in map_by_id("knowledgeItems"),
            "BACKUP_REFERENCE_INVALID",
        )
        sessions[row["id"]] = row

    exercises = map_by_id("exercises")
    lessons = map_by_id("lessons")
    instances = {}
    positions_by_session: dict[str, set[int]] = defaultdict(set)
    instance_fields = {
        "id",
        "exercise_id",
        "lesson_id",
        "content_version",
        "created_at",
        "session_id",
        "hint_used",
        "answered_at",
        "position",
    }
    for row in backup["exerciseInstances"]:
        _require(isinstance(row, dict) and set(row) == instance_fields, "BACKUP_INSTANCE_INVALID")
        _require(
            isinstance(row["id"], str)
            and 8 <= len(row["id"]) <= 100
            and row["id"] not in instances,
            "BACKUP_DUPLICATE_ID",
        )
        _require(
            row["exercise_id"] in exercises and row["lesson_id"] in lessons,
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row["exercise_id"] in lessons[row["lesson_id"]]["exerciseIds"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row["session_id"] in sessions
            and row["content_version"] == sessions[row["session_id"]]["contentVersion"],
            "BACKUP_REFERENCE_INVALID",
        )
        historical = exercises_for_revision(row["content_version"]).get(row["exercise_id"])
        _require(
            historical is not None and historical["lessonId"] == row["lesson_id"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(type(row["position"]) is int and row["position"] >= 0, "BACKUP_INSTANCE_INVALID")
        _require(
            row["position"] not in positions_by_session[row["session_id"]],
            "BACKUP_DUPLICATE_ID",
        )
        positions_by_session[row["session_id"]].add(row["position"])
        _require(
            type(row["hint_used"]) is int and row["hint_used"] in (0, 1), "BACKUP_INSTANCE_INVALID"
        )
        _parse_datetime(row["created_at"], "BACKUP_TIME_INVALID")
        if row["answered_at"] is not None:
            _parse_datetime(row["answered_at"], "BACKUP_TIME_INVALID")
        instances[row["id"]] = row
    for positions in positions_by_session.values():
        _require(positions == set(range(len(positions))), "BACKUP_INSTANCE_INVALID")

    attempt_fields = {
        "id",
        "instance_id",
        "exercise_id",
        "knowledge_id",
        "mode",
        "first_try_correct",
        "hint_used",
        "due_credit",
        "clock_pending",
        "occurred_at",
        "business_date",
        "answer_json",
    }
    attempt_ids = set()
    attempted_instances = set()
    _require(isinstance(backup["attempts"], list), "BACKUP_INVALID")
    for row in backup["attempts"]:
        _require(isinstance(row, dict) and set(row) == attempt_fields, "BACKUP_ATTEMPT_INVALID")
        _require(
            isinstance(row["id"], str)
            and 8 <= len(row["id"]) <= 100
            and row["id"] not in attempt_ids,
            "BACKUP_DUPLICATE_ID",
        )
        attempt_ids.add(row["id"])
        original_instance = instances.get(row["instance_id"])
        _require(original_instance is not None, "BACKUP_REFERENCE_INVALID")
        exercise = exercises_for_revision(original_instance["content_version"]).get(
            row["exercise_id"]
        )
        _require(
            bool(exercise)
            and row["knowledge_id"] == exercise["primaryKnowledgeId"]
            and row["mode"] == exercise["type"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            type(row["first_try_correct"]) is int and row["first_try_correct"] in (0, 1),
            "BACKUP_ATTEMPT_INVALID",
        )
        _require(
            type(row["hint_used"]) is int and row["hint_used"] in (0, 1), "BACKUP_ATTEMPT_INVALID"
        )
        _require(
            type(row["due_credit"]) is int and row["due_credit"] in (0, 1), "BACKUP_ATTEMPT_INVALID"
        )
        _require(
            type(row["clock_pending"]) is int and row["clock_pending"] in (0, 1),
            "BACKUP_ATTEMPT_INVALID",
        )
        _require(not row["clock_pending"] or not row["due_credit"], "BACKUP_ATTEMPT_INVALID")
        _require(isinstance(row["business_date"], str), "BACKUP_ATTEMPT_INVALID")
        try:
            date.fromisoformat(row["business_date"])
        except ValueError:
            raise HTTPException(422, detail={"code": "BACKUP_TIME_INVALID"}) from None
        _parse_datetime(row["occurred_at"], "BACKUP_TIME_INVALID")
        _require(
            isinstance(row["answer_json"], str) and len(row["answer_json"]) <= 4096,
            "BACKUP_ATTEMPT_INVALID",
        )
        try:
            answer = json.loads(row["answer_json"], object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, ValueError, RecursionError):
            raise HTTPException(422, detail={"code": "BACKUP_ATTEMPT_INVALID"}) from None
        _require(isinstance(answer, dict) and set(answer) == {"optionId"}, "BACKUP_ATTEMPT_INVALID")
        instance = instances.get(row["instance_id"])
        _require(
            bool(instance)
            and instance["exercise_id"] == row["exercise_id"]
            and instance["answered_at"] is not None,
            "BACKUP_REFERENCE_INVALID",
        )
        _require(row["instance_id"] not in attempted_instances, "BACKUP_DUPLICATE_ID")
        attempted_instances.add(row["instance_id"])
        _require(row["hint_used"] == instance["hint_used"], "BACKUP_ATTEMPT_INVALID")
        answer_option_id = answer["optionId"]
        correct = answer_option_id == exercise.get("answer", {}).get("optionId")
        _require(
            any(option["id"] == answer_option_id for option in exercise.get("options", [])),
            "BACKUP_ATTEMPT_INVALID",
        )
        _require(
            row["first_try_correct"] == int(correct and not row["hint_used"]),
            "BACKUP_ATTEMPT_INVALID",
        )
        local_day = business_date(_parse_datetime(row["occurred_at"], "BACKUP_TIME_INVALID"))
        _require(row["business_date"] == local_day.isoformat(), "BACKUP_TIME_INVALID")

    skipped_ids = set()
    for row in backup["skippedInstances"]:
        _require(
            isinstance(row, dict) and set(row) == {"instanceId", "sessionId", "skippedAt"},
            "BACKUP_SKIP_INVALID",
        )
        _require(
            row["instanceId"] in instances
            and row["sessionId"] == instances[row["instanceId"]]["session_id"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row["instanceId"] not in skipped_ids
            and instances[row["instanceId"]]["answered_at"] is None,
            "BACKUP_DUPLICATE_ID",
        )
        skipped_ids.add(row["instanceId"])
        _parse_datetime(row["skippedAt"], "BACKUP_TIME_INVALID")

    knowledge = map_by_id("knowledgeItems")
    review_ids = set()
    for row in backup["reviewPlans"]:
        _require(
            isinstance(row, dict)
            and set(row) == {"knowledge_id", "stage", "due_date", "updated_at"},
            "BACKUP_REVIEW_INVALID",
        )
        _require(
            row["knowledge_id"] in knowledge and row["knowledge_id"] not in review_ids,
            "BACKUP_DUPLICATE_ID",
        )
        review_ids.add(row["knowledge_id"])
        _require(type(row["stage"]) is int and 0 <= row["stage"] <= 3, "BACKUP_REVIEW_INVALID")
        try:
            date.fromisoformat(row["due_date"])
        except (TypeError, ValueError):
            raise HTTPException(422, detail={"code": "BACKUP_TIME_INVALID"}) from None
        _parse_datetime(row["updated_at"], "BACKUP_TIME_INVALID")

    targets = map_by_id("readingTargets")
    for row in backup["assessmentSummaries"]:
        _require(
            isinstance(row, dict)
            and set(row) == {"targetId", "status", "summary", "engineVersion", "createdAt"},
            "BACKUP_ASSESSMENT_INVALID",
        )
        _require(
            isinstance(row["targetId"], str) and row["targetId"] in targets,
            "BACKUP_ASSESSMENT_INVALID",
        )
        _require(
            row["status"] in {"scored", "uncertain", "unsupported", "unavailable"},
            "BACKUP_ASSESSMENT_INVALID",
        )
        if row["status"] == "scored":
            _require(
                type(row["summary"].get("score")) in {int, float}
                and 0 <= row["summary"]["score"] <= 100
                and type(row["summary"].get("confidence")) in {int, float}
                and 0 <= row["summary"]["confidence"] <= 1,
                "BACKUP_ASSESSMENT_INVALID",
            )
        else:
            _require("score" not in row["summary"], "BACKUP_ASSESSMENT_INVALID")
        _require(
            isinstance(row["summary"], dict)
            and set(row["summary"])
            <= {"score", "confidence", "dimensions", "reason", "calibrationVersion"},
            "BACKUP_ASSESSMENT_INVALID",
        )
        _require(
            isinstance(row["engineVersion"], str) and len(row["engineVersion"]) <= 100,
            "BACKUP_ASSESSMENT_INVALID",
        )
        _parse_datetime(row["createdAt"], "BACKUP_TIME_INVALID")
    return {
        **backup,
        "contentVersion": curriculum["contentVersion"],
        "profile": {**backup["profile"], "contentVersion": curriculum["contentVersion"]},
    }


def _migrate_v2_backup(value: dict) -> dict:
    expected = {
        "schemaVersion",
        "contentVersion",
        "masteryRuleVersion",
        "exportedAt",
        "profile",
        "attempts",
        "sessions",
        "skippedInstances",
        "reviewPlans",
        "exerciseInstances",
        "assessmentSummaries",
        "note",
    }
    _require(set(value) == expected, "BACKUP_FIELDS_INVALID")
    _require(isinstance(value.get("profile"), dict), "BACKUP_PROFILE_INVALID")
    profile = value["profile"]
    _require(
        set(profile) == {"id", "selectedLessonId", "contentVersion", "revision", "settings"},
        "BACKUP_PROFILE_INVALID",
    )
    _require(
        isinstance(profile["settings"], dict)
        and set(profile["settings"]) == {"soundEnabled", "reducedMotion"}
        and profile["settings"]["reducedMotion"] is False,
        "BACKUP_PROFILE_INVALID",
    )
    _require(isinstance(value.get("sessions"), list), "BACKUP_INVALID")
    _require(isinstance(value.get("exerciseInstances"), list), "BACKUP_INVALID")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in value["exerciseInstances"]:
        _require(isinstance(item, dict) and "position" not in item, "BACKUP_INSTANCE_INVALID")
        _require(isinstance(item.get("session_id"), str), "BACKUP_INSTANCE_INVALID")
        grouped[item["session_id"]].append(item)
    positions = {}
    for items in grouped.values():
        for index, item in enumerate(
            sorted(items, key=lambda row: (row.get("created_at", ""), row.get("id", "")))
        ):
            positions[item["id"]] = index
    migrated = dict(value)
    migrated["schemaVersion"] = 3
    migrated["profile"] = {
        **profile,
        "roundsSinceBreak": 0,
        "settings": {**profile["settings"], "reducedMotion": False},
    }
    migrated["exerciseInstances"] = [
        {**item, "position": positions.get(item.get("id"), -1)}
        for item in value["exerciseInstances"]
    ]
    return _migrate_v3_backup(migrated)


def _migrate_v3_backup(value: dict) -> dict:
    _require(isinstance(value.get("sessions"), list), "BACKUP_INVALID")
    migrated = dict(value)
    migrated["schemaVersion"] = 4
    migrated["sessions"] = [{**session, "reviewKnowledgeId": None} for session in value["sessions"]]
    return _migrate_v4_backup(migrated)


def _migrate_v4_backup(value: dict) -> dict:
    _require(isinstance(value.get("attempts"), list), "BACKUP_INVALID")
    legacy_attempt_fields = {
        "id",
        "instance_id",
        "exercise_id",
        "knowledge_id",
        "mode",
        "first_try_correct",
        "hint_used",
        "due_credit",
        "occurred_at",
        "business_date",
        "answer_json",
    }
    _require(
        all(
            isinstance(attempt, dict) and set(attempt) == legacy_attempt_fields
            for attempt in value["attempts"]
        ),
        "BACKUP_ATTEMPT_INVALID",
    )
    migrated = dict(value)
    migrated["schemaVersion"] = 5
    migrated["attempts"] = [{**attempt, "clock_pending": 0} for attempt in value["attempts"]]
    return migrated


@router.post("/profiles/import-preview")
async def import_preview(request: Request, device: dict = Depends(parent)) -> dict:
    raw_buffer = bytearray()
    async for chunk in request.stream():
        if len(raw_buffer) + len(chunk) > IMPORT_MAX_BYTES:
            raise HTTPException(413, detail={"code": "BACKUP_TOO_LARGE"})
        raw_buffer.extend(chunk)
    raw = bytes(raw_buffer)
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(422, detail={"code": "BACKUP_INVALID"}) from None
    backup = _validate_backup(payload)
    digest = hashlib.sha256(raw).hexdigest()
    with connect() as db:
        revision = db.execute(
            "SELECT revision FROM household WHERE id=?", (device["household_id"],)
        ).fetchone()["revision"]
    token = secrets.token_urlsafe(32)
    expires = time.time() + IMPORT_PREVIEW_TTL
    with _import_previews_lock:
        now = time.time()
        for old_token, (_, _, _, expiry, _) in list(_import_previews.items()):
            if expiry <= now:
                del _import_previews[old_token]
        if len(_import_previews) >= IMPORT_MAX_ACTIVE_PREVIEWS:
            raise HTTPException(429, detail={"code": "IMPORT_PREVIEW_LIMIT"})
        _import_previews[token] = (device["household_id"], digest, revision, expires, backup)
    return {
        "previewToken": token,
        "sha256": digest,
        "migratedFromContentVersion": payload.get("contentVersion")
        if payload.get("contentVersion") != backup["contentVersion"]
        else None,
        "migratedFromSchemaVersion": payload.get("schemaVersion")
        if payload.get("schemaVersion") in {2, 3, 4}
        else None,
        "expiresInSeconds": IMPORT_PREVIEW_TTL,
        "revision": revision,
        "counts": {
            "sessions": len(backup["sessions"]),
            "exerciseInstances": len(backup["exerciseInstances"]),
            "attempts": len(backup["attempts"]),
            "clockPendingAttempts": sum(item["clock_pending"] for item in backup["attempts"]),
            "skippedInstances": len(backup["skippedInstances"]),
            "reviewPlans": len(backup["reviewPlans"]),
            "assessmentSummaries": len(backup["assessmentSummaries"]),
        },
        "willReplaceEntireHousehold": True,
    }


class ImportConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previewToken: str = Field(min_length=32, max_length=100)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expectedRevision: int = Field(ge=0)


def _restore_backup(db, household_id: str, device_id: str, backup: dict) -> None:
    db.execute("DELETE FROM request_receipts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM attempts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM skipped_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM exercise_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM sessions WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM review_plans WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM assessment_summaries WHERE household_id=?", (household_id,))

    instance_groups: dict[str, list[dict]] = defaultdict(list)
    for instance in backup["exerciseInstances"]:
        instance_groups[instance["session_id"]].append(instance)
    for session in backup["sessions"]:
        tasks = [
            {
                "instanceId": item["id"],
                "exercise": _public_exercise(
                    exercises_for_revision(item["content_version"])[item["exercise_id"]],
                    instance_id=item["id"],
                ),
            }
            for item in sorted(instance_groups[session["id"]], key=lambda row: row["position"])
        ]
        db.execute(
            """INSERT INTO sessions(id,household_id,device_id,content_version,started_at,
               tasks_json,status,review_knowledge_id) VALUES(?,?,?,?,?,?,?,?)""",
            (
                session["id"],
                household_id,
                device_id,
                session["contentVersion"],
                session["startedAt"],
                json.dumps(tasks, ensure_ascii=False),
                session["status"],
                session["reviewKnowledgeId"],
            ),
        )
    for item in backup["exerciseInstances"]:
        db.execute(
            """INSERT INTO exercise_instances(id,household_id,exercise_id,lesson_id,
               content_version,created_at,session_id,hint_used,answered_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                item["id"],
                household_id,
                item["exercise_id"],
                item["lesson_id"],
                item["content_version"],
                item["created_at"],
                item["session_id"],
                item["hint_used"],
                item["answered_at"],
            ),
        )
    for item in backup["attempts"]:
        db.execute(
            """INSERT INTO attempts(id,household_id,device_id,instance_id,exercise_id,
               knowledge_id,mode,first_try_correct,hint_used,due_credit,occurred_at,
               business_date,answer_json,clock_pending) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item["id"],
                household_id,
                device_id,
                item["instance_id"],
                item["exercise_id"],
                item["knowledge_id"],
                item["mode"],
                item["first_try_correct"],
                item["hint_used"],
                item["due_credit"],
                item["occurred_at"],
                item["business_date"],
                item["answer_json"],
                item["clock_pending"],
            ),
        )
    for item in backup["skippedInstances"]:
        db.execute(
            "INSERT INTO skipped_instances(instance_id,household_id,skipped_at) VALUES(?,?,?)",
            (item["instanceId"], household_id, item["skippedAt"]),
        )
    for item in backup["reviewPlans"]:
        db.execute(
            """INSERT INTO review_plans(household_id,knowledge_id,stage,due_date,updated_at)
               VALUES(?,?,?,?,?)""",
            (
                household_id,
                item["knowledge_id"],
                item["stage"],
                item["due_date"],
                item["updated_at"],
            ),
        )
    for item in backup["assessmentSummaries"]:
        db.execute(
            """INSERT INTO assessment_summaries(request_id,household_id,target_id,status,
               summary_json,engine_version,created_at) VALUES(?,?,?,?,?,?,?)""",
            (
                secrets.token_urlsafe(18),
                household_id,
                item["targetId"],
                item["status"],
                json.dumps(item["summary"], ensure_ascii=False),
                item["engineVersion"],
                item["createdAt"],
            ),
        )


@router.post("/profiles/import")
def import_profile(body: ImportConfirm, device: dict = Depends(parent)) -> dict:
    with _import_previews_lock:
        preview = _import_previews.get(body.previewToken)
    if not preview:
        raise HTTPException(410, detail={"code": "IMPORT_PREVIEW_EXPIRED"})
    household_id, digest, preview_revision, expires, backup = preview
    if expires <= time.time():
        with _import_previews_lock:
            _import_previews.pop(body.previewToken, None)
        raise HTTPException(410, detail={"code": "IMPORT_PREVIEW_EXPIRED"})
    if household_id != device["household_id"] or digest != body.sha256:
        raise HTTPException(409, detail={"code": "IMPORT_PREVIEW_MISMATCH"})
    if preview_revision != body.expectedRevision:
        raise HTTPException(409, detail={"code": "REVISION_CONFLICT"})
    with transaction() as db:
        household = db.execute(
            "SELECT revision FROM household WHERE id=?", (household_id,)
        ).fetchone()
        if not household or household["revision"] != body.expectedRevision:
            with _import_previews_lock:
                _import_previews.pop(body.previewToken, None)
            raise HTTPException(409, detail={"code": "REVISION_CONFLICT"})
        _restore_backup(db, household_id, device["id"], backup)
        row = db.execute(
            """UPDATE household SET selected_lesson_id=?,sound_enabled=?,reduced_motion=?,
               playback_gap_tenths=?,rounds_since_break=?,
               revision=revision+1 WHERE id=? RETURNING *""",
            (
                backup["profile"]["selectedLessonId"],
                int(backup["profile"]["settings"]["soundEnabled"]),
                int(backup["profile"]["settings"]["reducedMotion"]),
                gap_tenths(
                    backup["profile"]["settings"].get("playbackGapSeconds", GAP["defaultSeconds"])
                ),
                backup["profile"]["roundsSinceBreak"],
                household_id,
            ),
        ).fetchone()
    with _import_previews_lock:
        _import_previews.pop(body.previewToken, None)
    return {"imported": True, "profile": public_profile(row)}


class DeleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=1, max_length=40)


class ClockPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(pattern=r"^(discard|keep-unscored)$")
    confirmation: str = Field(min_length=1, max_length=40)


def _delete_learning_rows(db, household_id: str) -> None:
    db.execute("DELETE FROM request_receipts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM assessment_summaries WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM attempts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM skipped_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM exercise_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM sessions WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM review_plans WHERE household_id=?", (household_id,))


@router.delete("/profiles/data")
def delete_profile_data(body: DeleteData, device: dict = Depends(parent)) -> dict:
    if body.confirmation != "删除我的学习记录":
        raise HTTPException(422, detail={"code": "CONFIRMATION_REQUIRED"})
    with transaction() as db:
        household_id = device["household_id"]
        _delete_learning_rows(db, household_id)
        db.execute(
            """UPDATE household SET selected_lesson_id='lesson-01',rounds_since_break=0,
               revision=revision+1 WHERE id=?""",
            (household_id,),
        )
        row = db.execute("SELECT * FROM household WHERE id=?", (household_id,)).fetchone()
    return {"deleted": True, "profile": public_profile(row)}


@router.post("/profiles/clock-pending/resolve")
def resolve_clock_pending(body: ClockPendingResolution, device: dict = Depends(parent)) -> dict:
    if device["clock_skew_detected"]:
        raise HTTPException(409, detail={"code": "CLOCK_NOT_RESTORED"})
    expected = "删除待校时练习" if body.resolution == "discard" else "保留为不计分练习"
    if body.confirmation != expected:
        raise HTTPException(422, detail={"code": "CONFIRMATION_REQUIRED"})
    household_id = device["household_id"]
    with transaction() as db:
        pending = db.execute(
            "SELECT id,instance_id FROM attempts WHERE household_id=? AND clock_pending=1",
            (household_id,),
        ).fetchall()
        if body.resolution == "keep-unscored":
            db.execute(
                """UPDATE attempts SET clock_pending=0,due_credit=0
                   WHERE household_id=? AND clock_pending=1""",
                (household_id,),
            )
        elif pending:
            pending_ids = {row["id"] for row in pending}
            receipt_ids = []
            for row in db.execute(
                "SELECT request_id,result_json FROM request_receipts WHERE household_id=?",
                (household_id,),
            ):
                try:
                    result = json.loads(row["result_json"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if result.get("attemptId") in pending_ids:
                    receipt_ids.append(row["request_id"])
            db.executemany(
                "DELETE FROM request_receipts WHERE request_id=?", [(i,) for i in receipt_ids]
            )
            instance_ids = [row["instance_id"] for row in pending]
            db.executemany(
                """UPDATE exercise_instances SET answered_at=NULL
                   WHERE id=? AND session_id IN (SELECT id FROM sessions WHERE status='active')""",
                [(instance_id,) for instance_id in instance_ids],
            )
            db.executemany("DELETE FROM attempts WHERE id=?", [(row["id"],) for row in pending])
        db.execute("UPDATE household SET revision=revision+1 WHERE id=?", (household_id,))
    return {"resolved": len(pending), "resolution": body.resolution}


@router.delete("/profiles/reset")
def reset_profile(body: DeleteData, response: Response, device: dict = Depends(parent)) -> dict:
    if body.confirmation != "重置家庭档案":
        raise HTTPException(422, detail={"code": "CONFIRMATION_REQUIRED"})
    household_id = device["household_id"]
    reset_at = now_iso()
    with transaction() as db:
        _delete_learning_rows(db, household_id)
        db.execute("DELETE FROM pairing_codes")
        db.execute(
            "UPDATE devices SET revoked_at=? WHERE household_id=? AND revoked_at IS NULL",
            (reset_at, household_id),
        )
        db.execute(
            """UPDATE household SET selected_lesson_id='lesson-01',sound_enabled=1,
               reduced_motion=0,playback_gap_tenths=?,rounds_since_break=0,
               revision=revision+1 WHERE id=?""",
            (round(GAP["defaultSeconds"] * 10), household_id),
        )
    with _import_previews_lock:
        for token, preview in list(_import_previews.items()):
            if preview[0] == household_id:
                _import_previews.pop(token, None)
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"reset": True, "pairingRequired": True}


class StartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessonId: str | None = None


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
    questions = [
        by_id[qid] for qid in lesson["exerciseIds"] if _objective_available(by_id[qid], audio_ids)
    ]
    if not questions:
        raise HTTPException(409, detail={"code": "LESSON_NOT_READY"})
    session_id = secrets.token_urlsafe(18)
    now = now_iso()
    tasks = []
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
        history = db.execute(
            """SELECT i.exercise_id, COALESCE(a.occurred_at,s.skipped_at) AS completed_at
               FROM exercise_instances i
               LEFT JOIN attempts a ON a.instance_id=i.id
               LEFT JOIN skipped_instances s ON s.instance_id=i.id
               WHERE i.household_id=? AND i.lesson_id=?
                 AND (a.id IS NOT NULL OR s.instance_id IS NOT NULL)""",
            (device["household_id"], lesson["id"]),
        ).fetchall()
        selected_ids = plan_practice(
            [q["id"] for q in questions],
            [
                PracticeCompletion(row["exercise_id"], datetime.fromisoformat(row["completed_at"]))
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
                    lesson["id"],
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
        revision = db.execute(
            "UPDATE household SET revision=revision+1 WHERE id=? RETURNING revision",
            (device["household_id"],),
        ).fetchone()["revision"]
    return {
        "id": session_id,
        "lessonId": lesson["id"],
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


@router.get("/daily-reading")
def get_daily_reading(device: dict = Depends(paired)) -> dict:
    from server.daily_reading import status

    return status()


@router.get("/daily-audio/{asset_id}")
def get_daily_audio(
    asset_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    device: dict = Depends(paired),
) -> Response:
    from server.daily_reading import audio_response

    return audio_response(asset_id, range_header)


@router.post("/daily-reading/{item_id}/recognize")
async def recognize_daily_reading(item_id: str, request: Request, device: dict = Depends(mutable)):
    from fastapi.concurrency import run_in_threadpool

    from server.reading_recognition import recognize, request_audio

    payload = await request_audio(request, item_id)
    return await run_in_threadpool(recognize, item_id, payload)
