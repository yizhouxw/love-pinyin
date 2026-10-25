"""Shared authentication, origin and clock dependencies."""

import hashlib
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse

from fastapi import Cookie, Depends, Header, HTTPException, Request

from server.storage import connect, now_iso, transaction

COOKIE = "lp_session"


CSRF_COOKIE = "lp_csrf"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_local(request: Request) -> bool:
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


def _is_parent_entry(request: Request) -> bool:
    return bool(
        request.client
        and request.client.host == "127.0.0.1"
        and request.url.hostname == "127.0.0.1"
    )


def _require_parent_entry(request: Request) -> None:
    if not _is_parent_entry(request):
        raise HTTPException(403, detail={"code": "PARENT_LOCAL_REQUIRED"})


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
                      h.game_session_minutes,h.game_daily_minutes,h.game_state_json,
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


def parent(_local: None = Depends(_require_parent_entry), device: dict = Depends(mutable)) -> dict:
    return _require_parent(device)


def parent_read(
    _local: None = Depends(_require_parent_entry), device: dict = Depends(paired)
) -> dict:
    return _require_parent(device)


def _require_parent(device: dict) -> dict:
    if not device["is_parent"]:
        raise HTTPException(403, detail={"code": "PARENT_AUTH_REQUIRED"})
    return device
