"""Explicit, single-flight installation of the optional local recognition model."""

import logging
import subprocess
import tempfile
import threading
from pathlib import Path

from server import qwen_recognition as qwen

_lock = threading.Lock()
_state = "idle"


def status() -> dict:
    with _lock:
        state = _state
    if not qwen.supported():
        state = "unsupported"
    elif qwen.installed_signature(qwen.MODEL_DIR) is not None:
        state = "installed"
    elif state == "installed":
        state = "idle"
    return {"state": state}


def start() -> dict:
    global _state
    with _lock:
        if not qwen.supported():
            return {"state": "unsupported"}
        if _state == "downloading":
            return {"state": _state}
        if qwen.installed_signature(qwen.MODEL_DIR) is not None:
            return {"state": "installed"}
        _state = "downloading"
        threading.Thread(target=_download, daemon=True).start()
    return {"state": "downloading"}


def install(destination: Path) -> None:
    config = qwen.manifest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".qwen-download-") as tmp:
        root = Path(tmp) / "verified"
        root.mkdir()
        hosts = ("https://huggingface.co", "https://hf-mirror.com")
        for name, entry in config["files"].items():
            url = f"{config['repository']}/resolve/{config['revision']}/{name}?download=true"
            for host in hosts:
                result = subprocess.run(
                    [
                        "/usr/bin/curl",
                        "--disable",
                        "--proto",
                        "=https",
                        "--proto-redir",
                        "=https",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--location",
                        "--connect-timeout",
                        "10",
                        "--max-time",
                        "900",
                        "--max-filesize",
                        str(max(entry["bytes"], 1_048_576)),
                        "--output",
                        str(root / name),
                        f"{host}/{url}",
                    ],
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    hosts = (host, *(alternate for alternate in hosts if alternate != host))
                    break
            else:
                raise OSError(f"Optional model file download failed: {name}")
        if qwen.installed_signature(root) is None:
            raise ValueError("Optional model integrity check failed")
        if destination.exists():
            if qwen.installed_signature(destination) is not None:
                return
            destination.rename(Path(tmp) / "invalid")
        root.rename(destination)


def _download() -> None:
    global _state
    try:
        install(qwen.MODEL_DIR)
        result = "installed"
    except Exception:
        logging.exception("Optional model installation failed")
        result = "failed"
    with _lock:
        _state = result
