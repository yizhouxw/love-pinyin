"""Offline learnable readouts; every model receives the same optimization budget."""

import torch
from torch import nn


class TemporalBranch(nn.Module):
    def __init__(self, dimensions, outputs, hidden, dropout, pitch_dimensions=0):
        super().__init__()
        from pinyin_matcher.pretrained_temporal import TEMPORAL_BINS

        self.bins = TEMPORAL_BINS
        self.channels = dimensions // self.bins
        self.pitch_dimensions = pitch_dimensions
        self.norm = nn.LayerNorm(self.channels)
        self.conv = nn.Conv1d(self.channels, hidden // 2, 3, padding=1)
        self.attention = nn.Conv1d(hidden // 2, 1, 1)
        self.classifier = nn.Sequential(
            nn.Linear(hidden + pitch_dimensions, hidden // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, outputs),
        )

    def forward(self, vector):
        frames = vector[:, : self.bins * self.channels].reshape(-1, self.bins, self.channels)
        encoded = torch.nn.functional.gelu(self.conv(self.norm(frames).transpose(1, 2)))
        attention = self.attention(encoded).softmax(-1)
        pooled = torch.cat(((encoded * attention).sum(-1), encoded.mean(-1)), -1)
        if self.pitch_dimensions:
            pooled = torch.cat((pooled, vector[:, -self.pitch_dimensions :]), -1)
        return self.classifier(pooled)


class ComponentHeads(nn.Module):
    def __init__(
        self, dimensions, counts, *, variant, hidden=256, dropout=0.2, pitch_dimensions=68
    ):
        super().__init__()
        self.variant = variant
        if variant == "temporal":
            self.initial = TemporalBranch(dimensions, counts[0], hidden, dropout)
            self.final = TemporalBranch(dimensions, counts[1], hidden, dropout)
            self.tone = TemporalBranch(dimensions, counts[2], hidden, dropout, pitch_dimensions)
            self.acoustic = nn.Identity()
            return
        if variant == "independent":

            def branch(inputs, outputs):
                return nn.Sequential(
                    nn.Linear(inputs, hidden),
                    nn.LayerNorm(hidden),
                    nn.GELU(),
                    nn.Dropout(dropout),
                    nn.Linear(hidden, outputs),
                )

            self.initial = branch(dimensions, counts[0])
            self.final = branch(dimensions, counts[1])
            self.tone = branch(dimensions + pitch_dimensions, counts[2])
            self.acoustic = nn.Identity()
            return
        if variant == "linear":
            self.acoustic = nn.Identity()
            width = dimensions
        elif variant in {"multihead", "tone-specialist"}:
            self.acoustic = nn.Sequential(
                nn.Linear(dimensions, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(dropout)
            )
            width = hidden
        else:
            raise ValueError("UNKNOWN_READOUT_VARIANT")
        self.initial = nn.Linear(width, counts[0])
        self.final = nn.Linear(width, counts[1])
        self.tone = (
            nn.Sequential(
                nn.Linear(width + pitch_dimensions, hidden // 2),
                nn.LayerNorm(hidden // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden // 2, counts[2]),
            )
            if variant == "tone-specialist"
            else nn.Linear(width + pitch_dimensions, counts[2])
        )

    def forward(self, acoustic, pitch):
        encoded = self.acoustic(acoustic)
        return (
            self.initial(encoded),
            self.final(encoded),
            self.tone(torch.cat((encoded, pitch), -1)),
        )
