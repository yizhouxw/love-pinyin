"""Local-only SenseVoiceSmall acoustic features, with no text-based matching.

SANM inference equations adapted from QwenAudio/SenseVoice model.py at
586bbdb2b052f4fe19322581825228b6810a9fb3 (MIT; see THIRD_PARTY_NOTICES.md).
Weights retain the separate FunASR Model License, not the code's MIT license.
No downloaded Python is executed and this module never downloads resources.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from torchaudio.compliance.kaldi import fbank

REVISION = "3847d57b6bdf2dd8875cb1508d2af43d80a16bf7"
SOURCE_REVISION = "586bbdb2b052f4fe19322581825228b6810a9fb3"
FILES = {
    "model.pt": "833ca2dcfdf8ec91bd4f31cfac36d6124e0c459074d5e909aec9cabe6204a3ea",
    "am.mvn": "29b3c740a2c0cfc6b308126d31d7f265fa2be74f3bb095cd2f143ea970896ae5",
    "config.yaml": "f71e239ba36705564b5bf2d2ffd07eece07b8e3f2bbf6d2c99d8df856339ac19",
}


def _check_files(directory: Path, *, include_weights: bool = True) -> None:
    for name, expected in FILES.items():
        if name == "model.pt" and not include_weights:
            continue
        with (directory / name).open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"SENSEVOICE_FILE_SHA256_MISMATCH: {name}")


class _FeedForward(nn.Module):
    def __init__(self):
        super().__init__()
        self.w_1 = nn.Linear(512, 2048)
        self.w_2 = nn.Linear(2048, 512)

    def forward(self, x):
        return self.w_2(F.relu(self.w_1(x)))


class _Attention(nn.Module):
    def __init__(self, input_size: int):
        super().__init__()
        self.linear_out = nn.Linear(512, 512)
        self.linear_q_k_v = nn.Linear(input_size, 1536)
        self.fsmn_block = nn.Conv1d(512, 512, 11, groups=512, bias=False)

    def forward(self, x, mask):
        batch, time, _ = x.shape
        q, k, v = self.linear_q_k_v(x).split(512, dim=-1)
        valid = mask.transpose(1, 2)
        memory = v * valid
        memory = self.fsmn_block(F.pad(memory.transpose(1, 2), (5, 5))).transpose(1, 2)
        memory = (memory + v * valid) * valid
        q = q.reshape(batch, time, 4, 128).transpose(1, 2)
        k = k.reshape(batch, time, 4, 128).transpose(1, 2)
        v = v.reshape(batch, time, 4, 128).transpose(1, 2)
        scores = (q * (128**-0.5)) @ k.transpose(-2, -1)
        invalid = ~mask[:, None].bool()
        weights = scores.masked_fill(invalid, -math.inf).softmax(dim=-1)
        weights = weights.masked_fill(invalid, 0)
        context = (weights @ v).transpose(1, 2).reshape(batch, time, 512)
        return self.linear_out(context) + memory


class _Layer(nn.Module):
    def __init__(self, input_size: int = 512):
        super().__init__()
        self.self_attn = _Attention(input_size)
        self.feed_forward = _FeedForward()
        self.norm1 = nn.LayerNorm(input_size)
        self.norm2 = nn.LayerNorm(512)
        self.input_size = input_size

    def forward(self, x, mask):
        attention = self.self_attn(self.norm1(x), mask)
        x = x + attention if self.input_size == 512 else attention
        return x + self.feed_forward(self.norm2(x))


class _Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoders0 = nn.ModuleList([_Layer(560)])
        self.encoders = nn.ModuleList([_Layer() for _ in range(49)])
        self.tp_encoders = nn.ModuleList([_Layer() for _ in range(20)])
        self.after_norm = nn.LayerNorm(512)
        self.tp_norm = nn.LayerNorm(512)

    def forward(self, x, lengths):
        positions = torch.arange(1, x.shape[1] + 1, device=x.device, dtype=x.dtype)
        scales = torch.exp(
            torch.arange(280, device=x.device, dtype=x.dtype) * (-math.log(10000) / 279)
        )
        phase = positions[:, None] * scales[None]
        x = x * math.sqrt(512) + torch.cat((phase.sin(), phase.cos()), dim=-1)[None]
        mask = (torch.arange(x.shape[1], device=x.device)[None] < lengths[:, None])[:, None]
        for layer in [*self.encoders0, *self.encoders]:
            x = layer(x, mask)
        x = self.after_norm(x)
        for layer in self.tp_encoders:
            x = layer(x, mask)
        return self.tp_norm(x)


def _cmvn(path: Path) -> torch.Tensor:
    lines = path.read_text(encoding="utf-8").splitlines()
    values = []
    for index, line in enumerate(lines):
        if line.startswith(("<AddShift>", "<Rescale>")):
            values.append([float(x) for x in lines[index + 1].split("[")[1].split("]")[0].split()])
    result = torch.tensor(values, dtype=torch.float32)
    if result.shape != (2, 560) or not torch.isfinite(result).all():
        raise ValueError("SENSEVOICE_CMVN_INVALID")
    return result


class SenseVoiceFeatures:
    """Target-independent 512D encoder frames, about one per 60ms.

    ``device='mps'`` is for offline feature preparation only. Deployed inference
    must construct with the default ``device='cpu'`` and two Torch threads.
    Character CTC weights are intentionally not loaded into the matching model.
    """

    dimension = 512
    dimensions = 512
    sample_rate = 16000
    model_id = "sensevoice-small"

    def __init__(
        self,
        directory: str | Path,
        *,
        device: str = "cpu",
        verify: bool = True,
        quantized: bool = False,
    ):
        directory = Path(directory)
        if verify:
            _check_files(directory, include_weights=not quantized)
        if device not in {"cpu", "mps"}:
            raise ValueError("CPU_OR_OFFLINE_MPS_REQUIRED")
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        self.device = torch.device(device)
        self.cmvn = _cmvn(directory / "am.mvn")
        self.onnx = None
        if quantized:
            if device != "cpu":
                raise ValueError("ONNX_REQUIRES_CPU")
            import onnxruntime as ort

            graph = directory / "encoder.int8.onnx"
            metadata = json.loads(graph.with_suffix(".onnx.json").read_text())
            if (
                metadata["parentRevision"] != REVISION
                or metadata["parentSha256"] != FILES["model.pt"]
                or metadata["targetInput"] is not False
            ):
                raise ValueError("SENSEVOICE_ONNX_PARENT_MISMATCH")
            if verify:
                with graph.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                if digest != metadata["sha256"]:
                    raise ValueError("SENSEVOICE_ONNX_SHA256_MISMATCH")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            self.onnx = ort.InferenceSession(
                str(graph), options, providers=["CPUExecutionProvider"]
            )
            return
        state = torch.load(directory / "model.pt", map_location="cpu", weights_only=True, mmap=True)
        with torch.device("meta"):
            self.encoder = _Encoder()
        self.encoder.load_state_dict(
            {
                key.removeprefix("encoder."): value
                for key, value in state.items()
                if key.startswith("encoder.")
            },
            strict=True,
            assign=True,
        )
        self.embed = nn.Embedding.from_pretrained(state["embed.weight"], freeze=True)
        self.encoder.to(self.device).eval()
        self.embed.to(self.device).eval()

    def frontend(self, samples: np.ndarray) -> torch.Tensor:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) < 400 or not np.isfinite(samples).all():
            raise ValueError("FINITE_MONO_16KHZ_REQUIRED")
        features = fbank(
            torch.from_numpy(samples.copy())[None] * 32768,
            num_mel_bins=80,
            frame_length=25,
            frame_shift=10,
            dither=0,
            energy_floor=0,
            window_type="hamming",
            sample_frequency=16000,
            snip_edges=True,
        )
        # Official LFR: 7 stacked frames, stride 6, endpoint replication.
        count = math.ceil(len(features) / 6)
        features = torch.cat((features[:1].expand(3, -1), features), dim=0)
        required = (count - 1) * 6 + 7
        if len(features) < required:
            features = torch.cat((features, features[-1:].expand(required - len(features), -1)))
        features = features.unfold(0, 7, 6).transpose(1, 2).reshape(count, 560)
        return (features + self.cmvn[0]) * self.cmvn[1]

    def extract_batch(self, samples: list[np.ndarray]) -> list[np.ndarray]:
        features = [self.frontend(wave) for wave in samples]
        if self.onnx is not None:
            return [
                self.onnx.run(None, {"features": item.numpy()[None]})[0][0] for item in features
            ]
        lengths = torch.tensor([len(item) + 4 for item in features], device=self.device)
        padded = torch.zeros(len(features), int(lengths.max()), 560, device=self.device)
        # Fixed zh, emotion, event, no-ITN prompts; no target, Hanzi, or transcript.
        with torch.inference_mode():
            prompt = self.embed(torch.tensor([3, 1, 2, 15], device=self.device))
            for index, item in enumerate(features):
                padded[index, :4] = prompt
                padded[index, 4 : len(item) + 4] = item.to(self.device)
            encoded = self.encoder(padded, lengths)
            return [encoded[i, 4 : lengths[i]].cpu().numpy() for i in range(len(features))]

    def extract(self, samples: np.ndarray) -> np.ndarray:
        return self.extract_batch([samples])[0]


class _ExportEncoder(nn.Module):
    def __init__(self, model: SenseVoiceFeatures):
        super().__init__()
        self.encoder = model.encoder
        self.embed = model.embed

    def forward(self, features):
        prompt = self.embed(torch.tensor([3, 1, 2, 15], device=features.device))
        prompt = prompt[None].expand(features.shape[0], -1, -1)
        padded = torch.cat((prompt, features), dim=1)
        lengths = torch.ones(padded.shape[0], device=features.device, dtype=torch.long)
        lengths = lengths * padded.shape[1]
        return self.encoder(padded, lengths)[:, 4:]


def export_onnx(directory: str | Path) -> dict:
    """Explicit local FP32 export + dynamic per-channel INT8 MatMul quantization."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    directory = Path(directory)
    model = SenseVoiceFeatures(directory)
    graph = directory / "encoder.onnx"
    torch.onnx.export(
        _ExportEncoder(model),
        torch.zeros(1, 67, 560),
        str(graph),
        input_names=["features"],
        output_names=["encoded"],
        dynamic_axes={"features": {0: "batch", 1: "time"}, "encoded": {0: "batch", 1: "time"}},
        opset_version=17,
        dynamo=False,
    )
    quantized = directory / "encoder.int8.onnx"
    quantize_dynamic(
        str(graph),
        str(quantized),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul"],
        per_channel=True,
    )
    with quantized.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    metadata = {
        "schemaVersion": 1,
        "model": "SenseVoiceSmall acoustic encoder (no character CTC)",
        "parentRevision": REVISION,
        "parentSha256": FILES["model.pt"],
        "sha256": digest,
        "bytes": quantized.stat().st_size,
        "quantization": "ORT dynamic per-channel signed INT8 MatMul; Conv/normalization FP32",
        "prompts": ["zh", "emotion", "event", "no-itn"],
        "targetInput": False,
    }
    quantized.with_suffix(".onnx.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata
