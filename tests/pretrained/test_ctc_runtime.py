"""Direct CTC boundary contracts; these fixtures are not quality evidence."""

import json

import numpy as np
import pytest

from pinyin_matcher.pretrained_ctc_runtime import (
    NativeCTCMatcher,
    bundle,
    calibrate,
    load_encoder,
    native_decision,
)
from pinyin_matcher.pretrained_evaluate import compare_targets
from pinyin_matcher.pretrained_features import configuration
from pinyin_matcher.pretrained_native import native_rime_aliases


def test_unknown_blank_or_multiple_protection_cannot_be_bypassed_by_threshold():
    probabilities = [np.array([1.0, 0.0])] * 3
    threshold = {"probability": 0.35, "margin": 0}
    assert native_decision(probabilities, {}, [0, 0, 0], threshold) == "matched"
    assert (
        native_decision(probabilities, {"forceUncertain": True}, [0, 0, 0], threshold)
        == "uncertain"
    )
    assert (
        native_decision(probabilities, {"unavailable": True}, [0, 0, 0], threshold) == "uncertain"
    )


def test_force_uncertain_protects_all_wrong_target_comparisons():
    class Matcher:
        targets = {
            "pm-ma1": {"id": "pm-ma1", "onset": "m", "rime": "a", "tone": 1},
            "pm-ba1": {"id": "pm-ba1", "onset": "b", "rime": "a", "tone": 1},
        }
        metadata = {
            "vocabulary": {"onset": ["m", "b"], "rime": ["a"], "tone": ["1"]},
            "thresholds": {"probability": 0.35, "margin": 0},
        }

    row = {
        "id": "root",
        "source": "fixture",
        "speakerId": "speaker",
        "parentSha256": "parent",
        "split": "calibration",
        "onset": "b",
        "rime": "a",
        "tone": 1,
        "syllable": "ba1",
        "labelProvenance": "Algorithm contract only",
    }
    records = compare_targets(
        row,
        Matcher(),
        {
            "status": "uncertain",
            "internalEvidence": {
                "onset": {"probabilities": [1.0, 0.0]},
                "rime": {"probabilities": [1.0]},
                "tone": {"probabilities": [1.0]},
                "forceUncertain": True,
            },
        },
    )
    assert len(records) == 2
    assert all(record["status"] == "uncertain" for record in records)


def test_calibration_rejects_reserved_test_before_cache_or_audio(tmp_path):
    manifest = tmp_path / "test-manifest.json"
    manifest.write_text(json.dumps({"frozenTestIncluded": True, "items": [{"split": "test"}]}))
    with pytest.raises(ValueError, match="CANNOT_OPEN_FROZEN_TEST"):
        calibrate(
            "hanziflow",
            manifest,
            tmp_path / "missing-cache",
            tmp_path / "missing-model",
            tmp_path / "output",
        )


@pytest.mark.parametrize(
    ("architecture", "expected_error"),
    [
        ("sensevoice-50-ctc-v1", "CTC_TRAIN_CALIBRATION_INVENTORY_REQUIRED"),
        ("sensevoice-70-native-sequence-v1", "CTC_TRAIN_CALIBRATION_INVENTORY_REQUIRED"),
        (None, "ORIGINAL_SENSEVOICE_HAS_NO_PHONETIC_HEAD"),
        ("sensevoice-70-native-sequence-int8-v1", "ORIGINAL_SENSEVOICE_HAS_NO_PHONETIC_HEAD"),
    ],
)
def test_calibration_accepts_only_declared_unquantized_phonetic_derivatives(
    tmp_path, monkeypatch, architecture, expected_error
):
    import pinyin_matcher.pretrained_ctc_runtime as runtime
    import pinyin_matcher.pretrained_experiment as experiment
    from pinyin_matcher.catalog import fingerprint

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": []}))
    cache = tmp_path / "cache"
    cache.mkdir()
    identity = {"derivative": {"architecture": architecture}}
    (cache / "identity.json").write_text(json.dumps(identity))
    (cache / "cache.json").write_text(
        json.dumps({"manifestSha256": fingerprint(manifest), "testIncluded": False})
    )
    monkeypatch.setattr(experiment, "cache_identity", lambda *args: identity)
    monkeypatch.setattr(experiment, "read_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(runtime, "verify_source", lambda *args: None)
    with pytest.raises(ValueError, match=expected_error):
        calibrate("sensevoice", manifest, cache, tmp_path / "model", tmp_path / "output")


def test_native_ctc_bad_package_never_loads_encoder(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_ctc_runtime as runtime

    def forbidden(*args, **kwargs):
        pytest.fail("Digest-invalid package must fail before model allocation")

    monkeypatch.setattr(runtime, "load_encoder", forbidden)
    (tmp_path / "graph").write_bytes(b"changed graph")
    metadata = {
        "schemaVersion": 1,
        "headKind": "native-ctc",
        "model": "hanziflow",
        "encoderBackend": "torch",
        "configuration": configuration(),
        "nativeRimeAliases": native_rime_aliases("hanziflow"),
        "packageFiles": {"graph": {"sha256": "0" * 64}},
    }
    (tmp_path / "model.json").write_text(json.dumps(metadata))
    model = NativeCTCMatcher(tmp_path)
    assert model.info()["status"] == "unavailable"
    assert model.problem == "BUNDLE_RESOURCE_DIGEST_MISMATCH"


def test_int8_encoder_routes_explicitly_without_loading_fp32_parent(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []
    sentinel = object()

    def adapter(directory, *, threads):
        calls.append((directory, threads))
        return sentinel

    monkeypatch.setitem(
        sys.modules,
        "pinyin_matcher.pretrained_sensevoice_export",
        SimpleNamespace(OnnxSenseVoiceEvidence=adapter),
    )
    (tmp_path / "tuned.json").write_text(json.dumps({"architecture": "sensevoice-50-ctc-int8-v1"}))
    assert load_encoder("sensevoice", tmp_path) is sentinel
    assert calls == [(tmp_path, 2)]


def test_quantized_bundle_rejects_another_finetuned_parent_before_copy(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_experiment as experiment
    from pinyin_matcher.catalog import fingerprint

    original, calibration, quantized = [tmp_path / name for name in ("fp32", "cal", "int8")]
    for directory in (original, calibration, quantized):
        directory.mkdir()
    (original / "tuned.json").write_text(json.dumps({"files": {}, "parentWeightSha256": "source"}))
    derivative = {"metadataSha256": fingerprint(original / "tuned.json")}
    monkeypatch.setattr(
        experiment,
        "cache_identity",
        lambda *args: {"derivative": derivative, "model": {"revision": "pinned"}},
    )
    (calibration / "model.json").write_text(
        json.dumps(
            {
                "model": "sensevoice",
                "headKind": "native-ctc",
                "testUsed": False,
                "acousticDerivative": derivative,
            }
        )
    )
    (quantized / "parent-tuned.json").write_text("different original weights")
    (quantized / "tuned.json").write_text(json.dumps({"architecture": "sensevoice-50-ctc-int8-v1"}))
    with pytest.raises(ValueError, match="QUANTIZED_PARENT_IDENTITY_MISMATCH"):
        bundle(calibration, original, tmp_path / "package", quantized_model=quantized)
    assert not (tmp_path / "package").exists()
