"""Validate faithful daily content and optional real local resource readiness."""

import argparse
import hashlib
import json
import re
import unicodedata

from scripts.daily_reading_rules import MARKS, expected_audio, key, unique_items
from server import daily_pronunciation, daily_reading, learning_audio, reading_timings
from server.audio_assets import _verified_file
from server.content import load_writing


def validate_categories(data: dict, navigation: dict, hanzi: dict) -> None:
    """Check authored categories, never infer words or sentences from syllable length."""
    sections = [section for day in data["days"] for section in day["sections"]]
    labels = {
        "comparison": "辨音对比",
        "spelling": "拼读组合",
        "words": "词语",
        "sentences": "句子",
    }
    if list(navigation) != [section["id"] for section in sections]:
        raise ValueError("Daily navigation sections do not match content")
    annotated = set()
    for section in sections:
        kind = section.get("kind")
        if kind not in {"phonics", *labels}:
            raise ValueError(f"Invalid daily category: {section['id']}")
        groups = navigation[section["id"]]
        if [key for group in groups for key in group["itemIds"]] != [
            item["id"] for item in section["items"]
        ]:
            raise ValueError(f"Daily navigation item order: {section['id']}")
        if kind in labels and any(
            group["family"] != labels[kind] or group["compact"] for group in groups
        ):
            raise ValueError(f"Daily navigation category: {section['id']}")
        if kind in {"words", "sentences"}:
            if labels[kind] not in section["title"]:
                raise ValueError(f"Daily category title: {section['id']}")
            for item in section["items"]:
                annotated.add(item["id"])
                text = hanzi.get(item["id"], "")
                if len(re.findall(r"[\u3400-\u9fff]", text)) != len(item["syllables"]):
                    raise ValueError(f"Daily character coverage: {item['id']}")
                if item["spokenText"] and item["spokenText"] != text:
                    raise ValueError(f"Daily character narration: {item['id']}")
                # Authored classification plus punctuation guard catches the reported mixing.
                for value in [item["display"], text]:
                    terminal = bool(re.search(r"[。！？.!?]$", value))
                    if terminal != (kind == "sentences"):
                        raise ValueError(f"Daily word/sentence category: {item['id']}")
    if set(hanzi) != annotated:
        raise ValueError("Daily character annotations do not match words and sentences")


def validate_normalization(data: dict, ledger: dict, policy: dict, inventory: dict) -> None:
    """Compare against source occurrences, not the old Word's raw item count.

    Source repetitions are intentional input to this rule. Reimporting a changed
    Word/PDF requires a new reviewed ledger, not restoring removed duplicate IDs.
    """
    if ledger["sourceSha256"] != data["source"]["sha256"]:
        raise ValueError("Daily source ledger digest mismatch")
    sections = [s for day in data["days"] for s in day["sections"]]
    if [s["id"] for s in sections] != [s["id"] for s in ledger["sections"]]:
        raise ValueError("Daily source sections mismatch")
    consonants = set(inventory["initials"] + inventory["orthographicLetters"])
    if policy["unmarkedTone"] != 1 or policy["deduplicateWithin"] != "section":
        raise ValueError("Invalid daily tone/deduplication policy")
    neutrals = policy["neutralSyllableIndices"]
    seen_neutrals = set()
    for section, source in zip(sections, ledger["sections"], strict=True):
        expected = unique_items(source["items"])
        if [i["id"] for i in section["items"]] != [i["id"] for i in expected]:
            raise ValueError(f"Daily within-section deduplication: {section['id']}")
        for item, original in zip(section["items"], expected, strict=True):
            if any(
                item[field] != original[field] for field in ("original", "display", "syllables")
            ):
                raise ValueError(f"Daily source text changed: {item['id']}")
            if len({key(i) for i in section["items"]}) != len(section["items"]):
                raise ValueError("Duplicate daily pinyin within section")
            positions = neutrals.get(item["id"], [])
            unmarked = [
                n
                for n, s in enumerate(item["syllables"])
                if s not in consonants
                and not any(m in unicodedata.normalize("NFD", s) for m in MARKS)
            ]
            if section["kind"] in {"words", "sentences"}:
                if positions != unmarked:
                    raise ValueError(f"Daily neutral tone positions: {item['id']}")
            elif positions:
                raise ValueError("Neutral tones only apply to words and sentences")
            if positions:
                seen_neutrals.add(item["id"])
            if any(
                s not in [item["syllables"][n] for n in positions] for s in item["missingSyllables"]
            ):
                raise ValueError("Only neutral tones may use Chinese narration")
            if item["audioIds"] != expected_audio(item, policy, consonants):
                raise ValueError(f"Daily demonstration tone mismatch: {item['id']}")
            derived = any(a in policy["derivedFirstTones"] for a in item["audioIds"])
            if bool(item.get("derivedAudio")) != derived:
                raise ValueError("Daily derived audio attribution missing")
    if seen_neutrals != set(neutrals):
        raise ValueError("Stale neutral tone exceptions")
    if data["derivedAssets"] != list(policy["derivedFirstTones"]):
        raise ValueError("Daily derived asset coverage")
    assets = {a["id"]: a for a in data["assets"]}
    for recipe in policy["derivedFirstTones"].values():
        if assets[recipe["sourceId"]]["sha256"] != recipe["sourceSha256"]:
            raise ValueError("Daily derived source digest")


