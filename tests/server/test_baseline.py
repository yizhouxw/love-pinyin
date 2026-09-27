def test_health_and_deferred_assessment_are_not_exposed(paired_client):
    assert paired_client.get("/api/v1/health").json()["status"] == "ok"
    capability = paired_client.get("/api/v1/capabilities").json()
    assert "assessment" not in capability
    assert "/api/v1/assessments" not in paired_client.get("/openapi.json").json()["paths"]
    assert (
        paired_client.get("/api/v1/health")
        .headers["permissions-policy"]
        .startswith("microphone=()")
    )


def test_api_docs_do_not_load_external_cdn_scripts(test_client):
    assert "swagger-ui" not in test_client.get("/docs").text.lower()
    assert "redoc" not in test_client.get("/redoc").text.lower()
    assert test_client.get("/openapi.json").status_code == 200
