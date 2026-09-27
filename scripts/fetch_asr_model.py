"""Explicitly download the pinned Whisper model; never called at app startup."""

from __future__ import annotations

import argparse
import os
import tempfile
import urllib.request
from pathlib import Path

from .asr_model import MODEL_FILENAME, MODEL_URL, validate_model


def install(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        validate_model(destination)
        return destination
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "love-pinyin-model-fetch/1"})
    fd, temporary = tempfile.mkstemp(prefix=f".{MODEL_FILENAME}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=60) as response:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary_path = Path(temporary)
        validate_model(temporary_path)
        temporary_path.replace(destination)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("models/whisper-small/ggml-small.bin"),
    )
    args = parser.parse_args()
    path = install(args.destination)
    print(f"已安装并校验模型: {path.resolve()}")


if __name__ == "__main__":
    main()
