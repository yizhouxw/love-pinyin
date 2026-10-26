"""Numerical padding regression; it is not pronunciation evidence."""

import numpy as np
import pytest


def test_padding_does_not_change_real_frames_or_classification():
    torch = pytest.importorskip("torch")
    from pinyin_matcher.acoustic_v2 import AcousticMatcherV2

    torch.manual_seed(18)
    model = AcousticMatcherV2(8, 3, 4, hidden=16, blocks=4, expansion=2).eval()
    actual = torch.randn(1, 37, 68)
    padded = torch.cat([actual, torch.randn(1, 90, 68)], dim=1)
    with torch.no_grad():
        first = model(actual, torch.tensor([37]))
        second = model(padded, torch.tensor([37]))
    np.testing.assert_allclose(first[0].numpy(), second[0][:, :37].numpy(), atol=1e-5)
    for a, b in zip(first[1:], second[1:], strict=True):
        np.testing.assert_allclose(a.numpy(), b.numpy(), atol=1e-5)
