"""ADAPT-01/02 real range, evidence thresholds and frozen portable scene settings."""

import pytest

from server import storage
from server.content import load_curriculum
from server.game_adaptation import plan_game, recommend, valid_settings
from tests.server.test_game_zone import request


def test_recommendations_need_real_evidence_and_do_not_recommend_fast():
    assert recommend({})["level"] == "gentle"
    assert recommend({"a": {"sampleSize": 8, "correctCount": 5}})["level"] == "gentle"
    assert recommend({"a": {"sampleSize": 8, "correctCount": 6}})["level"] == "steady"
    skilled = {str(i): {"sampleSize": 8, "correctCount": 7, "status": "mastered"} for i in range(4)}
    assert recommend(skilled)["level"] == "challenge"
    assert recommend(skilled)["speed"] == "normal"


def test_planner_prefers_weak_and_current_without_repeats():
    questions = [
        {"id": f"q{i}", "lessonId": "current" if i >= 6 else "old", "primaryKnowledgeId": str(i)}
        for i in range(12)
    ]
    chosen = plan_game(questions, [], {"2": {"status": "practicing"}}, "current")
    assert chosen == ["q2", "q6", "q7", "q8", "q9", "q10"]
    assert len(plan_game(questions, [], {}, "current")) == 6


@pytest.mark.parametrize("game_id", ["sound", "tone", "shape", "blend"])
def test_all_scenes_start_first_lesson_and_freeze_manual_settings(
    paired_client, registered_audio_catalog, game_id
):
    client = paired_client
    response = request(
        client, "/sessions", {"gameId": game_id, "gameDifficulty": "challenge", "gameSpeed": "fast"}
    )
    assert response.status_code == 200, response.text
    session = response.json()
    assert all(task["exercise"]["lessonId"] == "lesson-01" for task in session["tasks"])
    assert all(task["exercise"].get("audioRef") for task in session["tasks"])
    settings = session["gameSettings"]
    assert settings["level"] == "challenge" and settings["speed"] == "fast"
    assert settings["recommendation"]["level"] == "gentle"
    assert client.get("/api/v1/sessions/current").json()["gameSettings"] == settings
    exported = client.get("/api/v1/profiles/export").json()
    assert exported["sessions"][0]["gameSettings"] == settings
    from server.profile_backup import _restore_backup, _validate_backup

    _validate_backup(exported)
    with storage.transaction() as db:
        profile = db.execute("SELECT * FROM household").fetchone()
        device = db.execute("SELECT * FROM devices").fetchone()
        _restore_backup(db, profile["id"], device["id"], exported)
    assert client.get("/api/v1/sessions/current").json()["gameSettings"] == settings
    # The game does not manufacture attempts while only flying/rowing.
    assert client.get("/api/v1/profiles/export").json()["attempts"] == []
    assert request(client, "/sessions", {"gameId": game_id, "gameSpeed": "warp"}).status_code == 422


def test_settings_validation_rejects_malformed_and_accepts_legacy():
    assert valid_settings({})
    assert not valid_settings([])
    assert not valid_settings({"version": 1})


def test_adaptive_auto_ignores_future_knowledge(
    paired_client, registered_audio_catalog, monkeypatch
):
    import server.routes.sessions as sessions

    future = next(
        k["id"] for k in load_curriculum()["knowledgeItems"] if k["lessonId"] == "lesson-03"
    )
    monkeypatch.setattr(
        sessions,
        "_mastery",
        lambda *_: {future: {"sampleSize": 99, "correctCount": 99, "status": "mastered"}},
    )
    session = request(paired_client, "/sessions", {"gameId": "blend"}).json()
    assert session["gameSettings"]["level"] == "gentle"
    assert session["gameSettings"]["recommendation"]["sampleSize"] == 0


@pytest.mark.parametrize("game_id", ["sound", "tone", "shape", "blend"])
def test_scene_genre_does_not_trap_later_learners_in_first_lesson(
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
    session = request(client, "/sessions", {"gameId": game_id}).json()
    assert len(session["tasks"]) == 6
    assert all(t["exercise"]["lessonId"] == "lesson-03" for t in session["tasks"])
