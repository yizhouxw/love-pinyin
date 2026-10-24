"""Align bundled Chinese demonstrations locally; never process children's recordings."""

import hashlib
import json
import os
import re
import wave
from pathlib import Path

from scripts.fetch_tts_model import verify_files
from server import daily_reading, learning_audio, reading_timings

ROOT = Path(__file__).resolve().parents[1]


def build():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from mlx_audio.stt.utils import load_model

    config = json.loads((ROOT / "content/reading-alignment-build.json").read_text())
    path = ROOT / "models/qwen3-aligner" / config["directory"]
    verify_files(path, config)
    model = load_model(path, strict=True)
    manifest = learning_audio.read_manifest()
    output = {}
    existing = reading_timings.read()
    items = [
        item
        for day in daily_reading.load()["days"]
        for section in day["sections"]
        for item in section["items"]
    ]
    items += [
        {**item, **daily_reading.sentence_readings()[item["id"]]}
        for item in items
        if item["id"] in daily_reading.sentence_readings()
    ]
    for item in items:
        if not item["narrationId"]:
            continue
        id = item["narrationId"]
        asset = manifest[id]
        if id in output:
            continue
        audio = ROOT / "resources/audio" / asset["file"]
        digest = hashlib.sha256(audio.read_bytes()).hexdigest()
        if digest != asset["sha256"]:
            raise ValueError(f"Voice digest mismatch: {id}")
        try:
            reading_timings.checked(item, asset, existing.get(id, {}))
            output[id] = existing[id]
            continue
        except ValueError:
            pass
        result = model.generate(audio=str(audio), text=item["spokenText"], language="Chinese")
        characters = "".join(re.findall(r"[\u3400-\u9fff]", item["spokenText"]))
        if "".join(word.text for word in result.items) != characters or len(result.items) != len(
            item["syllables"]
        ):
            raise ValueError(f"Cannot map Chinese alignment to syllables: {id}")
        with wave.open(str(audio)) as pcm:
            duration = pcm.getnframes() / pcm.getframerate()
        timings = []
        for word in result.items:
            start = min(word.start_time, duration)
            end = min(word.end_time, duration)
            # The aligner has 80ms resolution. Give collapsed short sounds
            # a 40ms highlight window anchored to their predicted onset.
            if end == start:
                end = min(start + 0.04, duration)
            if start < 0 or end < start or (timings and start < timings[-1]["start"]):
                raise ValueError(f"Invalid alignment times: {id}")
            timings.append({"start": round(start, 3), "end": round(end, 3)})
        output[id] = {
            "sha256": digest,
            "textSha256": learning_audio.text_digest(item["spokenText"]),
            "timings": timings,
        }
        print(f"Aligned {len(output)}: {id}", flush=True)
    target = ROOT / "content/daily-reading-timings.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "modelRevision": config["revision"],
                "resolutionSeconds": 0.08,
                "items": output,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    os.replace(temporary, target)
    return len(output)


if __name__ == "__main__":
    print(build())
