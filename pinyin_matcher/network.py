"""Small target-independent temporal network. Imported only by offline training."""

import torch
from torch import nn


class TemporalBlock(nn.Module):
    def __init__(self, hidden: int, expansion: int, dilation: int):
        super().__init__()
        width = hidden * expansion
        self.layers = nn.Sequential(
            nn.Conv1d(hidden, width, 1),
            nn.BatchNorm1d(width),
            nn.SiLU(),
            nn.Conv1d(width, width, 5, padding=dilation * 2, dilation=dilation, groups=width),
            nn.BatchNorm1d(width),
            nn.SiLU(),
            nn.Conv1d(width, hidden, 1),
            nn.BatchNorm1d(hidden),
            nn.Dropout(0.1),
        )
        self.activation = nn.SiLU()

    def forward(self, value):
        return self.activation(value + self.layers(value))


class AcousticMatcher(nn.Module):
    def __init__(self, tokens: int, onsets: int, rimes: int, hidden=192, blocks=10, expansion=3):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(68, hidden, 5, padding=2),
            nn.BatchNorm1d(hidden),
            nn.SiLU(),
            *[TemporalBlock(hidden, expansion, 2 ** (index % 4)) for index in range(blocks)],
        )
        self.phone = nn.Conv1d(hidden, tokens, 1)
        self.onset = nn.Linear(hidden, onsets)
        self.rime = nn.Linear(hidden, rimes)
        self.tone = nn.Sequential(nn.Linear(hidden + 12, 128), nn.SiLU(), nn.Linear(128, 6))

    def forward(self, acoustic, lengths):
        encoded = self.encoder(acoustic.transpose(1, 2))
        positions = torch.arange(acoustic.shape[1], device=acoustic.device)[None, :]
        mask = (positions < lengths[:, None]).to(acoustic.dtype)
        pooled = (encoded * mask[:, None, :]).sum(2) / lengths[:, None].clamp(min=1)
        pitch = acoustic[:, :, 64:]
        # Three temporal bins retain rising/falling/dipping contour information.
        summaries = []
        for part in range(3):
            region = (
                (positions * 3 >= lengths[:, None] * part)
                & (positions * 3 < lengths[:, None] * (part + 1))
            ).to(acoustic.dtype)
            summaries.append(
                (pitch * region[:, :, None]).sum(1) / region.sum(1)[:, None].clamp(min=1)
            )
        tone = self.tone(torch.cat([pooled, *summaries], dim=1))
        return self.phone(encoded).transpose(1, 2), self.onset(pooled), self.rime(pooled), tone
