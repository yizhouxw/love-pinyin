"""Padding-invariant phonetic encoder; imported only by offline training."""

import torch
from torch import nn


class FrameNorm(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.norm = nn.LayerNorm(channels)

    def forward(self, value):
        return self.norm(value.transpose(1, 2)).transpose(1, 2)


class MaskedBlock(nn.Module):
    def __init__(self, hidden, expansion, dilation):
        super().__init__()
        width = hidden * expansion
        self.expand = nn.Sequential(nn.Conv1d(hidden, width, 1), FrameNorm(width), nn.SiLU())
        self.temporal = nn.Sequential(
            nn.Conv1d(width, width, 5, padding=2 * dilation, dilation=dilation, groups=width),
            FrameNorm(width),
            nn.SiLU(),
        )
        self.project = nn.Sequential(
            nn.Conv1d(width, hidden, 1), FrameNorm(hidden), nn.Dropout(0.1)
        )
        self.activation = nn.SiLU()

    def forward(self, value, mask):
        expanded = self.expand(value) * mask
        temporal = self.temporal(expanded) * mask
        return self.activation(value + self.project(temporal)) * mask


class AcousticMatcherV2(nn.Module):
    def __init__(self, tokens, onsets, rimes, hidden=192, blocks=10, expansion=3):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv1d(68, hidden, 5, padding=2), FrameNorm(hidden), nn.SiLU())
        self.blocks = nn.ModuleList(
            [MaskedBlock(hidden, expansion, 2 ** (i % 4)) for i in range(blocks)]
        )
        self.phone = nn.Conv1d(hidden, tokens, 1)
        self.onset = nn.Linear(hidden * 2, onsets)
        self.rime = nn.Linear(hidden * 2, rimes)
        self.tone = nn.Sequential(nn.Linear(hidden, 128), nn.SiLU(), nn.Linear(128, 6))

    def forward(self, acoustic, lengths):
        positions = torch.arange(acoustic.shape[1], device=acoustic.device)[None, :]
        mask = (positions < lengths[:, None]).to(acoustic.dtype)[:, None, :]
        # All biases and normalization outputs at padded frames are removed
        # before another temporal kernel can see them.
        encoded = self.stem(acoustic.transpose(1, 2) * mask) * mask
        for block in self.blocks:
            encoded = block(encoded, mask)
        pooled = encoded.sum(2) / lengths[:, None].clamp(min=1)
        beginning = ((positions * 5 < lengths[:, None] * 2) & (positions < lengths[:, None])).to(
            acoustic.dtype
        )
        ending = ((positions * 5 >= lengths[:, None] * 2) & (positions < lengths[:, None])).to(
            acoustic.dtype
        )
        onset_pool = (encoded * beginning[:, None, :]).sum(2) / beginning.sum(1)[:, None].clamp(
            min=1
        )
        rime_pool = (encoded * ending[:, None, :]).sum(2) / ending.sum(1)[:, None].clamp(min=1)
        return (
            self.phone(encoded).transpose(1, 2),
            self.onset(torch.cat([pooled, onset_pool], 1)),
            self.rime(torch.cat([pooled, rime_pool], 1)),
            self.tone(pooled),
        )
