"""HTTP endpoints for profiles."""

import hashlib
import json
import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from server.api_dependencies import COOKIE, CSRF_COOKIE, parent, parent_read
from server.content import map_by_id
from server.game_policy import POLICY, empty_clock
from server.playback_settings import GAP, gap_tenths
from server.profile_backup import (
    IMPORT_MAX_BYTES,
    _delete_learning_rows,
    _restore_backup,
    _unique_json_object,
    _validate_backup,
)
from server.storage import connect, now_iso, public_profile, transaction

router = APIRouter()

_import_previews: dict[str, tuple[str, str, int, float, dict]] = {}


_import_previews_lock = threading.Lock()


IMPORT_PREVIEW_TTL = 300


IMPORT_MAX_ACTIVE_PREVIEWS = 8


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
    gameSessionMinutes: int | None = Field(
        default=None, strict=True, ge=1, le=POLICY["sessionMaxMinutes"]
    )
    gameDailyMinutes: int | None = Field(
        default=None, strict=True, ge=1, le=POLICY["dailyMaxMinutes"]
    )
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
               game_session_minutes=COALESCE(?,game_session_minutes),
               game_daily_minutes=COALESCE(?,game_daily_minutes),
               reduced_motion=COALESCE(?,reduced_motion),
               playback_gap_tenths=COALESCE(?,playback_gap_tenths),
               revision=revision+1 WHERE id=?""",
            (
                int(body.soundEnabled),
                body.gameSessionMinutes,
                body.gameDailyMinutes,
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
                      review_knowledge_id AS reviewKnowledgeId,game_id AS gameId
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
                for key in (
                    "id",
                    "contentVersion",
                    "startedAt",
                    "status",
                    "reviewKnowledgeId",
                    "gameId",
                )
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
               playback_gap_tenths=?,rounds_since_break=?,game_session_minutes=?,game_daily_minutes=?,
               revision=revision+1 WHERE id=? RETURNING *""",
            (
                backup["profile"]["selectedLessonId"],
                int(backup["profile"]["settings"]["soundEnabled"]),
                int(backup["profile"]["settings"]["reducedMotion"]),
                gap_tenths(
                    backup["profile"]["settings"].get("playbackGapSeconds", GAP["defaultSeconds"])
                ),
                backup["profile"]["roundsSinceBreak"],
                backup["profile"]["settings"].get("gameSessionMinutes", POLICY["sessionMinutes"]),
                backup["profile"]["settings"].get("gameDailyMinutes", POLICY["dailyMinutes"]),
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
               game_session_minutes=?,game_daily_minutes=?,game_state_json=?,
               revision=revision+1 WHERE id=?""",
            (
                round(GAP["defaultSeconds"] * 10),
                POLICY["sessionMinutes"],
                POLICY["dailyMinutes"],
                json.dumps(empty_clock()),
                household_id,
            ),
        )
    with _import_previews_lock:
        for token, preview in list(_import_previews.items()):
            if preview[0] == household_id:
                _import_previews.pop(token, None)
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"reset": True, "pairingRequired": True}
