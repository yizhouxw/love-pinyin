import hashlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from server import source_audio, storage
from server.main import app


@pytest.fixture(autouse=True)
def isolate_selected_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(source_audio, "SOURCE_DIR", tmp_path / "selected-audio")


@pytest.fixture
def test_client(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DATABASE_PATH", tmp_path / "test.sqlite3")
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        yield client


@pytest.fixture
def paired_client(test_client):
    code = test_client.post("/api/v1/local/pairing-code").json()["code"]
    response = test_client.post("/api/v1/pair", json={"code": code, "label": "测试家长"})
    assert response.status_code == 200
    assert response.json()["isParent"] is True
    return test_client


@pytest.fixture
def install_standard(monkeypatch):
    """Synthetic registration fixture, never pronunciation-quality evidence."""
    import hashlib
    import json
    from copy import deepcopy

    def install(target, payload=b"synthetic-standard-audio-for-integrity-tests"):
        source = deepcopy(source_audio.catalog())
        digest = hashlib.sha256(payload).hexdigest()
        source["assets"] = [
            {
                "id": target["id"],
                "targetSignature": source_audio.target_signature(target),
                "filename": "sample.mp3",
                "sha256": digest,
                "bytes": len(payload),
                "exampleTone": None,
            }
        ]
        root = source_audio.SOURCE_DIR
        (root / "clips").mkdir(parents=True, exist_ok=True)
        path = root / "clips" / f"{digest}.mp3"
        path.write_bytes(payload)
        (root / "installation.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "enabled": True,
                    "commit": source["commit"],
                    "archiveSha256": source["archiveSha256"],
                }
            )
        )
        monkeypatch.setattr(source_audio, "catalog", lambda: source)
        return path

    return install


@pytest.fixture
def registered_audio_catalog(monkeypatch):
    source = deepcopy(source_audio.catalog())
    payload = b"synthetic-registration-only-not-pronunciation-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    for row in source["assets"]:
        row.update(sha256=digest, bytes=len(payload))
    monkeypatch.setattr(source_audio, "catalog", lambda: source)
    root = source_audio.SOURCE_DIR
    (root / "clips").mkdir(parents=True)
    path = root / "clips" / f"{digest}.mp3"
    path.write_bytes(payload)
    (root / "installation.json").write_text(
        json.dumps(
            {
                "version": 1,
                "enabled": True,
                "commit": source["commit"],
                "archiveSha256": source["archiveSha256"],
            }
        )
    )
    return path
