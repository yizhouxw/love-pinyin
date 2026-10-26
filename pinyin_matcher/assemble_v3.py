"""Explicitly assemble a private V3 calibration candidate; never downloads weights."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.inference import PinyinMatcher
from pinyin_matcher.package import bundle_path
from pinyin_matcher.pitch_swift import MODEL_SHA256, PITCH_FEATURE_VERSION


def _populate(acoustic: Path, pitch: Path, tracker: Path, output: Path, *, precision="int8"):
    if output.exists():
        raise ValueError("CANDIDATE_ALREADY_EXISTS")
    if fingerprint(tracker / "model.onnx") != MODEL_SHA256:
        raise ValueError("PITCH_TRACKER_MODEL_DIGEST_MISMATCH")
    metadata_file = "model.fp32.json" if precision == "fp32" else "model.json"
    metadata = json.loads((acoustic / metadata_file).read_text())
    inputs = acoustic / "run-inputs.json"
    if inputs.is_file():
        if inputs.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("TRAINING_PROVENANCE_INVALID")
        metadata["dataProvenance"] = json.loads(inputs.read_text())
    source_files = {
        name: bundle_path(acoustic, name) for name in [metadata["file"], metadata["catalogFile"]]
    }
    if fingerprint(source_files[metadata["file"]]) != metadata["sha256"]:
        raise ValueError("ACOUSTIC_MODEL_DIGEST_MISMATCH")
    output.mkdir(parents=True)
    for name in [metadata["file"], metadata["catalogFile"]]:
        shutil.copyfile(source_files[name], bundle_path(output, name))
    shutil.copyfile(pitch, output / "pitch.onnx")
    shutil.copyfile(tracker / "model.onnx", output / "swift-f0.onnx")
    shutil.copyfile(tracker / "LICENSE", output / "SWIFT-F0-LICENSE")
    metadata.update(
        version="masked-phonetic-swift-v3-" + metadata["sha256"][:12],
        decisionVersion=3,
        calibrationPassed=False,
        qualityPassed=False,
        thresholds={
            "minimumContentMargin": 0.5,
            "maximumFreeCtcAdvantage": 0.05,
            "minimumToneProbability": 0.5,
        },
        pitchTone={
            "file": "pitch.onnx",
            "sha256": fingerprint(output / "pitch.onnx"),
            "featureVersion": PITCH_FEATURE_VERSION,
            "parameters": 10468,
            "inputShape": [32, 4],
            "tracker": {
                "file": "swift-f0.onnx",
                "sha256": MODEL_SHA256,
                "version": "swift-f0-0.3.0",
                "licenseFile": "SWIFT-F0-LICENSE",
                "licenseSha256": fingerprint(output / "SWIFT-F0-LICENSE"),
            },
        },
    )
    atomic_json(output / "model.json", metadata)
    candidate = PinyinMatcher(output)
    if candidate.session is None:
        raise ValueError(candidate.problem)
    return candidate.capabilities()


def assemble(acoustic: Path, pitch: Path, tracker: Path, output: Path, *, precision="int8"):
    if precision not in {"int8", "fp32"}:
        raise ValueError("MODEL_PRECISION_UNSUPPORTED")
    if output.exists():
        raise ValueError("CANDIDATE_ALREADY_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".matcher-candidate-", dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        capabilities = _populate(acoustic, pitch, tracker, staging, precision=precision)
        staging.rename(output)
    return capabilities


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acoustic", type=Path, required=True)
    parser.add_argument("--pitch", type=Path, required=True)
    parser.add_argument("--tracker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--precision", choices=["int8", "fp32"], default="int8")
    args = parser.parse_args()
    print(
        json.dumps(
            assemble(args.acoustic, args.pitch, args.tracker, args.output, precision=args.precision)
        )
    )
