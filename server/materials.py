"""Project the same UI data contract from original and household content."""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from pypinyin import Style, lazy_pinyin

from server import learning_audio
from server.content import load_curriculum

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "content/ios-original-practice.json"
GENERATED = ROOT / "resources/audio/ios-practice"
WORD_SOURCE = ROOT / "content/word-practice/lessons.json"


def original_packs(standard_ids: set[str]) -> tuple[dict, dict, dict[str, str]]:
    data = json.loads(ORIGINAL.read_text())
    curriculum = load_curriculum()
    voice = {}

    def speak(text: str) -> str:
        asset_id = "original-" + learning_audio.text_digest(text)[:24]
        voice[asset_id] = text
        return asset_id

    def word(text: str) -> dict:
        return {
            "text": text,
            "pinyin": " ".join(lazy_pinyin(text, style=Style.TONE)),
            "audioId": speak(text),
        }

    # The teaching target and its availability come from the actual installed audio bank.
    by_text = {}
    for item in curriculum["audioRequirements"]:
        if item["id"] in standard_ids:
            by_text.setdefault(item["transcript"], item["id"])
    days = []
    daily_aliases = {}
    instruction_id = speak(data["dailyInstruction"])
    for lesson, groups in zip(curriculum["lessons"], data["daily"], strict=True):
        number = lesson["order"]
        day_id = f"day-{number:02}"
        sections = []
        for index, group in enumerate(groups, 1):
            section_id = f"original-{day_id}-{index}"
            items = []
            for position, text in enumerate(group, 1):
                syllables = text.split()
                audio_ids = []
                for syllable in syllables:
                    audio_id = by_text.get(syllable)
                    if audio_id is None:
                        raise ValueError(f"No standard audio for original practice: {syllable}")
                    daily_aliases[audio_id] = audio_id
                    audio_ids.append(audio_id)
                items.append(
                    {
                        "id": f"{section_id}-{position}",
                        "display": text,
                        "original": text,
                        "syllables": syllables,
                        "audioIds": audio_ids,
                        "audioNotes": [],
                        "missingSyllables": [],
                        "narrationId": None,
                        "spokenText": None,
                        "available": True,
                    }
                )
            sections.append(
                {
                    "id": section_id,
                    "kind": "phonics",
                    "title": ("听音跟读", "对比与拼读", "两音连读")[index - 1],
                    "instruction": data["dailyInstruction"],
                    "instructionId": instruction_id,
                    "items": items,
                }
            )
        days.append(
            {
                "id": day_id,
                "number": number,
                "title": lesson["title"],
                "sourcePage": 0,
                "sections": sections,
            }
        )

    daily = {
        "version": 1,
        "ui": json.loads((ROOT / "content/daily-reading.json").read_text())["ui"],
        "source": {
            "filename": "爱拼音自编材料",
            "sha256": learning_audio.text_digest(ORIGINAL.read_text()),
            "pages": 0,
            "practiceCount": len(days),
        },
        "days": days,
        "assessment": {"available": False, "mode": "asr-syllable-match", "toneAssessed": False},
    }
    original_words = []
    word_ui = json.loads(WORD_SOURCE.read_text())
    for index, row in enumerate(data["words"], 1):
        original_words.append(
            {
                "id": f"original-word-{index:02}",
                "title": row["title"],
                "page": 0,
                "audioId": speak(row["title"]),
                "unit": row["unit"],
                "unitTitle": "爱拼音自编练习",
                "read": [word(text) for text in row["read"]],
                "write": [word(text) for text in row["write"]],
                "characters": row["write"],
                "characterItems": [word(text) for text in row["write"]],
                "passages": [
                    {
                        "title": row["title"],
                        "page": 0,
                        "required": False,
                        "readingOnly": False,
                        "paragraphs": [{"text": row["passage"], "audioId": speak(row["passage"])}],
                    }
                ],
            }
        )
    if len(original_words) != 38:
        raise ValueError("Expected 38 independently written word lessons")
    words = {
        "version": 1,
        "source": {
            "file": "爱拼音自编材料",
            "edition": "爱拼音",
            "textbook": "",
            "sha256": daily["source"]["sha256"],
        },
        "lessons": original_words,
        "ui": word_ui["ui"],
        "pinyinNote": word_ui["pinyinNote"],
    }
    return (
        {
            "daily": daily,
            "words": words,
            "audioPrefix": ORIGINAL_PREFIX,
            "lessons": original_lessons(),
        },
        daily_aliases,
        voice,
    )


