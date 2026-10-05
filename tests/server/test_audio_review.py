"""Synthetic PCM tests prove authoring integrity, never pronunciation validity."""

import hashlib
import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from scripts.audio_review import create_app, write_json
from server import private_standard_audio as standard
from server.api import _available_standard_audio, _objective_available
from server.content import load_curriculum


@pytest.fixture
def authoring(tmp_path, monkeypatch):
    work = tmp_path / "review"
    path = work / "sources/test.wav"
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 16000)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(
        work / "catalog.json",
        {
            "version": 1,
            "sources": [
                {
                    "id": "test",
                    "name": "synthetic-test.wav",
                    "sourceSha256": sha,
                    "file": "sources/test.wav",
                    "sha256": sha,
                    "duration": 1,
                }
            ],
            "candidates": [],
        },
    )
    monkeypatch.setattr(standard, "STANDARD_DIR", tmp_path / "standard")
    app = create_app(work)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001)) as client:
        client.headers["X-Review-Token"] = app.state.review_token
        yield client, work


def draft(client, **overrides):
    return client.post(
        "/api/draft",
        json={
            "sourceId": "test",
            "start": 0.1,
            "end": 0.4,
            "targetId": "audio-final-a",
            **overrides,
        },
    )


def confirmation(row, **overrides):
    return {
        "targetId": row["id"],
        "sha256": row["sha256"],
        "revision": row["revision"],
        "teachingReviewer": "Synthetic test reviewer A",
        "qualityReviewer": "Synthetic test reviewer B",
        "targetAndPronunciationConfirmed": True,
        "qualityAndBoundariesConfirmed": True,
        "privateUseOnly": True,
        **overrides,
    }


def test_precise_cut_and_invalid_boundaries(authoring):
    client, work = authoring
    response = client.post("/api/preview", json={"sourceId": "test", "start": 0.1, "end": 0.4})
    assert response.status_code == 200
    with wave.open(io.BytesIO(response.content)) as audio:
        assert audio.getnframes() == 4800
        assert audio.readframes(4800) == b"\x01\x00" * 4800
    for start, end in [(0.5, 0.4), (0, 1.1), (0, 0.01), (-1, 0.4)]:
        assert (
            client.post(
                "/api/preview", json={"sourceId": "test", "start": start, "end": end}
            ).status_code
            == 422
        )
    (work / "sources/test.wav").write_bytes(b"corrupted")
    assert (
        client.post("/api/preview", json={"sourceId": "test", "start": 0.1, "end": 0.4}).status_code
        == 404
    )


def test_draft_revision_binds_bounds_even_when_pcm_identical(authoring):
    client, _ = authoring
    first = draft(client).json()
    assert draft(client).status_code == 409
    second = draft(client, start=0.2, end=0.5, expectedRevision=first["revision"]).json()
    assert first["sha256"] == second["sha256"]
    assert first["revision"] != second["revision"]
    assert client.post("/api/activate", json=confirmation(first)).status_code == 409
    assert (
        client.post(
            "/api/activate", json=confirmation(second, qualityReviewer="Synthetic test reviewer A")
        ).status_code
        == 422
    )
    assert (
        client.post("/api/activate", json=confirmation(second, privateUseOnly=False)).status_code
        == 422
    )


def test_private_activation_api_integrity_and_revocation(authoring, paired_client):
    client, _ = authoring
    row = draft(client).json()
    wanted = next(a for a in load_curriculum()["audioRequirements"] if a["id"] == row["id"])
    assert not standard.available(wanted)
    assert paired_client.get("/api/v1/audio/audio-final-a").status_code == 404
    assert client.post("/api/activate", json=confirmation(row)).status_code == 200
    assert standard.available(wanted)
    listening = next(q for q in load_curriculum()["exercises"] if q.get("audioRef") == wanted["id"])
    assert _objective_available(listening, _available_standard_audio(load_curriculum()))
    response = paired_client.get("/api/v1/audio/audio-final-a", headers={"Range": "bytes=0-43"})
    assert response.status_code == 206 and len(response.content) == 44
    exposed = next(
        a
        for a in paired_client.get("/api/v1/curriculum").json()["audioRequirements"]
        if a["id"] == wanted["id"]
    )
    assert exposed["available"] is True
    assert exposed["status"] == wanted["status"] != "approved"
    assert not standard.available({**wanted, "transcript": "changed target"})
    assert (
        client.post("/api/deactivate", json={"targetId": row["id"], "sha256": "stale"}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/deactivate", json={"targetId": row["id"], "sha256": row["sha256"]}
        ).status_code
        == 200
    )
    assert paired_client.get("/api/v1/audio/audio-final-a").status_code == 404
    assert not _objective_available(listening, _available_standard_audio(load_curriculum()))
    assert client.post("/api/activate", json=confirmation(row)).status_code == 200
    (standard.STANDARD_DIR / row["file"]).write_bytes(b"tampered")
    assert not standard.available(wanted)
    assert paired_client.get("/api/v1/audio/audio-final-a").status_code == 404


def test_authoring_access_controls(authoring):
    client, _ = authoring
    assert client.get("/").status_code == 200
    assert "blob:" in client.get("/").headers["Content-Security-Policy"]
    for headers in [
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ]:
        assert client.get("/api/catalog", headers=headers).status_code == 403
    assert client.post("/api/preview", headers={"X-Review-Token": ""}, json={}).status_code == 403
    with TestClient(
        client.app, base_url="http://127.0.0.1", client=("192.168.1.2", 50000)
    ) as remote:
        assert remote.get("/").status_code == 403
    assert draft(client, targetId="../../etc/passwd").status_code == 404


def test_duplicate_or_malformed_private_manifest_fails_closed(authoring):
    client, _ = authoring
    row = draft(client).json()
    client.post("/api/activate", json=confirmation(row))
    path = standard.STANDARD_DIR / "manifest.json"
    original = json.loads(path.read_text())
    original["assets"] *= 2
    write_json(path, original)
    assert standard.read_assets() == {}
    path.write_text("{broken")
    assert standard.read_assets() == {}


def test_import_revalidates_source_and_converted_cache(tmp_path, monkeypatch):
    from scripts import audio_review

    source = tmp_path / "input"
    source.mkdir()
    original = source / "test.mp3"
    original.write_bytes(b"explicit test source")
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    (candidates / "candidate-index.csv").write_text(
        "candidate_id,source_file,source_sha256,start_seconds,end_seconds,clip_sha256\n"
        f"c1,test.mp3,{audio_review.digest(original)},0.1,0.4,unused\n"
    )
    monkeypatch.setattr(audio_review, "lesson_recordings", lambda: {"lesson": {"file": "test.mp3"}})
    calls = []

    def convert(command, **_kwargs):
        calls.append(command)
        with wave.open(command[-1], "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x01\x00" * 16000)

    monkeypatch.setattr(audio_review.subprocess, "run", convert)
    work = tmp_path / "work"
    result = audio_review.import_sources(source, candidates, work)
    audio_review.import_sources(source, candidates, work)
    assert len(calls) == 1
    (work / result["sources"][0]["file"]).write_bytes(b"tampered cache")
    audio_review.import_sources(source, candidates, work)
    assert len(calls) == 2
    original.write_bytes(b"different original")
    with pytest.raises(ValueError, match="source does not match"):
        audio_review.import_sources(source, candidates, work)
