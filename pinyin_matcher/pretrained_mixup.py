"""Feature-space regularization; never claims additional speech or expert labels."""

import json

import torch
from torch.nn import functional as F

from pinyin_matcher.catalog import ROOT

CONFIG = ROOT / "content/pronunciation-pretrained-mixup.json"


def configuration():
    config = json.loads(CONFIG.read_text())
    if config["betaAlpha"] != 0.4 or config["lossWeight"] != 0.5 or config["finalTestUsed"]:
        raise ValueError("MIXUP_PROTOCOL_CHANGED")
    return config


def mixup_loss(head, acoustic, pitch, labels, annotations, rng):
    valid = (annotations == 1).all(1) & (labels >= 0).all(1)
    x, p, y = acoustic[valid], pitch[valid], labels[valid]
    if len(y) < 2:
        return acoustic.sum() * 0
    config = configuration()
    coefficient = float(rng.beta(config["betaAlpha"], config["betaAlpha"]))
    permutation = torch.tensor(rng.permutation(len(y)), device=y.device)
    output = head(
        coefficient * x + (1 - coefficient) * x[permutation],
        coefficient * p + (1 - coefficient) * p[permutation],
    )
    return (
        sum(
            coefficient * F.cross_entropy(logits, y[:, i])
            + (1 - coefficient) * F.cross_entropy(logits, y[permutation, i])
            for i, logits in enumerate(output)
        )
        * config["lossWeight"]
    )
