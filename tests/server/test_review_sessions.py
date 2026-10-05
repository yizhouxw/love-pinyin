from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest

from server import api, storage
from server.content import load_curriculum, map_by_id


def _set_due_plan(client, knowledge_id="k-tone-4", due=None):
    household_id = client.get("/api/v1/bootstrap").json()["profile"]["id"]
    with storage.transaction() as db:
        db.execute(
            "UPDATE household SET selected_lesson_id='lesson-02' WHERE id=?", (household_id,)
        )
        db.execute(
            """INSERT OR REPLACE INTO review_plans(
               household_id,knowledge_id,stage,due_date,updated_at) VALUES(?,?,?,?,?)""",
            (
                household_id,
                knowledge_id,
                0,
                (due or date.today() - timedelta(days=1)).isoformat(),
                "2026-09-01T00:00:00+00:00",
            ),
        )
    return household_id


def _headers(client):
    return {"X-LP-CSRF": client.cookies.get("lp_csrf")}


def test_review_session_has_two_distinct_questions_and_skip_keeps_plan_due(paired_client):
    household_id = _set_due_plan(paired_client)
    response = paired_client.post(
        "/api/v1/reviews/k-tone-4/sessions", json={}, headers=_headers(paired_client)
    )
    assert response.status_code == 200
    session = response.json()
    assert session["reviewKnowledgeId"] == "k-tone-4"
    assert len(session["tasks"]) == 2
    assert len({task["exercise"]["id"] for task in session["tasks"]}) == 2
    for task in session["tasks"]:
        skipped = paired_client.post(
            f"/api/v1/instances/{task['instanceId']}/skip", headers=_headers(paired_client)
        )
        assert skipped.status_code == 200
    paired_client.post(f"/api/v1/sessions/{session['id']}/finish", headers=_headers(paired_client))
    with storage.connect() as db:
        plan = db.execute(
            """SELECT stage,due_date FROM review_plans
               WHERE household_id=? AND knowledge_id='k-tone-4'""",
            (household_id,),
        ).fetchone()
    assert plan["stage"] == 0
    assert plan["due_date"] == (date.today() - timedelta(days=1)).isoformat()


def test_review_session_refuses_early_and_single_question_content(paired_client, monkeypatch):
    _set_due_plan(paired_client, due=date.today() + timedelta(days=1))
    early = paired_client.post(
        "/api/v1/reviews/k-tone-4/sessions", json={}, headers=_headers(paired_client)
    )
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "REVIEW_NOT_DUE"
    _set_due_plan(paired_client, knowledge_id="k-tone-4")
    content = deepcopy(load_curriculum())
    candidates = [q["id"] for q in content["exercises"] if q["primaryKnowledgeId"] == "k-tone-4"]
    for lesson in content["lessons"]:
        lesson["exerciseIds"] = [qid for qid in lesson["exerciseIds"] if qid not in candidates[1:]]
    monkeypatch.setattr(api, "load_curriculum", lambda: content)
    insufficient = paired_client.post(
        "/api/v1/reviews/k-tone-4/sessions", json={}, headers=_headers(paired_client)
    )
    assert insufficient.status_code == 409
    assert insufficient.json()["detail"]["code"] == "REVIEW_CONTENT_INSUFFICIENT"


def test_two_answered_review_questions_that_fail_retry_next_day(paired_client):
    household_id = _set_due_plan(paired_client)
    session = paired_client.post(
        "/api/v1/reviews/k-tone-4/sessions", json={}, headers=_headers(paired_client)
    ).json()
    questions = map_by_id("exercises")
    for index, task in enumerate(session["tasks"]):
        question = questions[task["exercise"]["id"]]
        wrong = next(
            option["id"]
            for option in question["options"]
            if option["id"] != question["answer"]["optionId"]
        )
        response = paired_client.post(
            f"/api/v1/instances/{task['instanceId']}/answer",
            json={"requestId": f"review-fail-{index:02}", "answerOptionId": wrong},
            headers=_headers(paired_client),
        )
        assert response.status_code == 200
    paired_client.post(f"/api/v1/sessions/{session['id']}/finish", headers=_headers(paired_client))
    with storage.connect() as db:
        plan = db.execute(
            """SELECT stage,due_date FROM review_plans
               WHERE household_id=? AND knowledge_id='k-tone-4'""",
            (household_id,),
        ).fetchone()
    assert plan["stage"] == 0
    assert plan["due_date"] == (date.today() + timedelta(days=1)).isoformat()


