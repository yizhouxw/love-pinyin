from fastapi.testclient import TestClient

from server import source_audio
from server.main import app


def test_material_choice_is_saved_and_media_remains_range_addressable(paired_client, monkeypatch):
    monkeypatch.setattr(source_audio, "installed", lambda: True)
    initial = paired_client.get("/api/v1/practice-packs").json()
    assert initial["selected"] == "original"
    assert initial["original"]["words"]["lessons"][0]["title"] == "身边的人"
    assert initial["household"]["words"]["lessons"][0]["title"] == "天地人"

    endpoint = "/api/v1/household/material-source"
    csrf = {"X-LP-CSRF": paired_client.cookies["lp_csrf"]}
    assert paired_client.put(endpoint, json={"source": "household"}).status_code == 403
    assert paired_client.put(endpoint, headers=csrf, json={"source": "missing"}).status_code == 422
    assert (
        paired_client.put(endpoint, headers=csrf, json={"source": "household"}).status_code == 200
    )
    assert paired_client.get("/api/v1/practice-packs").json()["selected"] == "household"
    assert paired_client.get("/api/v1/guest/practice-packs").json()["selected"] == "original"

    code = paired_client.post("/api/v1/pairing-codes", headers=csrf).json()["code"]
    with TestClient(app, base_url="http://192.0.2.2", client=("192.0.2.3", 50000)) as child:
        assert child.post("/api/v1/pair", json={"code": code}).json()["isParent"] is False
        assert child.get("/api/v1/practice-packs").json()["selected"] == "household"
        child_csrf = {"X-LP-CSRF": child.cookies["lp_csrf"]}
        assert (
            child.put(endpoint, headers=child_csrf, json={"source": "original"}).status_code == 403
        )
        assert (
            paired_client.put(endpoint, headers=csrf, json={"source": "original"}).status_code
            == 200
        )
        assert child.get("/api/v1/practice-packs").json()["selected"] == "original"

    course = initial["original"]["lessons"]["lesson-01"]["audioId"]
    for path in (
        f"voice/{course}",
        "audio/original-audio-final-a",
        "daily-audio/audio-final-a",
    ):
        response = paired_client.get(f"/api/v1/{path}", headers={"Range": "bytes=0-15"})
        assert response.status_code == 206
        assert len(response.content) == 16
