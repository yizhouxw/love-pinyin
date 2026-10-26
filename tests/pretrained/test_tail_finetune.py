"""Prefix/tail arithmetic and gradient boundaries, without pronunciation claims."""

import numpy as np
import pytest
import torch
from torch import nn

from pinyin_matcher.pretrained_factorized import FactorizedHeads, factorized_loss
from pinyin_matcher.pretrained_features import pool_frames
from pinyin_matcher.pretrained_sensevoice import _Encoder, _Layer
from pinyin_matcher.pretrained_tail_finetune import (
    FrozenPrefix,
    TrainableTail,
    pool_valid_frames,
    state_digest,
)


class TinyLayer(nn.Module):
    def __init__(self, inputs=512):
        super().__init__()
        self.project = nn.Linear(inputs, 512, bias=False) if inputs != 512 else nn.Identity()
        self.scale = nn.Parameter(torch.tensor(0.99))

    def forward(self, x, mask):
        return self.project(x) * self.scale * mask.transpose(1, 2)


class TinyEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoders0 = nn.ModuleList([TinyLayer(560)])
        self.encoders = nn.ModuleList([TinyLayer() for _ in range(49)])
        self.tp_encoders = nn.ModuleList([TinyLayer() for _ in range(20)])
        self.after_norm = nn.LayerNorm(512)
        self.tp_norm = nn.LayerNorm(512)

    forward = _Encoder.forward


def test_prefix_tail_matches_seventy_layer_order_and_preserves_prompts():
    torch.manual_seed(3182026)
    source = TinyEncoder().eval()
    prefix, tail = FrozenPrefix(source), TrainableTail(source)
    x, lengths = torch.randn(2, 12, 560), torch.tensor([8, 12])
    expected = source(x, lengths)
    cached = prefix(x, lengths)
    actual = tail(cached, lengths)
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    assert cached.shape == (2, 12, 512)
    assert len(prefix.main) == 50 and len(prefix.task) == 14 and len(tail.layers) == 6
    assert not any(p.requires_grad for p in prefix.parameters())
    assert all(p.requires_grad for p in tail.parameters())


def test_real_sanm_tail_masks_padding_at_attention_and_convolution():
    torch.manual_seed(8)
    source = TinyEncoder()
    source.tp_encoders[-1] = _Layer()
    tail = TrainableTail(source).eval()
    x, lengths = torch.randn(2, 12, 512), torch.tensor([7, 12])
    padded = tail(x, lengths)
    single = tail(x[:1, :7], lengths[:1])
    torch.testing.assert_close(padded[0, :7], single[0], rtol=1e-5, atol=2e-6)
    changed = x.clone()
    changed[0, 7:] = 123
    torch.testing.assert_close(tail(changed, lengths)[0, :7], padded[0, :7])


def test_pooling_excludes_prompts_padding_and_matches_uneven_thirds():
    rng = np.random.default_rng(4)
    x = torch.from_numpy(rng.normal(size=(3, 13, 512)).astype(np.float32))
    lengths = torch.tensor([5, 9, 13])
    actual = pool_valid_frames(x, lengths).numpy()
    for i, length in enumerate(lengths):
        np.testing.assert_allclose(actual[i], pool_frames(x[i, 4:length].numpy()), atol=1e-6)
    changed = x.clone()
    changed[:, :4] = 1000
    changed[0, 5:] = 1000
    changed[1, 9:] = 1000
    torch.testing.assert_close(pool_valid_frames(changed, lengths), torch.from_numpy(actual))
    with pytest.raises(ValueError, match="TAIL_VALID_LENGTH_INVALID"):
        pool_valid_frames(x, torch.tensor([4, 9, 13]))


def test_warmup_and_tail_gradients_cannot_change_frozen_prefix():
    torch.manual_seed(19)
    source = TinyEncoder()
    prefix, tail = FrozenPrefix(source), TrainableTail(source)
    original = state_digest(prefix)
    cached = prefix(torch.randn(2, 10, 560), torch.tensor([8, 10])).detach()
    head = FactorizedHeads(2560, [3, 4, 5], hidden=16, dropout=0)
    labels = torch.tensor([[0, 1, 2], [1, 2, 3]])
    annotations = torch.tensor([[1, 1, 1], [0, -1, 1]])
    tail.requires_grad_(False)
    identity, validity = head.separate(
        pool_valid_frames(tail(cached, torch.tensor([8, 10])), torch.tensor([8, 10])),
        torch.randn(2, 68),
    )
    factorized_loss(identity, validity, labels, annotations)[0].backward()
    assert all(p.grad is None for p in tail.parameters())
    head.zero_grad()
    tail.requires_grad_(True)
    identity, validity = head.separate(
        pool_valid_frames(tail(cached, torch.tensor([8, 10])), torch.tensor([8, 10])),
        torch.randn(2, 68),
    )
    factorized_loss(identity, validity, labels, annotations)[0].backward()
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in tail.parameters())
    assert all(p.grad is None for p in prefix.parameters())
    assert state_digest(prefix) == original
