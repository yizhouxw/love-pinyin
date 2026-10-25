"""Explicitly install daily PinYinSound clips from the already pinned archive."""

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from scripts.prepare_pinyin_source import MAX_ARCHIVE, atomic_json, check_recording
from server import daily_reading, source_audio


def prepare(archive: Path, *, archive_digest: str | None = None) -> dict:
    source = source_audio.catalog()
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Source archive too large")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != (
        archive_digest or source["archiveSha256"]
    ):
        raise ValueError("Source archive does not match pinned PinYinSound")
    if not source_audio.installed():
        raise ValueError(
            "Run prepare:pinyin first; daily reading does not enable a disabled source"
        )
    root = source_audio.SOURCE_DIR
    clips = root / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    report = []
    with tempfile.TemporaryDirectory(prefix="daily-pinyin-") as temp, zipfile.ZipFile(archive) as z:
        workspace = Path(temp)
        for asset in daily_reading.load()["assets"]:
            name = f"PinYinSound-{source['commit']}/{asset['filename']}"
            members = [m for m in z.infolist() if m.filename == name]
            if len(members) != 1 or members[0].file_size != asset["bytes"]:
                raise ValueError(f"Invalid source member: {asset['id']}")
            raw = z.read(members[0])
            if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
                raise ValueError(f"Source digest mismatch: {asset['id']}")
            candidate = workspace / f"{asset['sha256']}.mp3"
            candidate.write_bytes(raw)
            report.append(
                {"id": asset["id"], **check_recording(candidate, workspace / "check.wav")}
            )
        for asset in daily_reading.load()["assets"]:
            target = clips / f"{asset['sha256']}.mp3"
            temporary = target.with_suffix(".daily.tmp")
            temporary.write_bytes((workspace / target.name).read_bytes())
            os.replace(temporary, target)
    atomic_json(root / "daily-decode-report.json", {"assets": report})
    from scripts.build_first_tones import prepare as prepare_first_tones

    with tempfile.TemporaryDirectory(prefix="daily-first-tone-") as temp:
        derived = prepare_first_tones(daily_reading.load()["assets"], Path(temp))
    return {"clips": len(report), "derivedClips": len(derived), "source": source["commit"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive.expanduser()), ensure_ascii=False))


if __name__ == "__main__":
    main()
