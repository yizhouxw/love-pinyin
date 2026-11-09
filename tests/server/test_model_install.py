import hashlib
from pathlib import Path
from types import SimpleNamespace

from server import model_install, qwen_recognition


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


def test_model_appears_only_after_verified_download_and_can_retry(monkeypatch, tmp_path):
    path = tmp_path / "model"
    data = b"pinned"
    config = {
        "repository": "owner/name",
        "revision": "a" * 40,
        "files": {"weights": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}},
    }
    monkeypatch.setattr(qwen_recognition, "MODEL_DIR", path)
    monkeypatch.setattr(qwen_recognition, "supported", lambda: True)
    monkeypatch.setattr(qwen_recognition, "manifest", lambda: config)
    monkeypatch.setattr(model_install, "_state", "downloading")
    calls = []

    def fetch(argv, **options):
        assert not path.exists()
        calls.append(argv[-1])
        Path(argv[argv.index("--output") + 1]).write_bytes(data if len(calls) == 2 else b"broken")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(model_install.subprocess, "run", fetch)
    model_install._download()
    assert model_install.status()["state"] == "failed"
    assert qwen_recognition.status()["available"] is False
    model_install._download()
    assert model_install.status()["state"] == "installed"
    assert qwen_recognition.status()["available"] is True
    assert all(config["revision"] in url for url in calls)
    (path / "weights").write_bytes(b"broken")
    assert qwen_recognition.status()["available"] is False
