"""Build the redistributable iOS audio bank from explicitly supplied fixed sources."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import wave
import zipfile
from array import array
from pathlib import Path

from server import source_audio
from server.content import load_curriculum

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "content/ios-standard-audio.json"
OUTPUT = ROOT / "resources/audio/ios-standard"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chen_recording(root: Path, name: str) -> bytes:
    file = root / f"cmn-{name}.mp3"
    tags = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", file]
        )
    )["format"]["tags"]
    if tags.get("SWAC_COLL_LICENSE") != "CC-BY-SA-3.0" or tags.get("SWAC_TEXT") != name:
        raise ValueError(f"Unexpected original recording label or license: {name}")
    return file.read_bytes()


def without_onset(source: bytes, start: float, end: float) -> bytes:
    samples = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "mp3",
            "-i",
            "pipe:0",
            "-af",
            f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
            f"afade=t=in:d=0.012,afade=t=out:st={end - start - 0.02:.3f}:d=0.02",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-f",
            "s16le",
            "pipe:1",
        ],
        input=source,
    )
    if max(map(abs, array("h", samples)), default=0) < 500:
        raise ValueError("Extracted final is silent")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(samples)
    return output.getvalue()


def prepare(chen_repo: Path, archive: Path, output: Path) -> None:
    policy = json.loads(POLICY.read_text())
    sources = policy["sources"]
    revision = subprocess.check_output(
        ["git", "-C", chen_repo, "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != sources["chen"]["revision"]:
        raise ValueError("audio-cmn checkout must match the pinned revision")
    if digest(archive.read_bytes()) != sources["bopomofo"]["archiveSha256"]:
        raise ValueError("Official audio archive does not match the pinned SHA-256")
    chen_dir = chen_repo / "64k/syllabs"
    targets = {row["id"]: row for row in load_curriculum()["audioRequirements"]}
    output.mkdir(parents=True, exist_ok=True)
    clips = {}
    with zipfile.ZipFile(archive) as bopomofo:
        (output / "bopomofo-NOTICE.txt").write_bytes(bopomofo.read("license.txt"))
        for row in source_audio.catalog()["assets"]:
            asset_id = row["id"]
            kind = targets[asset_id]["kind"]
            spelling = row["filename"].removesuffix(".mp3").replace("ü", "v")
            source = "chen"
            extension = "mp3"
            change = "filename only"
            if kind == "initial":
                number = 1 + policy["initialSymbolOrder"].index(spelling)
            elif kind == "final":
                number = policy["finalSymbolNumbers"].get(spelling)
            else:
                number = None
            if number is not None:
                source, extension = "bopomofo", "wav"
                source_file = f"audio/F{number}.WAV"
                original = clip = bopomofo.read(source_file)
            else:
                if kind == "final" and spelling == "ong":
                    recipe = policy["ong"]
                    name = recipe["source"]
                    original = chen_recording(chen_dir, name)
                    clip = without_onset(original, recipe["startSeconds"], recipe["endSeconds"])
                    change = (
                        f"韵母裁切 {recipe['startSeconds']}–{recipe['endSeconds']} 秒，短淡入淡出"
                    )
                    extension = "wav"
                else:
                    vowel = re.fullmatch(r"([iuv])([1-4])", spelling)
                    if kind == "final":
                        name = policy["finalSyllableSpellings"][spelling]
                    elif vowel:
                        name = policy["isolatedVowelSpellings"][vowel[1]] + vowel[2]
                    else:
                        name = spelling
                    original = clip = chen_recording(chen_dir, name)
                source_file = f"64k/syllabs/cmn-{name}.mp3"
            sha = digest(clip)
            filename = f"{sha}.{extension}"
            destination = output / filename
            if not destination.exists():
                destination.write_bytes(clip)
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-xerror", "-i", destination, "-f", "null", "-"],
                    check=True,
                )
            elif digest(destination.read_bytes()) != sha:
                raise ValueError(f"Existing clip has a different digest: {destination}")
            clips[asset_id] = {
                "source": source,
                "sourceFile": source_file,
                "sourceSha256": digest(original),
                "file": filename,
                "sha256": sha,
                "changes": change,
            }
    (output / "manifest.json").write_text(
        json.dumps({"version": 1, "sources": sources, "clips": clips}, ensure_ascii=False, indent=2)
        + "\n"
    )
    print(f"{len(clips)} targets, {len({asset['file'] for asset in clips.values()})} audio files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chen-repo", required=True, type=Path)
    parser.add_argument("--bopomofo-archive", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.chen_repo, args.bopomofo_archive, OUTPUT)


if __name__ == "__main__":
    main()
