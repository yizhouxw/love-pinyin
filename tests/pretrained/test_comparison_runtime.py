"""Comparison runtime contract fixtures are not pronunciation-quality evidence."""

import threading

import numpy as np

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.pretrained_comparison_runtime import ComparisonMatcher


def _matcher(monkeypatch, cancel=None):
    matcher = ComparisonMatcher.__new__(ComparisonMatcher)
    matcher.metadata = {
        "model": "hanziflow",
        "variant": "test-only",
        "thresholds": {"accept": 0.9, "reject": 0.3},
    }
    matcher.targets = {"pm-ma1": {"id": "pm-ma1", "onset": "m", "rime": "a", "tone": 1}}
    matcher.lock = threading.Lock()
    matcher.problem = ""
    matcher.encoder = matcher.session = object()

    class Head:
        def probabilities_for_targets(self, native, targets, *, pitch):
            if cancel is not None:
                cancel.set()
            return np.ones((len(targets), 3), dtype=np.float32)

    matcher.head = Head()
    monkeypatch.setattr(
        "pinyin_matcher.pretrained_comparison_runtime.signal_guard", lambda samples: None
    )
    monkeypatch.setattr(
        "pinyin_matcher.pretrained_comparison_runtime.represent",
        lambda encoder, samples: {
            "pitch": np.zeros(68),
            **{"native_" + key: np.zeros((10, 3)) for key in ("initial", "final", "tone")},
        },
    )
    return matcher


def test_comparison_evidence_and_unknown_target_preserve_status_contract(monkeypatch):
    matcher = _matcher(monkeypatch)
    payload = encode_wav(np.zeros(8000, dtype=np.float32))
    assert matcher.match("unknown", payload)["status"] == "unavailable"
    assert matcher.match("pm-ma1", b"invalid")["status"] == "uncertain"
    result = matcher.match("pm-ma1", payload, evidence=True)
    assert result["status"] == "matched"
    assert result["internalEvidence"]["targetDecisions"] == {"pm-ma1": "matched"}
    assert result["experimental"] is True and result["toneAssessed"] is False


def test_cancel_during_comparison_cannot_return_a_late_match(monkeypatch):
    cancel = threading.Event()
    matcher = _matcher(monkeypatch, cancel)
    result = matcher.match("pm-ma1", encode_wav(np.zeros(8000, dtype=np.float32)), cancel=cancel)
    assert result["status"] == "uncertain" and result["reason"] == "CANCELLED"
    assert not matcher.lock.locked()
