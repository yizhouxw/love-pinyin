"""Same-origin, authenticated in-memory pronunciation requests and summary history."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from server import pronunciation
from server.api_dependencies import mutable, paired
from server.storage import connect

router = APIRouter()


async def read_audio(request: Request) -> bytes:
    from server.reading_recognition import MAX_BYTES

    if request.headers.get("content-type", "").split(";")[0] != "audio/wav":
        raise HTTPException(415, detail={"code": "READING_PCM_REQUIRED"})
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_BYTES:
            raise HTTPException(413, detail={"code": "READING_TOO_LARGE"})
    return bytes(payload)


@router.post("/pronunciation/{target_id}/assess")
async def assess(
    target_id: str,
    request: Request,
    x_lp_request_id: str = Header(min_length=8, max_length=80, pattern=r"^[\w-]+$"),
    device: dict = Depends(mutable),
) -> dict:
    payload = await read_audio(request)
    return await run_in_threadpool(
        pronunciation.assess, target_id, x_lp_request_id, payload, device["household_id"]
    )


@router.get("/pronunciation/{target_id}/history")
def history(target_id: str, device: dict = Depends(paired)) -> dict:
    import json

    if target_id not in pronunciation.targets():
        raise HTTPException(404, detail={"code": "PRONUNCIATION_TARGET_NOT_FOUND"})
    with connect() as db:
        rows = db.execute(
            "SELECT result_json FROM pronunciation_attempts WHERE household_id=? AND target_id=? "
            "ORDER BY created_at DESC,request_id DESC LIMIT 20",
            (device["household_id"], target_id),
        ).fetchall()
        counts = db.execute(
            "SELECT json_extract(result_json,'$.match.status') AS status,COUNT(*) AS count "
            "FROM pronunciation_attempts WHERE household_id=? AND target_id=? GROUP BY status",
            (device["household_id"], target_id),
        ).fetchall()
    return {
        "items": [json.loads(row["result_json"]) for row in rows],
        "counts": {row["status"]: row["count"] for row in counts},
    }
