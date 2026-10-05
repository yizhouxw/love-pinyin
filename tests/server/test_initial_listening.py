"""BANK-04 rotation/persistence boundaries; synthetic registration is not sound evidence."""

import hashlib
import json
from copy import deepcopy

import pytest

from server import source_audio
from server.content import load_curriculum


@pytest.fixture
def registered_audio(monkeypatch):
    source = deepcopy(source_audio.catalog())
    payload = b"synthetic-registration-only-not-pronunciation-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    for row in source["assets"]:
        row.update(sha256=digest, bytes=len(payload))
    monkeypatch.setattr(source_audio, "catalog", lambda: source)
    root = source_audio.SOURCE_DIR
    (root / "clips").mkdir(parents=True)
    path = root / "clips" / f"{digest}.mp3"
    path.write_bytes(payload)
    (root / "installation.json").write_text(
        json.dumps(
            {
                "version": 1,
                "enabled": True,
                "commit": source["commit"],
                "archiveSha256": source["archiveSha256"],
            }
        )
    )
    return path


def post(client, path, body=None):
    response = client.post(path, json=body, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("lesson_id", [f"lesson-{n:02}" for n in range(3, 9)])
def test_all_new_initial_listening_tasks_reachable_and_persisted(
    paired_client, registered_audio, lesson_id
):
    client = paired_client
    content = load_curriculum()
    questions = {
        q["id"]: q
        for q in content["exercises"]
        if q["lessonId"] == lesson_id and q["type"] != "read-aloud"
    }
    new_ids = {qid for qid in questions if int(qid.rsplit("-", 1)[1]) >= 70}
    profile = client.get("/api/v1/profiles/progress").json()
    response = client.put(
        "/api/v1/household/current-lesson",
        json={"lessonId": lesson_id, "expectedRevision": profile["revision"]},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert response.status_code == 200
    reached = set()
    seen = set()
    for round_index in range((len(questions) + 5) // 6):
        if round_index and round_index % 2 == 0:
            post(client, "/api/v1/rest/complete")
        session = post(client, "/api/v1/sessions", {})
        ids = [task["exercise"]["id"] for task in session["tasks"]]
        assert len(ids) == len(set(ids)) == 6
        assert set(ids) - seen
        seen.update(ids)
        for task in session["tasks"]:
            qid = task["exercise"]["id"]
            if qid in new_ids and qid not in reached:
                q = questions[qid]
                assert task["exercise"]["audioRef"] == q["audioRef"]
                result = post(
                    client,
                    f"/api/v1/instances/{task['instanceId']}/answer",
                    {"requestId": f"bank04-{qid}", "answerOptionId": q["answer"]["optionId"]},
                )
                assert result["correct"]
                reached.add(qid)
            else:
                post(client, f"/api/v1/instances/{task['instanceId']}/skip")
        post(client, f"/api/v1/sessions/{session['id']}/finish")
    assert reached == new_ids
    backup = client.get("/api/v1/profiles/export").json()
    assert {attempt["exercise_id"] for attempt in backup["attempts"]} == new_ids
    assert all(attempt["first_try_correct"] == 1 for attempt in backup["attempts"])
    # A broken file must remove those listening tasks from new sessions, not
    # substitute silent choices or record the device failure as a child's mistake.
    registered_audio.write_bytes(b"corrupted")
    post(client, "/api/v1/rest/complete")
    after = post(client, "/api/v1/sessions", {})
    assert not any(task["exercise"].get("audioRef") for task in after["tasks"])
    assert len(client.get("/api/v1/profiles/export").json()["attempts"]) == len(new_ids)
