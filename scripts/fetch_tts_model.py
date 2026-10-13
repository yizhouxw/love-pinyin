"""Explicitly install the pinned Kokoro model for maintainers, not audio playback."""

import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install():
    config = json.loads((ROOT / "content" / "voice-build.json").read_text())
    destination = ROOT / "models" / "kokoro"
    model = destination / config["directory"]
    if model.is_dir():
        for name, digest in config["files"].items():
            if hashlib.sha256((model / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"TTS model digest mismatch: {name}")
        return model
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        root = Path(temporary)
        archive = root / "source.tar.bz2"
        with (
            urllib.request.urlopen(config["archiveUrl"], timeout=60) as response,
            archive.open("wb") as output,
        ):
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 512 * 1024 * 1024:
                    raise ValueError("TTS archive too large")
                output.write(block)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != config["archiveSha256"]:
            raise ValueError("TTS archive digest mismatch")
        with tarfile.open(archive) as data:
            data.extractall(root, filter="data")
        for name, digest in config["files"].items():
            if (
                hashlib.sha256((root / config["directory"] / name).read_bytes()).hexdigest()
                != digest
            ):
                raise ValueError(f"TTS model digest mismatch: {name}")
        shutil.move(root / config["directory"], model)
    return model


if __name__ == "__main__":
    print(install())
