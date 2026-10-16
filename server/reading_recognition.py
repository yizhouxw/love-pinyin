"""Ephemeral, local ASR matching. No pronunciation score or persisted child audio."""

import io
import json
import math
import os
import re
import threading
import time
import unicodedata
import wave
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request

from scripts.asr_model import validate_model
from server.daily_reading import load

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "whisper-small" / "ggml-small.bin"
CONFIG_PATH = ROOT / "content" / "reading-recognition.json"
MAX_BYTES = 960_044
_LOCK = threading.Lock()
_MODEL = None
_TOKEN = re.compile(r"[\u3400-\u9fff]+|[A-Za-züÜāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+[1-5]?")


@lru_cache(maxsize=1)
def config() -> dict:
    data = json.loads(CONFIG_PATH.read_text())
    if data["version"] != 1 or data["mode"] != "asr-syllable-match":
        raise ValueError("Unknown ASR configuration")
    return data


def find_item(item_id: str) -> dict:
    for day in load()["days"]:
        for section in day["sections"]:
            for item in section["items"]:
                if item["id"] == item_id:
                    return item
    raise HTTPException(404, detail={"code": "READING_TARGET_NOT_FOUND"})


def base_syllable(value: str) -> str:
    value = value.lower().replace("v", "ü").replace("u:", "ü").replace("ɑ", "a").replace("ɡ", "g")
    result = []
    for char in unicodedata.normalize("NFD", value):
        if char == "\u0308":
            result.append(char)
        elif not unicodedata.combining(char) and char not in "12345":
            result.append(char)
    return unicodedata.normalize("NFC", "".join(result))


def match_transcript(item: dict, transcript: str) -> dict:
    from pypinyin import Style, lazy_pinyin

    transcript = unicodedata.normalize("NFC", transcript).replace("u:", "ü")
    actual = []
    presented = []
    unknown = bool(re.search(r"\w", _TOKEN.sub("", transcript)))
    for token in _TOKEN.findall(unicodedata.normalize("NFC", transcript)):
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            values = lazy_pinyin(token, style=Style.NORMAL, v_to_u=True)
            display = lazy_pinyin(token, style=Style.TONE, v_to_u=True)
            if any(re.search(r"[\u3400-\u9fff]", value) for value in values):
                unknown = True
            actual.extend(values)
            presented.extend(display)
        else:
            actual.append(base_syllable(token))
            presented.append(token.lower())
    expected = [base_syllable(value) for value in item["syllables"]]
    known = {
        base_syllable(value)
        for day in load()["days"]
        for section in day["sections"]
        for row in section["items"]
        for value in row["syllables"]
    }
    if any(
        base_syllable(token) not in known
        for token in _TOKEN.findall(transcript)
        if not re.fullmatch(r"[\u3400-\u9fff]+", token)
    ):
        unknown = True
    # Do not delete additional syllables or infer boundaries from the expected answer.
    if not actual or unknown:
        status = "uncertain"
    elif len(actual) == len(expected) and all(
        observed in config()["initialReadingAliases"].get(target, [target])
        for observed, target in zip(actual, expected, strict=True)
    ):
        status = "matched"
    else:
        status = "different"
    return {
        "status": status,
        "transcript": transcript[:500],
        "recognizedPinyin": " ".join(presented)[:500],
        "mode": "asr-syllable-match",
        "toneAssessed": False,
    }


def status() -> dict:
    available = MODEL_PATH.is_file() and MODEL_PATH.stat().st_size == 487_601_967
    return {"available": available, "mode": "asr-syllable-match", "toneAssessed": False}


def reject(reason: str, status: str = "uncertain") -> dict:
    return {"status": status, "reason": reason, "mode": "asr-syllable-match", "toneAssessed": False}


def decode_pcm(payload: bytes):
    import numpy as np

    try:
        with wave.open(io.BytesIO(payload), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
                or audio.getcomptype() != "NONE"
            ):
                raise ValueError("PCM format")
            frames = audio.getnframes()
            if not 2400 <= frames <= 480_000:
                raise ValueError("PCM duration")
            raw = audio.readframes(frames)
            if len(raw) != frames * 2:
                raise ValueError("PCM truncated")
    except (wave.Error, EOFError, ValueError) as error:
        raise HTTPException(422, detail={"code": "READING_PCM_INVALID"}) from error
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768


def recognize(item_id: str, payload: bytes) -> dict:
    global _MODEL
    import numpy as np

    item = find_item(item_id)
    samples = decode_pcm(payload)
    if (
        float(np.sqrt(np.mean(samples * samples))) < 0.002
        or np.count_nonzero(np.abs(samples) > 0.005) < 1600
    ):
        return reject("SILENCE_OR_TOO_QUIET")
    if float(np.mean(np.abs(samples) > 0.99)) > 0.2:
        return reject("CLIPPED_AUDIO")
    if not _LOCK.acquire(blocking=False):
        return reject("RECOGNIZER_BUSY", "unavailable")
    try:
        if _MODEL is None:
            try:
                validate_model(MODEL_PATH)
                from pywhispercpp.model import Model

                params = config()
                _MODEL = Model(
                    str(MODEL_PATH.resolve()),
                    context_params={"use_gpu": False}
                    if os.environ.get("LOVE_PINYIN_ASR_CPU_ONLY") == "1"
                    else None,
                    language=params["language"],
                    initial_prompt=params["initialPrompt"],
                    no_context=params["noContext"],
                    temperature=params["temperature"],
                    print_realtime=False,
                    print_progress=False,
                    print_timestamps=False,
                    redirect_whispercpp_logs_to=None,
                )
            except (ImportError, ValueError, RuntimeError, OSError):
                return reject("MODEL_UNAVAILABLE", "unavailable")
        started = time.monotonic()
        segments = _MODEL.transcribe(
            samples,
            n_processors=1,
            extract_probability=True,
            abort_callback=lambda: time.monotonic() - started > config()["timeoutSeconds"],
        )
        if time.monotonic() - started > config()["timeoutSeconds"]:
            return reject("RECOGNITION_TIMEOUT", "unavailable")
        nonempty = [segment for segment in segments if segment.text.strip()]
        if not nonempty or any(
            not math.isfinite(segment.probability)
            or segment.probability < config()["minimumSegmentProbability"]
            for segment in nonempty
        ):
            return reject("NOT_CLEAR_ENOUGH")
        transcript = "".join(segment.text for segment in nonempty).strip()
        return match_transcript(item, transcript)
    except (RuntimeError, ValueError, OSError):
        return reject("RECOGNITION_FAILED", "unavailable")
    finally:
        _LOCK.release()


async def request_audio(request: Request, item_id: str) -> bytes:
    find_item(item_id)
    if request.headers.get("content-type", "").split(";")[0] != "audio/wav":
        raise HTTPException(415, detail={"code": "READING_PCM_REQUIRED"})
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_BYTES:
            raise HTTPException(413, detail={"code": "READING_TOO_LONG"})
    return bytes(payload)
