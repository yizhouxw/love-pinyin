"""Explicitly install the pinned Kokoro model for maintainers, not audio playback."""

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
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
                str(512 * 1024 * 1024),
                "--output",
                str(archive),
                config["archiveUrl"],
            ],
            check=True,
            capture_output=True,
            timeout=930,
        )
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
