def post_answer(client, instance_id, request_id, option_id):
    return client.post(
        f"/api/v1/instances/{instance_id}/answer",
        json={"requestId": request_id, "answerOptionId": option_id},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )


def test_retry_returns_same_result_without_incrementing_revision(paired_client):
    client = paired_client
    session = client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")}
    ).json()
    task = session["tasks"][0]
    option_id = task["exercise"]["options"][0]["id"]
    before = client.get("/api/v1/bootstrap").json()["profile"]["revision"]

    first = post_answer(client, task["instanceId"], "answer-retry-request-0001", option_id)
    retried = post_answer(client, task["instanceId"], "answer-retry-request-0001", option_id)

    assert first.status_code == retried.status_code == 200
    assert retried.json() == first.json()
    assert client.get("/api/v1/bootstrap").json()["profile"]["revision"] == before + 1
    assert len(client.get("/api/v1/profiles/progress").json()["attempts"]) == 1


def test_request_id_cannot_be_reused_for_another_answer(paired_client):
    client = paired_client
    session = client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")}
    ).json()
    task = session["tasks"][0]
    options = task["exercise"]["options"]
    request_id = "answer-retry-request-0002"
    accepted = post_answer(client, task["instanceId"], request_id, options[0]["id"])
    conflict = post_answer(client, task["instanceId"], request_id, options[1]["id"])

    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(client.get("/api/v1/profiles/progress").json()["attempts"]) == 1
