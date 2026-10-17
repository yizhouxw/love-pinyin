"""HTTP endpoints for resources."""

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response

from server import source_audio
from server.api_dependencies import _get_device, _is_parent_entry, mutable, paired
from server.content import load_curriculum, load_illustrations, load_writing
from server.learning_audio import learning_audio_response, learning_audio_status
from server.learning_state import _available_standard_audio, _public_exercise
from server.storage import connect, public_profile

router = APIRouter()


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
            "isLocalHost": _is_parent_entry(request),
            "contentVersion": load_curriculum()["contentVersion"],
        }
    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE household_id=?", (device["household_id"],)
        ).fetchone()[0]
    return {
        "paired": True,
        "isLocalHost": _is_parent_entry(request),
        "device": {
            "id": device["id"],
            "label": device["label"],
            "isParent": bool(device["is_parent"]) and _is_parent_entry(request),
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
