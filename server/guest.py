"""Stateless guest operations. Only the browser retains progress between requests."""

import json
import re

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server import api_dependencies, profile_backup, storage
from server.content import load_curriculum
from server.game_policy import POLICY
from server.playback_settings import GAP, gap_tenths
from server.routes import attempts, games, profiles, progress, resources, sessions

router = APIRouter(prefix="/api/v1/guest")

MAX_BYTES = 4 * 1_048_576


class GuestOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=200)
    method: str = Field(default="GET", pattern="^(GET|POST|PUT|PATCH)$")
    body: dict = Field(default_factory=dict)
    state: dict | None = None


def dispatch(operation: GuestOperation, device: dict):
    path, method, body = operation.path, operation.method, operation.body
    if method == "GET":
        if path == "/games":
            return games.games(device)
        if path == "/bootstrap":
            with storage.connect() as db:
                row = db.execute("SELECT * FROM household").fetchone()
            return {
                "paired": True,
                "guest": True,
                "device": {"label": "访客", "isParent": False},
                "profile": storage.public_profile(row),
            }
        if path == "/profiles/progress":
            return progress.progress(device)
        if path == "/sessions/current":
            return sessions.current_session(device)
    if method == "PATCH":
        match = re.fullmatch(r"/sessions/([\w-]+)/game-settings", path)
        if match:
            return sessions.change_game_settings(
                match[1], sessions.SceneSettingsChange.model_validate(body), device
            )
    if method == "PUT":
        if path == "/household/current-lesson":
            return profiles.select_lesson(profiles.LessonChoice.model_validate(body), device)
        if path == "/household/settings":
            return profiles.settings(profiles.Settings.model_validate(body), device)
    if method == "POST":
        if path in {"/games/heartbeat", "/games/pause"}:
            return games.game_clock(path.rsplit("/", 1)[1], device)
        if path == "/sessions":
            return sessions.start_session(sessions.StartSession.model_validate(body), device)
        if path == "/rest/complete":
            return sessions.complete_rest(device)
        match = re.fullmatch(r"/sessions/([\w-]+)/finish", path)
        if match:
            return sessions.finish_session(match[1], device)
        match = re.fullmatch(r"/reviews/([\w-]+)/sessions", path)
        if match:
            return sessions.start_review_session(match[1], device)
        match = re.fullmatch(r"/instances/([\w-]+)/(hint|skip|answer)", path)
        if match:
            instance_id, action = match.groups()
            if action == "hint":
                return attempts.mark_hint(instance_id, device)
            if action == "skip":
                return attempts.skip_instance(instance_id, device)
            answer = attempts.SubmitAnswer.model_validate(body)
            # Backup restoration intentionally drops credentials/request receipts.
            # An already-cached answer still cannot be counted a second time.
            session = sessions.current_session(device)
            previous = session and session["results"].get(instance_id)
            if previous and previous.get("answerOptionId") == answer.answerOptionId:
                return previous
            return attempts.submit_answer(instance_id, answer, device)
    raise HTTPException(404, detail={"code": "GUEST_OPERATION_UNAVAILABLE"})


def execute(operation: GuestOperation) -> dict:
    with storage.ephemeral_database():
        household = storage.ensure_household(load_curriculum()["contentVersion"])
        household_id = household["id"]
        with storage.transaction() as db:
            db.execute(
                """INSERT INTO devices(
                       id,household_id,token_hash,csrf_hash,label,is_parent,created_at)
                   VALUES('guest',?,'guest','guest','访客',1,?)""",
                (household_id, storage.now_iso()),
            )
            if operation.state is not None:
                backup = profile_backup._validate_backup(operation.state)
                profile_backup._restore_backup(db, household_id, "guest", backup)
                profile = backup["profile"]
                db.execute(
                    """UPDATE household SET selected_lesson_id=?,sound_enabled=?,reduced_motion=?,
                       playback_gap_tenths=?,rounds_since_break=?,revision=?,
                       game_session_minutes=?,game_daily_minutes=? WHERE id=?""",
                    (
                        profile["selectedLessonId"],
                        int(profile["settings"]["soundEnabled"]),
                        int(profile["settings"]["reducedMotion"]),
                        gap_tenths(
                            profile["settings"].get("playbackGapSeconds", GAP["defaultSeconds"])
                        ),
                        profile["roundsSinceBreak"],
                        profile["revision"],
                        profile["settings"].get("gameSessionMinutes", POLICY["sessionMinutes"]),
                        profile["settings"].get("gameDailyMinutes", POLICY["dailyMinutes"]),
                        household_id,
                    ),
                )
            row = db.execute("SELECT * FROM household").fetchone()
        device = {**dict(row), "household_id": household_id, "id": "guest", "is_parent": 1}
        result = dispatch(operation, device)
        state = profiles.export_profile(device)
        if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES - 4096:
            raise HTTPException(413, detail={"code": "GUEST_CACHE_FULL"})
        return {"result": result, "state": state}


@router.post("/operate")
async def operate(request: Request):
    api_dependencies._check_origin(request)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, detail={"code": "GUEST_CACHE_FULL"})
    try:
        value = json.loads(raw, object_pairs_hook=profile_backup._unique_json_object)
        operation = GuestOperation.model_validate(value)
        if operation.method == "PUT" and operation.path in {
            "/household/current-lesson",
            "/household/settings",
        }:
            api_dependencies._require_parent_entry(request)
        payload = await run_in_threadpool(execute, operation)
        if operation.path == "/bootstrap":
            payload["result"]["isLocalHost"] = api_dependencies._is_parent_entry(request)
        return JSONResponse(payload)
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, detail={"code": "GUEST_CACHE_INVALID"}) from error


@router.get("/curriculum")
def curriculum():
    return resources.curriculum({})


@router.get("/learning-audio")
def learning_audio():
    return resources.get_learning_audio({})


@router.get("/audio/{asset_id}")
def audio(asset_id: str, range_header: str | None = Header(default=None, alias="Range")):
    return resources.get_audio_asset(asset_id, range_header, {})


@router.get("/voice/{asset_id}")
def voice(asset_id: str, range_header: str | None = Header(default=None, alias="Range")):
    return resources.get_learning_voice(asset_id, range_header, {})


@router.get("/daily-reading")
def daily_reading():
    return resources.get_daily_reading({})


@router.get("/daily-audio/{asset_id}")
def daily_audio(asset_id: str, range_header: str | None = Header(default=None, alias="Range")):
    return resources.get_daily_audio(asset_id, range_header, {})


@router.post("/daily-reading/{item_id}/recognize")
async def recognize_daily_reading(item_id: str, request: Request):
    from server.reading_recognition import recognize, request_audio

    api_dependencies._check_origin(request)
    payload = await request_audio(request, item_id)
    return await run_in_threadpool(recognize, item_id, payload)


@router.post("/pronunciation/{target_id}/assess")
async def assess_pronunciation(
    target_id: str,
    request: Request,
    x_lp_request_id: str = Header(min_length=8, max_length=80, pattern=r"^[\w-]+$"),
) -> dict:
    from server import pronunciation
    from server.routes.pronunciation import read_audio

    api_dependencies._check_origin(request)
    payload = await read_audio(request)
    return await run_in_threadpool(pronunciation.assess, target_id, x_lp_request_id, payload, None)
