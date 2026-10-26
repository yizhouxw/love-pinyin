"""Standalone CPU export of the separately trained 70-layer phonetic CTC model.

Original ASR weights provide the frozen acoustic prefix; only explicitly trained
phonetic heads produce CTC evidence. No character decoding, network, or target
enters the graph. Numerical parity never establishes pronunciation quality.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch
from torch import nn

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_sensevoice import FILES, REVISION, _cmvn
from pinyin_matcher.pretrained_sensevoice_export import OnnxSenseVoiceEvidence, session

SOURCE_ARCHITECTURE = "sensevoice-70-native-sequence-v1"
ARCHITECTURE = "sensevoice-70-native-sequence-int8-v1"
GRAPH = "encoder.int8.onnx"
HEADS = ("initial", "final", "tone")
CONFIG = ROOT / "content/pronunciation-pretrained-native-sequence.json"
RESOURCES = {
    "am.mvn",
    "config.yaml",
    "MODEL_LICENSE",
    "README.md",
    "SOURCE-MIT.txt",
    "v2_1_target_schema.json",
    *(f"v2_1_{head}_vocabulary.json" for head in HEADS),
}
RESERVED_EXPORT_NAMES = {
    "encoder.fp32.onnx",
    GRAPH,
    "parent-tuned.json",
    "training-config.json",
    "tuned.json",
}


def source_resource_records(parent):
    """Retain all parent provenance, refusing output collisions or unsafe names."""
    records = {
        name: value for name, value in parent["files"].items() if name != "tuned.safetensors"
    }
    seen = set()
    for name in records:
        path = Path(name)
        folded = name.casefold()
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or name != path.as_posix()
            or "\\" in name
            or "\x00" in name
            or path.parts[0].casefold() in {value.casefold() for value in RESERVED_EXPORT_NAMES}
            or folded in seen
        ):
            raise ValueError("NATIVE_SEQUENCE_EXPORT_RESOURCE_NAME_COLLISION:" + name)
        seen.add(folded)
    return records


class NativeSequenceGraph(nn.Module):
    """Dynamic-batch/time full encoder, with the four fixed contextual prompts."""

    def __init__(self, encoder, embed, heads):
        super().__init__()
        self.encoder, self.embed, self.heads = encoder, embed, heads
        self.register_buffer("prompt_ids", torch.tensor([3, 1, 2, 15]), persistent=False)

    def forward(self, features, lengths):
        prompt = self.embed(self.prompt_ids)
        padded = torch.cat((prompt[None].expand(features.shape[0], -1, -1), features), 1)
        frames = self.encoder(padded, lengths + 4)[:, 4:]
        return (
            frames,
            self.heads.initial_head(frames),
            self.heads.final_head(frames),
            self.heads.tone_head(frames),
        )


def export(directory: Path, output: Path, *, source: Path | None = None):
    from onnxruntime.quantization import QuantType, quantize_dynamic

    from pinyin_matcher.pretrained_native_sequence import NativeSequenceEvidence

    if output.exists():
        raise ValueError("NATIVE_SEQUENCE_EXPORT_OUTPUT_EXISTS")
    adapter = NativeSequenceEvidence(directory, source=source, device="cpu", threads=2)
    parent = adapter.metadata
    config = json.loads(CONFIG.read_text())
    if (
        parent.get("architecture") != SOURCE_ARCHITECTURE
        or parent.get("configurationSha256") != fingerprint(CONFIG)
        or parent.get("configuration") != config
        or not RESOURCES.issubset(parent.get("files", {}))
    ):
        raise ValueError("NATIVE_SEQUENCE_EXPORT_SOURCE_CONFIGURATION_MISMATCH")
    resources = source_resource_records(parent)
    for name, record in resources.items():
        path = (directory / name).resolve()
        if (
            not path.is_relative_to(directory.resolve())
            or fingerprint(path) != record["sha256"]
            or path.stat().st_size != record["bytes"]
        ):
            raise ValueError("NATIVE_SEQUENCE_EXPORT_SOURCE_CHANGED:" + name)
    model = NativeSequenceGraph(adapter.encoder, adapter.embed, adapter.heads).eval()
    output.mkdir(parents=True)
    fp32, int8 = output / "encoder.fp32.onnx", output / GRAPH
    outputs = ["frames", *HEADS]
    with torch.inference_mode():
        torch.onnx.export(
            model,
            (torch.zeros(1, 8, 560), torch.tensor([8])),
            str(fp32),
            input_names=["features", "lengths"],
            output_names=outputs,
            dynamic_axes={
                "features": {0: "batch", 1: "time"},
                "lengths": {0: "batch"},
                **{key: {0: "batch", 1: "time"} for key in outputs},
            },
            opset_version=17,
            dynamo=False,
            external_data=False,
        )
    quantize_dynamic(
        str(fp32),
        str(int8),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm"],
        per_channel=True,
        use_external_data_format=False,
    )
    for name in sorted(resources):
        if fingerprint(directory / name) != parent["files"][name]["sha256"]:
            raise ValueError("NATIVE_SEQUENCE_EXPORT_SOURCE_CHANGED:" + name)
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(directory / name, output / name)
    shutil.copy2(directory / "tuned.json", output / "parent-tuned.json")
    shutil.copy2(CONFIG, output / "training-config.json")
    metadata = {
        **{k: v for k, v in parent.items() if k != "sourceDirectory"},
        "architecture": ARCHITECTURE,
        "parentTunedMetadataSha256": fingerprint(output / "parent-tuned.json"),
        "parentTunedWeightSha256": parent["files"]["tuned.safetensors"]["sha256"],
        "exportCodeSha256": fingerprint(Path(__file__)),
        "sourceConfigurationSha256": fingerprint(output / "training-config.json"),
        "quantization": "ORT dynamic per-channel signed INT8 MatMul/Gemm; Conv/normalization FP32",
        "inputs": ["features", "lengths"],
        "outputs": outputs,
        "targetInput": False,
        "standaloneCpuPackage": True,
        "fullCpuCalibrationRequired": True,
        "qualityEstablishedByNumericalParity": False,
        "fp32Export": {"sha256": fingerprint(fp32), "bytes": fp32.stat().st_size},
        "files": {
            name: {"sha256": fingerprint(output / name), "bytes": (output / name).stat().st_size}
            for name in [GRAPH, "parent-tuned.json", "training-config.json", *sorted(resources)]
        },
    }
    (output / "tuned.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    return metadata


def verify_quantized_identity(directory: Path):
    """Check every resource before opening the graph, without any parent directory."""
    directory = Path(directory).resolve()
    metadata = json.loads((directory / "tuned.json").read_text())
    parent_path = directory / "parent-tuned.json"
    parent = json.loads(parent_path.read_text())
    if (
        metadata.get("architecture") != ARCHITECTURE
        or parent.get("architecture") != SOURCE_ARCHITECTURE
        or any(m.get("sourceRevision") != REVISION for m in (metadata, parent))
        or any(m.get("parentWeightSha256") != FILES["model.pt"] for m in (metadata, parent))
        or any(m.get("sourceWeightsSha256") != FILES["model.pt"] for m in (metadata, parent))
        or metadata.get("parentTunedMetadataSha256") != fingerprint(parent_path)
        or metadata.get("parentTunedWeightSha256")
        != parent.get("files", {}).get("tuned.safetensors", {}).get("sha256")
        or metadata.get("targetInput") is not False
        or metadata.get("standaloneCpuPackage") is not True
        or metadata.get("nativeRimeAliases") != native_rime_aliases("hanziflow")
        or parent.get("nativeRimeAliases") != native_rime_aliases("hanziflow")
    ):
        raise ValueError("NATIVE_SEQUENCE_ONNX_PARENT_IDENTITY_MISMATCH")
    required = {GRAPH, "parent-tuned.json", "training-config.json", *RESOURCES}
    if not required.issubset(metadata.get("files", {})):
        raise ValueError("NATIVE_SEQUENCE_ONNX_REQUIRED_FILES_MISSING")
    for name, record in source_resource_records(parent).items():
        copied = metadata["files"].get(name, {})
        if record.get("sha256") != copied.get("sha256") or record.get("bytes") != copied.get(
            "bytes"
        ):
            raise ValueError("NATIVE_SEQUENCE_ONNX_PARENT_RESOURCE_MISMATCH:" + name)
    registry = json.loads((ROOT / "content/pronunciation-pretrained-models.json").read_text())[
        "models"
    ]
    pinned = {item["path"]: item["sha256"] for item in registry["sensevoice"]["files"]}
    pinned["SOURCE-MIT.txt"] = fingerprint(ROOT / "resources/licenses/SenseVoice-MIT.txt")
    pinned.update(
        {
            item["path"]: item["sha256"]
            for item in registry["hanziflow"]["files"]
            if item["path"].startswith("v2_1_")
        }
    )
    for name, record in metadata["files"].items():
        path = (directory / name).resolve()
        if (
            not path.is_relative_to(directory)
            or fingerprint(path) != record["sha256"]
            or path.stat().st_size != record["bytes"]
        ):
            raise ValueError("NATIVE_SEQUENCE_ONNX_RESOURCE_DIGEST_MISMATCH:" + name)
        if name in pinned and record["sha256"] != pinned[name]:
            raise ValueError("NATIVE_SEQUENCE_ONNX_FIXED_SOURCE_CHANGED:" + name)
    config_path = directory / "training-config.json"
    config = json.loads(config_path.read_text())
    config_sha = fingerprint(config_path)
    if (
        metadata.get("sourceConfigurationSha256") != config_sha
        or parent.get("configurationSha256") != config_sha
        or metadata.get("configurationSha256") != config_sha
        or parent.get("configuration") != config
        or metadata.get("configuration") != config
        or config.get("finalTestUsed") is not False
        or config.get("prompts") != [3, 1, 2, 15]
        or config.get("dither") != 0
    ):
        raise ValueError("NATIVE_SEQUENCE_ONNX_TRAINING_CONFIGURATION_MISMATCH")
    return metadata


class OnnxNativeSequenceEvidence(OnnxSenseVoiceEvidence):
    """Independent new identity checks; reuse only the stable official front end."""

    def __init__(self, directory: Path, *, device="cpu", threads=2):
        if device != "cpu" or threads != 2:
            raise ValueError("NATIVE_SEQUENCE_ONNX_REQUIRES_CPU_TWO_THREADS")
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        self.directory = Path(directory)
        self.metadata = verify_quantized_identity(self.directory)
        self.cmvn = _cmvn(self.directory / "am.mvn")
        self.vocabularies = {
            head: json.loads((self.directory / f"v2_1_{head}_vocabulary.json").read_text())
            for head in HEADS
        }
        for head, count in zip(HEADS, (24, 44, 7), strict=True):
            table = self.vocabularies[head]
            if (
                len(table) != count
                or set(table.values()) != set(range(count))
                or table.get("<blank>") != 0
            ):
                raise ValueError("NATIVE_SEQUENCE_ONNX_VOCABULARY_INVALID")
        self.session = session(self.directory / GRAPH)
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError("NATIVE_SEQUENCE_ONNX_CPU_PROVIDER_REQUIRED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.model, args.output, source=args.source)
    print(json.dumps({"architecture": result["architecture"], "graph": result["files"][GRAPH]}))


if __name__ == "__main__":
    main()
