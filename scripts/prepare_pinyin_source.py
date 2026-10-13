"""Explicit, pinned import of the household's chosen demonstration recordings."""

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import tempfile
import urllib.request
import wave
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from server import source_audio
from server.content import load_curriculum
from server.source_audio import target_signature

MAX_ARCHIVE = 32 * 1024 * 1024


def atomic_json(path: Path, data: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def check_recording(path: Path, output: Path) -> dict:
    subprocess.run(
        [
            "/usr/bin/afconvert",
            "-f",
            "WAVE",
            "-d",
            "LEI16@16000",
            "-c",
            "1",
            str(path),
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with wave.open(str(output)) as audio:
        seconds = audio.getnframes() / audio.getframerate()
        if not 0.1 <= seconds <= 10 or audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError(f"Unexpected audio format/duration: {path.name}")
        raw = audio.readframes(audio.getnframes())
    samples = [value[0] / 32768 for value in struct.iter_unpack("<h", raw)]
    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    if peak < 0.01 or rms < 0.001:
        raise ValueError(f"Silent/near-silent source recording: {path.name}")
    return {"seconds": round(seconds, 6), "peak": round(peak, 6), "rms": round(rms, 6)}


def prepare(archive: Path, destination: Path, *, archive_digest: str | None = None) -> dict:
    source = source_audio.catalog()
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Source archive too large")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != (
        archive_digest or source["archiveSha256"]
    ):
        raise ValueError("Source archive digest does not match the pinned version")
    targets = {a["id"]: a for a in load_curriculum()["audioRequirements"]}
    for row in source["assets"]:
        if (
            row["id"] not in targets
            or target_signature(targets[row["id"]]) != row["targetSignature"]
        ):
            raise ValueError(f"Source mapping needs review: {row['id']}")
    destination.mkdir(parents=True, exist_ok=True)
    clips = destination / "clips"
    clips.mkdir(exist_ok=True)
    report = []
    with (
        tempfile.TemporaryDirectory(prefix="pinyin-source-") as temporary,
        zipfile.ZipFile(archive) as z,
    ):
        workspace = Path(temporary)
        for row in source["assets"]:
            name = f"PinYinSound-{source['commit']}/{row['filename']}"
            matches = [item for item in z.infolist() if item.filename == name]
            if (
                len(matches) != 1
                or matches[0].file_size != row["bytes"]
                or row["bytes"] > 2_000_000
            ):
                raise ValueError(f"Missing, duplicate or invalid source member: {row['filename']}")
            data = z.read(matches[0])
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError(f"Source file digest mismatch: {row['filename']}")
            candidate = workspace / f"{row['sha256']}.mp3"
            candidate.write_bytes(data)
            decoded = check_recording(candidate, workspace / "check.wav")
            report.append({"id": row["id"], **decoded})
        # Enable only after every member has passed integrity and actual decoding checks.
        for row in source["assets"]:
            target = clips / f"{row['sha256']}.mp3"
            staging = target.with_suffix(".tmp")
            staging.write_bytes((workspace / target.name).read_bytes())
            os.replace(staging, target)
    state = {
        "version": 1,
        "enabled": True,
        "commit": source["commit"],
        "archiveSha256": source["archiveSha256"],
        "preparedAt": datetime.now(UTC).isoformat(),
    }
    if archive_digest:
        state.update(transport="git-archive", transportSha256=archive_digest)
    atomic_json(destination / "decode-report.json", {"assets": report})
    atomic_json(destination / "installation.json", state)
    return {**state, "mappings": len(report), "files": len({r["sha256"] for r in source["assets"]})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, help="Use an existing pinned ZIP; do not access network"
    )
    parser.add_argument(
        "--disable", action="store_true", help="Disable source without deleting files"
    )
    args = parser.parse_args()
    root = source_audio.SOURCE_DIR
    if args.disable:
        root.mkdir(parents=True, exist_ok=True)
        atomic_json(root / "installation.json", {"version": 1, "enabled": False})
        print("PinYinSound household source disabled; files retained")
        return
    if args.archive:
        result = prepare(args.archive.expanduser(), root)
    else:
        with tempfile.TemporaryDirectory(prefix="pinyin-download-") as temporary:
            path = Path(temporary) / "source.zip"
            with urllib.request.urlopen(
                source_audio.catalog()["archiveUrl"], timeout=60
            ) as response:
                data = response.read(MAX_ARCHIVE + 1)
            if len(data) > MAX_ARCHIVE:
                raise ValueError("Source archive too large")
            path.write_bytes(data)
            result = prepare(path, root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
