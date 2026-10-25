"""Pure household game clock: union of short leases, Shanghai days, bounded runs."""

import json
import math
from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "content/games.json").read_text())
POLICY = CATALOG["policy"]
GAMES = {game["id"]: game for game in CATALOG["games"]}
ZONE = ZoneInfo("Asia/Shanghai")


def empty_clock() -> dict:
    return {"version": 1, "days": {}, "runSeconds": 0, "accountedAt": 0, "leaseUntil": 0}


def validate_clock(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(empty_clock()):
        raise ValueError("game clock fields")
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["days"], dict)
        or len(value["days"]) > 32
    ):
        raise ValueError("game clock version/days")
    for key, seconds in value["days"].items():
        if datetime.strptime(key, "%Y-%m-%d").date().isoformat() != key:
            raise ValueError("game day")
        if (
            type(seconds) not in (int, float)
            or not math.isfinite(seconds)
            or not 0 <= seconds <= 86400
        ):
            raise ValueError("game seconds")
    for key in ("runSeconds", "accountedAt", "leaseUntil"):
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1e12:
            raise ValueError("game clock number")
    if value["leaseUntil"] > value["accountedAt"] + POLICY["leaseSeconds"]:
        raise ValueError("unbounded game lease")
    return deepcopy(value)


def settle(state: dict, now: float) -> dict:
    result = deepcopy(state)
    start = result["accountedAt"]
    end = min(now, result["leaseUntil"])
    if end > start:
        result["runSeconds"] += end - start
        while start < end:
            local = datetime.fromtimestamp(start, UTC).astimezone(ZONE)
            midnight = datetime.combine(local.date() + timedelta(days=1), time(), ZONE).timestamp()
            stop = min(end, midnight)
            day = local.date().isoformat()
            result["days"][day] = result["days"].get(day, 0) + stop - start
            start = stop
    result["accountedAt"] = max(now, result["accountedAt"])
    if now >= result["leaseUntil"] + POLICY["breakSeconds"]:
        result["runSeconds"] = 0
    # Keep a bounded month of usage in portable snapshots.
    result["days"] = dict(sorted(result["days"].items())[-32:])
    return result


def allowance(state: dict, now: float, session_minutes: int, daily_minutes: int) -> dict:
    day = datetime.fromtimestamp(now, UTC).astimezone(ZONE).date().isoformat()
    daily = state["days"].get(day, 0)
    remaining = max(0, min(session_minutes * 60 - state["runSeconds"], daily_minutes * 60 - daily))
    reason = (
        "GAME_CLOCK_ROLLBACK"
        if now < state["accountedAt"]
        else "GAME_DAILY_LIMIT"
        if daily >= daily_minutes * 60
        else "GAME_SESSION_LIMIT"
        if state["runSeconds"] >= session_minutes * 60
        else None
    )
    return {
        "day": day,
        "dailySeconds": daily,
        "sessionSeconds": state["runSeconds"],
        "remainingSeconds": remaining,
        "reason": reason,
        "breakRemainingSeconds": max(0, state["leaseUntil"] + POLICY["breakSeconds"] - now)
        if reason == "GAME_SESSION_LIMIT"
        else 0,
        "leaseSeconds": max(0, min(state["leaseUntil"] - now, remaining)) if not reason else 0,
        "sessionMinutes": session_minutes,
        "dailyMinutes": daily_minutes,
    }


def transition(
    state: dict, now: float, session_minutes: int, daily_minutes: int, action: str
) -> tuple[dict, dict]:
    updated = settle(state, now)
    status = allowance(updated, now, session_minutes, daily_minutes)
    if action == "heartbeat" and not status["reason"]:
        updated["leaseUntil"] = now + min(POLICY["leaseSeconds"], status["remainingSeconds"])
    elif action == "pause":
        updated["leaseUntil"] = min(updated["leaseUntil"], now)
    return updated, allowance(updated, now, session_minutes, daily_minutes)
