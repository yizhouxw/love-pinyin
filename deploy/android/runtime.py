"""Fetch only the fixed, hashed Android runtime; never model weights."""

import hashlib
import json
import urllib.request
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "content/android-asr.json").read_text())["runtime"]
    target = root / f"deploy/android/app/libs/sherpa-onnx-{config['version']}.aar"
    target.parent.mkdir(parents=True, exist_ok=True)

    def verified(path: Path) -> bool:
        if not path.is_file():
            return False
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest() == config["sha256"]

    if not verified(target):
        partial = target.with_suffix(".partial")
        try:
            with (
                urllib.request.urlopen(config["url"], timeout=60) as response,
                partial.open("wb") as output,
            ):
                while block := response.read(1024 * 1024):
                    output.write(block)
            if not verified(partial):
                raise ValueError("Android runtime checksum mismatch")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
