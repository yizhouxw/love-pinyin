def mutable_post(client, path, json=None):
    return client.post(
        path,
        json=json,
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )


def test_skip_is_recoverable_and_does_not_create_attempt(paired_client):
    client = paired_client
    started = mutable_post(client, "/api/v1/sessions", json={}).json()
    task = started["tasks"][0]

    skipped = mutable_post(client, f"/api/v1/instances/{task['instanceId']}/skip")
    assert skipped.status_code == 200
    assert skipped.json()["skipped"] is True

    # A retried skip is idempotent, and a refresh recovers it as a completed
    # task without treating it as an answer or mastery event.
    assert mutable_post(client, f"/api/v1/instances/{task['instanceId']}/skip").status_code == 200
    current = client.get("/api/v1/sessions/current").json()
    assert current["results"][task["instanceId"]]["skipped"] is True
    assert client.get("/api/v1/profiles/progress").json()["attempts"] == []
    exported = client.get("/api/v1/profiles/export").json()
    assert exported["sessions"][0]["id"] == started["id"]
    assert exported["skippedInstances"][0]["instanceId"] == task["instanceId"]

    answered = mutable_post(
        client,
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={
            "requestId": "skip-test-request-01",
            "answerOptionId": task["exercise"]["options"][0]["id"],
        },
    )
    assert answered.status_code == 409
    assert answered.json()["detail"]["code"] == "INSTANCE_ALREADY_SKIPPED"


def test_skipped_task_requires_active_owned_session(paired_client):
    client = paired_client
    started = mutable_post(client, "/api/v1/sessions", json={}).json()
    task = started["tasks"][0]
    finished = mutable_post(client, f"/api/v1/sessions/{started['id']}/finish")
    assert finished.status_code == 200
    assert finished.json()["completedRound"] is False

    response = mutable_post(client, f"/api/v1/instances/{task['instanceId']}/skip")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_NOT_ACTIVE"
    assert client.get("/api/v1/profiles/progress").json()["attempts"] == []


def test_garden_counts_only_fully_completed_sessions(paired_client):
    client = paired_client
    started = mutable_post(client, "/api/v1/sessions", json={}).json()

    # Finishing early does not earn a leaf, even though the session is closed.
    early = mutable_post(client, f"/api/v1/sessions/{started['id']}/finish")
    assert early.json()["completedRound"] is False
    assert client.get("/api/v1/profiles/progress").json()["completedSessions"] == 0

    # The same closed session cannot be completed retroactively.
    for task in started["tasks"]:
        skipped = mutable_post(client, f"/api/v1/instances/{task['instanceId']}/skip")
        assert skipped.status_code == 409

    complete = mutable_post(client, "/api/v1/sessions", json={}).json()
    for task in complete["tasks"]:
        skipped = mutable_post(client, f"/api/v1/instances/{task['instanceId']}/skip")
        assert skipped.status_code == 200
    finished = mutable_post(client, f"/api/v1/sessions/{complete['id']}/finish")
    assert finished.json()["completedRound"] is True
    assert client.get("/api/v1/profiles/progress").json()["completedSessions"] == 1

    # Completion is derived from retained sessions, so deleting learning data
    # also removes the garden growth.
    deleted = client.request(
        "DELETE",
        "/api/v1/profiles/data",
        json={"confirmation": "删除我的学习记录"},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert deleted.status_code == 200
    assert client.get("/api/v1/profiles/progress").json()["completedSessions"] == 0
