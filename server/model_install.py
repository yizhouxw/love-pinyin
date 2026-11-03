"""Explicit, single-flight installation of the optional local recognition model."""

import logging
import threading

from scripts.asr_model import validate_model
from scripts.fetch_asr_model import install
from server import reading_recognition

_lock = threading.Lock()
_state = "idle"


def status() -> dict:
    with _lock:
        state = _state
    if reading_recognition.status()["available"]:
        state = "installed"
    return {"state": state}


def start() -> dict:
    global _state
    with _lock:
        if _state == "downloading":
            return {"state": _state}
        _state = "downloading"
        threading.Thread(target=_download, daemon=True).start()
    return {"state": "downloading"}


def _download() -> None:
    global _state
    try:
        path = reading_recognition.MODEL_PATH
        if path.exists():
            try:
                validate_model(path)
            except ValueError:
                path.unlink()
        install(path)
        result = "installed"
    except Exception:
        logging.exception("Optional model installation failed")
        result = "failed"
    with _lock:
        _state = result
