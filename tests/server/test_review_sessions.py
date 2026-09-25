from datetime import date, timedelta

from server import storage
from server.content import map_by_id


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


def test_review_session_refuses_early_and_single_question_content(paired_client):
    _set_due_plan(paired_client, due=date.today() + timedelta(days=1))
    early = paired_client.post(
        "/api/v1/reviews/k-tone-4/sessions", json={}, headers=_headers(paired_client)
    )
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "REVIEW_NOT_DUE"
    _set_due_plan(paired_client, knowledge_id="k-letter-y")
    insufficient = paired_client.post(
        "/api/v1/reviews/k-letter-y/sessions", json={}, headers=_headers(paired_client)
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
