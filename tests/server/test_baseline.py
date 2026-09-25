from fastapi.testclient import TestClient

from server.main import app


def test_health_and_unready_assessment_are_truthful():
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        capability = client.get("/api/v1/capabilities").json()
        assert capability["assessment"]["available"] is False
        assert capability["externalAudioTransfer"] is False
        response = client.post("/api/v1/assessments")
        assert response.status_code == 503
        assert "score" not in response.json()
        assert response.headers["cache-control"] == "no-store"


def test_api_docs_do_not_load_external_cdn_scripts():
    with TestClient(app) as client:
        assert client.get("/docs").status_code in (404, 405)
        assert client.get("/openapi.json").status_code == 200
