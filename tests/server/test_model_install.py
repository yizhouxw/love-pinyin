from server import model_install, reading_recognition


def test_model_download_requires_authentication(test_client):
    assert test_client.get("/api/v1/local/recognition-model").status_code == 401
    assert test_client.post("/api/v1/local/recognition-model").status_code == 401


def test_model_download_requires_local_parent_and_csrf(test_client, paired_client):
    assert test_client.get("/api/v1/local/recognition-model").status_code == 200
    assert test_client.post("/api/v1/local/recognition-model").status_code == 403
    response = test_client.post(
        "/api/v1/local/recognition-model",
        headers={"origin": "http://evil.example", "x-lp-csrf": test_client.cookies["lp_csrf"]},
    )
    assert response.status_code == 403


def test_failed_download_can_be_retried_and_corrupt_model_replaced(monkeypatch, tmp_path):
    path = tmp_path / "model.bin"
    path.write_bytes(b"corrupt")
    monkeypatch.setattr(reading_recognition, "MODEL_PATH", path)
    monkeypatch.setattr(model_install, "_state", "downloading")
    calls = []

    def install(destination):
        calls.append(destination)
        assert not destination.exists()
        raise OSError("offline")

    monkeypatch.setattr(model_install, "install", install)
    model_install._download()
    assert model_install.status()["state"] == "failed"
    assert calls == [path]
