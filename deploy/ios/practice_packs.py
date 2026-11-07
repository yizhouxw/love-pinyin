"""Project the same UI data contract from original and household content."""

import json
from pathlib import Path

from pypinyin import Style, lazy_pinyin

from server import learning_audio
from server.content import load_curriculum

ROOT = Path(__file__).resolve().parents[2]
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
    return {"daily": daily, "words": words}, daily_aliases, voice


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
