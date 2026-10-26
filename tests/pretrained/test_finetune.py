"""Fine-tuning mathematical/provenance contracts, without quality claims."""

import itertools
import random
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from pinyin_matcher.pretrained_finetune import (
    _training_mode,
    epoch_items,
    fine_tune_configuration,
    freeze_for_finetuning,
    signed_ctc_events,
    train,
)


def collapse(path):
    return [
        value
        for index, value in enumerate(path)
        if value and (index == 0 or value != path[index - 1])
    ]


@pytest.mark.parametrize("labels", [[1], [1, 2], [1, 1]])
def test_signed_ctc_exact_event_matches_full_native_path_enumeration(labels):
    values = torch.tensor(
        [[[0.2, 0.8, -0.1], [0.7, 0.4, 0.1], [0.1, 0.6, 0.9]]],
        dtype=torch.float64,
        requires_grad=True,
    )
    probabilities = values[0].detach().softmax(-1).numpy()
    event = sum(
        np.prod([probabilities[index, value] for index, value in enumerate(path)])
        for path in itertools.product(range(3), repeat=3)
        if collapse(path) == labels
    )
    losses, nlls = signed_ctc_events(
        [values, values, values],
        torch.tensor([3]),
        [[labels, labels, labels]],
        torch.tensor([[1, 0, -1]]),
    )
    np.testing.assert_allclose(nlls.detach().numpy(), np.full((1, 3), -np.log(event)))
    assert float(losses[0, 0].detach()) == pytest.approx(-np.log(event))
    assert float(losses[0, 1].detach()) == pytest.approx(-np.log1p(-event))
    assert float(losses[0, 2].detach()) == 0
    losses.sum().backward()
    assert torch.isfinite(values.grad).all()


def test_correct_and_error_ctc_events_drive_opposite_expected_phone_gradients():
    def gradient(annotation):
        value = torch.tensor([[[0.0, 0.4, -0.2]]], requires_grad=True)
        losses, _ = signed_ctc_events(
            [value, value, value],
            torch.tensor([1]),
            [[[1], [1], [1]]],
            torch.tensor([[annotation, -1, -1]]),
        )
        losses.sum().backward()
        return value.grad[0, 0, 1].item()

    assert gradient(1) < 0
    assert gradient(0) > 0
    assert gradient(-1) == 0


class SmallEncoder(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = torch.nn.Module()
        self.encoder.layers = torch.nn.ModuleList(
            [torch.nn.Sequential(torch.nn.Linear(2, 2), torch.nn.Dropout(0.3)) for _ in range(24)]
        )
        self.frontend = torch.nn.Linear(2, 2)
        self.config = SimpleNamespace(apply_spec_augment=True, layerdrop=0.1)
        self.checkpointing_disabled = False

    def gradient_checkpointing_disable(self):
        self.checkpointing_disabled = True


class SmallHanzi(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = SmallEncoder()
        self.initial_head = torch.nn.Linear(2, 3)
        self.final_head = torch.nn.Linear(2, 3)
        self.tone_head = torch.nn.Linear(2, 3)


def test_only_last_two_layers_and_native_heads_train_frozen_dropout_stays_off():
    model = SmallHanzi()
    trainable = freeze_for_finetuning(model)
    assert len(trainable) == 10
    assert all(
        name.startswith(("encoder.encoder.layers.22.", "encoder.encoder.layers.23."))
        or name.startswith(("initial_head.", "final_head.", "tone_head."))
        for name in trainable
    )
    _training_mode(model)
    assert not model.encoder.frontend.training
    assert not model.encoder.encoder.layers[21].training
    assert model.encoder.encoder.layers[22].training
    assert model.tone_head.training
    assert not model.encoder.config.apply_spec_augment
    assert model.encoder.config.layerdrop == 0
    assert model.encoder.checkpointing_disabled


def test_compositions_use_only_expert_all_correct_roots_and_keep_repeated_ctc_labels():
    natural = [
        {
            "id": str(index),
            "samples": np.ones(2400, dtype=np.float32) * 0.1,
            "targets": [[1], [2], [3]],
            "annotations": [1, 1, 1] if index == 0 else [0, -1, 1],
            "trusted": index == 0,
        }
        for index in range(5)
    ]
    items, count = epoch_items(natural, random.Random(18))
    assert count == 1
    assert len(items) == 6
    assert items[:5] == natural
    assert items[-1]["id"] == "composition:0:0"
    assert items[-1]["targets"] == [[1, 1], [2, 2], [3, 3]]
    assert items[-1]["annotations"] == [1, 1, 1]
    assert len(items[-1]["samples"]) == 4800 + 2880


def test_old_alignment_manifest_cannot_start_training(tmp_path):
    manifest = tmp_path / "old.json"
    manifest.write_text('{"version":"old-wrong-apical-alignment"}')
    with pytest.raises(ValueError, match="REBUILT_MODEL_SPECIFIC_ALIGNMENT"):
        train(tmp_path / "missing-model", manifest, tmp_path / "output", device="cpu")
    assert not (tmp_path / "output").exists()
    config = fine_tune_configuration()
    assert config["maximumEpochs"] == 10
    assert config["batchSize"] == 16
