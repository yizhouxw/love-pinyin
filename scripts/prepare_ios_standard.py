"""Build the redistributable iOS audio bank from a fixed mainland Mandarin recording bank."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import unicodedata
import wave
from array import array
from pathlib import Path

from server import daily_reading, source_audio
from server.content import load_curriculum
from server.materials import WORD_SOURCE, original_packs

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


def install_clip(output: Path, recording: bytes, extension: str) -> tuple[str, str]:
    sha = digest(recording)
    filename = f"{sha}.{extension}"
    destination = output / filename
    if not destination.exists():
        destination.write_bytes(recording)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", destination, "-f", "null", "-"],
            check=True,
        )
    elif digest(destination.read_bytes()) != sha:
        raise ValueError(f"Existing clip has a different digest: {destination}")
    return filename, sha


def crop_recording(source: bytes, start: float, end: float) -> bytes:
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
        raise ValueError("Extracted clip is silent")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(samples)
    return output.getvalue()


def spelling_targets(standard_ids: set[str]) -> set[str]:
    original, _, _ = original_packs(standard_ids)
    words = [
        *original["words"]["lessons"],
        *json.loads(WORD_SOURCE.read_text())["lessons"],
    ]
    readings = [item["pinyin"] for lesson in words for item in lesson["read"]]
    readings.extend(
        " ".join(item["syllables"])
        for daily in (original["daily"], daily_reading.load())
        for day in daily["days"]
        for section in day["sections"]
        if section["kind"] != "sentences"
        for item in section["items"]
    )
    readings.extend(
        example["pinyin"]
        for entry in daily_reading.word_examples().values()
        for example in entry["examples"]
    )
    tones = {"\u0304": 1, "\u0301": 2, "\u030c": 3, "\u0300": 4}
    targets = set()
    for reading in readings:
        for value in re.split(r"[\s'’·-]+", reading.lower()):
            decomposed = unicodedata.normalize("NFD", value)
            tone = next((tones[mark] for mark in decomposed if mark in tones), 5)
            plain = unicodedata.normalize(
                "NFC", "".join(char for char in decomposed if char not in tones)
            ).replace("ü", "v")
            if re.fullmatch(r"[a-z]+", plain):
                targets.add(f"{plain}{tone}")
    return targets


def prepare(chen_repo: Path, output: Path) -> None:
    policy = json.loads(POLICY.read_text())
    sources = policy["sources"]
    revision = subprocess.check_output(
        ["git", "-C", chen_repo, "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != sources["chen"]["revision"]:
        raise ValueError("audio-cmn checkout must match the pinned revision")
    chen_dir = chen_repo / "64k/syllabs"
    targets = {row["id"]: row for row in load_curriculum()["audioRequirements"]}
    output.mkdir(parents=True, exist_ok=True)
    clips = {}
    for row in source_audio.catalog()["assets"]:
        asset_id = row["id"]
        kind = targets[asset_id]["kind"]
        spelling = row["filename"].removesuffix(".mp3").replace("ü", "v")
        crop = None
        if kind == "initial":
            name, start, end = policy["initialCrops"][spelling]
            crop = (start, end)
        elif kind == "final" and spelling == "ong":
            recipe = policy["ong"]
            name = recipe["source"]
            crop = (recipe["startSeconds"], recipe["endSeconds"])
        elif kind == "final":
            name = policy["finalSyllableSpellings"].get(spelling, f"{spelling}1")
        else:
            vowel = re.fullmatch(r"([iuv])([1-4])", spelling)
            name = policy["isolatedVowelSpellings"][vowel[1]] + vowel[2] if vowel else spelling

        original = chen_recording(chen_dir, name)
        if crop:
            clip = crop_recording(original, *crop)
            extension = "wav"
            change = f"裁切 {crop[0]}–{crop[1]} 秒，短淡入淡出"
        else:
            clip, extension, change = original, "mp3", "filename only"
        filename, sha = install_clip(output, clip, extension)
        clips[asset_id] = {
            "source": "chen",
            "sourceFile": f"64k/syllabs/cmn-{name}.mp3",
            "sourceSha256": digest(original),
            "file": filename,
            "sha256": sha,
            "changes": change,
        }
    spelling = {}
    for name in sorted(spelling_targets(set(clips))):
        recorded_name = policy["spellingAliases"].get(name, name)
        source_file = f"cmn-{recorded_name}.mp3"
        if not (chen_dir / source_file).is_file():
            continue
        recording = chen_recording(chen_dir, recorded_name)
        filename, sha = install_clip(output, recording, "mp3")
        spelling[name] = {
            "source": "chen",
            "sourceFile": f"64k/syllabs/{source_file}",
            "sourceSha256": sha,
            "file": filename,
            "sha256": sha,
            "changes": "filename only",
        }
    (output / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "sources": sources, "clips": clips, "spelling": spelling},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"{len(clips)} standard targets, {len(spelling)} spelling targets")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chen-repo", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.chen_repo, OUTPUT)


if __name__ == "__main__":
    main()
