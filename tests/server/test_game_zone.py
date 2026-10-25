"""GAME-01/02/03: actual transactions plus deterministic clock boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from server import storage
from server.content import map_by_id
from server.game_policy import GAMES, empty_clock, transition
from server.game_service import clock_status
from server.profile_backup import _restore_backup, _validate_backup


@pytest.fixture(autouse=True)
def game_audio(registered_audio_catalog):
    """Only registration integrity, never pronunciation evidence."""


def request(client, path, body=None, method="post"):
    return client.request(
        method.upper(),
        "/api/v1" + path,
        json=body,
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )


def frozen(monkeypatch, stamp="2026-10-25T02:00:00+00:00"):
    current = [datetime.fromisoformat(stamp).timestamp()]
    monkeypatch.setattr(storage, "now_utc", lambda: datetime.fromtimestamp(current[0], UTC))
    return current


def test_clock_exact_caps_pause_resume_and_real_break():
    state = empty_clock()
    base = 1792893600
    state, _ = transition(state, base, 1, 2, "heartbeat")
    for seconds in range(4, 60, 4):
        state, status = transition(state, base + seconds, 1, 2, "heartbeat")
        assert status["reason"] is None
    state, status = transition(state, base + 60, 1, 2, "heartbeat")
    assert status["sessionSeconds"] == 60
    assert status["reason"] == "GAME_SESSION_LIMIT"
    # Exiting/reopening doesn't waive the break, even if the browser refreshes.
    state, _ = transition(state, base + 61, 1, 2, "pause")
    state, status = transition(state, base + 659, 1, 2, "heartbeat")
    assert status["reason"] == "GAME_SESSION_LIMIT"
    state, status = transition(state, base + 660, 1, 2, "heartbeat")
    assert status["reason"] is None and status["sessionSeconds"] == 0
    for seconds in range(664, 724, 4):
        state, status = transition(state, base + seconds, 1, 2, "heartbeat")
    assert status["reason"] == "GAME_DAILY_LIMIT"
    assert status["dailySeconds"] == 120


def test_clock_short_exit_sleep_background_and_overlapping_devices():
    base = 1792893600
    state, _ = transition(empty_clock(), base, 15, 60, "heartbeat")
    # The same household's simultaneous renewal cannot double-charge.
    state, _ = transition(state, base + 4, 15, 60, "heartbeat")
    state, _ = transition(state, base + 4, 15, 60, "heartbeat")
    state, status = transition(state, base + 5, 15, 60, "pause")
    assert status["dailySeconds"] == status["sessionSeconds"] == 5
    state, status = transition(state, base + 20, 15, 60, "heartbeat")
    assert status["sessionSeconds"] == 5
    state, status = transition(state, base + 300, 15, 60, "status")
    assert status["sessionSeconds"] == 17  # at most the granted twelve seconds
    state, status = transition(state, base + 632, 15, 60, "status")
    assert status["sessionSeconds"] == 0
    assert status["dailySeconds"] == 17


def test_clock_midnight_rollback_and_lower_limit():
    base = datetime.fromisoformat("2026-10-25T15:59:55+00:00").timestamp()
    state, _ = transition(empty_clock(), base, 15, 60, "heartbeat")
    state, status = transition(state, base + 10, 15, 60, "heartbeat")
    assert state["days"] == {"2026-10-25": 5, "2026-10-26": 5}
    assert status["dailySeconds"] == 5 and status["sessionSeconds"] == 10
    state, status = transition(state, base + 5, 15, 60, "heartbeat")
    assert status["reason"] == "GAME_CLOCK_ROLLBACK" and status["leaseSeconds"] == 0
    assert state["runSeconds"] == 10
    # Existing larger allowance must stop immediately after a parent lowers it.
    state["runSeconds"] = 61
    _, status = transition(state, base + 11, 1, 60, "heartbeat")
    assert status["reason"] == "GAME_SESSION_LIMIT"


@pytest.mark.parametrize("game_id", list(GAMES))
def test_game_sessions_use_learned_content_and_freeze_recovery(
    paired_client, registered_audio_catalog, game_id
):
    client = paired_client
    revision = client.get("/api/v1/profiles/progress").json()["revision"]
    assert (
        request(
            client,
            "/household/current-lesson",
            {"lessonId": "lesson-03", "expectedRevision": revision},
            "put",
        ).status_code
        == 200
    )
    response = request(client, "/sessions", {"gameId": game_id})
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["gameId"] == game_id
    assert len(session["tasks"]) == 12
    assert len({t["exercise"]["id"] for t in session["tasks"]}) == len(session["tasks"])
    lesson_ids = {"lesson-01", "lesson-02", "lesson-03"}
    for task in session["tasks"]:
        question = map_by_id("exercises")[task["exercise"]["id"]]
        assert question["type"] in GAMES[game_id]["modes"]
        assert question["lessonId"] in lesson_ids
        assert "answer" not in task["exercise"]
    restored = client.get("/api/v1/sessions/current").json()
    assert restored["tasks"] == session["tasks"] and restored["gameId"] == game_id


def test_game_limits_guard_answers_and_idempotent_receipts(paired_client, monkeypatch):
    client = paired_client
    clock = frozen(monkeypatch)
    settings = {"soundEnabled": True, "gameSessionMinutes": 1, "gameDailyMinutes": 2}
    assert request(client, "/household/settings", settings, "put").status_code == 200
    session = request(client, "/sessions", {"gameId": "shape"}).json()
    first, second = session["tasks"][:2]
    question = map_by_id("exercises")[first["exercise"]["id"]]
    payload = {"requestId": "game-answer-1", "answerOptionId": question["answer"]["optionId"]}
    original = request(client, f"/instances/{first['instanceId']}/answer", payload)
    assert original.status_code == 200
    base = clock[0]
    for seconds in range(4, 64, 4):
        clock[0] = base + seconds
        request(client, "/games/heartbeat")
    assert client.get("/api/v1/games").json()["clock"]["reason"] == "GAME_SESSION_LIMIT"
    assert (
        request(client, f"/instances/{first['instanceId']}/answer", payload).json()
        == original.json()
    )
    for action in ("hint", "skip", "answer"):
        body = {"requestId": "game-answer-2", "answerOptionId": "a"} if action == "answer" else None
        blocked = request(client, f"/instances/{second['instanceId']}/{action}", body)
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "GAME_SESSION_LIMIT"
    assert client.get("/api/v1/games").json()["report"]["answered"] == 1
    assert request(client, "/sessions", {"gameId": "shape"}).status_code == 409
    # Re-running additive migrations is safe and doesn't reset a clock.
    storage.migrate()
    assert client.get("/api/v1/games").json()["clock"]["sessionSeconds"] == 60
    # Regular classroom practice is not governed by the game budget.
    assert request(client, "/sessions", {}).status_code == 200


def test_game_settings_ranges_backup_and_delete_boundaries(paired_client, monkeypatch):
    client = paired_client
    clock = frozen(monkeypatch)
    for key in ("gameSessionMinutes", "gameDailyMinutes"):
        for invalid in (0, -1, True, 1.5, "15", 181):
            assert (
                request(
                    client, "/household/settings", {"soundEnabled": True, key: invalid}, "put"
                ).status_code
                == 422
            )
    request(
        client,
        "/household/settings",
        {"soundEnabled": True, "gameSessionMinutes": 7, "gameDailyMinutes": 23},
        "put",
    )
    session = request(client, "/sessions", {"gameId": "shape"}).json()
    task = session["tasks"][0]
    request(client, f"/instances/{task['instanceId']}/hint")
    question = map_by_id("exercises")[task["exercise"]["id"]]
    request(
        client,
        f"/instances/{task['instanceId']}/answer",
        {"requestId": "hinted-game-answer", "answerOptionId": question["answer"]["optionId"]},
    )
    request(client, f"/instances/{session['tasks'][1]['instanceId']}/skip")
    clock[0] += 5
    request(client, "/games/pause")
    data = client.get("/api/v1/games").json()
    assert data["report"]["answered"] == data["report"]["hints"] == data["report"]["skipped"] == 1
    assert data["report"]["independentCorrect"] == 0
    backup = client.get("/api/v1/profiles/export").json()
    validated = _validate_backup(backup)
    with storage.transaction() as db:
        row = db.execute("SELECT * FROM household").fetchone()
        household_id = row["id"]
        device_id = db.execute("SELECT id FROM devices").fetchone()[0]
        _restore_backup(db, household_id, device_id, validated)
    restored = client.get("/api/v1/profiles/export").json()
    assert restored["profile"]["gameState"] == backup["profile"]["gameState"]
    assert restored["sessions"] == backup["sessions"]
    assert restored["profile"]["settings"]["gameSessionMinutes"] == 7
    assert (
        request(
            client, "/profiles/data", {"confirmation": "删除我的学习记录"}, "delete"
        ).status_code
        == 200
    )
    assert client.get("/api/v1/games").json()["clock"]["dailySeconds"] == 5
    assert client.get("/api/v1/games").json()["report"]["answered"] == 0
    old = deepcopy(backup)
    old["profile"].pop("gameState")
    old["profile"]["settings"].pop("gameSessionMinutes")
    old["profile"]["settings"].pop("gameDailyMinutes")
    for session in old["sessions"]:
        session.pop("gameId")
        session.pop("gameRun", None)
    _validate_backup(old)
    bad = deepcopy(backup)
    bad["profile"]["gameState"]["leaseUntil"] = 1e11
    with pytest.raises(HTTPException):
        _validate_backup(bad)


def test_household_concurrent_renewals_are_union_not_sum(paired_client, monkeypatch):
    clock = frozen(monkeypatch)
    request(paired_client, "/games/heartbeat")
    with storage.connect() as db:
        household_id = db.execute("SELECT id FROM household").fetchone()[0]
    clock[0] += 4

    def renew(_):
        with storage.transaction() as db:
            return clock_status(db, household_id, "heartbeat")

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(renew, range(8)))
    assert all(status["dailySeconds"] == 4 for status in statuses)


def test_guest_clock_survives_request_restore_and_never_touches_family(paired_client, monkeypatch):
    from server.guest import GuestOperation, execute

    clock = frozen(monkeypatch)
    before = paired_client.get("/api/v1/profiles/export").json()["profile"]
    first = execute(GuestOperation(path="/games/heartbeat", method="POST"))
    clock[0] += 5
    second = execute(GuestOperation(path="/games", state=first["state"]))
    assert second["result"]["clock"]["dailySeconds"] == 5
    assert paired_client.get("/api/v1/profiles/export").json()["profile"] == before


def test_game_migration_failure_is_atomic(paired_client):
    with storage.transaction() as db:
        db.execute("ALTER TABLE sessions DROP COLUMN game_id")
        for column in ("game_session_minutes", "game_daily_minutes", "game_state_json"):
            db.execute(f"ALTER TABLE household DROP COLUMN {column}")
        db.execute("DELETE FROM schema_migrations WHERE version=8")
        db.execute(
            "CREATE TRIGGER fail_game_migration BEFORE INSERT ON schema_migrations "
            "WHEN NEW.version=8 BEGIN SELECT RAISE(ABORT,'game migration failure'); END;"
        )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError, match="game migration failure"):
        storage.migrate()
    with storage.connect() as db:
        assert "game_state_json" not in {
            row["name"] for row in db.execute("PRAGMA table_info(household)")
        }
        assert "game_id" not in {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
        db.execute("DROP TRIGGER fail_game_migration")
    storage.migrate()
    assert paired_client.get("/api/v1/games").json()["clock"]["dailyMinutes"] == 60


def test_game_backup_import_api_restores_settings_budget_and_source(paired_client, monkeypatch):
    client = paired_client
    clock = frozen(monkeypatch)
    request(
        client,
        "/household/settings",
        {"soundEnabled": True, "gameSessionMinutes": 8, "gameDailyMinutes": 32},
        "put",
    )
    request(client, "/sessions", {"gameId": "shape"})
    clock[0] += 5
    request(client, "/games/pause")
    backup = client.get("/api/v1/profiles/export").json()
    request(
        client,
        "/household/settings",
        {"soundEnabled": True, "gameSessionMinutes": 1, "gameDailyMinutes": 1},
        "put",
    )
    for invalid_id in ([], {}, True, "missing"):
        bad = deepcopy(backup)
        bad["sessions"][0]["gameId"] = invalid_id
        assert request(client, "/profiles/import-preview", bad).status_code == 422
    preview = request(client, "/profiles/import-preview", backup).json()
    result = request(
        client,
        "/profiles/import",
        {
            "previewToken": preview["previewToken"],
            "sha256": preview["sha256"],
            "expectedRevision": preview["revision"],
        },
    )
    assert result.status_code == 200
    status = client.get("/api/v1/games").json()["clock"]
    assert status["sessionMinutes"] == 8 and status["dailyMinutes"] == 32
    assert status["dailySeconds"] == status["sessionSeconds"] == 5
    assert client.get("/api/v1/sessions/current").json()["gameId"] == "shape"
    legacy = deepcopy(backup)
    legacy["profile"].pop("gameState")
    for key in ("gameSessionMinutes", "gameDailyMinutes"):
        legacy["profile"]["settings"].pop(key)
    for session in legacy["sessions"]:
        session.pop("gameId")
        session.pop("gameRun", None)
    preview = request(client, "/profiles/import-preview", legacy).json()
    result = request(
        client,
        "/profiles/import",
        {
            "previewToken": preview["previewToken"],
            "sha256": preview["sha256"],
            "expectedRevision": preview["revision"],
        },
    )
    assert result.status_code == 200
    status = client.get("/api/v1/games").json()["clock"]
    assert status["sessionMinutes"] == 15 and status["dailyMinutes"] == 60
    assert status["dailySeconds"] == 0


def test_daily_limit_survives_break_and_shanghai_midnight_resets_only_day(
    paired_client, monkeypatch
):
    client = paired_client
    now = frozen(monkeypatch, "2026-10-25T15:59:50+00:00")
    request(
        client,
        "/household/settings",
        {"soundEnabled": True, "gameSessionMinutes": 15, "gameDailyMinutes": 1},
        "put",
    )
    with storage.transaction() as db:
        row = db.execute("SELECT id FROM household").fetchone()
        state = {
            **empty_clock(),
            "days": {"2026-10-25": 59},
            "runSeconds": 30,
            "accountedAt": now[0],
            "leaseUntil": now[0],
        }
        db.execute(
            "UPDATE household SET game_state_json=? WHERE id=?", (json.dumps(state), row["id"])
        )
    status = request(client, "/games/heartbeat").json()
    assert status["leaseSeconds"] == 1
    now[0] += 1
    assert request(client, "/games/heartbeat").json()["reason"] == "GAME_DAILY_LIMIT"
    assert (
        request(client, "/sessions", {"gameId": "shape"}).json()["detail"]["code"]
        == "GAME_DAILY_LIMIT"
    )
    now[0] += 10
    status = request(client, "/games/heartbeat").json()
    assert status["reason"] is None and status["dailySeconds"] == 0
    assert status["sessionSeconds"] == 31
    # A pause retains the previous day's total in the portable snapshot.
    request(client, "/games/pause")
    backup = client.get("/api/v1/profiles/export").json()
    assert backup["profile"]["gameState"]["days"]["2026-10-25"] == 60
