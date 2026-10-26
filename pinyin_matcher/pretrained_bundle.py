"""Install local CPU model bundles; no network or application integration."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_prepare import REGISTRY


def bundle(heads: Path, acoustic: Path, output: Path, *, backend="int8", pitch_model=None) -> dict:
    if output.exists():
        raise ValueError("BUNDLE_DESTINATION_ALREADY_EXISTS")
    comparison = (heads / "comparison.json").is_file()
    metadata = json.loads((heads / ("comparison.json" if comparison else "model.json")).read_text())
    if metadata.get("acousticProbe"):
        raise ValueError("INTERMEDIATE_PROBE_REQUIRES_BOUND_ENCODER_EXPORT")
    if (metadata.get("acousticDerivative") or {}).get("architecture") == (
        "sensevoice-70-native-sequence-v1"
    ):
        raise ValueError("NATIVE_SEQUENCE_POOLED_READOUT_REQUIRES_BOUND_ENCODER_BACKEND")
    if comparison:
        metadata["headKind"] = "native-comparison"
        calibration = json.loads((heads / "calibration.json").read_text())
        if calibration.get("finalTestRead") is not False:
            raise ValueError("COMPARISON_TEST_USAGE_UNDECLARED")
        metadata["testUsed"] = False
        metadata["calibrationReportSha256"] = fingerprint(heads / "calibration.json")
    name = metadata["model"]
    registry = json.loads(REGISTRY.read_text())["models"][name]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pretrained-bundle-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        encoder = stage / "encoder"
        encoder.mkdir()
        head_files = (
            ("comparison.json", "comparison.onnx", "comparison-normalization.npz")
            if comparison
            else ("heads.onnx", "normalization.npz")
        )
        for filename in head_files:
            shutil.copy2(heads / filename, stage / filename)
        if metadata.get("pitchOverride"):
            if pitch_model is None:
                raise ValueError("EXPLICIT_LOCAL_PITCH_MODEL_REQUIRED")
            source_identity = metadata["pitchOverride"]["sourceIdentity"]
            pitch_license = pitch_model.parent / "LICENSE"
            if (
                fingerprint(pitch_model) != source_identity["modelSha256"]
                or fingerprint(pitch_license) != source_identity["licenseSha256"]
            ):
                raise ValueError("PITCH_SOURCE_DIGEST_MISMATCH")
            (stage / "pitch").mkdir()
            shutil.copy2(pitch_model, stage / "pitch/model.onnx")
            shutil.copy2(pitch_license, stage / "pitch/LICENSE")
        derivative = metadata.get("acousticDerivative")
        if derivative:
            if name not in {"hanziflow", "sensevoice"} or backend != "torch":
                raise ValueError("DERIVATIVE_REQUIRES_TORCH_CPU")
            source_metadata = acoustic / "tuned.json"
            if fingerprint(source_metadata) != derivative["metadataSha256"]:
                raise ValueError("DERIVATIVE_METADATA_DIGEST_MISMATCH")
            tuned = json.loads(source_metadata.read_text())
            for relative, entry in tuned["files"].items():
                source = (acoustic / relative).resolve()
                if (
                    not source.is_relative_to(acoustic.resolve())
                    or fingerprint(source) != entry["sha256"]
                ):
                    raise ValueError("DERIVATIVE_SOURCE_DIGEST_MISMATCH")
                destination = encoder / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            shutil.copy2(source_metadata, encoder / "tuned.json")
        elif backend == "torch":
            for entry in registry["files"]:
                source = acoustic / entry["path"]
                if fingerprint(source) != entry["sha256"]:
                    raise ValueError("ACOUSTIC_SOURCE_DIGEST_MISMATCH")
                shutil.copy2(source, encoder / entry["path"])
        elif backend == "int8":
            filenames = [
                entry["path"]
                for entry in registry["files"]
                if not entry["path"].endswith((".pt", ".bin", ".safetensors"))
            ]
            filenames += (
                ["encoder.int8.onnx", "encoder.int8.onnx.json"]
                if name == "sensevoice"
                else ["acoustic.int8.onnx", "acoustic.onnx.json"]
            )
            for filename in filenames:
                shutil.copy2(acoustic / filename, encoder / filename)
        else:
            raise ValueError("CPU_BACKEND_INVALID")
        metadata["encoderBackend"] = backend
        metadata["acousticSource"] = registry
        metadata["packageFiles"] = {
            str(path.relative_to(stage)): {
                "sha256": fingerprint(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        metadata["packageBytes"] = sum(r["bytes"] for r in metadata["packageFiles"].values())
        (stage / "model.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        stage.rename(output)
    return {
        "directory": str(output.resolve()),
        "model": name,
        "backend": backend,
        "bytes": metadata["packageBytes"],
        "sha256": fingerprint(output / "model.json"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heads", type=Path, required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=["int8", "torch"], default="int8")
    parser.add_argument("--pitch-model", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            bundle(
                args.heads,
                args.encoder,
                args.output,
                backend=args.backend,
                pitch_model=args.pitch_model,
            )
        )
    )
