"""Collect full MATCH-16 calibration, stress and CPU evidence with digest checks."""

import argparse
import json
from pathlib import Path

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import write

NAMES = (
    "sensevoice-factorized-v1",
    "tencent-zh-base-multihead-v1",
    "tencent-zh-base-factorized-v1",
    "chinese-xlsr-asr-factorized-v1",
    "tencent-zh-raw-factorized-v1",
    "tencent-zh-tail-v1-joint",
    "tencent-zh-tail-v1-retrained",
    "chinese-xlsr-tail-v1-joint",
)
MANIFEST = "2e1259602b83a2d1445f8a58dfba28c21d2e83213993fc6cdb3b4fbc38ceff01"
STRESS = {
    "sensevoice-factorized-v1": "stress-match13-v2",
    "tencent-zh-base-multihead-v1": "stress-match16-tencent",
    "tencent-zh-base-factorized-v1": "stress-match16-tencent",
    "chinese-xlsr-asr-factorized-v1": "stress-match16-xlsr",
    "tencent-zh-raw-factorized-v1": "stress-match16-raw-tail",
    "tencent-zh-tail-v1-joint": "stress-match16-joint",
    "tencent-zh-tail-v1-retrained": "stress-match16-raw-tail",
    "chinese-xlsr-tail-v1-joint": "stress-match16-xlsr-tail",
}
TRAINING = {
    "sensevoice-factorized-v1": "sensevoice-factorized-v1",
    "tencent-zh-base-multihead-v1": "tencent-zh-base-multihead-v1",
    "tencent-zh-base-factorized-v1": "tencent-zh-base-factorized-v1",
    "chinese-xlsr-asr-factorized-v1": "chinese-xlsr-asr-factorized-v1",
    "tencent-zh-raw-factorized-v1": "tencent-zh-raw-factorized-v1",
    "tencent-zh-tail-v1-retrained": "tencent-zh-tail-v1-retrained-heads",
}


def collect(root: Path, bundles: Path, output: Path):
    if output.exists():
        raise ValueError("CHINESE_REPORT_OUTPUT_EXISTS")
    result = {
        "schemaVersion": 1,
        "phase": "calibration-diagnostic",
        "finalTestUsed": False,
        "models": {},
    }
    reference = json.loads((root / "stress-match13-v2/manifest.json").read_text())
    fields = ("id", "sha256", "targetIds", "expectedBehavior")
    expected_cases = [
        tuple(json.dumps(row[key], sort_keys=True) for key in fields) for row in reference["cases"]
    ]
    for name in NAMES:
        model_file = bundles / name / "model.json"
        model_sha = fingerprint(model_file)
        metrics_file = root / (name + "-full-calibration.json")
        full = json.loads(metrics_file.read_text())
        stress = json.loads((root / (name + "-stress.json")).read_text())
        cpu = json.loads((root / (name + "-cpu.json")).read_text())
        cold = json.loads((root / (name + "-cold.json")).read_text())
        if (
            full["manifestSha256"] != MANIFEST
            or full["modelSha256"] != model_sha
            or full["rows"] != 4202
            or full["metrics"]["positive"]["n"] != 2239
            or stress["metadataSha256"] != model_sha
            or cpu["modelSha256"] != model_sha
            or cold["modelSha256"] != model_sha
            or stress["plannedCases"] != 312
            or stress["phase"] != "calibration-diagnostic"
            or cpu["threads"] != 2
            or cold["threads"] != 2
        ):
            raise ValueError("CHINESE_REPORT_INPUT_MISMATCH: " + name)
        stress_manifest = root / STRESS[name] / "manifest.json"
        cases = json.loads(stress_manifest.read_text())["cases"]
        actual_cases = [
            tuple(json.dumps(row[key], sort_keys=True) for key in fields) for row in cases
        ]
        if (
            fingerprint(stress_manifest) != stress["manifestSha256"]
            or actual_cases != expected_cases
        ):
            raise ValueError("CHINESE_REPORT_STRESS_MISMATCH: " + name)
        meta = json.loads(model_file.read_text())
        for field in ("predictions", "modelInfo", "package"):
            stress.pop(field, None)
        cold.pop("command", None)
        result["models"][name] = {
            "modelSha256": model_sha,
            "fullCalibrationSha256": fingerprint(metrics_file),
            "metrics": full["metrics"],
            "stress": stress,
            "cpu": cpu,
            "cold": cold,
            "selectedEpoch": meta.get("selectedEpoch"),
            "checkpointSelection": meta.get("checkpointSelection"),
            "acousticSource": meta.get("acousticSource"),
            "packageFiles": meta.get("packageFiles"),
            "thresholds": meta.get("thresholds"),
        }
        if name in TRAINING:
            training = root / TRAINING[name] / "training.json"
            result["models"][name]["trainingHistory"] = json.loads(training.read_text())
            result["models"][name]["trainingHistorySha256"] = fingerprint(training)
        retest = root / (name + "-cpu-quiet-retest.json")
        if retest.exists():
            quiet = json.loads(retest.read_text())
            if quiet["modelSha256"] != model_sha or quiet["threads"] != 2:
                raise ValueError("CHINESE_REPORT_CPU_RETEST_MISMATCH: " + name)
            result["models"][name]["cpuQuietRetest"] = quiet
    tail = root / "tencent-zh-tail-v1/training.json"
    result["tailTraining"] = json.loads(tail.read_text())
    result["tailTrainingSha256"] = fingerprint(tail)
    xlsr_tail = root / "chinese-xlsr-tail-v1/training.json"
    result["xlsrTailTraining"] = json.loads(xlsr_tail.read_text())
    result["xlsrTailTrainingSha256"] = fingerprint(xlsr_tail)
    write(output, result)
    return {"models": len(result["models"]), "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(**vars(args))))


if __name__ == "__main__":
    main()
