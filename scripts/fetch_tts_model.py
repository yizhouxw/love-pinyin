"""Explicitly install pinned Qwen3-TTS files for maintainers, not audio playback."""

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_files(model: Path, config: dict):
    for name, digest in config["files"].items():
        path = (model / name).resolve(strict=True)
        if model.resolve() not in path.parents:
            raise ValueError(f"TTS model path escapes directory: {name}")
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ValueError(f"TTS model digest mismatch: {name}")


def install():
    config = json.loads((ROOT / "content" / "voice-build.json").read_text())
    destination = ROOT / "models" / "qwen3-tts"
    model = destination / config["directory"]
    if model.is_dir():
        verify_files(model, config)
        return model
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        root = Path(temporary)
        for name in config["files"]:
            path = root / name
            if root.resolve() not in path.resolve().parents:
                raise ValueError(f"TTS model path escapes directory: {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Downloading fixed TTS resource: {name}", flush=True)
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
                    "3600",
                    "--max-filesize",
                    str(config["sizes"][name]),
                    "--output",
                    str(path),
                    f"{config['downloadSource']}/resolve/{config['revision']}/{name}",
                ],
                check=True,
                capture_output=True,
                timeout=3630,
            )
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != config["files"][name]:
                    raise ValueError(f"TTS model digest mismatch: {name}")
        verify_files(root, config)
        shutil.move(root, model)
    return model


if __name__ == "__main__":
    print(install())
