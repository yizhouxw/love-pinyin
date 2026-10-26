import json
import os
from pathlib import Path

import numpy as np
import pytest
import torch

from pinyin_matcher.pretrained_sensevoice_finetune import (
    TunedSenseVoiceEvidence,
    _frontend,
    _PhoneticSense,
    configuration,
    select_trainable,
)


def test_sense_phonetic_architecture_keeps_exactly50_layers_and_freezes_first44():
    with torch.device("meta"):
        model = _PhoneticSense(16)
    assert len(model.encoder.encoders0) + len(model.encoder.encoders) == 50
    assert not hasattr(model.encoder, "tp_encoders")
    assert not hasattr(model.encoder, "tp_norm")
    heads = select_trainable(model, tail=False)
    assert len(heads) == 6
    tail = select_trainable(model, tail=True)
    assert {
        int(name.split(".")[2]) for name in tail if name.startswith("encoder.encoders.")
    } == set(range(43, 49))
    assert not any(name.startswith("encoder.encoders0.") for name in tail)
    assert not any(parameter.requires_grad for parameter in model.encoder.encoders[42].parameters())
    assert all(parameter.requires_grad for parameter in model.encoder.encoders[43].parameters())
    assert not model.embed.weight.requires_grad
    assert len(tail) > len(heads)
    assert sum(parameter.numel() for parameter in model.parameters()) < 350_000_000


def test_source_frontend_short_word_and_repeated_composition_have_legal_ctc_duration():
    with torch.device("meta"):
        model = _PhoneticSense(16)
    model.cmvn = torch.stack((torch.zeros(560), torch.ones(560)))
    samples = np.random.default_rng(18).normal(0, 0.1, 2400).astype(np.float32)
    short = _frontend(model, samples)
    repeated = _frontend(model, np.r_[samples, np.zeros(2880, dtype=np.float32), samples])
    assert short.shape == (3, 560)
    assert len(repeated) >= 3
    assert torch.isfinite(short).all() and torch.isfinite(repeated).all()
    with pytest.raises(ValueError, match="FINITE_MONO"):
        _frontend(model, np.zeros(399, dtype=np.float32))


def test_fixed_protocol_distinguishes_random_phonetic_heads_from_source_character_ctc():
    config = configuration()
    assert config["warmupEpochs"] == 2
    assert config["fineTuneEpochs"] == 10
    assert config["trainableEncoderLayers"] == 6
    assert config["dither"] == 0
    assert config["finalTestUsedForModelSelection"] is False
    assert json.loads(json.dumps(config)) == config


def test_opt_in_actual_cpu_derivative_never_loads_original_torch_checkpoint(monkeypatch):
    root = os.environ.get("PRETRAINED_MODELS")
    directory = Path(root or "/missing") / "sensevoice-finetuned-v1"
    if not root or not (directory / "tuned.json").is_file():
        pytest.skip("Explicit local derivative models required")

    def forbidden(*_, **__):
        raise AssertionError("Original torch checkpoint access forbidden")

    monkeypatch.setattr(torch, "load", forbidden)
    model = TunedSenseVoiceEvidence(directory, device="cpu", threads=2)
    samples = np.random.default_rng(3182026).normal(0, 0.1, 3200).astype(np.float32)
    result = model.evidence(samples)
    assert result["frames"].shape == (3, 512)
    assert set(result["native"]) == {"initial", "final", "tone"}
    assert all(np.isfinite(value).all() for value in result["native"].values())
    assert not (directory / "model.pt").exists()
    assert all(parameter.device.type == "cpu" for parameter in model.model.parameters())
