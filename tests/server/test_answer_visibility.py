from server.content import map_by_id


def test_curriculum_and_session_hide_answer_and_hint_until_requested(paired_client):
    client = paired_client
    course = client.get("/api/v1/curriculum").json()
    assert course["exercises"]
    assert all("answer" not in row and "hint" not in row for row in course["exercises"])

    session = client.post(
        "/api/v1/sessions",
        json={},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    ).json()
    task = session["tasks"][0]
    assert "answer" not in task["exercise"]
    assert "hint" not in task["exercise"]

    expected = map_by_id("exercises")[task["exercise"]["id"]]["answer"]["optionId"]
    result = client.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={"requestId": "hidden-answer-test-01", "answerOptionId": expected},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert result.status_code == 200
    assert result.json()["correctOptionId"] == expected
