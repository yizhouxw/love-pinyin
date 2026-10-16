import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from server.audio_assets import file_audio_response
from server.text_compression import TextCompressionMiddleware


def test_gzip_negotiation_preserves_api_json_and_no_store(test_client):
    path = "/api/v1/guest/curriculum"
    plain = test_client.get(path, headers={"Accept-Encoding": "identity"})
    compressed = test_client.get(path, headers={"Accept-Encoding": "gzip"})
    assert compressed.json() == plain.json()
    assert compressed.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in compressed.headers["vary"].lower()
    assert int(compressed.headers["content-length"]) < len(plain.content) / 2
    assert compressed.headers["cache-control"] == plain.headers["cache-control"] == "no-store"
    assert "content-encoding" not in plain.headers


def test_media_and_byte_ranges_are_not_compressed(tmp_path):
    payload = b"synthetic non-private audio range fixture" * 4000
    path = tmp_path / "fixture.mp3"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    def media(request):
        return file_audio_response(path, "audio/mpeg", digest, request.headers.get("range"))

    def text(request):
        return JSONResponse({"message": "text" * 4000})

    app = Starlette(
        routes=[Route("/api/v1/guest/audio/sample", media), Route("/api/v1/text", text)]
    )
    app.add_middleware(TextCompressionMiddleware)
    with TestClient(app) as client:
        whole = client.get("/api/v1/guest/audio/sample", headers={"Accept-Encoding": "gzip"})
        assert whole.content == payload
        assert "content-encoding" not in whole.headers
        ranged = client.get(
            "/api/v1/guest/audio/sample", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-1"}
        )
        assert ranged.status_code == 206
        assert ranged.content == payload[:2]
        assert ranged.headers["content-range"] == f"bytes 0-1/{len(payload)}"
        assert ranged.headers["content-length"] == "2"
        assert "content-encoding" not in ranged.headers
        invalid = client.get(
            "/api/v1/guest/audio/sample",
            headers={"Accept-Encoding": "gzip", "Range": "bytes=9999999-"},
        )
        assert invalid.status_code == 416
        assert "content-encoding" not in invalid.headers
        text_range = client.get(
            "/api/v1/text", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-1"}
        )
        assert "content-encoding" not in text_range.headers


def test_successful_hashed_static_files_cache_but_html_and_errors_do_not(test_client):
    assets = Path("dist/assets")
    scripts = list(assets.glob("*.js"))
    if scripts:
        response = test_client.get(
            "/assets/" + scripts[0].name, headers={"Accept-Encoding": "gzip"}
        )
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    root = test_client.get("/")
    assert root.headers["cache-control"] == "no-store"
    font = test_client.get("/fonts/andika/Andika-Regular.woff2")
    if font.headers["content-type"].startswith("font/"):
        assert font.headers["cache-control"] == "public, max-age=86400"
        assert "content-encoding" not in font.headers
    for url in [
        "/fonts/missing.woff2",
        "/assets/missing-12345678.js",
        "/api/v1/guest/voice/missing",
    ]:
        assert test_client.get(url).headers["cache-control"] == "no-store"
