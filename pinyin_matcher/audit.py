"""Quarantine low-quality synthetic roots before freezing training data."""

import argparse
import json
import re
from pathlib import Path

from pinyin_matcher.audio import AudioRejected, decode_wav, features
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.data import read_manifest
from pinyin_matcher.generate import atomic_json


def audit(path: Path) -> dict:
    data = json.loads(path.read_text())
    rows = read_manifest(path)
    included, quarantined = [], []
    for row in rows:
        try:
            samples = decode_wav((path.parent / row["file"]).read_bytes())
            _, info = features(samples)
            if info["durationSeconds"] > 2:
                raise AudioRejected("ISOLATED_TARGET_TOO_LONG")
            if info["voicedFrames"] < 8:
                raise AudioRejected("NO_RELIABLE_VOICED_SPEECH")
            if re.fullmatch(r"voice-[0-9]{2}", row["voiceFamilyId"]):
                locations = [path.parent / "references", path.parent.parent / "references"]
                reference = next(
                    (
                        base / (row["voiceFamilyId"] + ".wav")
                        for base in locations
                        if (base / (row["voiceFamilyId"] + ".wav")).is_file()
                    ),
                    None,
                )
                if reference is None:
                    raise ValueError("REFERENCE_AUDIO_MISSING")
                row["referenceSha256"] = fingerprint(reference)
            included.append(row)
        except AudioRejected as error:
            quarantined.append({**row, "quarantineReason": str(error)})
    data["items"] = included
    data.setdefault("quarantined", []).extend(quarantined)
    atomic_json(path, data)
    summary = {
        "included": len(included),
        "quarantined": len(quarantined),
        "labelProvenance": data.get("labelProvenance", "tts-intended"),
        "checks": "duration,integrity,energy,clipping,voicing; no human-accuracy assertion",
    }
    atomic_json(path.with_name("quality-audit.json"), summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(audit(args.manifest))
