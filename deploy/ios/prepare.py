"""Stage iOS resources from the same validated sources as the desktop app."""

import argparse
import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

from server import daily_reading, learning_audio, source_audio
from server.content import load_curriculum
from server.game_levels import catalog as level_catalog
from server.game_levels import freeze_run
from server.game_policy import CATALOG as GAME_RULES
from server.learning_state import _objective_available
from server.routes import resources

ROOT = Path(__file__).resolve().parents[2]


def encode_narration(source: Path, encoded: Path, decoded: Path) -> None:
    subprocess.run(
        [
            "/usr/bin/afconvert",
            "-f",
            "m4af",
            "-d",
            "aac",
            "-b",
            "64000",
            "--no-filler",
            source,
            encoded,
        ],
        check=True,
    )
    subprocess.run(
        ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16", encoded, decoded],
        check=True,
    )
    with wave.open(str(source)) as original, wave.open(str(decoded)) as result:
        if (original.getframerate(), original.getnframes()) != (
            result.getframerate(),
            result.getnframes(),
        ):
            raise ValueError(f"Encoded narration changed the timeline: {source.name}")
    decoded.unlink()


def game_resources() -> dict:
    routes = level_catalog()
    # Runtime binding needs the shortened patterns for every authored segment.
    # Reuse the same frozen pattern projection as B/S and discard the build-only IDs.
    slots = [{"instanceId": f"build-slot-{i}"} for i in range(GAME_RULES["play"]["maxTasks"])]
    patterns = {}
    for level in routes["levels"]:
        patterns.update(freeze_run(level, slots)["patterns"])
    return {"rules": GAME_RULES, "routes": {**routes, "patterns": patterns}}


def prepare(output: Path, trial_aac: bool) -> None:
    web = output / "Web"
    web.mkdir(parents=True)
    shutil.copytree(ROOT / "dist", web, dirs_exist_ok=True)
    shutil.copytree(ROOT / "resources/licenses", output / "Licenses")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, output / name)
    clips = output / "Audio"
    clips.mkdir()
    catalog: dict[str, dict] = {}
    encoded_narration: dict[str, dict] = {}

    def add(kind: str, asset_id: str, path: Path, digest: str) -> None:
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Missing or corrupt audio: {kind}/{asset_id}")
        if trial_aac and kind == "voice" and path.suffix == ".wav":
            if digest not in encoded_narration:
                name = f"{digest}.m4a"
                encoded = clips / name
                encode_narration(path, encoded, output / "decoded.wav")
                encoded_narration[digest] = {
                    "file": name,
                    "sha256": hashlib.sha256(encoded.read_bytes()).hexdigest(),
                    "originalSha256": digest,
                    "encoding": "afconvert 2.0 AAC 64000 bps",
                }
            catalog[f"{kind}/{asset_id}"] = encoded_narration[digest]
            return
        name = f"{digest}{path.suffix}"
        if not (clips / name).exists():
            shutil.copyfile(path, clips / name)
        catalog[f"{kind}/{asset_id}"] = {"file": name, "sha256": digest}

    registered_ids = {row["id"] for row in source_audio.catalog()["assets"]}
    for target in load_curriculum()["audioRequirements"]:
        if target["id"] not in registered_ids:
            continue
        path, digest = source_audio.registered_path(target)
        add("audio", target["id"], path, digest)
    manifest = learning_audio.read_manifest()
    for asset_id, expected in learning_audio.expected_assets().items():
        path, _, digest = learning_audio.registered_file(manifest[asset_id], expected)
        add("voice", asset_id, path, digest)
    daily = daily_reading.load()
    for asset_id in [*(a["id"] for a in daily["assets"]), *daily.get("derivedAssets", [])]:
        add("daily-audio", asset_id, *daily_reading.registered(asset_id))
    data = output / "Data"
    data.mkdir()
    reading = daily_reading.status()
    reading["assessment"]["available"] = False
    curriculum = load_curriculum()
    standard = {
        target["id"]
        for target in curriculum["audioRequirements"]
        if f"audio/{target['id']}" in catalog
    }
    scripts = learning_audio.narration_scripts()
    classroom = {
        "version": curriculum["contentVersion"],
        "lessons": curriculum["lessons"],
        "knowledgeItems": curriculum["knowledgeItems"],
        "game": game_resources(),
        "eligible": [
            {
                "exercise": question,
                "explanation": scripts[f"hint-{question['id']}"],
            }
            for question in curriculum["exercises"]
            if _objective_available(question, standard)
        ],
    }
    for name, payload in {
        "audio": catalog,
        "web-files": sorted(
            str(path.relative_to(web)) for path in web.rglob("*") if path.is_file()
        ),
        "curriculum": resources.curriculum({}),
        "classroom": classroom,
        "daily-reading": reading,
        "learning-audio": learning_audio.learning_audio_status(),
    }.items():
        (data / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--trial-aac", action="store_true")
    args = parser.parse_args()
    prepare(args.output, args.trial_aac)
