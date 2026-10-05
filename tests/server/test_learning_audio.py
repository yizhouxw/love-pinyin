import hashlib
import json
import wave
from copy import deepcopy

import pytest

from scripts import prepare_learning_audio
from server import api, learning_audio


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def private_audio(monkeypatch, tmp_path):
    narration_path = tmp_path / "narration.json"
    recordings_path = tmp_path / "recordings.json"
    narration = {
        "version": 1,
        "ui": {"audio_error": {"text": "点一下小喇叭。"}},
        "exercises": {
            "q-01-01": {
                "text": "请看看这张卡片。",
                "hint": "仔细看上方的记号。",
                "options": {"a": "字母的上方"},
            },
        },
    }
    write_json(narration_path, narration)
    write_json(
        recordings_path,
        {
            "version": 1,
            "lessons": {
                "lesson-02": {"file": "2iuvYW.mp3", "title": "第二课合课录音"},
                "lesson-09": {"file": "2iuvYW.mp3", "title": "第九课合课录音"},
            },
        },
    )
    root = tmp_path / "private-audio"
    root.mkdir()
    monkeypatch.setattr(learning_audio, "load_writing", lambda: {"ui": {}, "glyphs": {}})
    monkeypatch.setattr(learning_audio, "load_illustrations", lambda: {"items": {}})
    monkeypatch.setattr(learning_audio, "NARRATION_PATH", narration_path)
    monkeypatch.setattr(learning_audio, "RECORDINGS_PATH", recordings_path)
    monkeypatch.setattr(learning_audio, "LEARNING_AUDIO_DIR", root)
    payload = b"RIFF-test-file-for-authentication-range-and-integrity"
    audio_path = root / "instruction.wav"
    audio_path.write_bytes(payload)
    asset_id = "ui-audio_error"
    asset = {
        "id": asset_id,
        **learning_audio.expected_assets()[asset_id],
        "file": "instruction.wav",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest = {"version": 1, "assets": [asset]}
    write_json(root / "manifest.json", manifest)
    return root, asset, payload, narration, narration_path


def test_actual_content_scripts_are_all_valid_chinese_and_ids_include_ui_error():
    scripts = learning_audio.narration_scripts()
    assert "ui-audio_error" in scripts
    assert len(scripts) > 100
    assert set(learning_audio.expected_assets()) >= set(scripts)


def test_private_audio_requires_pairing_and_reports_only_verified_ids(private_audio, test_client):
    assert test_client.get("/api/v1/learning-audio").status_code == 401
    assert test_client.get("/api/v1/voice/ui-audio_error").status_code == 401


def test_private_audio_is_seekable_and_catalog_does_not_expose_disk_paths(
    private_audio, paired_client
):
    root, asset, payload, _, _ = private_audio
    catalog = paired_client.get("/api/v1/learning-audio")
    assert catalog.status_code == 200
    assert catalog.json()["narration"] == {
        "ui-audio_error": True,
        "prompt-q-01-01": False,
        "hint-q-01-01": False,
        "option-q-01-01-a": False,
    }
    assert not catalog.json()["lessons"]["lesson-09"]["available"]
    assert str(root) not in catalog.text
    route = f"/api/v1/voice/{asset['id']}"
    response = paired_client.get(route)
    assert response.content == payload
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["etag"] == f'"sha256-{asset["sha256"]}"'
    ranged = paired_client.get(route, headers={"Range": "bytes=2-5"})
    assert ranged.status_code == 206
    assert ranged.content == payload[2:6]
    assert ranged.headers["content-range"] == f"bytes 2-5/{len(payload)}"
    suffix = paired_client.get(route, headers={"Range": "bytes=-4"})
    assert suffix.content == payload[-4:]
    invalid = paired_client.get(route, headers={"Range": "bytes=0-1,3-5"})
    assert invalid.status_code == 416
    assert not invalid.content


def test_changed_recording_or_changed_script_becomes_unavailable(private_audio, paired_client):
    root, asset, payload, narration, narration_path = private_audio
    route = f"/api/v1/voice/{asset['id']}"
    (root / "instruction.wav").write_bytes(payload + b"changed")
    assert paired_client.get(route).status_code == 404
    assert paired_client.get("/api/v1/learning-audio").json()["narration"][asset["id"]] is False
    (root / "instruction.wav").write_bytes(payload)
    narration["ui"]["audio_error"]["text"] = "新的中文指令。"
    write_json(narration_path, narration)
    assert paired_client.get(route).status_code == 404


def test_private_audio_rejects_unknown_id_traversal_symlink_and_duplicate_manifest(
    private_audio, paired_client, tmp_path
):
    root, asset, payload, _, _ = private_audio
    outside = tmp_path / "secret.wav"
    outside.write_bytes(payload)
    link = root / "link.wav"
    link.symlink_to(outside)
    for filename in ["../secret.wav", str(outside), "link.wav", "nested/../instruction.wav"]:
        write_json(root / "manifest.json", {"version": 1, "assets": [{**asset, "file": filename}]})
        assert paired_client.get(f"/api/v1/voice/{asset['id']}").status_code == 404
    write_json(root / "manifest.json", {"version": 1, "assets": [asset, asset]})
    assert paired_client.get(f"/api/v1/voice/{asset['id']}").status_code == 404
    write_json(root / "manifest.json", {"version": 1, "assets": [{**asset, "id": "unregistered"}]})
    assert paired_client.get("/api/v1/voice/unregistered").status_code == 404


def test_preparer_uses_cache_and_keeps_course_sources_unchanged(
    private_audio, monkeypatch, tmp_path
):
    root, _, _, narration, narration_path = private_audio
    calls = []

    def fake_synthesize(text, destination):
        calls.append(text)
        with wave.open(str(destination), "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(22050)
            recording.writeframes(b"\0\0" * 2205)
        return 0.1

    monkeypatch.setattr(prepare_learning_audio, "synthesize", fake_synthesize)
    monkeypatch.setattr(prepare_learning_audio, "_recording_duration", lambda _: 4.0)
    source = tmp_path / "user-recordings"
    source.mkdir()
    source_file = source / "2iuvYW.mp3"
    source_file.write_bytes(b"MP3-fixture-bytes")
    source_stat = source_file.stat()
    first = prepare_learning_audio.prepare(source)
    assert first["generatedFiles"] == 4
    assert first["importedFiles"] == 1
    assert first["lessonIds"] == 2
    assert len(calls) == 4
    assert source_file.stat().st_mtime_ns == source_stat.st_mtime_ns
    assert source_file.read_bytes() == b"MP3-fixture-bytes"
    second = prepare_learning_audio.prepare()
    assert second["generatedFiles"] == 0
    assert second["importedFiles"] == 0
    assert second["lessonIds"] == 2
    assert len(calls) == 4
    assert (root / "manifest.json").stat().st_mode & 0o777 == 0o600
    assert all(learning_audio.available_assets().values())
    narration["ui"]["audio_error"]["text"] = "请重播。"
    write_json(narration_path, narration)
    assert prepare_learning_audio.prepare()["generatedFiles"] == 1
    assert len(calls) == 5


def test_preparer_refuses_latin_or_pinyin_before_synthesizing(private_audio, monkeypatch):
    _, _, _, narration, narration_path = private_audio
    narration["exercises"]["q-01-01"]["text"] = "请朗读 ā"
    write_json(narration_path, narration)
    monkeypatch.setattr(
        prepare_learning_audio, "synthesize", lambda *_: pytest.fail("must not synthesize pinyin")
    )
    with pytest.raises(ValueError, match="Latin/pinyin"):
        prepare_learning_audio.prepare()


def test_trusted_source_enables_listening_without_review(
    paired_client, monkeypatch, install_standard
):
    content = deepcopy(api.load_curriculum())
    first_question = next(item for item in content["exercises"] if item["id"] == "q-01-01")
    asset = next(
        item for item in content["audioRequirements"] if item["id"] == first_question["audioRef"]
    )
    standard_file = install_standard(asset)
    monkeypatch.setattr(api, "load_curriculum", lambda: content)
    response = paired_client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")}
    )
    assert response.status_code == 200
    assert response.json()["tasks"][0]["exercise"]["id"] == "q-01-01"
    assert response.json()["audioAvailable"] is True
    assert paired_client.get("/api/v1/capabilities").json()["audio"]["available"] is True
    standard_file.write_bytes(b"corrupt")
    unavailable = paired_client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")}
    )
    assert unavailable.status_code == 200
    assert all(task["exercise"]["type"] != "listen-choice" for task in unavailable.json()["tasks"])
    assert unavailable.json()["audioAvailable"] is False


def test_hint_returns_question_specific_script_without_creating_answers(paired_client):
    client = paired_client
    csrf = {"X-LP-CSRF": client.cookies.get("lp_csrf")}
    session = client.post("/api/v1/sessions", json={}, headers=csrf).json()
    task = session["tasks"][0]
    question_id = task["exercise"]["id"]
    assert "hint" not in task["exercise"]
    before = client.get("/api/v1/profiles/progress").json()
    hint = client.post(f"/api/v1/instances/{task['instanceId']}/hint", headers=csrf)
    assert hint.status_code == 200
    assert hint.json()["explanation"] == learning_audio.narration_scripts()[f"hint-{question_id}"]
    assert "第一声" in hint.json()["explanation"]  # Actual first usable question.
    assert client.get("/api/v1/profiles/progress").json()["attempts"] == before["attempts"]
    revision = client.get("/api/v1/profiles/progress").json()["revision"]
    assert (
        client.post(f"/api/v1/instances/{task['instanceId']}/hint", headers=csrf).status_code == 200
    )
    assert client.get("/api/v1/profiles/progress").json()["revision"] == revision
