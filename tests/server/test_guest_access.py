"""Guest progress is returned to the caller, never persisted in the household DB."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from server import api, storage
from server.guest import GuestOperation, execute
from server.main import app


def snapshot():
    with storage.connect() as db:
        return list(db.iterdump())


def operate(client, path, state=None, method="GET", body=None):
    response = client.post(
        "/api/v1/guest/operate",
        json={"path": path, "method": method, "body": body or {}, "state": state},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_guest_answer_refresh_finish_and_isolation(paired_client):
    before = snapshot()
    guest = operate(paired_client, "/bootstrap")
    assert guest["result"]["guest"]
    state = guest["state"]
    started = operate(paired_client, "/sessions", state, "POST", {"lessonId": "lesson-01"})
    task = started["result"]["tasks"][0]
    hinted = operate(
        paired_client, f"/instances/{task['instanceId']}/hint", started["state"], "POST"
    )
    body = {
        "requestId": "guest-answer-01",
        "answerOptionId": hinted["result"]["answer"]["optionId"],
    }
    answered = operate(
        paired_client, f"/instances/{task['instanceId']}/answer", hinted["state"], "POST", body
    )
    assert answered["result"]["correct"]
    assert not answered["result"]["firstTryCorrect"]
    assert len(answered["state"]["attempts"]) == 1
    # Every request reconstitutes an isolated in-memory database, like a reload.
    restored = operate(paired_client, "/sessions/current", answered["state"])
    assert task["instanceId"] in restored["result"]["results"]
    repeat = operate(
        paired_client, f"/instances/{task['instanceId']}/answer", answered["state"], "POST", body
    )
    assert len(repeat["state"]["attempts"]) == 1
    finished = operate(
        paired_client, f"/sessions/{started['result']['id']}/finish", restored["state"], "POST"
    )
    stats = operate(paired_client, "/profiles/progress", finished["state"])
    assert stats["result"]["attemptCount"] == 1
    assert operate(paired_client, "/profiles/progress")["result"]["attemptCount"] == 0
    assert snapshot() == before


def test_guest_settings_revision_and_concurrent_scopes(test_client):
    before = snapshot()
    guest = operate(test_client, "/bootstrap")
    changed = operate(
        test_client,
        "/household/current-lesson",
        guest["state"],
        "PUT",
        {
            "lessonId": "lesson-03",
            "expectedRevision": 0,
        },
    )
    settings = operate(
        test_client,
        "/household/settings",
        changed["state"],
        "PUT",
        {
            "soundEnabled": True,
            "reducedMotion": True,
        },
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                execute,
                [
                    GuestOperation(path="/profiles/progress", state=settings["state"]),
                    GuestOperation(path="/profiles/progress"),
                ],
            )
        )
    assert results[0]["result"]["selectedLessonId"] == "lesson-03"
    assert results[0]["result"]["settings"]["reducedMotion"]
    assert results[1]["result"]["selectedLessonId"] == "lesson-01"
    assert snapshot() == before


def test_guest_rejects_family_operations_and_invalid_state(test_client):
    before = snapshot()
    for path in [
        "/profiles/export",
        "/pairing-codes",
        "/local/pairing-code",
        "/devices",
        "/profiles/reset",
    ]:
        response = test_client.post("/api/v1/guest/operate", json={"path": path, "method": "POST"})
        assert response.status_code == 404
    assert (
        test_client.post(
            "/api/v1/guest/operate", json={"path": "/bootstrap", "state": {}}
        ).status_code
        == 422
    )
    assert test_client.post("/api/v1/guest/operate", content=b"x" * 1_048_577).status_code == 413
    assert (
        test_client.post(
            "/api/v1/guest/operate",
            json={"path": "/bootstrap"},
            headers={"origin": "https://other.invalid"},
        ).status_code
        == 403
    )
    assert test_client.get("/api/v1/profiles/progress").status_code == 401
    assert snapshot() == before


def test_guest_real_audio_uses_same_validated_source(test_client, install_standard):
    target = api.load_curriculum()["audioRequirements"][0]
    install_standard(target)
    response = test_client.get(
        f"/api/v1/guest/audio/{target['id']}", headers={"Range": "bytes=0-3"}
    )
    assert response.status_code == 206
    assert len(response.content) == 4
    assert test_client.get("/api/v1/guest/audio/missing").status_code == 404
    assert test_client.get("/api/v1/guest/voice/missing").status_code == 404
    assert test_client.get("/api/v1/guest/curriculum").status_code == 200
    assert test_client.get("/api/v1/guest/learning-audio").status_code == 200


def test_expired_cookie_keeps_local_pairing_entry(test_client):
    test_client.cookies.set("lp_session", "expired")
    response = test_client.get("/api/v1/bootstrap")
    assert response.status_code == 200
    assert response.json()["isLocalHost"]
    assert not response.json()["paired"]
    with TestClient(app, base_url="http://mac.local", client=("192.168.1.50", 4000)) as remote:
        assert not remote.get("/api/v1/bootstrap").json()["isLocalHost"]
        assert remote.post("/api/v1/local/pairing-code").status_code == 403
