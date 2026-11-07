"""Stage iOS resources from the same validated sources as the desktop app."""

import argparse
import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

from deploy.ios.practice_packs import WORD_SOURCE, original_packs, original_voice
from server import daily_reading, learning_audio, source_audio
from server.content import load_curriculum
from server.game_levels import catalog as level_catalog
from server.game_levels import freeze_run
from server.game_policy import CATALOG as GAME_RULES
from server.learning_state import _objective_available
from server.routes import resources

ROOT = Path(__file__).resolve().parents[2]
COURSE_AUDIO = ROOT / "resources/audio/ios-lessons"
COURSE_SCRIPTS = ROOT / "content/ios-lesson-narration.json"
PUBLIC_STANDARD = ROOT / "resources/audio/ios-standard"
IOS_WEB = ROOT / "build/ios/Web"


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


def public_standard_catalog(required: set[str]) -> dict:
    manifest = PUBLIC_STANDARD / "manifest.json"
    if not manifest.is_file():
        raise ValueError("Public iOS build requires a complete redistributable standard audio bank")
    payload = json.loads(manifest.read_text())
    if payload.get("version") != 1 or not payload.get("sources"):
        raise ValueError("Public standard audio source documentation is missing")
    for source in payload["sources"].values():
        if source.get("license") not in {
            "CC0-1.0",
            "CC-BY-4.0",
            "CC-BY-SA-3.0",
            "Apache-2.0",
            "MIT",
        } or not all(source.get(field) for field in ("url", "licenseUrl", "attribution")):
            raise ValueError("Public standard audio requires redistributable sources")
    clips = payload["clips"]
    if set(clips) != required:
        raise ValueError("Public standard audio must cover the current classroom and games")
    for asset in clips.values():
        if (
            asset["source"] not in payload["sources"]
            or Path(asset["file"]).name != asset["file"]
            or Path(asset["file"]).suffix not in {".wav", ".mp3"}
        ):
            raise ValueError("Invalid public standard audio entry")
    return payload


def validate_practice_audio(packs: dict, catalog: dict) -> None:
    for name in ("original", "household"):
        if name not in packs:
            continue
        pack = packs[name]
        for day in pack["daily"]["days"]:
            for section in day["sections"]:
                instruction = section.get("instructionId") or f"daily-instruction-{section['id']}"
                if f"voice/{instruction}" not in catalog:
                    raise ValueError(f"Missing instruction audio for {name}/{section['id']}")
                for item in section["items"]:
                    if any(f"daily-audio/{asset}" not in catalog for asset in item["audioIds"]):
                        raise ValueError(f"Missing standard audio for {name}/{item['id']}")
        for lesson in pack["words"]["lessons"]:
            ids = [
                lesson["audioId"],
                *(
                    item["audioId"]
                    for key in ("read", "write", "characterItems")
                    for item in lesson[key]
                ),
                *(
                    paragraph["audioId"]
                    for passage in lesson["passages"]
                    for paragraph in passage["paragraphs"]
                ),
            ]
            if any(f"voice/{asset}" not in catalog for asset in ids):
                raise ValueError(f"Missing word or reading audio for {name}/{lesson['id']}")


def validate_public_materials(web: Path, catalog: dict, lesson_manifest: dict) -> None:
    """Catch leaked family text or source recordings before publishing resources."""
    legacy = {row["sha256"] for row in source_audio.catalog()["assets"]}
    legacy.update(row["sha256"] for row in daily_reading.load()["assets"])
    legacy.update(
        row["sha256"]
        for row in lesson_manifest.values()
        if row.get("sourceType") == "user-provided-recording"
    )
    if any(asset["sha256"] in legacy for asset in catalog.values()):
        raise ValueError("Family audio found in public resources")
    household = json.loads(WORD_SOURCE.read_text())
    scripts = [
        paragraph["text"]
        for lesson in household["lessons"]
        for passage in lesson["passages"]
        for paragraph in passage["paragraphs"]
    ]
    family_signatures = [household["source"]["sha256"], daily_reading.load()["source"]["sha256"]]
    family_signatures += [text for text in scripts if len(text) >= 12]
    for script in web.rglob("*.js"):
        content = script.read_text()
        if any(text in content for text in family_signatures):
            raise ValueError(f"Family practice text found in {script.name}")