def validate(release: bool = False) -> dict:
    data = daily_reading.load()
    ledger = json.loads((daily_reading.CONTENT.parent / "daily-reading-source.json").read_text())
    from server.content import load_curriculum

    validate_normalization(
        data, ledger, daily_pronunciation.policy(), load_curriculum()["inventory"]
    )
    pdf = daily_reading.CONTENT.parents[1] / "resources" / data["source"]["filename"]
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != ledger["sourceSha256"]:
        raise ValueError("Daily source changed; review the new Word/PDF and rebuild its ledger")
    validate_categories(
        data,
        json.loads((daily_reading.CONTENT.parent / "daily-reading-navigation.json").read_text()),
        json.loads((daily_reading.CONTENT.parent / "daily-reading-hanzi.json").read_text()),
    )
    scripts = daily_reading.scripts()
    if any(re.search(r"[A-Za-z\u00c0-\u024f]", text) for text in scripts.values()):
        raise ValueError("Daily narration must not synthesize pinyin text")
    sections = [s for d in data["days"] for s in d["sections"]]
    items = [i for s in sections for i in s["items"]]
    if len({s["id"] for s in sections}) != len(sections):
        raise ValueError("Daily source coverage changed without a reviewed content update")
    examples = daily_reading.word_examples()
    sentences = daily_reading.sentence_readings()
    sentence_items = [i for s in sections if s["kind"] == "sentences" for i in s["items"]]
    if set(sentences) != {i["id"] for i in sentence_items}:
        raise ValueError("Sentence recording coverage mismatch")
    hanzi = json.loads((daily_reading.CONTENT.parent / "daily-reading-hanzi.json").read_text())
    if any(sentences[i["id"]]["spokenText"] != hanzi[i["id"]] for i in sentence_items):
        raise ValueError("Sentence text mismatch")
    for section in sections:
        if "组词" in section["title"]:
            for item in section["items"]:
                if item["display"] not in examples:
                    raise ValueError(f"Missing word examples: {item['id']}")
    for item in items:
        if item["missingSyllables"] and not item["narrationId"]:
            raise ValueError(f"No usable demonstration for {item['id']}")
        if item["narrationId"] and not item["spokenText"]:
            raise ValueError(f"Missing Chinese word script for {item['id']}")
    if release:
        from scripts.asr_model import validate_model
        from server.reading_recognition import MODEL_PATH

        validate_model(MODEL_PATH)
        status = daily_reading.status()
        timelines = reading_timings.read()
        manifest = learning_audio.read_manifest()
        for item in items:
            if item["narrationId"]:
                reading_timings.checked(
                    item, manifest[item["narrationId"]], timelines[item["narrationId"]]
                )
        missing = [
            i["id"]
            for d in status["days"]
            for s in d["sections"]
            for i in s["items"]
            if not i["available"]
        ]
        available = learning_audio.available_assets()
        missing += [key for key in scripts if not available.get(key)]
        for item in sentence_items:
            sentence = sentences[item["id"]]
            checked = reading_timings.checked(
                {**item, "spokenText": sentence["spokenText"]},
                manifest[sentence["narrationId"]],
                timelines.get(sentence["narrationId"], {}),
            )
            if any(a["start"] >= b["start"] for a, b in zip(checked, checked[1:], strict=False)):
                raise ValueError(f"Sentence character boundaries overlap: {item['id']}")
        # Writing also uses a few pinned clips that do not occur in the PDF items.
        writing = load_writing()
        targets = [t for group in writing["lessons"].values() for t in group]
        for entry in [*writing["glyphs"].values(), *targets]:
            clip = entry["pronunciation"]
            if clip["kind"] == "daily-audio":
                path, digest = daily_reading.registered(clip["id"])
                handle, _ = _verified_file(path, digest)
                handle.close()
        if missing:
            raise ValueError(f"Daily reading resources not ready: {missing}")
    return {
        "days": len(data["days"]),
        "items": len(items),
        "standardClips": len(data["assets"]),
        "derivedFirstTones": len(data["derivedAssets"]),
        "release": release,
        "automaticRecognition": True,
        "professionalAssessment": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    print(validate(parser.parse_args().release))


if __name__ == "__main__":
    main()
