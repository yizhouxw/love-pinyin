"""Optional local Qwen transcription. Audio stays in memory."""

import hashlib
import json
import os
import platform
import threading
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

import numpy as np

from server import reading_recognition as reading
from server.storage import DATA_DIR

MANIFEST = Path(__file__).resolve().parents[1] / "content" / "qwen-asr.json"
MODEL_DIR = DATA_DIR / "models" / "qwen3-asr-0.6b"
_lock = threading.Lock()
_model = None
_model_signature = None


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def supported() -> bool:
    return (
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and (find_spec("mlx_audio") is not None)
    )


@lru_cache(maxsize=4)
def _verified(folder: Path, signature: tuple) -> bool:
    try:
        for name, entry in manifest()["files"].items():
            with (folder / name).open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != entry["sha256"]:
                    return False
        return True
    except OSError:
        return False


def installed_signature(folder: Path) -> tuple | None:
    try:
        values = []
        for name, entry in manifest()["files"].items():
            stat = (folder / name).stat()
            if stat.st_size != entry["bytes"]:
                return None
            values.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        signature = tuple(values)
        return signature if _verified(folder, signature) else None
    except OSError:
        return None


def status() -> dict:
    return {
        "available": supported() and installed_signature(MODEL_DIR) is not None,
        "mode": "asr-syllable-match",
        "toneAssessed": False,
    }


def transcribe(payload: bytes, *, maximum_frames: int = 480_000, tokens: int = 192) -> dict:
    global _model, _model_signature
    samples = reading.decode_pcm(payload)
    if len(samples) > maximum_frames:
        return reading.reject("READING_TOO_LONG")
    if float(np.sqrt(np.mean(samples * samples))) < 0.002 or (
        np.count_nonzero(np.abs(samples) > 0.005) < 1600
    ):
        return reading.reject("SILENCE_OR_TOO_QUIET")
    if float(np.mean(np.abs(samples) > 0.99)) > 0.2:
        return reading.reject("CLIPPED_AUDIO")
    if not supported():
        return reading.reject("MODEL_UNAVAILABLE", "unavailable")
    signature = installed_signature(MODEL_DIR)
    if signature is None:
        return reading.reject("MODEL_UNAVAILABLE", "unavailable")
    if not _lock.acquire(blocking=False):
        return reading.reject("RECOGNIZER_BUSY", "unavailable")
    try:
        if _model is None or _model_signature != signature:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            from mlx_audio.stt.utils import load_model

            _model = load_model(MODEL_DIR.resolve(), strict=True)
            _model_signature = signature
        result = _model.generate(
            samples, language="Chinese", temperature=0, max_tokens=tokens, verbose=False
        )
        if result.generation_tokens >= tokens or not result.text.strip():
            return reading.reject("NOT_CLEAR_ENOUGH")
        return {"transcript": result.text.strip()}
    except (ImportError, RuntimeError, ValueError, OSError):
        return reading.reject("RECOGNITION_FAILED", "unavailable")
    finally:
        _lock.release()


def recognize(item_id: str, payload: bytes) -> dict:
    item = reading.find_item(item_id)
    result = transcribe(payload)
    if "transcript" not in result:
        return result
    return reading.match_transcript(item, result["transcript"])
