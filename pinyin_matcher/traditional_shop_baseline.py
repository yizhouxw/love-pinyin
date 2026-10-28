"""Run the preserved non-Transformer baseline on identical diagnostic roots."""

import argparse
import json
from collections import Counter
from pathlib import Path

from threadpoolctl import threadpool_limits

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.data import read_manifest
from pinyin_matcher.inference import PinyinMatcher
from pinyin_matcher.pretrained_experiment import read_rows
from pinyin_matcher.traditional_shop import load, nearest


def evaluate(package, baseline, tts_manifest, real_manifest, output):
    if output.exists():
        raise ValueError("TRADITIONAL_BASELINE_OUTPUT_EXISTS")
    data, _ = load(package)
    matcher = PinyinMatcher(baseline, threads=2)
    if matcher.session is None:
        raise ValueError("TRADITIONAL_BASELINE_UNAVAILABLE: " + matcher.problem)
    ids = [t["id"] for t in data["targets"]]
    if set(ids) != set(matcher.metadata["coveredTargetIds"]):
        raise ValueError("TRADITIONAL_BASELINE_TARGET_COVERAGE_CHANGED")
    alternatives = nearest(data["targets"])
    synthetic = read_manifest(tts_manifest)
    real = read_rows(real_manifest, verify_splits=("calibration",))
    groups = {
        "tts-calibration-weak-intended": [r for r in synthetic if r["split"] == "calibration"],
        "tts-previous-test-diagnostic-weak-intended": [
            r for r in synthetic if r["split"] == "test"
        ],
        "ompal-expert-calibration-diagnostic": [
            r
            for r in real
            if r["split"] == "calibration"
            and r.get("expertLabel") in {"unanimous-correct", "unanimous-error"}
            and "pm-" + r["syllable"] in ids
        ],
    }
    results = {}
    for name, rows in groups.items():
        counts, families = Counter(), set()
        for position, row in enumerate(rows):
            is_real = name.startswith("ompal")
            target = "pm-" + row["syllable"] if is_real else row["targetId"]
            index = ids.index(target)
            families.add(row.get("speakerId", row.get("voiceFamilyId")))
            flagged = bool(row.get("labelPolicyFlags") or row.get("numericalQualityFlags"))
            path = Path(row["file"]) if is_real else tts_manifest.parent / row["file"]
            audio = path.read_bytes()
            result = {"status": "uncertain"} if flagged else matcher.match(target, audio)
            status = (
                result["status"]
                if result["status"] in {"matched", "retry", "uncertain"}
                else "uncertain"
            )
            correct = not is_real or row["expertLabel"] == "unanimous-correct"
            if correct:
                counts["correctRoots"] += 1
                counts["correct_" + status] += 1
                if alternatives[index]:
                    counts["nearRoots"] += 1
                    any_false = False
                    if not flagged:
                        for alt in alternatives[index]:
                            if matcher.match(ids[alt], audio)["status"] == "matched":
                                any_false = True
                    counts["nearFalseAcceptRoots"] += int(any_false)
                else:
                    counts["noNearNeighborInPilot"] += 1
            else:
                counts["expertErrorRoots"] += 1
                counts["expertError_" + status] += 1
            counts["predeclaredUnassessableRoots"] += int(flagged)
            if (position + 1) % 100 == 0:
                print(
                    json.dumps({"group": name, "evaluated": position + 1, "total": len(rows)}),
                    flush=True,
                )
        results[name] = {
            "roots": len(rows),
            "speakerOrVoiceFamilyIds": len(families),
            "methods": {"preserved-baseline": dict(counts)},
        }
    report = {
        "schemaVersion": 1,
        "phase": "diagnostic-not-final-acceptance",
        "baselineModelSha256": fingerprint(baseline / "model.json"),
        "ttsManifestSha256": fingerprint(tts_manifest),
        "realManifestSha256": fingerprint(real_manifest),
        "threads": 2,
        "finalTestUsed": False,
        "groups": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "baseline", "tts-manifest", "real-manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    with threadpool_limits(limits=2):
        print(json.dumps(evaluate(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == "__main__":
    main()
