from server import storage


def _csrf(client):
    return {"X-LP-CSRF": client.cookies.get("lp_csrf")}


def test_unknown_saved_lesson_requires_reselection_without_losing_history(paired_client):
    client = paired_client
    original = client.post("/api/v1/sessions", json={}, headers=_csrf(client)).json()
    for task in original["tasks"]:
        response = client.post(
            f"/api/v1/instances/{task['instanceId']}/skip", headers=_csrf(client)
        )
        assert response.status_code == 200
    completed = client.post(f"/api/v1/sessions/{original['id']}/finish", headers=_csrf(client))
    assert completed.json()["completedRound"] is True

    household_id = client.get("/api/v1/bootstrap").json()["profile"]["id"]
    with storage.transaction() as db:
        db.execute(
            """UPDATE household SET selected_lesson_id='retired-lesson-v0',revision=revision+1
               WHERE id=?""",
            (household_id,),
        )

    progress = client.get("/api/v1/profiles/progress").json()
    assert progress["selectedLessonId"] == "retired-lesson-v0"
    assert progress["completedSessions"] == 1

    regular = client.post("/api/v1/sessions", json={"lessonId": "lesson-02"}, headers=_csrf(client))
    review = client.post("/api/v1/reviews/k-tone-4/sessions", json={}, headers=_csrf(client))
    assert regular.status_code == review.status_code == 409
    assert regular.json()["detail"]["code"] == "CURRENT_LESSON_REQUIRES_SELECTION"
    assert review.json()["detail"]["code"] == "CURRENT_LESSON_REQUIRES_SELECTION"

    with storage.connect() as db:
        sessions_before_reselection = db.execute(
            "SELECT COUNT(*) FROM sessions WHERE household_id=?", (household_id,)
        ).fetchone()[0]
    assert sessions_before_reselection == 1

    selected = client.put(
        "/api/v1/household/current-lesson",
        json={"lessonId": "lesson-02", "expectedRevision": progress["revision"]},
        headers=_csrf(client),
    )
    assert selected.status_code == 200
    assert selected.json()["selectedLessonId"] == "lesson-02"
    after_selection = client.get("/api/v1/profiles/progress").json()
    assert after_selection["completedSessions"] == 1
    assert client.post("/api/v1/sessions", json={}, headers=_csrf(client)).status_code == 200