def test_passing_two_question_review_advances_stage_from_shanghai_completion_day(
    paired_client, monkeypatch
):
    completed_on = date(2026, 9, 27)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 9, 27, 0, 30, tzinfo=UTC)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(api, "datetime", FrozenDateTime)
    household_id = paired_client.get("/api/v1/bootstrap").json()["profile"]["id"]
    questions = [
        question
        for question in map_by_id("exercises").values()
        if question["primaryKnowledgeId"] == "k-tone-4"
        and question["type"] in {"symbol-choice", "tone-choice", "blend-choice"}
    ]
    with storage.transaction() as db:
        device_id = db.execute(
            "SELECT id FROM devices WHERE household_id=? AND revoked_at IS NULL LIMIT 1",
            (household_id,),
        ).fetchone()["id"]
        db.execute(
            "UPDATE household SET selected_lesson_id='lesson-02' WHERE id=?", (household_id,)
        )
        db.execute(
            """INSERT INTO review_plans(
               household_id,knowledge_id,stage,due_date,updated_at) VALUES(?,?,?,?,?)""",
            (household_id, "k-tone-4", 0, "2026-09-26", "2026-09-25T00:00:00+00:00"),
        )
        for index, question in enumerate(questions[:5]):
            instance_id = f"history-instance-{index}"
            occurred_at = datetime(2026, 9, 25, index, tzinfo=UTC).isoformat()
            correct = index != 2
            answer_id = question["answer"]["optionId"]
            db.execute(
                """INSERT INTO exercise_instances(
                   id,household_id,exercise_id,lesson_id,content_version,created_at,session_id,
                   answered_at) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    instance_id,
                    household_id,
                    question["id"],
                    "lesson-02",
                    "test-content-v1",
                    occurred_at,
                    "historical-session",
                    occurred_at,
                ),
            )
            db.execute(
                """INSERT INTO attempts(
                   id,household_id,device_id,instance_id,exercise_id,knowledge_id,mode,
                   first_try_correct,hint_used,due_credit,occurred_at,business_date,answer_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f"history-attempt-{index}",
                    household_id,
                    device_id,
                    instance_id,
                    question["id"],
                    "k-tone-4",
                    question["type"],
                    int(correct),
                    0,
                    1,
                    occurred_at,
                    "2026-09-25",
                    '{"optionId":"' + answer_id + '"}',
                ),
            )

    headers = _headers(paired_client)
    started = paired_client.post("/api/v1/reviews/k-tone-4/sessions", json={}, headers=headers)
    assert started.status_code == 200
    session = started.json()
    assert len(session["tasks"]) == 2
    for index, task in enumerate(session["tasks"]):
        question = map_by_id("exercises")[task["exercise"]["id"]]
        response = paired_client.post(
            f"/api/v1/instances/{task['instanceId']}/answer",
            json={
                "requestId": f"review-pass-{index:02}",
                "answerOptionId": question["answer"]["optionId"],
            },
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["firstTryCorrect"] is True

    finished = paired_client.post(f"/api/v1/sessions/{session['id']}/finish", headers=headers)
    assert finished.status_code == 200
    with storage.connect() as db:
        plan = db.execute(
            "SELECT stage,due_date FROM review_plans WHERE household_id=? AND knowledge_id=?",
            (household_id, "k-tone-4"),
        ).fetchone()
    assert plan["stage"] == 1
    assert plan["due_date"] == (completed_on + timedelta(days=3)).isoformat()


# BANK-03 checks all actual knowledge, with only historical due-state seeded in
# isolated SQLite. Missing standard audio must not leave a one-question review.
@pytest.mark.parametrize("knowledge_id", [k["id"] for k in load_curriculum()["knowledgeItems"]])
def test_all_knowledge_has_two_distinct_available_visual_review_tasks(paired_client, knowledge_id):
    client = paired_client
    household_id = _set_due_plan(client, knowledge_id=knowledge_id)
    with storage.transaction() as db:
        db.execute(
            "UPDATE household SET selected_lesson_id='lesson-14' WHERE id=?", (household_id,)
        )
    response = client.post(
        f"/api/v1/reviews/{knowledge_id}/sessions", json={}, headers=_headers(client)
    )
    assert response.status_code == 200, response.text
    session = response.json()
    assert len(session["tasks"]) == 2
    assert len({t["exercise"]["id"] for t in session["tasks"]}) == 2
    questions = map_by_id("exercises")
    for index, task in enumerate(session["tasks"]):
        question = questions[task["exercise"]["id"]]
        assert question["primaryKnowledgeId"] == knowledge_id
        assert not question.get("audioRef")
        answered = client.post(
            f"/api/v1/instances/{task['instanceId']}/answer",
            json={
                "requestId": f"bank03-review-{index}",
                "answerOptionId": question["answer"]["optionId"],
            },
            headers=_headers(client),
        )
        assert answered.status_code == 200
        assert answered.json()["correct"] is True
    finished = client.post(f"/api/v1/sessions/{session['id']}/finish", headers=_headers(client))
    assert finished.status_code == 200
    assert finished.json()["completedRound"] is True
    assert len(client.get("/api/v1/profiles/progress").json()["attempts"]) == 2
