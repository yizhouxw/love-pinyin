"""Diagnostic TTS and expert-root evaluation for traditional shop matchers."""

import argparse
import json
from collections import Counter
from pathlib import Path

from threadpoolctl import threadpool_limits

from pinyin_matcher.audio import AudioRejected, decode_wav, features
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.data import read_manifest
from pinyin_matcher.pretrained_experiment import read_rows
from pinyin_matcher.pretrained_runtime import signal_guard
from pinyin_matcher.traditional_shop import comparison, config, encode, load, nearest, score_model


def evaluate(package: Path, tts_manifest: Path, real_manifest: Path, output: Path):
    if output.exists():
        raise ValueError("TRADITIONAL_EVALUATION_EXISTS")
    model, bank = load(package)
    targets = model["targets"]
    ids = [x["id"] for x in targets]
    rivals = nearest(targets)
    families = [r["voiceFamilyId"] for r in model["templateProvenance"]]
    tts = [r for r in read_manifest(tts_manifest) if r["split"] in {"calibration", "test"}]
    real = [
        r
        for r in read_rows(real_manifest, verify_splits=("calibration",))
        if r["split"] == "calibration"
        and r.get("expertLabel") in {"unanimous-correct", "unanimous-error"}
        and "pm-" + r["syllable"] in ids
    ]
    groups = {
        "tts-calibration-weak-intended": tts,
        "tts-previous-test-diagnostic-weak-intended": [r for r in tts if r["split"] == "test"],
        "ompal-expert-calibration-diagnostic": real,
    }
    groups["tts-calibration-weak-intended"] = [r for r in tts if r["split"] == "calibration"]
    results = {}
    for name, rows in groups.items():
        counters = {key: Counter() for key in model["models"]}
        known_speakers = set()
        for number, row in enumerate(rows):
            is_real = name.startswith("ompal")
            expected = "pm-" + row["syllable"] if is_real else row["targetId"]
            index = ids.index(expected)
            known_speakers.add(row.get("speakerId", row.get("voiceFamilyId")))
            positive = not is_real or row["expertLabel"] == "unanimous-correct"
            invalid = bool(row.get("labelPolicyFlags") or row.get("numericalQualityFlags"))
            try:
                path = Path(row["file"]) if is_real else tts_manifest.parent / row["file"]
                wave = decode_wav(path.read_bytes())
                invalid = invalid or bool(signal_guard(wave))
                if not invalid:
                    encoded = encode(features(wave)[0])
                    pairs = comparison(encoded, bank, families, rivals)
            except (AudioRejected, ValueError):
                invalid = True
            for method, counter in counters.items():
                threshold = model["thresholds"][method]
                scores = None if invalid else score_model(method, pairs, model["models"][method])

                def classify(value, threshold=threshold):
                    if value is None:
                        return "uncertain"
                    return (
                        "matched"
                        if value >= threshold
                        else "retry"
                        if value <= config()["rejectThreshold"]
                        else "uncertain"
                    )

                status = classify(None if scores is None else scores[index])
                if positive:
                    counter["correctRoots"] += 1
                    counter["correct_" + status] += 1
                    if rivals[index]:
                        counter["nearRoots"] += 1
                        counter["nearFalseAcceptRoots"] += int(
                            scores is not None
                            and any(scores[j] >= threshold for j in rivals[index])
                        )
                    else:
                        counter["noNearNeighborInPilot"] += 1
                else:
                    counter["expertErrorRoots"] += 1
                    counter["expertError_" + status] += 1
                counter["unassessableRoots"] += int(invalid)
            if (number + 1) % 100 == 0:
                print(
                    json.dumps({"group": name, "evaluated": number + 1, "total": len(rows)}),
                    flush=True,
                )
        results[name] = {
            "roots": len(rows),
            "speakerOrVoiceFamilyIds": len(known_speakers),
            "methods": {key: dict(value) for key, value in counters.items()},
        }
    result = {
        "schemaVersion": 1,
        "phase": "diagnostic-not-final-acceptance",
        "ttsLabelLimit": "Generated text is intended, "
        "not independently verified actual pronunciation.",
        "realLabelLimit": "Expert labels apply to source words; "
        "automatic clip boundaries lack individual human review.",
        "ttsManifestSha256": fingerprint(tts_manifest),
        "realManifestSha256": fingerprint(real_manifest),
        "modelSha256": fingerprint(package / "model.json"),
        "threads": 2,
        "finalTestUsed": False,
        "groups": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "tts-manifest", "real-manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    with threadpool_limits(limits=2):
        print(json.dumps(evaluate(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == "__main__":
    main()
