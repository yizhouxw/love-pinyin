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