def prepare(output: Path, trial_aac: bool, public: bool = False) -> None:
    required_standard = {row["id"] for row in source_audio.catalog()["assets"]}
    public_standard = public_standard_catalog(required_standard)
    web = output / "Web"
    web.mkdir(parents=True)
    shutil.copytree(IOS_WEB, web, dirs_exist_ok=True)
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

    for asset_id, asset in public_standard["clips"].items():
        add("audio", asset_id, PUBLIC_STANDARD / asset["file"], asset["sha256"])
    shutil.copyfile(PUBLIC_STANDARD / "manifest.json", output / "StandardAudioSources.json")
    shutil.copyfile(
        PUBLIC_STANDARD / "bopomofo-NOTICE.txt", output / "Licenses/bopomofo-NOTICE.txt"
    )

    original, aliases, practice_scripts = original_packs(required_standard)
    for asset_id, standard_id in aliases.items():
        catalog[f"daily-audio/{asset_id}"] = catalog[f"audio/{standard_id}"]
    for asset_id, path, digest in original_voice(practice_scripts):
        add("voice", asset_id, path, digest)
    practice_packs = {
        "original": original,
        "standardSources": list(public_standard["sources"].values()),
    }
    if not public:
        daily = daily_reading.load()
        for asset_id in [*(a["id"] for a in daily["assets"]), *daily.get("derivedAssets", [])]:
            add("daily-audio", asset_id, *daily_reading.registered(asset_id))
        reading = daily_reading.status()
        reading["assessment"]["available"] = False
        hanzi = json.loads((ROOT / "content/daily-reading-hanzi.json").read_text())
        for day in reading["days"]:
            for section in day["sections"]:
                for item in section["items"]:
                    if item["id"] in hanzi:
                        item["hanzi"] = hanzi[item["id"]]
        practice_packs["household"] = {
            "daily": reading,
            "words": json.loads(WORD_SOURCE.read_text()),
        }

    course_manifest = json.loads((COURSE_AUDIO / "manifest.json").read_text())
    course_scripts = json.loads(COURSE_SCRIPTS.read_text())["lessons"]
    current_lessons = load_curriculum()["lessons"]
    if set(course_manifest["lessons"]) != {lesson["id"] for lesson in current_lessons}:
        raise ValueError("iOS course audio must cover all current lessons")
    lesson_audio = {}
    for lesson in current_lessons:
        lesson_id = lesson["id"]
        asset = course_manifest["lessons"][lesson_id]
        filename = f"{lesson_id}.mp3"
        if asset["file"] != filename or asset["textSha256"] != learning_audio.text_digest(
            "\n".join(course_scripts[lesson_id])
        ):
            raise ValueError(f"Stale course recording: {lesson_id}")
        asset_id = f"lesson-{lesson_id}"
        add("voice", asset_id, COURSE_AUDIO / filename, asset["sha256"])
        lesson_audio[lesson_id] = {
            "audioId": asset_id,
            "title": f"{lesson['title']} · 爱拼音原创课程",
            "available": True,
            "sourceType": "local-open-tts",
        }
    manifest = learning_audio.read_manifest()
    public_voice_prefixes = (
        "ui-",
        "prompt-",
        "hint-",
        "option-",
        "writing-",
        "picture-",
        "word-ui-",
        "daily-ui-",
    )
    for asset_id, expected in learning_audio.expected_assets().items():
        if expected["purpose"] == "whole-lesson-recording":
            continue
        if public and not asset_id.startswith(public_voice_prefixes):
            continue
        path, _, digest = learning_audio.registered_file(manifest[asset_id], expected)
        add("voice", asset_id, path, digest)
    validate_practice_audio(practice_packs, catalog)
    if public:
        validate_public_materials(web, catalog, manifest)
    data = output / "Data"
    data.mkdir()
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
        "practice-packs": practice_packs,
        "distribution": {"profile": "public" if public else "household"},
        "learning-audio": {
            "narration": {asset_id: f"voice/{asset_id}" in catalog for asset_id in scripts},
            "lessons": lesson_audio,
        },
    }.items():
        (data / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--trial-aac", action="store_true")
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()
    prepare(args.output, args.trial_aac, args.public)
