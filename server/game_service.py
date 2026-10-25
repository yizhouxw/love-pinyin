"""Game clock persistence and guards, always under the caller's SQLite lock."""

import json
from datetime import timedelta

from fastapi import HTTPException

from server import storage
from server.game_policy import GAMES, allowance, settle, transition


def clock_status(db, household_id: str, action: str = "status") -> dict:
    row = db.execute("SELECT * FROM household WHERE id=?", (household_id,)).fetchone()
    old = json.loads(row["game_state_json"])
    state, status = transition(
        old,
        storage.now_utc().timestamp(),
        row["game_session_minutes"],
        row["game_daily_minutes"],
        action,
    )
    if action != "status" and state != old:
        db.execute(
            "UPDATE household SET game_state_json=?,revision=revision+1 WHERE id=?",
            (json.dumps(state), household_id),
        )
    return status


def require_game_lease(db, household_id: str, session_id: str) -> None:
    session = db.execute(
        "SELECT status,game_id FROM sessions WHERE id=? AND household_id=?",
        (session_id, household_id),
    ).fetchone()
    if not session or not session["game_id"]:
        return
    if session["status"] != "active":
        raise HTTPException(409, detail={"code": "SESSION_NOT_ACTIVE"})
    row = db.execute("SELECT * FROM household WHERE id=?", (household_id,)).fetchone()
    now = storage.now_utc().timestamp()
    state = settle(json.loads(row["game_state_json"]), now)
    status = allowance(state, now, row["game_session_minutes"], row["game_daily_minutes"])
    if status["reason"] or status["leaseSeconds"] <= 0:
        raise HTTPException(409, detail={"code": status["reason"] or "GAME_PAUSED"})


def game_report(db, household_id: str) -> dict:
    today = storage.now_utc()
    start = (today - timedelta(days=7)).isoformat()
    rows = db.execute(
        """SELECT a.knowledge_id,a.first_try_correct,a.hint_used,a.clock_pending
        FROM attempts a JOIN exercise_instances i ON i.id=a.instance_id
        JOIN sessions s ON s.id=i.session_id
        WHERE a.household_id=? AND s.game_id IS NOT NULL AND a.occurred_at>=?""",
        (household_id, start),
    ).fetchall()
    skipped = db.execute(
        """SELECT COUNT(*) FROM skipped_instances sk
        JOIN exercise_instances i ON i.id=sk.instance_id JOIN sessions s ON s.id=i.session_id
        WHERE sk.household_id=? AND s.game_id IS NOT NULL AND sk.skipped_at>=?""",
        (household_id, start),
    ).fetchone()[0]
    return {
        "answered": len(rows),
        "independentCorrect": sum(
            bool(r["first_try_correct"]) and not r["clock_pending"] for r in rows
        ),
        "hints": sum(bool(r["hint_used"]) for r in rows),
        "skipped": skipped,
        "pendingClock": sum(bool(r["clock_pending"]) for r in rows),
        "practiceKnowledgeIds": sorted(
            {
                r["knowledge_id"]
                for r in rows
                if not r["first_try_correct"] and not r["clock_pending"]
            }
        ),
        "games": list(GAMES.values()),
    }
