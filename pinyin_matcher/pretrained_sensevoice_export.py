"""Explicit standalone Sense50 phonetic ONNX INT8 export and CPU2 inference.

Exports preserve the FP32 source directory. Quantization requires a fresh full
CPU calibration; numerical parity examples cannot establish pronunciation quality.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import onnxruntime as ort

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_sensevoice import FILES, REVISION, SenseVoiceFeatures, _cmvn

ARCHITECTURE = "sensevoice-50-ctc-int8-v1"
HEADS = ("initial", "final", "tone")
GRAPH = "encoder.int8.onnx"


def session(graph: Path):
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(graph), options, providers=["CPUExecutionProvider"])


def export(directory: Path, output: Path):
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from torch import nn

    from pinyin_matcher.pretrained_sensevoice_finetune import TunedSenseVoiceEvidence

    if output.exists():
        raise ValueError("SENSEVOICE_ONNX_OUTPUT_ALREADY_EXISTS")
    adapter = TunedSenseVoiceEvidence(directory, device="cpu", threads=2)

    class Export(nn.Module):
        def __init__(self):
            super().__init__()
            self.model = adapter.model

        def forward(self, features, lengths):
            prompt = self.model.embed(torch.tensor([3, 1, 2, 15], device=features.device))
            padded = torch.cat((prompt[None].expand(features.shape[0], -1, -1), features), 1)
            frames = self.model.encoder(padded, lengths + 4)[:, 4:]
            return (
                frames,
                self.model.initial_head(frames),
                self.model.final_head(frames),
                self.model.tone_head(frames),
            )

    output.mkdir(parents=True)
    fp32, int8 = output / "encoder.fp32.onnx", output / GRAPH
    outputs = ["frames", *HEADS]
    with torch.inference_mode():
        torch.onnx.export(
            Export().eval(),
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
    parent = adapter.metadata
    resources = [name for name in parent["files"] if name != "tuned.safetensors"]
    for name in resources:
        shutil.copy2(directory / name, output / name)
    shutil.copy2(directory / "tuned.json", output / "parent-tuned.json")
    metadata = {
        **parent,
        "architecture": ARCHITECTURE,
        "parentTunedMetadataSha256": fingerprint(output / "parent-tuned.json"),
        "parentTunedWeightSha256": parent["files"]["tuned.safetensors"]["sha256"],
        "exportCodeSha256": fingerprint(Path(__file__)),
        "quantization": "ORT dynamic per-channel signed INT8 MatMul/Gemm; Conv/normalization FP32",
        "inputs": ["features", "lengths"],
        "outputs": outputs,
        "targetInput": False,
        "fullCpuCalibrationRequired": True,
        "qualityEstablishedByNumericalParity": False,
        "fp32Export": {"sha256": fingerprint(fp32), "bytes": fp32.stat().st_size},
        "files": {
            name: {"sha256": fingerprint(output / name), "bytes": (output / name).stat().st_size}
            for name in [GRAPH, "parent-tuned.json", *resources]
        },
    }
    (output / "tuned.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    return metadata


class OnnxSenseVoiceEvidence:
    dimensions = 512
    dimension = 512
    name = "sensevoice"
    device = "cpu"

    def __init__(self, directory: Path, *, device="cpu", threads=2, check=True):
        import torch

        directory = Path(directory)
        if device != "cpu" or threads != 2:
            raise ValueError("SENSEVOICE_ONNX_REQUIRES_CPU_TWO_THREADS")
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        metadata = json.loads((directory / "tuned.json").read_text())
        parent_path = directory / "parent-tuned.json"
        parent = json.loads(parent_path.read_text())
        if (
            metadata.get("architecture") != ARCHITECTURE
            or metadata.get("sourceRevision") != REVISION
            or metadata.get("parentWeightSha256") != FILES["model.pt"]
            or parent.get("architecture") != "sensevoice-50-ctc-v1"
            or parent.get("sourceRevision") != REVISION
            or parent.get("parentWeightSha256") != FILES["model.pt"]
            or metadata.get("targetInput") is not False
            or metadata.get("nativeRimeAliases") != native_rime_aliases("hanziflow")
            or metadata.get("parentTunedMetadataSha256") != fingerprint(parent_path)
            or metadata.get("parentTunedWeightSha256")
            != parent["files"]["tuned.safetensors"]["sha256"]
        ):
            raise ValueError("SENSEVOICE_ONNX_PARENT_IDENTITY_MISMATCH")
        required = {
            GRAPH,
            "parent-tuned.json",
            "am.mvn",
            "config.yaml",
            "MODEL_LICENSE",
            "v2_1_target_schema.json",
            *(f"v2_1_{head}_vocabulary.json" for head in HEADS),
        }
        if not required.issubset(metadata.get("files", {})):
            raise ValueError("SENSEVOICE_ONNX_REQUIRED_FILES_MISSING")
        if check:
            registry = json.loads(
                (ROOT / "content/pronunciation-pretrained-models.json").read_text()
            )["models"]
            pinned = {item["path"]: item["sha256"] for item in registry["sensevoice"]["files"]}
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
                    not path.is_relative_to(directory.resolve())
                    or fingerprint(path) != record["sha256"]
                    or path.stat().st_size != record["bytes"]
                ):
                    raise ValueError("SENSEVOICE_ONNX_RESOURCE_DIGEST_MISMATCH:" + name)
                if name in pinned and record["sha256"] != pinned[name]:
                    raise ValueError("SENSEVOICE_ONNX_FIXED_SOURCE_CHANGED:" + name)
        self.metadata, self.directory = metadata, directory
        self.cmvn = _cmvn(directory / "am.mvn")
        self.vocabularies = {
            head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text())
            for head in HEADS
        }
        self.session = session(directory / GRAPH)
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError("SENSEVOICE_ONNX_CPU_PROVIDER_REQUIRED")

    def evidence_batch(self, samples: list[np.ndarray]) -> list[dict]:
        if not samples:
            raise ValueError("SENSEVOICE_EMPTY_BATCH")
        features = [SenseVoiceFeatures.frontend(self, wave).numpy() for wave in samples]
        lengths = np.asarray([len(item) for item in features], dtype=np.int64)
        padded = np.zeros((len(features), int(lengths.max()), 560), dtype=np.float32)
        for index, item in enumerate(features):
            padded[index, : len(item)] = item
        outputs = self.session.run(None, {"features": padded, "lengths": lengths})
        return [
            {
                "frames": outputs[0][index, :length],
                "native": {
                    head: value[index, :length]
                    for head, value in zip(HEADS, outputs[1:], strict=True)
                },
            }
            for index, length in enumerate(lengths)
        ]

    def evidence(self, samples: np.ndarray) -> dict:
        return self.evidence_batch([samples])[0]

    def extract(self, samples: np.ndarray) -> np.ndarray:
        return self.evidence(samples)["frames"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = export(args.model, args.output)
    print(json.dumps({"architecture": result["architecture"], "graph": result["files"][GRAPH]}))


if __name__ == "__main__":
    main()
