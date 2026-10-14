"""Portable playback rhythm, represented exactly as integer tenths in storage."""

import json
import math
from pathlib import Path

GAP = json.loads((Path(__file__).resolve().parents[1] / "content/playback.json").read_text())["gap"]
DEFAULT_TENTHS = round(GAP["defaultSeconds"] * 10)


def gap_tenths(value: object) -> int:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid playback interval")
    tenths = round(value * 10)
    if not GAP["minSeconds"] <= value <= GAP["maxSeconds"] or abs(value * 10 - tenths) > 1e-8:
        raise ValueError("Playback interval must be 0.1–5 seconds in tenths")
    return tenths
