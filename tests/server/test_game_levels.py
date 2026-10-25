"""LEVEL-01/03/04: complete routes, different phonetic tasks, frozen portable data."""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from server import storage
from server.game_levels import catalog, validate_catalog
from server.profile_backup import _restore_backup, _validate_backup
from tests.server.test_game_zone import request


def test_entire_catalog_is_well_formed_and_rich():
    assert validate_catalog() == {"levels": 24, "chapters": 72, "slots": 288, "patterns": 48}
    data = catalog()
    assert (
        len(
            {
                tuple(s["patternId"] for c in level["chapters"] for s in c["segments"])
                for level in data["levels"]
            }
        )
        == 24
    )
    for scene in ("runner", "boat", "space"):
        assert (
            sum(len(p["obstacles"]) for p in data["patterns"].values() if p["scene"] == scene) >= 30
        )
    assert all(len(p["beats"]) >= 5 for p in data["patterns"].values() if p["scene"] == "drum")


@pytest.mark.parametrize("level", catalog()["levels"], ids=lambda level: level["id"])
def test_every_level_binds_twelve_real_different_learned_tasks(
    paired_client, registered_audio_catalog, level
):
    response = request(
        paired_client, "/sessions", {"gameId": level["gameId"], "gameLevelId": level["id"]}
    )
    assert response.status_code == 200, response.text
    session = response.json()
    run = session["gameRun"]
    assert run["level"]["id"] == level["id"]
    assert len(session["tasks"]) == 12
    assert len({t["exercise"]["id"] for t in session["tasks"]}) == 12
    assert len({t["exercise"]["primaryKnowledgeId"] for t in session["tasks"]}) >= 3
    assert len({t["exercise"]["audioRef"] for t in session["tasks"]}) >= 3
    assert all(t["exercise"]["lessonId"] == "lesson-01" for t in session["tasks"])
    assert [b["instanceId"] for b in run["bindings"]] == [t["instanceId"] for t in session["tasks"]]
    assert paired_client.get("/api/v1/sessions/current").json()["gameRun"] == run
    assert paired_client.get("/api/v1/profiles/export").json()["attempts"] == []


def test_frozen_run_survives_catalog_change_and_backup_roundtrip(
    paired_client, registered_audio_catalog, monkeypatch
):
    import server.game_levels as levels

    client = paired_client
    session = request(client, "/sessions", {"gameId": "sound", "gameLevelId": "runner-06"}).json()
    backup = client.get("/api/v1/profiles/export").json()
    future = deepcopy(catalog())
    future["levels"][5]["title"] = "未来修订的路线"
    monkeypatch.setattr(levels, "catalog", lambda: future)
    assert client.get("/api/v1/sessions/current").json()["gameRun"] == session["gameRun"]
    validated = _validate_backup(backup)
    with storage.transaction() as db:
        h = db.execute("SELECT id FROM household").fetchone()[0]
        d = db.execute("SELECT id FROM devices").fetchone()[0]
        _restore_backup(db, h, d, validated)
    assert client.get("/api/v1/sessions/current").json()["gameRun"] == session["gameRun"]
    for change in ("binding", "geometry", "version", "scene"):
        bad = deepcopy(backup)
        run = bad["sessions"][0]["gameRun"]
        if change == "binding":
            run["bindings"][0]["instanceId"] = "unrelated-task"
        elif change == "geometry":
            next(iter(run["patterns"].values()))["obstacles"][0]["at"] = 1e10
        elif change == "version":
            run["version"] = True
        else:
            run["level"]["scene"] = "boat"
        with pytest.raises(HTTPException):
            _validate_backup(bad)
    assert (
        request(client, "/sessions", {"gameId": "sound", "gameLevelId": "space-01"}).status_code
        == 422
    )
    assert client.get("/api/v1/sessions/current").json()["id"] == session["id"]


def test_bad_route_data_is_rejected_before_runtime(monkeypatch):
    from server import game_levels

    original = catalog()
    for kind in ("missing-pattern", "wrong-scene", "off-route", "duplicate-segment"):
        bad = deepcopy(original)
        if kind == "missing-pattern":
            bad["levels"][0]["chapters"][0]["segments"][0]["patternId"] = "missing"
        elif kind == "wrong-scene":
            bad["patterns"]["runner-route-01"]["scene"] = "boat"
        elif kind == "off-route":
            bad["patterns"]["drum-route-01"]["beats"] = [99999]
        else:
            bad["levels"][0]["chapters"][0]["segments"][1]["id"] = "segment-01"
        monkeypatch.setattr(game_levels, "catalog", lambda bad=bad: bad)
        with pytest.raises((ValueError, KeyError)):
            validate_catalog()


def test_level_migration_failure_rolls_back_atomically(paired_client):
    import sqlite3

    with storage.transaction() as db:
        db.execute("ALTER TABLE sessions DROP COLUMN game_run_json")
        db.execute("DELETE FROM schema_migrations WHERE version=10")
        db.execute(
            "CREATE TRIGGER fail_level BEFORE INSERT ON schema_migrations "
            "WHEN NEW.version=10 BEGIN SELECT RAISE(ABORT,'level failure'); END;"
        )
    with pytest.raises(sqlite3.IntegrityError, match="level failure"):
        storage.migrate()
    with storage.connect() as db:
        assert "game_run_json" not in {
            row["name"] for row in db.execute("PRAGMA table_info(sessions)")
        }
        db.execute("DROP TRIGGER fail_level")
    storage.migrate()
    assert paired_client.get("/api/v1/sessions/current").status_code == 200


def test_many_complete_routes_backup_roundtrips_past_old_one_mebibyte_limit(
    paired_client, registered_audio_catalog
):
    import json

    client = paired_client
    # Real session creation and route snapshots, with no child data or fabricated scores.
    for _ in range(125):
        response = request(client, "/sessions", {"gameId": "sound", "gameLevelId": "runner-06"})
        assert response.status_code == 200
    backup = client.get("/api/v1/profiles/export").json()
    assert len(json.dumps(backup).encode()) > 1_048_576
    preview = request(client, "/profiles/import-preview", backup)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    restored = request(
        client,
        "/profiles/import",
        {
            "previewToken": plan["previewToken"],
            "sha256": plan["sha256"],
            "expectedRevision": plan["revision"],
        },
    )
    assert restored.status_code == 200, restored.text
    result = client.get("/api/v1/profiles/export").json()
    assert result["sessions"] == backup["sessions"]
    assert result["attempts"] == []