def reusable_voice() -> dict[str, tuple[Path, str]]:
    """Reuse only identical input text from the locked open TTS inventory."""
    manifest = learning_audio.read_manifest()
    result = {}
    for asset_id, expected in learning_audio.expected_assets().items():
        asset = manifest.get(asset_id, {})
        if (
            expected["sourceType"] != "local-open-tts"
            or asset.get("sourceType") != "local-open-tts"
        ):
            continue
        if expected["textSha256"] not in result:
            path, _, digest = learning_audio.registered_file(asset, expected)
            result[expected["textSha256"]] = (path, digest)
    return result


def original_voice(scripts: dict[str, str]):
    generated = json.loads((GENERATED / "manifest.json").read_text())
    reuse = reusable_voice()
    for asset_id, text in scripts.items():
        text_sha = learning_audio.text_digest(text)
        if text_sha in reuse:
            yield asset_id, *reuse[text_sha]
        else:
            asset = generated[asset_id]
            if asset["textSha256"] != text_sha:
                raise ValueError(f"Stale original practice audio: {asset_id}")
            yield asset_id, GENERATED / f"{asset_id}.wav", asset["sha256"]


COURSE_AUDIO = ROOT / "resources/audio/ios-lessons"
STANDARD_AUDIO = ROOT / "resources/audio/ios-standard"
ORIGINAL_PREFIX = "original-"


@lru_cache(maxsize=1)
def standard_manifest() -> dict:
    return json.loads((STANDARD_AUDIO / "manifest.json").read_text())


@lru_cache(maxsize=1)
def original_content() -> tuple[dict, dict, dict[str, str]]:
    return original_packs(set(standard_manifest()["clips"]))


@lru_cache(maxsize=1)
def original_courses() -> dict:
    manifest = json.loads((COURSE_AUDIO / "manifest.json").read_text())["lessons"]
    scripts = json.loads((ROOT / "content/ios-lesson-narration.json").read_text())["lessons"]
    courses = {}
    for lesson in load_curriculum()["lessons"]:
        lesson_id = lesson["id"]
        asset = manifest[lesson_id]
        filename = f"{lesson_id}.mp3"
        if asset["file"] != filename or asset["textSha256"] != learning_audio.text_digest(
            "\n".join(scripts[lesson_id])
        ):
            raise ValueError(f"Stale course recording: {lesson_id}")
        courses[lesson_id] = (
            {
                "audioId": f"lesson-original-{lesson_id}",
                "title": f"{lesson['title']} · 爱拼音原创课程",
                "available": True,
                "sourceType": "local-open-tts",
            },
            COURSE_AUDIO / filename,
            asset["sha256"],
        )
    return courses


def original_lessons() -> dict:
    return {key: row[0] for key, row in original_courses().items()}


def household_content(*, offline: bool = False) -> dict:
    from server import daily_reading

    daily = daily_reading.status()
    if offline:
        daily["assessment"]["available"] = False
    hanzi = json.loads((ROOT / "content/daily-reading-hanzi.json").read_text())
    for day in daily["days"]:
        for section in day["sections"]:
            for item in section["items"]:
                if item["id"] in hanzi:
                    item["hanzi"] = hanzi[item["id"]]
    return {
        "daily": daily,
        "words": json.loads(WORD_SOURCE.read_text()),
        "audioPrefix": "",
        "lessons": learning_audio.learning_audio_status()["lessons"],
    }


def payload(selected: str) -> dict:
    from server import source_audio

    original, _, _ = original_content()
    result = {
        "selected": selected,
        "original": original,
        "standardSources": list(standard_manifest()["sources"].values()),
    }
    if source_audio.installed():
        result["household"] = household_content()
    return result


@lru_cache(maxsize=1)
def original_voice_assets() -> dict:
    _, _, scripts = original_content()
    return {
        **{key: (path, digest) for key, path, digest in original_voice(scripts)},
        **{row[0]["audioId"]: (row[1], row[2]) for row in original_courses().values()},
    }


def audio_response(kind: str, asset_id: str, byte_range: str | None):
    """Return None when the ID belongs to the existing household bank."""
    from server.audio_assets import file_audio_response

    if kind == "audio" and asset_id.startswith(ORIGINAL_PREFIX):
        key = asset_id.removeprefix(ORIGINAL_PREFIX)
    elif kind == "daily-audio" and asset_id in original_content()[1]:
        key = original_content()[1][asset_id]
    elif kind == "voice" and asset_id.startswith((ORIGINAL_PREFIX, "lesson-original-")):
        entry = original_voice_assets().get(asset_id)
        if not entry:
            raise HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})
        path, digest = entry
        return file_audio_response(path, media_type(path), digest, byte_range)
    else:
        return None
    clip = standard_manifest()["clips"].get(key)
    if not clip:
        raise HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})
    path = STANDARD_AUDIO / clip["file"]
    return file_audio_response(path, media_type(path), clip["sha256"], byte_range)


def media_type(path: Path) -> str:
    return "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
