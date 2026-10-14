"""Hash-bound, offline-produced alignment of known teaching audio, not child speech."""

import json
import math
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "content/daily-reading-timings.json"


def read() -> dict:
    data = json.loads(PATH.read_text())
    if data.get("version") != 1:
        raise ValueError("Unsupported reading timeline")
    return data["items"]


def checked(item: dict, asset: dict, timing: dict) -> list[dict]:
    from server.learning_audio import text_digest

    values = timing.get("timings", [])
    if (
        timing.get("sha256") != asset.get("sha256")
        or timing.get("textSha256") != text_digest(item["spokenText"])
        or len(values) != len(item["syllables"])
    ):
        raise ValueError("Reading timeline does not match speech")
    previous = -1
    for value in values:
        start, end = value.get("start"), value.get("end")
        if (
            type(start) not in (int, float)
            or type(end) not in (int, float)
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous
            or start < 0
            or end <= start
            or end > asset["durationSeconds"] + 0.002
        ):
            raise ValueError("Invalid reading timeline")
        previous = start
    return values
