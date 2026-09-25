def post(client, path, body=None):
    return client.post(
        path,
        json=body,
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )


def test_rest_prompt_after_two_completed_sessions_and_resume(paired_client):
    client = paired_client
    for round_number in (1, 2):
        session = post(client, "/api/v1/sessions", {}).json()
        for task in session["tasks"]:
            skipped = post(client, f"/api/v1/instances/{task['instanceId']}/skip")
            assert skipped.status_code == 200
        finished = post(client, f"/api/v1/sessions/{session['id']}/finish")
        assert finished.status_code == 200
        assert finished.json()["completedRound"] is True
        assert finished.json()["breakRequired"] is (round_number == 2)

    assert client.get("/api/v1/bootstrap").json()["profile"]["roundsSinceBreak"] == 2
    blocked = post(client, "/api/v1/sessions", {})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "REST_REQUIRED"

    rested = post(client, "/api/v1/rest/complete")
    assert rested.json() == {"breakRequired": False, "breakCompleted": True}
    assert client.get("/api/v1/bootstrap").json()["profile"]["roundsSinceBreak"] == 0
    assert post(client, "/api/v1/sessions", {}).status_code == 200


def test_incomplete_session_does_not_count_as_completed_round(paired_client):
    client = paired_client
    session = post(client, "/api/v1/sessions", {}).json()
    finished = post(client, f"/api/v1/sessions/{session['id']}/finish")
    assert finished.json()["completedRound"] is False
    assert client.get("/api/v1/bootstrap").json()["profile"]["roundsSinceBreak"] == 0


def test_parent_reduced_motion_preference_is_persisted(paired_client):
    client = paired_client
    updated = client.put(
        "/api/v1/household/settings",
        json={"soundEnabled": True, "reducedMotion": True},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert updated.status_code == 200
    assert updated.json()["settings"]["reducedMotion"] is True
    assert client.get("/api/v1/profiles/progress").json()["settings"]["reducedMotion"] is True
    assert (
        client.get("/api/v1/profiles/export").json()["profile"]["settings"]["reducedMotion"] is True
    )
