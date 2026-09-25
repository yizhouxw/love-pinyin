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
    assert mutable_post(client, f"/api/v1/sessions/{started['id']}/finish").status_code == 204

    response = mutable_post(client, f"/api/v1/instances/{task['instanceId']}/skip")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_NOT_ACTIVE"
    assert client.get("/api/v1/profiles/progress").json()["attempts"] == []
