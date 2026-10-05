"""Explicitly prepare private Mac narration; optionally import the user's MP3s.

This command uses only an installed system voice. It never downloads a voice,
calls a speech service, modifies source recordings, or publishes audio assets.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi import HTTPException

from server import learning_audio

VOICE = "Tingting"
RATE = 165
SAMPLE_RATE = 22050


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def synthesize(text: str, destination: Path) -> float:
    if not Path("/usr/bin/say").is_file():
        raise RuntimeError(
            "An installed macOS Tingting voice is required; no download is attempted"
        )
    fd, raw_path = tempfile.mkstemp(suffix=".wav", dir=destination.parent)
    os.close(fd)
    temporary = Path(raw_path)
    try:
        subprocess.run(
            [
                "/usr/bin/say",
                "-v",
                VOICE,
                "-r",
                str(RATE),
                "-o",
                str(temporary),
                "--file-format=WAVE",
                f"--data-format=LEI16@{SAMPLE_RATE}",
                text,
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
        with wave.open(str(temporary), "rb") as audio:
            if audio.getnframes() < 100 or audio.getnchannels() != 1:
                raise RuntimeError("System voice did not produce a valid mono recording")
            duration = audio.getnframes() / audio.getframerate()
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        return duration
    finally:
        temporary.unlink(missing_ok=True)


def _recording_duration(path: Path) -> float | None:
    if not Path("/usr/bin/afinfo").is_file():
        return None
    try:
        info = subprocess.run(
            ["/usr/bin/afinfo", str(path)], check=True, capture_output=True, text=True, timeout=20
        )
        match = re.search(r"estimated duration:\s*([\d.]+)\s*sec", info.stdout)
        return float(match[1]) if match else None
    except (OSError, subprocess.SubprocessError):
        return None


def _valid_existing(asset: dict | None, expected: dict, output: Path) -> bool:
    if not asset:
        return False
    try:
        path, _, digest = learning_audio.registered_file(asset, expected)
        return path.stat().st_size > 0 and file_digest(path) == digest
    except (HTTPException, OSError):
        return False


def prepare(source: Path | None = None) -> dict:
    output = learning_audio.LEARNING_AUDIO_DIR
    _private_dir(output)
    _private_dir(output / "narration")
    _private_dir(output / "lessons")
    # Validate every Chinese script before invoking the system voice.
    scripts = learning_audio.narration_scripts()
    expected = learning_audio.expected_assets()
    existing = learning_audio.read_manifest()
    generated = 0
    assets: list[dict] = []
    generated_by_text: dict[str, dict] = {}
    for asset_id, text in scripts.items():
        previous = existing.get(asset_id)
        if (
            _valid_existing(previous, expected[asset_id], output)
            and previous.get("voice") == VOICE
            and previous.get("rate") == RATE
            and previous.get("sampleRate") == SAMPLE_RATE
        ):
            assets.append(previous)
            generated_by_text[text] = previous
            continue
        if text in generated_by_text:
            assets.append({**generated_by_text[text], "id": asset_id})
            continue
        key = learning_audio.text_digest(f"{VOICE}:{RATE}:{SAMPLE_RATE}:{text}")
        relative = f"narration/{key}.wav"
        path = output / relative
        duration = synthesize(text, path)
        generated += 1
        asset = {
            "id": asset_id,
            **expected[asset_id],
            "file": relative,
            "sha256": file_digest(path),
            "durationSeconds": round(duration, 3),
            "voice": VOICE,
            "rate": RATE,
            "sampleRate": SAMPLE_RATE,
            "distribution": "private-personal-use",
        }
        assets.append(asset)
        generated_by_text[text] = asset

    imported = 0
    copies: dict[str, dict] = {}
    source = source.expanduser().resolve(strict=True) if source is not None else None
    if source is not None and not source.is_dir():
        raise ValueError("--source must identify the user's lesson recording directory")
    for lesson_id, item in learning_audio.lesson_recordings().items():
        asset_id = f"lesson-{lesson_id}"
        if source is None:
            if _valid_existing(existing.get(asset_id), expected[asset_id], output):
                assets.append(existing[asset_id])
            continue
        source_file = (source / item["file"]).resolve(strict=True)
        if source not in source_file.parents or not source_file.is_file():
            raise ValueError(f"recording is outside the selected source directory: {item['file']}")
        if item["file"] in copies:
            assets.append({**copies[item["file"]], "id": asset_id})
            continue
        digest = file_digest(source_file)
        if source_file.stat().st_size == 0:
            raise ValueError(f"recording is empty: {item['file']}")
        relative = f"lessons/{digest}.mp3"
        destination = output / relative
        if not destination.is_file() or file_digest(destination) != digest:
            fd, raw_path = tempfile.mkstemp(suffix=".mp3", dir=destination.parent)
            os.close(fd)
            temporary = Path(raw_path)
            try:
                shutil.copyfile(source_file, temporary)
                if file_digest(temporary) != digest:
                    raise RuntimeError(f"source changed while copying: {item['file']}")
                os.chmod(temporary, 0o600)
                temporary.replace(destination)
                imported += 1
            finally:
                temporary.unlink(missing_ok=True)
        asset = {
            "id": asset_id,
            **expected[asset_id],
            "file": relative,
            "sha256": digest,
            "durationSeconds": _recording_duration(destination),
            "distribution": "private-user-provided",
        }
        assets.append(asset)
        copies[item["file"]] = asset

    payload = json.dumps({"version": 1, "assets": assets}, ensure_ascii=False, indent=2) + "\n"
    fd, raw_path = tempfile.mkstemp(suffix=".json", dir=output)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    manifest_temporary = Path(raw_path)
    os.chmod(manifest_temporary, 0o600)
    manifest_temporary.replace(output / "manifest.json")
    unique = {asset["file"]: asset for asset in assets}
    return {
        "manifest": str(output / "manifest.json"),
        "narrationIds": len(scripts),
        "lessonIds": sum(asset["purpose"] == "whole-lesson-recording" for asset in assets),
        "files": len(unique),
        "generatedFiles": generated,
        "importedFiles": imported,
        "totalBytes": sum((output / filename).stat().st_size for filename in unique),
        "totalDurationSeconds": round(
            sum(asset.get("durationSeconds") or 0 for asset in unique.values()), 3
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, help="Explicit directory of user-provided course MP3s"
    )
    args = parser.parse_args()
    print(json.dumps(prepare(args.source), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
