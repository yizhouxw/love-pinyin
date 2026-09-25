from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from server.main import app


def test_two_devices_can_commit_different_answers_without_lost_revision(paired_client):
    parent = paired_client
    pairing_code = parent.post(
        "/api/v1/pairing-codes", headers={"X-LP-CSRF": parent.cookies.get("lp_csrf")}
    ).json()["code"]

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001)) as tablet:
        paired = tablet.post("/api/v1/pair", json={"code": pairing_code, "label": "平板"})
        assert paired.status_code == 200

        session = parent.post(
            "/api/v1/sessions", json={}, headers={"X-LP-CSRF": parent.cookies.get("lp_csrf")}
        ).json()
        tasks = session["tasks"][:2]
        revision_before = parent.get("/api/v1/bootstrap").json()["profile"]["revision"]
        barrier = Barrier(2)

        def submit(client, task, request_id):
            barrier.wait()
            return client.post(
                f"/api/v1/instances/{task['instanceId']}/answer",
                json={
                    "requestId": request_id,
                    "answerOptionId": task["exercise"]["options"][0]["id"],
                },
                headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(submit, parent, tasks[0], "tablet-concurrency-0001")
            second = pool.submit(submit, tablet, tasks[1], "tablet-concurrency-0002")
            responses = [first.result(), second.result()]

        assert [response.status_code for response in responses] == [200, 200]
        assert len({response.json()["attemptId"] for response in responses}) == 2
        assert parent.get("/api/v1/bootstrap").json()["profile"]["revision"] == revision_before + 2
        assert len(parent.get("/api/v1/profiles/progress").json()["attempts"]) == 2
