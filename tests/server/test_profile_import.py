import json

import pytest

from server import profile_backup
from server.content import map_by_id
from server.routes import profiles


def preview(client, payload):
    return client.post(
        "/api/v1/profiles/import-preview",
        content=json.dumps(payload, ensure_ascii=False),
        headers={
            "Content-Type": "application/json",
            "X-LP-CSRF": client.cookies.get("lp_csrf"),
        },
    )


@pytest.fixture(autouse=True)
def clean_preview_tokens():
    profiles._import_previews.clear()
    yield
    profiles._import_previews.clear()


def confirm(client, result, revision=None, sha256=None):
    return client.post(
        "/api/v1/profiles/import",
        json={
            "previewToken": result["previewToken"],
            "sha256": sha256 or result["sha256"],
            "expectedRevision": result["revision"] if revision is None else revision,
        },
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )


def test_export_is_valid_for_a_bound_parent_preview(paired_client):
    backup = paired_client.get("/api/v1/profiles/export").json()
    assert backup["schemaVersion"] == 5
    assert backup["masteryRuleVersion"] == 1

    response = preview(paired_client, backup)
    assert response.status_code == 200
    data = response.json()
    assert data["willReplaceEntireHousehold"] is True
    assert data["expiresInSeconds"] == 300
    assert data["counts"] == {
        "sessions": 0,
        "exerciseInstances": 0,
        "attempts": 0,
        "clockPendingAttempts": 0,
        "skippedInstances": 0,
        "reviewPlans": 0,
        "assessmentSummaries": 0,
    }
    assert len(data["previewToken"]) > 30


def test_preview_rejects_unknown_versions_without_mutating_profile(paired_client):
    backup = paired_client.get("/api/v1/profiles/export").json()
    before = paired_client.get("/api/v1/bootstrap").json()
    backup["schemaVersion"] = 999

    response = preview(paired_client, backup)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "BACKUP_VERSION_UNSUPPORTED"
    assert paired_client.get("/api/v1/bootstrap").json() == before


def test_preview_explicitly_migrates_schema_v2_backups(paired_client):
    backup = paired_client.get("/api/v1/profiles/export").json()
    backup["schemaVersion"] = 2
    backup["profile"].pop("gameState")
    backup["profile"]["settings"].pop("gameSessionMinutes")
    backup["profile"]["settings"].pop("gameDailyMinutes")
    backup["profile"]["settings"].pop("playbackGapSeconds")
    backup["profile"].pop("roundsSinceBreak")
    for instance in backup["exerciseInstances"]:
        instance.pop("position")

    response = preview(paired_client, backup)
    assert response.status_code == 200
    assert response.json()["migratedFromSchemaVersion"] == 2


def test_preview_migrates_schema_v3_review_session_marker(paired_client):
    backup = paired_client.get("/api/v1/profiles/export").json()
    backup["schemaVersion"] = 3
    for session in backup["sessions"]:
        session.pop("reviewKnowledgeId")
    response = preview(paired_client, backup)
    assert response.status_code == 200
    assert response.json()["migratedFromSchemaVersion"] == 3


def test_preview_migrates_schema_v4_clock_pending_field(paired_client):
    session = paired_client.post(
        "/api/v1/sessions",
        json={"lessonId": "lesson-01"},
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    ).json()
    task = session["tasks"][0]
    question = map_by_id("exercises")[task["exercise"]["id"]]
    answered = paired_client.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={
            "requestId": "legacy-v4-attempt",
            "answerOptionId": question["answer"]["optionId"],
        },
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    )
    assert answered.status_code == 200
    backup = paired_client.get("/api/v1/profiles/export").json()
    assert len(backup["attempts"]) == 1
    backup["schemaVersion"] = 4
    backup["attempts"][0].pop("clock_pending")
    response = preview(paired_client, backup)
    assert response.status_code == 200
    assert response.json()["migratedFromSchemaVersion"] == 4
    assert response.json()["counts"]["clockPendingAttempts"] == 0
    assert confirm(paired_client, response.json()).status_code == 200
    restored = paired_client.get("/api/v1/profiles/export").json()
    assert restored["attempts"][0]["clock_pending"] == 0


