import io
import threading
import wave
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server import daily_reading
from server import reading_recognition as recognition


def pcm(frames=8000, rate=16000, channels=1, amplitude=0):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(int(amplitude).to_bytes(2, "little", signed=True) * frames * channels)
    return output.getvalue()


def target(symbols):
    return {"syllables": symbols}


def test_recognized_chinese_homophones_match_syllables_without_claiming_tone():
    result = recognition.match_transcript(target(["ā"]), "啊~")
    assert result["status"] == "matched"
    assert result["toneAssessed"] is False
    assert recognition.match_transcript(target(["á"]), "啊")["status"] == "matched"
    assert recognition.match_transcript(target(["b"]), "波")["status"] == "matched"
    assert recognition.match_transcript(target(["b"]), "坡")["status"] == "different"
    assert recognition.match_transcript(target(["bà", "ba"]), "爸爸")["status"] == "matched"
    assert recognition.match_transcript(target(["bà", "ba"]), "妈妈")["status"] == "different"
    assert recognition.match_transcript(target(["nǚ"]), "女")["status"] == "matched"
    assert recognition.match_transcript(target(["nǐ"]), "女")["status"] == "different"


def test_extra_speech_is_not_deleted_and_latin_normalization_preserves_syllable_count():
    assert recognition.match_transcript(target(["ā"]), "这是啊")["status"] == "different"
    assert recognition.match_transcript(target(["bà", "ba"]), "ba4 ba5")["status"] == "matched"
    assert recognition.match_transcript(target(["bà", "ba"]), "baba")["status"] != "matched"
    assert recognition.match_transcript(target(["ā"]), "")["status"] == "uncertain"
    assert recognition.match_transcript(target(["lǜ"]), "lv4")["status"] == "matched"


def test_pcm_duration_format_and_truncation():
    assert len(recognition.decode_pcm(pcm())) == 8000
    for value in [b"bad", pcm(frames=100), pcm(rate=44100), pcm(channels=2), pcm()[:-4]]:
        with pytest.raises(HTTPException) as error:
            recognition.decode_pcm(value)
        assert error.value.status_code == 422


def test_silence_rejects_without_loading_model(monkeypatch):
    monkeypatch.setattr(recognition, "_MODEL", None)
    result = recognition.recognize("day-01-s1-i1", pcm())
    assert result["status"] == "uncertain"
    assert result["reason"] == "SILENCE_OR_TOO_QUIET"
    assert recognition._MODEL is None


def test_busy_missing_model_low_confidence_and_success_are_distinct(monkeypatch, tmp_path):
    lock = threading.Lock()
    monkeypatch.setattr(recognition, "_LOCK", lock)
    lock.acquire()
    assert recognition.recognize("day-01-s1-i1", pcm(amplitude=1000))["reason"] == "RECOGNIZER_BUSY"
    lock.release()
    monkeypatch.setattr(recognition, "_MODEL", None)
    monkeypatch.setattr(recognition, "MODEL_PATH", tmp_path / "missing.bin")
    assert (
        recognition.recognize("day-01-s1-i1", pcm(amplitude=1000))["reason"] == "MODEL_UNAVAILABLE"
    )

    class FakeModel:
        probability = 0.2

        def transcribe(self, *_args, **kwargs):
            assert kwargs["extract_probability"] is True
            assert callable(kwargs["abort_callback"])
            return [SimpleNamespace(text="啊", probability=self.probability)]

    model = FakeModel()
    monkeypatch.setattr(recognition, "_MODEL", model)
    assert recognition.recognize("day-01-s1-i1", pcm(amplitude=1000))["status"] == "uncertain"
    model.probability = 0.7
    assert recognition.recognize("day-01-s1-i1", pcm(amplitude=1000))["status"] == "matched"
    assert lock.acquire(blocking=False)
    lock.release()


def test_endpoint_checks_csrf_target_format_size_and_guest_origin(paired_client, monkeypatch):
    url = "/api/v1/daily-reading/day-01-s1-i1/recognize"
    assert (
        paired_client.post(url, content=pcm(), headers={"Content-Type": "audio/wav"}).status_code
        == 403
    )
    headers = {"Content-Type": "audio/wav", "X-LP-CSRF": paired_client.cookies["lp_csrf"]}
    response = paired_client.post(url, content=pcm(), headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "uncertain"
    assert (
        paired_client.post(
            url, content=b"x" * (recognition.MAX_BYTES + 1), headers=headers
        ).status_code
        == 413
    )
    assert paired_client.post(url, content=b"bad", headers=headers).status_code == 422
    assert (
        paired_client.post(
            url.replace("day-01-s1-i1", "unknown"), content=pcm(), headers=headers
        ).status_code
        == 404
    )
    assert (
        paired_client.post(
            url, content=pcm(), headers={**headers, "Content-Type": "audio/webm"}
        ).status_code
        == 415
    )
    guest = url.replace("/api/v1/", "/api/v1/guest/")
    assert (
        paired_client.post(
            guest,
            content=pcm(),
            headers={"Content-Type": "audio/wav", "Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        paired_client.post(guest, content=pcm(), headers={"Content-Type": "audio/wav"}).json()[
            "status"
        ]
        == "uncertain"
    )


def test_scenario_prompt_does_not_contain_current_target_or_previous_attempt():
    params = recognition.config()
    assert "拼音跟读" in params["initialPrompt"]
    assert params["noContext"] is True
    assert all(
        item["display"] not in params["initialPrompt"]
        for day in daily_reading.load()["days"]
        for section in day["sections"]
        for item in section["items"]
        if len(item["display"]) > 1
    )
