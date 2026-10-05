from datetime import UTC, datetime, timedelta

import pytest

from server.content import load_curriculum
from server.domain import PracticeCompletion, plan_practice

BASE = datetime(2026, 10, 5, tzinfo=UTC)


def test_rotation_prefers_unseen_then_less_practiced_then_older_completion():
    history = [
        PracticeCompletion("a", BASE),
        PracticeCompletion("a", BASE + timedelta(days=1)),
        PracticeCompletion("b", BASE + timedelta(hours=1)),
        PracticeCompletion("c", BASE),
        PracticeCompletion("another-lesson", BASE),
    ]
    assert plan_practice(["a", "b", "c", "d", "d"], history) == ["d", "c", "b", "a"]
    assert plan_practice(["a", "b", "c", "d"], history, limit=2) == ["d", "c"]
    assert plan_practice([], history) == []


def test_rotation_normalizes_timezones_and_preserves_content_order_for_ties():
    history = [
        PracticeCompletion("a", datetime.fromisoformat("2026-10-05T09:00:00+08:00")),
        PracticeCompletion("b", datetime.fromisoformat("2026-10-05T02:00:00+00:00")),
        PracticeCompletion("c", datetime.fromisoformat("2026-10-05T01:00:00+00:00")),
    ]
    assert plan_practice(["b", "c", "a"], history) == ["c", "a", "b"]
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_practice(["a"], [PracticeCompletion("a", datetime(2026, 10, 5))])
    with pytest.raises(ValueError, match="positive"):
        plan_practice(["a"], [], limit=0)


def post(client, path, body=None):
    response = client.post(path, json=body, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")})
    assert response.status_code == 200, response.text
    return response.json()


def test_only_completed_or_skipped_tasks_rotate_and_reload_keeps_frozen_list(paired_client):
    client = paired_client
    original = post(client, "/api/v1/sessions", {})
    original_ids = [task["exercise"]["id"] for task in original["tasks"]]
    post(client, f"/api/v1/sessions/{original['id']}/finish")
    again = post(client, "/api/v1/sessions", {})
    assert [task["exercise"]["id"] for task in again["tasks"]] == original_ids
    first, second = again["tasks"][:2]
    post(client, f"/api/v1/instances/{first['instanceId']}/skip")
    correct = next(q for q in load_curriculum()["exercises"] if q["id"] == second["exercise"]["id"])
    post(
        client,
        f"/api/v1/instances/{second['instanceId']}/answer",
        {"requestId": "rotation-answer-01", "answerOptionId": correct["answer"]["optionId"]},
    )
    assert client.get("/api/v1/sessions/current").json()["tasks"] == again["tasks"]
    post(client, f"/api/v1/sessions/{again['id']}/finish")
    next_session = post(client, "/api/v1/sessions", {})
    next_ids = [task["exercise"]["id"] for task in next_session["tasks"]]
    assert first["exercise"]["id"] not in next_ids
    assert second["exercise"]["id"] not in next_ids
    assert next_ids[0] == original_ids[2]  # Created but not reached, so still unseen.
    assert any(question_id.startswith("q-01-2") for question_id in next_ids)
    progress = client.get("/api/v1/profiles/progress").json()
    assert len(progress["attempts"]) == 1  # A skip is never a scored answer.
    cleared = client.request(
        "DELETE",
        "/api/v1/profiles/data",
        json={"confirmation": "删除我的学习记录"},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert cleared.status_code == 200
    reset = post(client, "/api/v1/sessions", {})
    assert [task["exercise"]["id"] for task in reset["tasks"]] == original_ids


@pytest.mark.parametrize("lesson_id", [f"lesson-{index:02d}" for index in range(1, 15)])
def test_every_lesson_has_six_real_tasks_and_all_authored_visual_tasks_are_reachable(
    paired_client, lesson_id
):
    client = paired_client
    content = load_curriculum()
    expected = {
        q["id"]
        for q in content["exercises"]
        if q["lessonId"] == lesson_id
        and q["type"] in {"symbol-choice", "tone-choice", "blend-choice"}
        and not q.get("audioRef")
    }
    assert len(expected) >= 6
    profile = client.get("/api/v1/profiles/progress").json()
    changed = client.put(
        "/api/v1/household/current-lesson",
        json={"lessonId": lesson_id, "expectedRevision": profile["revision"]},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert changed.status_code == 200
    seen = set()
    for round_index in range((len(expected) + 5) // 6):
        if round_index and round_index % 2 == 0:
            post(client, "/api/v1/rest/complete")
        session = post(client, "/api/v1/sessions", {})
        ids = [task["exercise"]["id"] for task in session["tasks"]]
        assert len(ids) == len(set(ids)) == 6
        assert set(ids) <= expected
        unseen = expected - seen
        assert unseen & set(ids)
        if len(unseen) >= 6:
            assert not (set(ids) & seen)
        for task in session["tasks"]:
            post(client, f"/api/v1/instances/{task['instanceId']}/skip")
        finished = post(client, f"/api/v1/sessions/{session['id']}/finish")
        assert finished["completedRound"]
        seen.update(ids)
        if seen == expected:
            break
    assert seen == expected
    assert client.get("/api/v1/profiles/progress").json()["attempts"] == []
