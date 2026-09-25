def test_health_and_unready_assessment_are_truthful(paired_client):
    assert paired_client.get("/api/v1/health").json()["status"] == "ok"
    capability = paired_client.get("/api/v1/capabilities").json()
    assert capability["assessment"]["available"] is False
    assert capability["externalAudioTransfer"] is False
    csrf = paired_client.cookies.get("lp_csrf")
    response = paired_client.post("/api/v1/assessments", headers={"X-LP-CSRF": csrf})
    assert response.status_code == 503
    assert "score" not in response.json()
    assert response.headers["cache-control"] == "no-store"


def test_api_docs_do_not_load_external_cdn_scripts(test_client):
    assert "swagger-ui" not in test_client.get("/docs").text.lower()
    assert "redoc" not in test_client.get("/redoc").text.lower()
    assert test_client.get("/openapi.json").status_code == 200
