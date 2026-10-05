"""Writing observation never creates a handwriting score; objective diagrams use real sessions."""

import pytest

from server.content import load_curriculum, load_writing
from server.learning_audio import narration_scripts
from tests.server.test_rule_practice import post


def test_writing_catalog_and_voice_contract(paired_client):
    writing = load_writing()
    assert paired_client.get("/api/v1/curriculum").json()["writing"] == writing
    assert paired_client.get("/api/v1/guest/curriculum").json()["writing"] == writing
    scripts = narration_scripts()
    for key, glyph in writing["glyphs"].items():
        assert scripts[f"writing-{key}-placement"] == glyph["description"]
        for i, stroke in enumerate(glyph["strokes"], 1):
            assert scripts[f"writing-{key}-stroke-{i}"] == stroke["instruction"]
    for key, mark in writing["marks"].items():
        assert scripts[f"writing-{key}"] == mark["stroke"]["instruction"]
    for targets in writing["lessons"].values():
        for target in targets:
            if "tone" in target:
                assert scripts[f"writing-{target['id']}-tone"] == target["note"]
    assert paired_client.get("/api/v1/profiles/export").json()["attempts"] == []


@pytest.mark.parametrize("lesson_id", ["lesson-01", "lesson-03", "lesson-06"])
def test_grid_diagram_task_rotation_and_restore(paired_client, lesson_id):
    client = paired_client
    curriculum = load_curriculum()
    question = next(
        q
        for q in curriculum["exercises"]
        if q["lessonId"] == lesson_id and any(o.get("writing") for o in q["options"])
    )
    revision = client.get("/api/v1/profiles/progress").json()["revision"]
    assert (
        client.put(
            "/api/v1/household/current-lesson",
            json={"lessonId": lesson_id, "expectedRevision": revision},
            headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
        ).status_code
        == 200
    )
    found = None
    for _ in range(10):
        post(client, "/api/v1/rest/complete")
        session = post(client, "/api/v1/sessions", {})
        for task in session["tasks"]:
            if task["exercise"]["id"] == question["id"]:
                found = task
                break
            post(client, f"/api/v1/instances/{task['instanceId']}/skip")
        if found:
            break
        post(client, f"/api/v1/sessions/{session['id']}/finish")
    assert found and found["exercise"]["options"] == question["options"]
    result = post(
        client,
        f"/api/v1/instances/{found['instanceId']}/answer",
        {"requestId": "write-01", "answerOptionId": question["answer"]["optionId"]},
    )
    assert result["correct"]
    backup = client.get("/api/v1/profiles/export").json()
    assert len(backup["attempts"]) == 1
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
    resumed = client.get("/api/v1/sessions/current").json()
    assert next(t for t in resumed["tasks"] if t["instanceId"] == found["instanceId"]) == found
    assert len(client.get("/api/v1/profiles/export").json()["attempts"]) == 1
