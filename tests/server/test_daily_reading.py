import hashlib
import json

import pytest

from server import daily_reading, learning_audio, source_audio


def test_pdf_sequence_preserves_duplicates_tones_and_shared_source_page():
    data = daily_reading.load()
    assert [d["sourcePage"] for d in data["days"]] == [3, 4, 4, *range(5, 16)]
    first = data["days"][0]["sections"][0]["items"]
    assert [i["display"] for i in first[:8]] == ["ā", "á", "ǎ", "à", "á", "ō", "è", "ó"]
    assert len(first) == 24
    assert first[0]["audioIds"] != first[1]["audioIds"]
    assert sum(len(s["items"]) for d in data["days"] for s in d["sections"]) == 840
    nasal = data["days"][12]["sections"][1]["items"]
    assert [i["display"] for i in nasal[:6]] == ["ūn", "ǚn", "ùn", "ǜn", "ǔn", "ǚn"]
    dad = data["days"][2]["sections"][2]["items"][0]
    assert dad["display"] == "bà ba"
    assert dad["spokenText"] == "爸爸"
    assert dad["narrationId"]
    assert "ba" in dad["missingSyllables"]  # Never replace a missing neutral tone with ba1.


def test_status_without_assets_never_fakes_assessment_or_available_audio(
    paired_client, monkeypatch, tmp_path
):
    from server import reading_recognition

    monkeypatch.setattr(reading_recognition, "MODEL_PATH", tmp_path / "missing-model.bin")
    response = paired_client.get("/api/v1/daily-reading")
    assert response.status_code == 200
    data = response.json()
    assert data["assessment"]["available"] is False
    standards = [
        i
        for d in data["days"]
        for s in d["sections"]
        for i in s["items"]
        if not i["narrationId"] and not i.get("sentenceReading")
    ]
    assert not any(i["available"] for i in standards)
    assert paired_client.get("/api/v1/daily-audio/daily-a1").status_code == 404


def test_daily_audio_requires_pairing_but_guest_resource_has_no_household_write(test_client):
    assert test_client.get("/api/v1/daily-reading").status_code == 401
    assert test_client.get("/api/v1/guest/daily-reading").status_code == 200
    assert test_client.get("/api/v1/guest/daily-audio/unknown").status_code == 404
    assert (
        "microphone=(self)"
        in test_client.get("/api/v1/guest/daily-reading").headers["permissions-policy"]
    )


def test_registered_audio_range_integrity_disable_and_allowlist(paired_client, monkeypatch):
    data = daily_reading.load()
    asset = data["assets"][0]
    payload = b"permitted-test-audio-not-pronunciation-proof"
    digest = hashlib.sha256(payload).hexdigest()
    test_data = {**data, "assets": [{**asset, "sha256": digest, "bytes": len(payload)}]}
    monkeypatch.setattr(daily_reading, "load", lambda: test_data)
    root = source_audio.SOURCE_DIR
    (root / "clips").mkdir(parents=True)
    path = root / "clips" / f"{digest}.mp3"
    path.write_bytes(payload)
    source = source_audio.catalog()
    state = {
        "version": 1,
        "enabled": True,
        "commit": source["commit"],
        "archiveSha256": source["archiveSha256"],
    }
    (root / "installation.json").write_text(json.dumps(state))
    url = f"/api/v1/daily-audio/{asset['id']}"
    response = paired_client.get(url, headers={"Range": "bytes=2-7"})
    assert response.status_code == 206
    assert response.content == payload[2:8]
    assert paired_client.get("/api/v1/daily-audio/not-registered").status_code == 404
    path.write_bytes(b"corrupt")
    assert paired_client.get(url).status_code == 404
    path.write_bytes(payload)
    state["enabled"] = False
    (root / "installation.json").write_text(json.dumps(state))
    assert paired_client.get(url).status_code == 404


def test_daily_scripts_are_chinese_and_keep_demos_separate():
    scripts = learning_audio.narration_scripts()
    assert scripts["daily-ui-record"]
    assert scripts["daily-word-day-03-s3-i1"] == "爸爸"
    assert not any("bà" in text for key, text in scripts.items() if key.startswith("daily-"))


def test_daily_preparation_rejects_wrong_archive_without_writing(tmp_path):
    from scripts.prepare_daily_reading import prepare

    source = tmp_path / "wrong.zip"
    source.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="pinned"):
        prepare(source)
    assert not source_audio.SOURCE_DIR.exists()
