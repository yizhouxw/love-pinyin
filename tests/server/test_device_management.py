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
