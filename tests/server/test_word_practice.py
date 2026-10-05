"""WORD-01 real session/restore contracts. Registered fixture audio is not sound evidence."""

import pytest

from server.content import load_curriculum, load_illustrations
from server.learning_audio import narration_scripts
from tests.server.test_rule_practice import post


def test_word_catalog_is_shared_by_family_and_guest_without_attempts(paired_client):
    book = load_illustrations()
    assert paired_client.get("/api/v1/curriculum").json()["illustrations"] == book
    assert paired_client.get("/api/v1/guest/curriculum").json()["illustrations"] == book
    scripts = narration_scripts()
    assert scripts["picture-intro"] == book["intro"]
    for key, item in book["items"].items():
        assert scripts[f"picture-{key}"] == item["description"]
    assert paired_client.get("/api/v1/profiles/export").json()["attempts"] == []


@pytest.mark.parametrize("number", range(3, 15))
def test_word_questions_rotate_save_and_restore(paired_client, registered_audio_catalog, number):
    client = paired_client
    lesson = f"lesson-{number:02}"
    content = load_curriculum()
    all_questions = [
        q for q in content["exercises"] if q["lessonId"] == lesson and q["type"] != "read-aloud"
    ]
    wanted = {
        q["id"]: q
        for q in all_questions
        if q.get("pictureId") or any(o.get("pictureId") for o in q["options"])
    }
    revision = client.get("/api/v1/profiles/progress").json()["revision"]
    assert (
        client.put(
            "/api/v1/household/current-lesson",
            json={"lessonId": lesson, "expectedRevision": revision},
            headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
        ).status_code
        == 200
    )
    found = set()
    for _ in range((len(all_questions) + 5) // 6):
        post(client, "/api/v1/rest/complete")
        session = post(client, "/api/v1/sessions", {})
        for task in session["tasks"]:
            qid = task["exercise"]["id"]
            if qid in wanted and qid not in found:
                q = wanted[qid]
                assert task["exercise"]["options"] == q["options"]
                assert task["exercise"].get("pictureId") == q.get("pictureId")
                result = post(
                    client,
                    f"/api/v1/instances/{task['instanceId']}/answer",
                    {"requestId": f"word01-{qid}", "answerOptionId": q["answer"]["optionId"]},
                )
                assert result["correct"]
                found.add(qid)
            else:
                post(client, f"/api/v1/instances/{task['instanceId']}/skip")
        post(client, f"/api/v1/sessions/{session['id']}/finish")
    assert found == set(wanted) and len(found) == 2
    backup = client.get("/api/v1/profiles/export").json()
    assert {a["exercise_id"] for a in backup["attempts"]} == found
    preview = post(client, "/api/v1/profiles/import-preview", backup)
    post(
        client,
        "/api/v1/profiles/import",
        {
            "previewToken": preview["previewToken"],
            "sha256": preview["sha256"],
            "expectedRevision": backup["profile"]["revision"],
        },
    )
    assert (
        client.get("/api/v1/profiles/export").json()["exerciseInstances"]
        == backup["exerciseInstances"]
    )
    registered_audio_catalog.write_bytes(b"corrupted")
    post(client, "/api/v1/rest/complete")
    new_session = post(client, "/api/v1/sessions", {})
    assert not any(t["exercise"]["id"] in wanted for t in new_session["tasks"])
    assert len(client.get("/api/v1/profiles/export").json()["attempts"]) == 2