def test_preview_rejects_oversized_payload_before_parsing(paired_client):
    response = paired_client.post(
        "/api/v1/profiles/import-preview",
        content=b" " * (16 * 1_048_576 + 1),
        headers={
            "Content-Type": "application/json",
            "X-LP-CSRF": paired_client.cookies.get("lp_csrf"),
        },
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "BACKUP_TOO_LARGE"


def test_export_with_a_skipped_task_passes_reference_validation(paired_client):
    task = paired_client.post(
        "/api/v1/sessions",
        json={},
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    ).json()["tasks"][0]
    paired_client.post(
        f"/api/v1/instances/{task['instanceId']}/skip",
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    )

    backup = paired_client.get("/api/v1/profiles/export").json()
    response = preview(paired_client, backup)
    assert response.status_code == 200
    assert response.json()["counts"]["sessions"] == 1
    assert response.json()["counts"]["exerciseInstances"] == 6
    assert response.json()["counts"]["skippedInstances"] == 1


def test_preview_rejects_duplicate_json_properties(paired_client):
    response = paired_client.post(
        "/api/v1/profiles/import-preview",
        content=b'{"schemaVersion":2,"schemaVersion":2}',
        headers={
            "Content-Type": "application/json",
            "X-LP-CSRF": paired_client.cookies.get("lp_csrf"),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "BACKUP_INVALID"


def test_export_with_an_answer_passes_first_result_validation(paired_client):
    task = paired_client.post(
        "/api/v1/sessions",
        json={},
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    ).json()["tasks"][0]
    correct_option = map_by_id("exercises")[task["exercise"]["id"]]["answer"]["optionId"]
    answered = paired_client.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={"requestId": "import-preview-answer-01", "answerOptionId": correct_option},
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    )
    assert answered.status_code == 200

    response = preview(paired_client, paired_client.get("/api/v1/profiles/export").json())
    assert response.status_code == 200
    assert response.json()["counts"]["attempts"] == 1


def test_confirm_replaces_data_and_restores_answer_and_skip_state(paired_client):
    client = paired_client
    session = client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")}
    ).json()
    first, second = session["tasks"][:2]
    correct_option = map_by_id("exercises")[first["exercise"]["id"]]["answer"]["optionId"]
    assert (
        client.post(
            f"/api/v1/instances/{first['instanceId']}/answer",
            json={"requestId": "restore-answer-0001", "answerOptionId": correct_option},
            headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/instances/{second['instanceId']}/skip",
            headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
        ).status_code
        == 200
    )
    backup = client.get("/api/v1/profiles/export").json()
    assert (
        client.request(
            "DELETE",
            "/api/v1/profiles/data",
            json={"confirmation": "删除我的学习记录"},
            headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
        ).status_code
        == 200
    )

    preview_result = preview(client, backup).json()
    restored = confirm(client, preview_result)
    assert restored.status_code == 200
    assert restored.json()["imported"] is True
    assert client.get("/api/v1/profiles/progress").json()["attempts"]
    current = client.get("/api/v1/sessions/current").json()
    assert current["results"][first["instanceId"]]["restored"] is True
    assert current["results"][second["instanceId"]]["skipped"] is True
    assert confirm(client, preview_result).status_code == 410


def test_confirm_refuses_stale_revision_and_wrong_digest(paired_client):
    client = paired_client
    backup = client.get("/api/v1/profiles/export").json()
    preview_result = preview(client, backup).json()
    wrong_digest = confirm(client, preview_result, sha256="0" * 64)
    assert wrong_digest.status_code == 409
    assert wrong_digest.json()["detail"]["code"] == "IMPORT_PREVIEW_MISMATCH"

    client.post("/api/v1/sessions", json={}, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")})
    stale = confirm(client, preview_result)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "REVISION_CONFLICT"
    assert client.get("/api/v1/sessions/current").status_code == 200


def test_failed_restore_rolls_back_existing_data(paired_client, monkeypatch):
    client = paired_client
    session = client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": client.cookies.get("lp_csrf")}
    ).json()
    task = session["tasks"][0]
    correct_option = map_by_id("exercises")[task["exercise"]["id"]]["answer"]["optionId"]
    client.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={"requestId": "rollback-answer-01", "answerOptionId": correct_option},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    before = client.get("/api/v1/profiles/export").json()
    preview_result = preview(client, before).json()
    restore = profile_backup._restore_backup

    def fail_after_write(db, household_id, device_id, payload):
        restore(db, household_id, device_id, payload)
        raise RuntimeError("injected restore failure")

    monkeypatch.setattr(profiles, "_restore_backup", fail_after_write)
    with pytest.raises(RuntimeError, match="injected restore failure"):
        confirm(client, preview_result)

    after = client.get("/api/v1/profiles/export").json()
    assert after["attempts"] == before["attempts"]
    assert after["exerciseInstances"] == before["exerciseInstances"]
    assert after["sessions"] == before["sessions"]
    assert after["profile"]["revision"] == before["profile"]["revision"]


def test_import_restores_motion_preference_and_rest_round_count(paired_client):
    client = paired_client
    headers = {"X-LP-CSRF": client.cookies.get("lp_csrf")}
    assert (
        client.put(
            "/api/v1/household/settings",
            json={"soundEnabled": True, "reducedMotion": True},
            headers=headers,
        ).status_code
        == 200
    )
    session = client.post("/api/v1/sessions", json={}, headers=headers).json()
    for task in session["tasks"]:
        assert (
            client.post(f"/api/v1/instances/{task['instanceId']}/skip", headers=headers).status_code
            == 200
        )
    assert (
        client.post(f"/api/v1/sessions/{session['id']}/finish", headers=headers).json()[
            "breakRequired"
        ]
        is False
    )

    backup = client.get("/api/v1/profiles/export").json()
    assert backup["profile"]["roundsSinceBreak"] == 1
    assert backup["profile"]["settings"]["reducedMotion"] is True
    assert (
        client.request(
            "DELETE",
            "/api/v1/profiles/data",
            json={"confirmation": "删除我的学习记录"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/household/settings",
            json={"soundEnabled": True, "reducedMotion": False},
            headers=headers,
        ).status_code
        == 200
    )

    preview_result = preview(client, backup).json()
    assert confirm(client, preview_result).status_code == 200
    assert client.get("/api/v1/bootstrap").json()["profile"]["roundsSinceBreak"] == 1
    assert client.get("/api/v1/profiles/progress").json()["settings"]["reducedMotion"] is True


def test_legacy_review_fields_do_not_block_restore_or_change_frozen_session(paired_client):
    from server.storage import transaction

    client = paired_client
    headers = {"X-LP-CSRF": client.cookies.get("lp_csrf")}
    created = client.post("/api/v1/sessions", json={}, headers=headers).json()
    with transaction() as db:
        row = db.execute("SELECT tasks_json FROM sessions WHERE id=?", (created["id"],)).fetchone()
        tasks = json.loads(row["tasks_json"])
        for task in tasks:
            task["exercise"]["reviewStatus"] = "needs-teacher-review"
        db.execute(
            "UPDATE sessions SET tasks_json=? WHERE id=?", (json.dumps(tasks), created["id"])
        )
    before = client.get("/api/v1/sessions/current").json()
    assert before["tasks"] == created["tasks"]
    assert "draftContent" not in before
    backup = client.get("/api/v1/profiles/export").json()
    result = preview(client, backup)
    assert result.status_code == 200
    assert confirm(client, result.json()).status_code == 200
    resumed = client.get("/api/v1/sessions/current").json()
    assert resumed["contentVersion"] == created["contentVersion"]
    assert resumed["tasks"] == created["tasks"]
    task = resumed["tasks"][0]
    question = map_by_id("exercises")[task["exercise"]["id"]]
    answered = client.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={
            "requestId": "restored-without-review-gate",
            "answerOptionId": question["answer"]["optionId"],
        },
        headers=headers,
    )
    assert answered.status_code == 200 and answered.json()["correct"] is True
