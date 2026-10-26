"""Offline learnable readouts; every model receives the same optimization budget."""

import torch
from torch import nn


class ComponentHeads(nn.Module):
    def __init__(
        self, dimensions, counts, *, variant, hidden=256, dropout=0.2, pitch_dimensions=68
    ):
        super().__init__()
        self.variant = variant
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
