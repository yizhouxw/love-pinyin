from fastapi.testclient import TestClient

from server import storage


def csrf(client):
    return {"X-LP-CSRF": client.cookies.get("lp_csrf")}


def set_reduced_motion(client, value):
    return client.put(
        "/api/v1/household/settings",
        json={"soundEnabled": True, "reducedMotion": value},
        headers=csrf(client),
    )


def test_delete_learning_records_preserves_household_settings_and_pairing(paired_client):
    parent = paired_client
    assert set_reduced_motion(parent, True).status_code == 200
    session = parent.post("/api/v1/sessions", json={}, headers=csrf(parent)).json()
    task = session["tasks"][0]
    answer = parent.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={
            "requestId": "delete-data-test-request-01",
            "answerOptionId": task["exercise"]["options"][0]["id"],
        },
        headers=csrf(parent),
    )
    assert answer.status_code == 200
    household_id = parent.get("/api/v1/bootstrap").json()["profile"]["id"]
    with storage.transaction() as db:
        db.execute(
            """INSERT INTO assessment_summaries(
               request_id,household_id,target_id,status,summary_json,engine_version,created_at)
               VALUES('summary-delete-test',?,'target-test','complete','{}','test-v1',?)""",
            (household_id, storage.now_iso()),
        )

    deleted = parent.request(
        "DELETE",
        "/api/v1/profiles/data",
        json={"confirmation": "删除我的学习记录"},
        headers=csrf(parent),
    )

    assert deleted.status_code == 200
    progress = parent.get("/api/v1/profiles/progress").json()
    assert progress["attempts"] == []
    assert progress["profileId"] == household_id
    assert parent.get("/api/v1/profiles/export").json()["profile"]["id"] == household_id
    assert progress["settings"]["reducedMotion"] is True
    assert parent.get("/api/v1/sessions/current").json() is None
    assert parent.get("/api/v1/profiles/export").json()["assessmentSummaries"] == []
    with storage.connect() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM assessment_summaries WHERE household_id=?", (household_id,)
            ).fetchone()[0]
            == 0
        )
    assert len(parent.get("/api/v1/devices").json()["devices"]) == 1


def test_reset_clears_settings_and_revokes_every_device_and_pending_code(paired_client):
    parent = paired_client
    household_id = parent.get("/api/v1/bootstrap").json()["profile"]["id"]
    assert set_reduced_motion(parent, True).status_code == 200
    invite = parent.post("/api/v1/pairing-codes", headers=csrf(parent)).json()["code"]
    pending_invite = parent.post("/api/v1/pairing-codes", headers=csrf(parent)).json()["code"]

    with TestClient(
        parent.app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50002),
    ) as tablet:
        paired = tablet.post("/api/v1/pair", json={"code": invite, "label": "平板"})
        assert paired.status_code == 200
        assert paired.json()["isParent"] is False
        denied = tablet.request(
            "DELETE",
            "/api/v1/profiles/reset",
            json={"confirmation": "重置家庭档案"},
            headers=csrf(tablet),
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "PARENT_AUTH_REQUIRED"

        wrong_confirmation = parent.request(
            "DELETE",
            "/api/v1/profiles/reset",
            json={"confirmation": "删除我的学习记录"},
            headers=csrf(parent),
        )
        assert wrong_confirmation.status_code == 422
        assert parent.get("/api/v1/bootstrap").json()["paired"] is True
        assert len(parent.get("/api/v1/devices").json()["devices"]) == 2

        reset = parent.request(
            "DELETE",
            "/api/v1/profiles/reset",
            json={"confirmation": "重置家庭档案"},
            headers=csrf(parent),
        )
        assert reset.status_code == 200
        assert reset.json() == {"reset": True, "pairingRequired": True}
        assert "lp_session=" in reset.headers["set-cookie"]
        assert "lp_csrf=" in reset.headers["set-cookie"]
        assert "Max-Age=0" in reset.headers["set-cookie"]
        assert parent.cookies.get("lp_session") is None
        assert parent.get("/api/v1/bootstrap").json()["paired"] is False
        assert tablet.get("/api/v1/bootstrap").status_code == 401
        assert (
            tablet.post("/api/v1/pair", json={"code": invite, "label": "旧邀请"}).status_code == 401
        )
        assert (
            parent.post(
                "/api/v1/pair", json={"code": pending_invite, "label": "待撤销邀请"}
            ).status_code
            == 401
        )

    with storage.connect() as db:
        household = db.execute("SELECT * FROM household WHERE id=?", (household_id,)).fetchone()
        assert household["selected_lesson_id"] == "lesson-01"
        assert household["sound_enabled"] == 1
        assert household["reduced_motion"] == 0
        assert household["rounds_since_break"] == 0
        assert (
            db.execute(
                "SELECT COUNT(*) FROM devices WHERE household_id=? AND revoked_at IS NULL",
                (household_id,),
            ).fetchone()[0]
            == 0
        )
        assert db.execute("SELECT COUNT(*) FROM pairing_codes").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT COUNT(*) FROM sessions WHERE household_id=?", (household_id,)
            ).fetchone()[0]
            == 0
        )

    new_code = parent.post("/api/v1/local/pairing-code").json()["code"]
    re_paired = parent.post("/api/v1/pair", json={"code": new_code, "label": "家长"})
    assert re_paired.status_code == 200
    assert re_paired.json()["isParent"] is True
    assert parent.get("/api/v1/bootstrap").json()["profile"]["settings"] == {
        "soundEnabled": True,
        "reducedMotion": False,
    }
