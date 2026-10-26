"""Derived weights must never share the original encoder's cache identity."""

import json

import pytest

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import cache_identity


def test_derivative_cache_identity_binds_weights_and_training_metadata(tmp_path):
    original = cache_identity("hanziflow")
    weights = tmp_path / "tuned.safetensors"
    weights.write_bytes(b"test-only-derived-weight-identity")
    metadata = {
        "parentWeightSha256": "parent-fingerprint",
        "sourceRevision": "fixed-revision",
        "files": {"tuned.safetensors": {"sha256": fingerprint(weights)}},
    }
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    derived = cache_identity("hanziflow", tmp_path)
    assert derived != original
    assert derived["derivative"]["weightSha256"] == fingerprint(weights)

    metadata["selectedEpoch"] = 3
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    assert cache_identity("hanziflow", tmp_path) != derived
    weights.write_bytes(b"changed-model-must-not-reuse-cached-predictions")
    with pytest.raises(ValueError, match="DERIVATIVE_WEIGHT_DIGEST_MISMATCH"):
        cache_identity("hanziflow", tmp_path)
