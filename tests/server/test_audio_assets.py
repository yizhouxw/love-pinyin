import hashlib

import pytest

from server import api


@pytest.fixture
def registered_audio(monkeypatch, paired_client, install_standard):
    payload = b"synthetic-sample-content-for-range-tests"
    asset = {
        "id": "audio-test-sample",
        "transcript": "a",
        "kind": "final",
        "knowledgeIds": [],
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    asset_file = install_standard(asset, payload)
    monkeypatch.setattr(api, "load_curriculum", lambda: {"audioRequirements": [asset]})
    return paired_client, asset, asset_file, payload


def test_audio_asset_is_authenticated_integrity_checked_and_not_cached(registered_audio):
    client, asset, _, payload = registered_audio
    response = client.get(f"/api/v1/audio/{asset['id']}")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["etag"] == f'"sha256-{asset["sha256"]}"'
    assert response.headers["cache-control"] == "no-store"


def test_audio_asset_supports_open_and_suffix_byte_ranges(registered_audio):
    client, asset, _, payload = registered_audio
    ranged = client.get(f"/api/v1/audio/{asset['id']}", headers={"Range": "bytes=2-5"})
    assert ranged.status_code == 206
    assert ranged.content == payload[2:6]
    assert ranged.headers["content-range"] == f"bytes 2-5/{len(payload)}"
    assert ranged.headers["content-length"] == "4"

    suffix = client.get(f"/api/v1/audio/{asset['id']}", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == payload[-3:]
    assert (
        suffix.headers["content-range"]
        == f"bytes {len(payload) - 3}-{len(payload) - 1}/{len(payload)}"
    )


@pytest.mark.parametrize("range_header", ["bytes=99-100", "bytes=5-2", "bytes=0-1,4-5", "bytes=-0"])
def test_invalid_ranges_return_416_without_audio_body(registered_audio, range_header):
    client, asset, _, payload = registered_audio
    response = client.get(f"/api/v1/audio/{asset['id']}", headers={"Range": range_header})
    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["content-range"] == f"bytes */{len(payload)}"


def test_audio_route_ignores_old_review_fields_but_rejects_unknown_and_corrupt_assets(
    registered_audio, monkeypatch
):
    client, asset, asset_file, _ = registered_audio
    assert client.get("/api/v1/audio/not-registered").status_code == 404
    assert client.get(f"/api/v1/audio/{asset['id']}").status_code == 200

    changed = {**asset, "reviewStatus": "needs-teacher-review"}
    monkeypatch.setattr(api, "load_curriculum", lambda: {"audioRequirements": [changed]})
    assert client.get(f"/api/v1/audio/{asset['id']}").status_code == 200

    unlicensed = {**asset, "rightsEvidence": ""}
    monkeypatch.setattr(api, "load_curriculum", lambda: {"audioRequirements": [unlicensed]})
    assert client.get(f"/api/v1/audio/{asset['id']}").status_code == 200

    monkeypatch.setattr(api, "load_curriculum", lambda: {"audioRequirements": [asset]})
    asset_file.write_bytes(b"changed after manifest approval")
    assert client.get(f"/api/v1/audio/{asset['id']}").status_code == 404


def test_legacy_paths_cannot_override_pinned_source(registered_audio, monkeypatch, tmp_path):
    client, asset, path, payload = registered_audio
    outside = tmp_path / "secret.mp3"
    outside.write_bytes(b"private")
    malicious = {
        **asset,
        "file": "audio/../secret.mp3",
        "status": "approved",
        "reviewStatus": "approved",
    }
    monkeypatch.setattr(api, "load_curriculum", lambda: {"audioRequirements": [malicious]})
    assert client.get(f"/api/v1/audio/{asset['id']}").content == payload
    path.unlink()
    path.symlink_to(outside)
    assert client.get(f"/api/v1/audio/{asset['id']}").status_code == 404


def test_audio_route_requires_a_paired_device(test_client):
    assert test_client.get("/api/v1/audio/audio-final-a").status_code == 401
