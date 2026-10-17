"""HTTP endpoints for pairing."""

import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from server.api_dependencies import (
    COOKIE,
    CSRF_COOKIE,
    _check_origin,
    _hash,
    _is_parent_entry,
    _require_parent_entry,
    mutable,
    parent,
    parent_read,
)
from server.storage import connect, now_iso, transaction

router = APIRouter()
local_router = APIRouter(prefix="/api/v1/local")

_failures: dict[str, deque[float]] = defaultdict(deque)


_failures_lock = threading.Lock()


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
    _require_parent_entry(request)
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
        is_parent = _is_parent_entry(request)
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
                int(is_parent),
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
    return {"paired": True, "isParent": is_parent, "deviceId": device_id}


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
