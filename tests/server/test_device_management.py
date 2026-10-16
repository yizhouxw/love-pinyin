from fastapi.testclient import TestClient


def test_parent_can_list_and_revoke_secondary_device_without_exposing_tokens(paired_client):
    parent = paired_client
    code_response = parent.post(
        "/api/v1/pairing-codes", headers={"X-LP-CSRF": parent.cookies.get("lp_csrf")}
    )
    assert code_response.status_code == 200

    with TestClient(
        parent.app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50001),
    ) as child:
        paired = child.post(
            "/api/v1/pair", json={"code": code_response.json()["code"], "label": "平板"}
        )
        assert paired.status_code == 200
        assert paired.json()["isParent"] is False
        child_id = paired.json()["deviceId"]

        devices = parent.get("/api/v1/devices").json()["devices"]
        assert len(devices) == 2
        for item in devices:
            assert not {"token", "csrf_hash", "csrf", "session"} & {key.lower() for key in item}
        assert next(item for item in devices if item["current"])["id"] != child_id

        denied = child.get("/api/v1/devices")
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "PARENT_AUTH_REQUIRED"

        self_revoke = parent.delete(
            f"/api/v1/devices/{next(item['id'] for item in devices if item['current'])}",
            headers={"X-LP-CSRF": parent.cookies.get("lp_csrf")},
        )
        assert self_revoke.status_code == 409
        assert self_revoke.json()["detail"]["code"] == "CANNOT_REVOKE_CURRENT_DEVICE"

        revoked = parent.delete(
            f"/api/v1/devices/{child_id}",
            headers={"X-LP-CSRF": parent.cookies.get("lp_csrf")},
        )
        assert revoked.status_code == 200
        assert revoked.json()["revoked"] is True
        assert child.get("/api/v1/bootstrap").json()["paired"] is False
        assert child.get("/api/v1/profiles/progress").status_code == 401
        assert [item["id"] for item in parent.get("/api/v1/devices").json()["devices"]] == [
            item["id"] for item in devices if item["current"]
        ]


def test_pairing_capability_distinguishes_loopback_from_remote_even_when_paired(paired_client):
    assert paired_client.get("/api/v1/bootstrap").json()["isLocalHost"] is True
    with TestClient(
        paired_client.app, base_url="https://192.168.1.2", client=("192.168.1.30", 50002)
    ) as remote:
        assert remote.get("/api/v1/bootstrap").json()["isLocalHost"] is False
        assert remote.post("/api/v1/local/pairing-code").status_code == 403
        assert remote.post("/api/v1/pairing-codes").status_code == 401
        code = paired_client.post("/api/v1/local/pairing-code").json()["code"]
        assert remote.post("/api/v1/pair", json={"code": code, "label": "iPad"}).status_code == 200
        state = remote.get("/api/v1/bootstrap").json()
        assert state["paired"] is True
        assert state["device"]["isParent"] is False
        assert state["isLocalHost"] is False
        assert (
            remote.post(
                "/api/v1/local/pairing-code", headers={"X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 403
        )
        assert (
            remote.post(
                "/api/v1/pairing-codes", headers={"X-LP-CSRF": remote.cookies.get("lp_csrf")}
            ).status_code
            == 403
        )


def test_device_model_used_code_and_server_connection_time(paired_client, monkeypatch):
    from urllib.parse import quote

    from server import api, storage

    parent = paired_client
    code = parent.post("/api/v1/local/pairing-code").json()["code"]
    with TestClient(parent.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50003)) as child:
        moment = "2026-10-16T04:05:06.000+00:00"
        monkeypatch.setattr(api, "now_iso", lambda: moment)
        response = child.post("/api/v1/pair", json={"code": code, "model": "iPad Air 5"})
        assert response.status_code == 200
        child_id = response.json()["deviceId"]
        listed = parent.get("/api/v1/devices").json()["devices"]
        row = next(item for item in listed if item["id"] == child_id)
        assert row["model"] == "iPad Air 5"
        assert row["pairingCode"] == code
        assert row["lastConnectedAt"] == moment
        assert child.post("/api/v1/pair", json={"code": code}).status_code == 401
        moment = "2026-10-16T04:06:07.000+00:00"
        assert (
            child.get(
                "/api/v1/bootstrap", headers={"X-LP-Device-Model": quote("iPad（浏览器推测）")}
            ).status_code
            == 200
        )
        row = next(
            item
            for item in parent.get("/api/v1/devices").json()["devices"]
            if item["id"] == child_id
        )
        assert row["lastConnectedAt"] == moment
        assert row["model"] == "iPad Air 5"
        with storage.transaction() as db:
            db.execute("UPDATE devices SET model=NULL WHERE id=?", (child_id,))
        child.get("/api/v1/bootstrap", headers={"X-LP-Device-Model": quote("iPad（浏览器推测）")})
        row = next(
            item
            for item in parent.get("/api/v1/devices").json()["devices"]
            if item["id"] == child_id
        )
        assert row["model"] == "iPad（浏览器推测）"
        csrf = {"X-LP-CSRF": parent.cookies.get("lp_csrf")}
        assert (
            parent.put(
                f"/api/v1/devices/{child_id}", json={"model": "iPad Pro 11"}, headers=csrf
            ).status_code
            == 200
        )
        assert (
            child.put(
                f"/api/v1/devices/{child_id}",
                json={"model": "bad"},
                headers={"X-LP-CSRF": child.cookies.get("lp_csrf")},
            ).status_code
            == 403
        )
        assert parent.put(f"/api/v1/devices/{child_id}", json={"model": "bad"}).status_code == 403
        for invalid in ["", " ", "x" * 81, "x\ny"]:
            assert (
                parent.put(
                    f"/api/v1/devices/{child_id}", json={"model": invalid}, headers=csrf
                ).status_code
                == 422
            )
        assert (
            parent.put(
                "/api/v1/devices/not-present", json={"model": "iPad"}, headers=csrf
            ).status_code
            == 404
        )
        assert parent.delete(f"/api/v1/devices/{child_id}", headers=csrf).status_code == 200
        moment = "2026-10-16T05:00:00.000+00:00"
        assert child.get("/api/v1/bootstrap").json()["paired"] is False
        with storage.connect() as db:
            saved = db.execute("SELECT * FROM devices WHERE id=?", (child_id,)).fetchone()
        assert saved["last_connected_at"] == "2026-10-16T04:06:07.000+00:00"
        assert (
            parent.put(
                f"/api/v1/devices/{child_id}", json={"model": "iPad"}, headers=csrf
            ).status_code
            == 404
        )
