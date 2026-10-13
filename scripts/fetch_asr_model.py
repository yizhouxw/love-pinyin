"""Install the pinned Whisper model during explicit setup, never during inference."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from .asr_model import MODEL_FILENAME, MODEL_SIZE, MODEL_URL, validate_model


def install(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        validate_model(destination)
        return destination
    fd, temporary = tempfile.mkstemp(prefix=f".{MODEL_FILENAME}.", dir=destination.parent)
    os.close(fd)
    try:
        subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--retry",
                "3",
                "--retry-delay",
                "2",
                "--connect-timeout",
                "20",
                "--max-time",
                "900",
                "--max-filesize",
                str(MODEL_SIZE),
                "--output",
                temporary,
                MODEL_URL,
            ],
            check=True,
            capture_output=True,
            timeout=930,
        )
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
