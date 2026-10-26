"""Explicit ONNX CPU export/quantization of local audited acoustic encoders.

No remote code, network, character decoding, target conditioning, or automatic
fallback. Export is an offline preparation step. Runtime only opens local files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from pinyin_matcher.catalog import ROOT

REGISTRY = ROOT / "content/pronunciation-pretrained-models.json"


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _native_names(name: str) -> list[str]:
    return ["initial", "final", "tone"] if name == "hanziflow" else ["phone"]


def export_wav2vec(name: str, directory: str | Path) -> dict:
    """Export FP32 and per-channel dynamic INT8 from pinned local weights."""
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from torch import nn

    from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

    class _ExportWav2Vec(nn.Module):
        def __init__(self, adapter: Wav2VecEvidence):
            super().__init__()
            self.model = adapter.model
            self.name = adapter.name

        def forward(self, waveform):
            if self.name == "hanziflow":
                return self.model(waveform)
            frames = self.model.wav2vec2(waveform).last_hidden_state
            return frames, self.model.lm_head(frames)

    directory = Path(directory)
    adapter = Wav2VecEvidence(name, directory, device="cpu", threads=2)
    model = _ExportWav2Vec(adapter).eval()
    encoder = adapter.model.encoder if name == "hanziflow" else adapter.model.wav2vec2
    # Torch legacy ONNX supports eager attention consistently across dynamic time.
    encoder.set_attn_implementation("eager")
    output_names = ["frames", *_native_names(name)]
    graph = directory / "acoustic.onnx"
    quantized = directory / "acoustic.int8.onnx"
    with torch.inference_mode():
        torch.onnx.export(
            model,
            torch.zeros(1, 8000),
            str(graph),
            input_names=["waveform"],
            output_names=output_names,
            dynamic_axes={
                "waveform": {0: "batch", 1: "samples"},
                **{key: {0: "batch", 1: "frames_count"} for key in output_names},
            },
            opset_version=17,
            dynamo=False,
            external_data=False,
        )
    quantize_dynamic(
        str(graph),
        str(quantized),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm"],
        per_channel=True,
        use_external_data_format=False,
    )
    parent = json.loads(REGISTRY.read_text())["models"][name]
    metadata = {
        "schemaVersion": 1,
        "model": name,
        "parentRevision": parent["revision"],
        "parentWeights": {
            entry["path"]: entry["sha256"]
            for entry in parent["files"]
            if entry["path"].endswith((".bin", ".safetensors"))
        },
        "quantization": "ORT dynamic per-channel signed INT8 MatMul/Gemm; Conv FP32",
        "outputs": output_names,
        "targetInput": False,
        "files": {
            path.name: {"sha256": _digest(path), "bytes": path.stat().st_size}
            for path in (graph, quantized)
        },
    }
    (directory / "acoustic.onnx.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


class OnnxWav2VecEvidence:
    """The same frame/native evidence contract with a two-thread CPU session."""

    dimensions = 1024
    device = "cpu"

    def __init__(
        self,
        name: str,
        directory: str | Path,
        *,
        quantized: bool = True,
        check: bool = True,
    ):
        if name not in {"hanziflow", "charsiu"}:
            raise ValueError("UNKNOWN_ACOUSTIC_MODEL")
        directory = Path(directory)
        self.name = name
        metadata = json.loads((directory / "acoustic.onnx.json").read_text())
        parent = json.loads(REGISTRY.read_text())["models"][name]
        expected_parents = {
            entry["path"]: entry["sha256"]
            for entry in parent["files"]
            if entry["path"].endswith((".bin", ".safetensors"))
        }
        graph = directory / ("acoustic.int8.onnx" if quantized else "acoustic.onnx")
        if (
            metadata["model"] != name
            or metadata["parentRevision"] != parent["revision"]
            or metadata["parentWeights"] != expected_parents
            or metadata["targetInput"] is not False
            or (check and _digest(graph) != metadata["files"][graph.name]["sha256"])
        ):
            raise ValueError("WAV2VEC_ONNX_INTEGRITY_MISMATCH")
        if check:
            needed = {"config.json"}
            needed.update(
                {f"v2_1_{key}_vocabulary.json" for key in _native_names(name)}
                if name == "hanziflow"
                else {"vocab.json"}
            )
            originals = {item["path"]: item for item in parent["files"]}
            for path in needed:
                if _digest(directory / path) != originals[path]["sha256"]:
                    raise ValueError("WAV2VEC_RUNTIME_RESOURCE_MISMATCH: " + path)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(graph), options, providers=["CPUExecutionProvider"])
        if name == "hanziflow":
            self.vocabularies = {
                key: json.loads((directory / f"v2_1_{key}_vocabulary.json").read_text())
                for key in _native_names(name)
            }
        else:
            self.vocabularies = {"phone": json.loads((directory / "vocab.json").read_text())}

    def evidence(self, samples: np.ndarray) -> dict:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) < 400 or not np.isfinite(samples).all():
            raise ValueError("INVALID_WAVEFORM")
        normalized = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
        outputs = self.session.run(None, {"waveform": normalized[None]})
        return {
            "frames": outputs[0][0],
            "native": {
                name: logits[0]
                for name, logits in zip(_native_names(self.name), outputs[1:], strict=True)
            },
        }

    def extract(self, samples: np.ndarray) -> np.ndarray:
        return self.evidence(samples)["frames"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=["hanziflow", "charsiu", "sensevoice"])
    parser.add_argument("--model", required=True, type=Path)
    args = parser.parse_args()
    start = time.perf_counter()
    if args.name == "sensevoice":
        from pinyin_matcher.pretrained_sensevoice import export_onnx

        result = export_onnx(args.model)
    else:
        result = export_wav2vec(args.name, args.model)
    result["elapsedSeconds"] = time.perf_counter() - start
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
