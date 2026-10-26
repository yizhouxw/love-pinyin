"""V3 adapter regressions; synthetic tensors prove contracts, not speech quality."""

import threading

import numpy as np
import pytest

from pinyin_matcher.catalog import load_catalog, targets_by_id
from pinyin_matcher.inference import PinyinMatcher
from pinyin_matcher.package import bundle_path


def matcher_with_stub_heads():
    matcher = object.__new__(PinyinMatcher)
    matcher.catalog = load_catalog()
    matcher.targets = targets_by_id(matcher.catalog)
    matcher.lock = threading.Lock()
    matcher.problem = ""
    matcher.metadata = {
        "decisionVersion": 3,
        "acousticInput": "mel-only",
        "coveredTargetIds": matcher.catalog["pilotIds"],
        "onsets": ["<unknown>", "m", "sh"],
        "rimes": ["<unknown>", "a", "i-retroflex"],
        "thresholds": {
            "minimumContentMargin": 0.5,
            "maximumFreeCtcAdvantage": 0.25,
            "minimumToneProbability": 0.5,
        },
    }
    return matcher


def test_raw_pitch_gets_waveform_and_acoustic_does_not_get_pitch_channels():
    matcher = matcher_with_stub_heads()
    array = np.ones((40, 68), dtype=np.float32)
    samples = np.arange(8000, dtype=np.float32) / 16000

    class Acoustic:
        def run(self, outputs, inputs, **kwargs):
            assert np.all(inputs["acoustic"][0, :, 64:] == 0)
            assert np.all(inputs["acoustic"][0, :, :64] == 1)
            phones = np.full((1, 40, len(matcher.catalog["tokens"])), -10.0)
            phones[:, :20, matcher.catalog["tokens"].index("I_m")] = 10
            phones[:, 20:, matcher.catalog["tokens"].index("F_a")] = 10
            return phones, np.array([[0, 9, 0]]), np.array([[0, 9, 0]]), np.zeros((1, 6))

    class Tracker:
        def contour(self, received, **kwargs):
            assert received is samples
            return np.ones((32, 4), dtype=np.float32), {"voicedFrames": 30}

    class Tone:
        def run(self, outputs, inputs, **kwargs):
            assert inputs["contour"].shape == (1, 32, 4)
            return [np.array([[-30, -8, -8, -8, 8, -30]])]

    matcher.session, matcher.pitch_tracker, matcher.pitch_session = Acoustic(), Tracker(), Tone()
    result = matcher._branch_evidence(array, samples, "pm-ma1")
    assert result["predictedPhones"] == ["I_m", "F_a"]
    assert result["predictedTone"] == 4
    assert result["toneProbability"] > 0.99
    assert result["pitchReliable"] is True
    assert np.all(array == 1)  # no caller input mutation


def test_v3_does_not_reject_from_the_retired_yin_voiced_count(monkeypatch):
    matcher = matcher_with_stub_heads()
    matcher.session = object()
    monkeypatch.setattr("pinyin_matcher.inference.decode_wav", lambda wav: np.zeros(8000))
    monkeypatch.setattr(
        "pinyin_matcher.inference.features",
        lambda samples: (np.zeros((40, 68)), {"voicedFrames": 0}),
    )
    matcher._branch_evidence = lambda *args, **kwargs: {
        "targetPhones": ["I_m", "F_a"],
        "targetTone": 1,
        "predictedPhones": ["I_m", "F_a"],
        "predictedTone": 1,
        "pitchReliable": True,
        "toneProbability": 0.99,
        "contentMargin": 9.0,
        "freeCtcAdvantage": 0.0,
    }
    result = matcher.match("pm-ma1", b"stub", include_evidence=True)
    assert result["status"] == "matched"
    assert result["toneAssessed"] is False
    assert result["branchEvidence"]["pitchReliable"] is True


@pytest.mark.parametrize(
    "name", ["../payload.bin", "x/../../payload.bin", "/tmp/payload.bin", ".", ".."]
)
def test_bundle_copy_cannot_escape_to_an_unrelated_file(tmp_path, name):
    with pytest.raises(ValueError, match="BUNDLE_"):
        bundle_path(tmp_path / "bundle", name)


def test_bundle_copy_rejects_an_outside_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"must not be copied")
    directory = tmp_path / "bundle"
    directory.mkdir()
    (directory / "weights.onnx").symlink_to(outside)
    with pytest.raises(ValueError, match="BUNDLE_PATH_ESCAPE"):
        bundle_path(directory, "weights.onnx")
