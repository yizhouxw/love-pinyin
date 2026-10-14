"""Validate faithful daily content and optional real local resource readiness."""

import argparse
import re

from server import daily_reading, learning_audio, reading_timings


def validate(release: bool = False) -> dict:
    data = daily_reading.load()
    scripts = daily_reading.scripts()
    if any(re.search(r"[A-Za-z\u00c0-\u024f]", text) for text in scripts.values()):
        raise ValueError("Daily narration must not synthesize pinyin text")
    sections = [s for d in data["days"] for s in d["sections"]]
    items = [i for s in sections for i in s["items"]]
    if len(items) != 840 or len({s["id"] for s in sections}) != len(sections):
        raise ValueError("Daily source coverage changed without a reviewed content update")
    examples = daily_reading.word_examples()
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
        if missing:
            raise ValueError(f"Daily reading resources not ready: {missing}")
    return {
        "days": len(data["days"]),
        "items": len(items),
        "standardClips": len(data["assets"]),
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
