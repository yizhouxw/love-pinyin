"""Prepare licensed PinYinSound tone anchors, excluding pilot reference recordings."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pinyin_matcher.audio import decode_wav, features
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog, targets_by_id
from pinyin_matcher.contour import contour
from pinyin_matcher.generate import atomic_json


def prepare(output: Path):
    targets = targets_by_id()
    pilot_targets = [targets[key] for key in load_catalog()["pilotIds"]]
    excluded = {target["standardAudioId"] for target in pilot_targets if target["standardAudioId"]}
    excluded_groups = {tuple(target["phones"]) for target in pilot_targets}
    assets = {
        asset["id"]: asset
        for asset in json.loads((ROOT / "content/daily-reading.json").read_text())["assets"]
    }
    output.mkdir(parents=True, exist_ok=True)
    rows, quarantined, seen = [], [], set()
    for target in targets.values():
        key = target["standardAudioId"]
        if (
            target["tone"] not in (1, 2, 3, 4)
            or not key
            or key in excluded
            or key in seen
            or tuple(target["phones"]) in excluded_groups
        ):
            continue
        seen.add(key)
        asset = assets[key]
        source = ROOT / "private/pinyinsound/clips" / (asset["sha256"] + ".mp3")
        if fingerprint(source) != asset["sha256"]:
            raise ValueError("STANDARD_AUDIO_DIGEST_MISMATCH")
        destination = output / (key + ".wav")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            check=True,
        )
        try:
            array, _ = features(decode_wav(destination.read_bytes()))
            contour(array)
        except ValueError as error:
            quarantined.append({"id": key, "reason": str(error)})
            continue
        group = "-".join(target["phones"])
        split = (
            "calibration"
            if int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 5 == 0
            else "train"
        )
        rows.append(
            {
                "id": key,
                "targetId": target["id"],
                "tone": target["tone"],
                "phoneticGroup": group,
                "split": split,
                "file": destination.name,
                "sha256": fingerprint(destination),
                "sourceSha256": asset["sha256"],
            }
        )
    report = {
        "version": 1,
        "cohort": "licensed-PinYinSound-standard-anchors-not-child",
        "splitUnit": "phonetic-group-not-independent-speaker",
        "pilotReferencesExcluded": sorted(excluded),
        "pilotPhoneticGroupsExcluded": [list(group) for group in sorted(excluded_groups)],
        "source": "https://github.com/cmguo/PinYinSound",
        "items": rows,
        "quarantined": quarantined,
    }
    atomic_json(output / "manifest.json", report)
    print(
        {
            "included": len(rows),
            "quarantined": len(quarantined),
            "train": sum(r["split"] == "train" for r in rows),
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args().output)
