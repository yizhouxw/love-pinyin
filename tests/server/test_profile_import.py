import json

from server.content import map_by_id


def preview(client, payload):
    return client.post(
        "/api/v1/profiles/import-preview",
        content=json.dumps(payload, ensure_ascii=False),
        headers={
            "Content-Type": "application/json",
            "X-LP-CSRF": client.cookies.get("lp_csrf"),
        },
    )


def test_export_is_valid_for_a_bound_parent_preview(paired_client):
    backup = paired_client.get("/api/v1/profiles/export").json()
    assert backup["schemaVersion"] == 2
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


def test_preview_rejects_oversized_payload_before_parsing(paired_client):
    response = paired_client.post(
        "/api/v1/profiles/import-preview",
        content=b" " * (1_048_576 + 1),
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
