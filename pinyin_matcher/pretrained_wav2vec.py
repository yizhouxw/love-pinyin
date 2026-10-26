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
        if name not in {"hanziflow", "charsiu"}:
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
        if name == "hanziflow":
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
        self.dimensions = 1024

    @torch.inference_mode()
    def evidence(self, samples: np.ndarray) -> dict:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) < 400 or not np.isfinite(samples).all():
            raise ValueError("INVALID_WAVEFORM")
        normalized = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
        waveform = torch.from_numpy(normalized).unsqueeze(0).to(self.device)
        if self.name == "hanziflow":
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
        normalized = [(s - s.mean()) / np.sqrt(s.var() + 1e-7) for s in samples]
        lengths = [len(s) for s in normalized]
        waveform = torch.zeros(len(samples), max(lengths), device=self.device)
        mask = torch.zeros(len(samples), max(lengths), device=self.device, dtype=torch.long)
        for i, sample in enumerate(normalized):
            waveform[i, : len(sample)] = torch.from_numpy(sample).to(self.device)
            mask[i, : len(sample)] = 1
        acoustic = self.model.encoder if self.name == "hanziflow" else self.model.wav2vec2
        frames = acoustic(waveform, attention_mask=mask).last_hidden_state
        if self.name == "hanziflow":
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
