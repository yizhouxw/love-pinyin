"""PLAY-01/02: configurable frozen journeys and portable in-game settings."""

from copy import deepcopy

import pytest

from server import storage
from server.game_levels import catalog, freeze_run, valid_run
from server.profile_backup import _restore_backup, _validate_backup
from tests.server.test_game_zone import request


@pytest.mark.parametrize("size", [3, 6, 20])
@pytest.mark.parametrize("level", catalog()["levels"], ids=lambda level: level["id"])
def test_all_routes_configure_multiple_learned_targets(
    paired_client, registered_audio_catalog, level, size
):
    client = paired_client
    response = request(
        client,
        "/sessions",
        {"gameId": level["gameId"], "gameLevelId": level["id"], "gameTaskCount": size},
    )
    assert response.status_code == 200, response.text
    session = response.json()
    assert len(session["tasks"]) == size
    assert len({t["exercise"]["id"] for t in session["tasks"]}) == size
    assert len({t["exercise"]["primaryKnowledgeId"] for t in session["tasks"]}) >= 3
    assert all(t["exercise"]["lessonId"] == "lesson-01" for t in session["tasks"])
    run = session["gameRun"]
    assert run["version"] == 2
    assert valid_run(run, level["gameId"], [t["instanceId"] for t in session["tasks"]])
    assert (
        max(len(c["segments"]) for c in run["level"]["chapters"])
        - min(len(c["segments"]) for c in run["level"]["chapters"])
        <= 1
    )
    assert all(p["choiceAt"] <= 360 for p in run["patterns"].values())
    backup = client.get("/api/v1/profiles/export").json()
    _validate_backup(backup)
    with storage.transaction() as db:
        h = db.execute("SELECT id FROM household").fetchone()[0]
        d = db.execute("SELECT id FROM devices").fetchone()[0]
        _restore_backup(db, h, d, backup)
    assert client.get("/api/v1/sessions/current").json()["gameRun"] == run


@pytest.mark.parametrize("size", [2, 21, 3.5, True, "6", None])
def test_invalid_count_does_not_replace_active_game(paired_client, registered_audio_catalog, size):
    client = paired_client
    session = request(client, "/sessions", {"gameId": "sound"}).json()
    assert len(session["tasks"]) == 6
    assert (
        request(client, "/sessions", {"gameId": "sound", "gameTaskCount": size}).status_code == 422
    )
    assert client.get("/api/v1/sessions/current").json()["id"] == session["id"]


def test_settings_change_preserves_frozen_teaching_and_backup(
    paired_client, registered_audio_catalog
):
    client = paired_client
    original = request(client, "/sessions", {"gameId": "tone"}).json()
    route = f"/sessions/{original['id']}/game-settings"
    response = request(client, route, {"difficulty": "challenge", "speed": "fast"}, "patch")
    assert response.status_code == 200, response.text
    changed = client.get("/api/v1/sessions/current").json()
    assert changed["gameSettings"]["level"] == "challenge"
    assert changed["gameSettings"]["speed"] == "fast"
    assert changed["gameSettings"]["recommendation"] == original["gameSettings"]["recommendation"]
    assert changed["tasks"] == original["tasks"]
    assert changed["gameRun"] == original["gameRun"]
    backup = client.get("/api/v1/profiles/export").json()
    _validate_backup(backup)
    assert backup["attempts"] == []
    assert backup["sessions"][0]["gameSettings"] == changed["gameSettings"]
    assert (
        request(client, route, {"difficulty": "warp", "speed": "slow"}, "patch").status_code == 422
    )
    auto = request(client, route, {"difficulty": "auto", "speed": "auto"}, "patch").json()
    assert auto["level"] == original["gameSettings"]["recommendation"]["level"]
    request(client, f"/sessions/{original['id']}/finish", {})
    assert (
        request(client, route, {"difficulty": "gentle", "speed": "slow"}, "patch").status_code
        == 404
    )


def test_old_twelve_task_run_stays_valid_and_cannot_be_silently_truncated():
    level = catalog()["levels"][0]
    old = freeze_run(level, [{"instanceId": f"old-{i}"} for i in range(12)], version=1)
    assert valid_run(old, "sound")
    damaged = deepcopy(old)
    damaged["bindings"].pop()
    assert not valid_run(damaged, "sound")
    damaged = deepcopy(old)
    damaged["level"]["chapters"][0]["segments"].pop()
    damaged["bindings"].pop(3)
    assert not valid_run(damaged, "sound")


def test_guest_settings_are_saved_in_snapshot_without_family_writes(
    test_client, registered_audio_catalog
):
    def guest(path, method="GET", body=None, state=None):
        response = test_client.post(
            "/api/v1/guest/operate",
            json={"path": path, "method": method, "body": body or {}, "state": state},
        )
        assert response.status_code == 200, response.text
        return response.json()

    started = guest("/sessions", "POST", {"gameId": "shape", "gameTaskCount": 20})
    # The transport returns the actual API result alongside the updated ephemeral backup.
    result = started["result"]
    updated = guest(
        f"/sessions/{result['id']}/game-settings",
        "PATCH",
        {"difficulty": "steady", "speed": "fast"},
        started["state"],
    )
    current = guest("/sessions/current", state=updated["state"])
    assert current["result"]["gameSettings"]["level"] == "steady"
    assert len(current["result"]["tasks"]) == 20
