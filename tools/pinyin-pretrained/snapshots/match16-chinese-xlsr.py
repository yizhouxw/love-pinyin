"""Local Wav2Vec2 acoustic adapters. No text decoding or executable remote code.

HanziFlow's published architecture is a Wav2Vec2Model and three linear CTC
heads. Charsiu's historical frame classifier has the same eval-forward as
Wav2Vec2ForCTC, but its posteriors MUST NOT be interpreted as CTC outputs.
"""

import json
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file
from torch import nn
from transformers import Wav2Vec2Config, Wav2Vec2ForCTC, Wav2Vec2Model

from pinyin_matcher.pretrained_prepare import verify


class HanziFlow(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        self.encoder = Wav2Vec2Model(Wav2Vec2Config.from_dict(config["wav2vec2_config"]))
        size = self.encoder.config.hidden_size
        self.initial_head = nn.Linear(size, config["initial_vocab_size"])
        self.final_head = nn.Linear(size, config["final_vocab_size"])
        self.tone_head = nn.Linear(size, config["tone_vocab_size"])

    def forward(self, waveform):
        encoded = self.encoder(waveform).last_hidden_state
        return (
            encoded,
            self.initial_head(encoded),
            self.final_head(encoded),
            self.tone_head(encoded),
        )


class Wav2VecEvidence:
    def __init__(self, name: str, directory: Path, *, device="cpu", threads=2, check=True):
        if name not in {
            "hanziflow",
            "charsiu",
            "tencent-zh-base",
            "tencent-zh-tail-v1",
            "chinese-xlsr-asr",
        }:
            raise ValueError("UNKNOWN_ACOUSTIC_MODEL")
        if threads != 2 and device == "cpu":
            raise ValueError("COMPARISON_REQUIRES_TWO_CPU_THREADS")
        self.name, self.device = name, device
        self.directory = directory
        torch.set_num_threads(threads)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        if check:
            verify(name, directory)
        config = json.loads((directory / "config.json").read_text())
        if name in {"tencent-zh-base", "tencent-zh-tail-v1"}:
            self.model = Wav2Vec2Model.from_pretrained(
                str(directory), local_files_only=True, use_safetensors=name == "tencent-zh-tail-v1"
            )
            self.vocabularies = {}
        elif name == "chinese-xlsr-asr":
            self.model = Wav2Vec2ForCTC.from_pretrained(
                str(directory), local_files_only=True, use_safetensors=False
            )
            self.vocabularies = {}
        elif name == "hanziflow":
            with torch.device("meta"):
                self.model = HanziFlow(config)
            self.model.load_state_dict(
                load_file(str(directory / "model.safetensors")), strict=True, assign=True
            )
            self.vocabularies = {
                key: json.loads((directory / f"v2_1_{key}_vocabulary.json").read_text())
                for key in ("initial", "final", "tone")
            }
        else:
            with torch.device("meta"):
                self.model = Wav2Vec2ForCTC(Wav2Vec2Config.from_dict(config))
            state = torch.load(
                directory / "pytorch_model.bin", map_location="cpu", weights_only=True, mmap=True
            )
            self.model.load_state_dict(state, strict=True, assign=True)
            self.vocabularies = {"phone": json.loads((directory / "vocab.json").read_text())}
        self.model.eval().to(device)
        self.dimensions = 768 if name.startswith("tencent-zh-") else 1024

    @torch.inference_mode()
    def evidence(self, samples: np.ndarray) -> dict:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) < 400 or not np.isfinite(samples).all():
            raise ValueError("INVALID_WAVEFORM")
        normalized = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
        waveform = torch.from_numpy(normalized).unsqueeze(0).to(self.device)
        if self.name.startswith("tencent-zh-"):
            frames = self.model(waveform).last_hidden_state
            native = {}
        elif self.name == "chinese-xlsr-asr":
            frames = self.model.wav2vec2(waveform).last_hidden_state
            native = {}
        elif self.name == "hanziflow":
            frames, initial, final, tone = self.model(waveform)
            native = {"initial": initial, "final": final, "tone": tone}
        else:
            frames = self.model.wav2vec2(waveform).last_hidden_state
            native = {"phone": self.model.lm_head(frames)}
        return {
            "frames": frames[0].cpu().numpy(),
            "native": {key: value[0].cpu().numpy() for key, value in native.items()},
        }

    def extract(self, samples: np.ndarray) -> np.ndarray:
        return self.evidence(samples)["frames"]

    @torch.inference_mode()
    def evidence_batch(self, samples: list[np.ndarray]) -> list[dict]:
        """Offline padded extraction with explicit masks and true frame lengths."""
        if self.name.startswith("tencent-zh-"):
            return self._chinese_masked_batch(samples)
        normalized = [(s - s.mean()) / np.sqrt(s.var() + 1e-7) for s in samples]
        lengths = [len(s) for s in normalized]
        waveform = torch.zeros(len(samples), max(lengths), device=self.device)
        mask = torch.zeros(len(samples), max(lengths), device=self.device, dtype=torch.long)
        for i, sample in enumerate(normalized):
            waveform[i, : len(sample)] = torch.from_numpy(sample).to(self.device)
            mask[i, : len(sample)] = 1
        acoustic = self.model.encoder if self.name == "hanziflow" else self.model.wav2vec2
        frames = acoustic(waveform, attention_mask=mask).last_hidden_state
        if self.name == "chinese-xlsr-asr":
            native = {}
        elif self.name == "hanziflow":
            native = {
                "initial": self.model.initial_head(frames),
                "final": self.model.final_head(frames),
                "tone": self.model.tone_head(frames),
            }
        else:
            native = {"phone": self.model.lm_head(frames)}
        counts = acoustic._get_feat_extract_output_lengths(torch.tensor(lengths)).tolist()
        return [
            {
                "frames": frames[i, :n].cpu().numpy(),
                "native": {k: v[i, :n].cpu().numpy() for k, v in native.items()},
            }
            for i, n in enumerate(counts)
        ]

    def _chinese_masked_batch(self, samples: list[np.ndarray]) -> list[dict]:
        """Apply the first per-channel group norm over each unpadded signal only."""
        normalized = [(s - s.mean()) / np.sqrt(s.var() + 1e-7) for s in samples]
        lengths = torch.tensor([len(s) for s in normalized], device=self.device)
        waveform = torch.zeros(len(samples), int(lengths.max()), device=self.device)
        for index, sample in enumerate(normalized):
            waveform[index, : len(sample)] = torch.from_numpy(sample).to(self.device)
        hidden = waveform[:, None, :]
        for layer in self.model.feature_extractor.conv_layers:
            conv = layer.conv
            if conv.padding != (0,) or conv.dilation != (1,):
                raise ValueError("CHINESE_BATCH_UNSUPPORTED_CONVOLUTION")
            hidden = conv(hidden)
            lengths = (lengths - conv.kernel_size[0]) // conv.stride[0] + 1
            mask = torch.arange(hidden.shape[-1], device=self.device)[None, :] < lengths[:, None]
            if hasattr(layer, "layer_norm"):
                norm = layer.layer_norm
                if not isinstance(norm, nn.GroupNorm) or norm.num_groups != hidden.shape[1]:
                    raise ValueError("CHINESE_BATCH_UNSUPPORTED_NORMALIZATION")
                valid = mask[:, None, :]
                mean = (hidden * valid).sum(-1, keepdim=True) / lengths[:, None, None]
                variance = ((hidden - mean).square() * valid).sum(-1, keepdim=True) / lengths[
                    :, None, None
                ]
                hidden = (hidden - mean) * torch.rsqrt(variance + norm.eps)
                hidden = hidden * norm.weight[None, :, None] + norm.bias[None, :, None]
            hidden = layer.activation(hidden) * mask[:, None, :]
        hidden = hidden.transpose(1, 2)
        hidden, _ = self.model.feature_projection(hidden)
        hidden = self.model.encoder(hidden, attention_mask=mask).last_hidden_state
        if self.model.adapter is not None:
            raise ValueError("CHINESE_BATCH_ADAPTER_UNSUPPORTED")
        return [
            {"frames": hidden[i, : int(length)].cpu().numpy(), "native": {}}
            for i, length in enumerate(lengths)
        ]
