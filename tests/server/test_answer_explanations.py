import pytest

from server.content import load_curriculum
from server.routes import attempts as attempt_routes


@pytest.mark.parametrize("correct", [True, False])
def test_explanation_is_frozen_in_receipt_and_does_not_use_hint(
    paired_client, monkeypatch, correct
):
    client = paired_client
    headers = {"X-LP-CSRF": client.cookies.get("lp_csrf")}
    session = client.post("/api/v1/sessions", json={}, headers=headers).json()
    task = session["tasks"][0]
    question = next(q for q in load_curriculum()["exercises"] if q["id"] == task["exercise"]["id"])
    option = next(
        o["id"]
        for o in question["options"]
        if (o["id"] == question["answer"]["optionId"]) == correct
    )
    body = {"requestId": "feedback-receipt-0001", "answerOptionId": option}
    route = f"/api/v1/instances/{task['instanceId']}/answer"
    response = client.post(route, json=body, headers=headers)
    assert response.status_code == 200
    result = response.json()
    audio_id = f"hint-{question['id']}"
    assert result["explanation"] == attempt_routes.narration_scripts()[audio_id]
    assert result["explanationAudioId"] == audio_id
    assert result["firstTryCorrect"] is correct
    assert result["hintUsed"] is False
    monkeypatch.setattr(attempt_routes, "narration_scripts", lambda: {audio_id: "修改后的脚本"})
    assert client.post(route, json=body, headers=headers).json() == result
    assert client.get(f"/api/v1/attempts/{body['requestId']}").json() == result
    attempts = client.get("/api/v1/profiles/export").json()["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["hint_used"] == 0
    assert attempts[0]["first_try_correct"] == int(correct)
