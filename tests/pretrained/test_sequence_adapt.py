"""Signed-event adaptation mechanics; these are not pronunciation-quality claims."""

import json

import numpy as np
import pytest
import torch

from pinyin_matcher import pretrained_sequence_adapt as adapt
from pinyin_matcher.catalog import fingerprint


def test_correct_event_and_error_event_have_opposite_gradients_unknown_is_zero():
    outputs = [torch.zeros(3, 1, 4, requires_grad=True) for _ in range(3)]
    annotations = torch.tensor([[1, -1, -1], [0, -1, -1], [-1, -1, -1]])
    loss = adapt.balanced_expert_loss(
        outputs, torch.tensor([1, 1, 1]), [[[2], [2], [2]]] * 3, annotations
    )
    # Single frame exact event has probability1/4; the two present groups are equal.
    assert float(loss.detach()) == pytest.approx((-np.log(0.25) - np.log(0.75)) / 2)
    loss.backward()
    assert outputs[0].grad[0, 0, 2] < 0
    assert outputs[0].grad[1, 0, 2] > 0
    assert torch.count_nonzero(outputs[0].grad[2]) == 0
    assert all(torch.count_nonzero(output.grad) == 0 for output in outputs[1:])


def test_all_unknown_ompal_keeps_zero_gradient_without_rescaling_native_domain():
    outputs = [torch.randn(2, 3, 5, requires_grad=True) for _ in range(3)]
    loss = adapt.balanced_expert_loss(
        outputs, torch.tensor([3, 3]), [[[2], [2], [2]]] * 2, torch.full((2, 3), -1)
    )
    native_loss = torch.tensor(4.0, requires_grad=True)
    total = 0.5 * native_loss + 0.5 * loss
    total.backward()
    assert float(total.detach()) == 2
    assert native_loss.grad == 0.5
    assert all(torch.count_nonzero(output.grad) == 0 for output in outputs)


def test_present_group_coefficients_match_component_balancing():
    annotations = np.asarray([[1, 1, -1], [1, 0, -1], [1, -1, -1]])
    counts, coefficients = adapt.group_coefficients(annotations)
    assert counts.tolist() == [[0, 3], [1, 1], [0, 0]]
    np.testing.assert_array_equal(coefficients, [[0, 0.5], [0.25, 0.25], [0, 0]])
    assert adapt.group_coefficients(np.full((3, 3), -1))[1].sum() == 0


def test_paired_sampling_visits_each_ompal_root_once_and_accounts_for_native_cycles():
    pairs = list(adapt.paired_batches(17, [5, 3, 9, 4, 2], batch_size=3, seed=8))
    assert pairs == list(adapt.paired_batches(17, [5, 3, 9, 4, 2], batch_size=3, seed=8))
    assert sorted(i for ompal, _ in pairs for i in ompal) == list(range(17))
    assert len(pairs) == 6
    assert len([i for _, native in pairs for i in native]) == 15
    assert sorted(i for _, native in pairs for i in native) == sorted(list(range(5)) * 3)
    for _, native in pairs:
        assert len(set(native)) == len(native)


def test_initializer_or_manifest_tampering_fails_before_model_loading(tmp_path, monkeypatch):
    initializer = tmp_path / "initializer"
    initializer.mkdir()
    native_manifest, ompal_manifest = tmp_path / "native.json", tmp_path / "ompal.json"
    native_config, ompal_config = tmp_path / "native-config.json", tmp_path / "ompal-config.json"
    paths = {
        "initializerMetadataSha256": initializer / "tuned.json",
        "initializerWeightsSha256": initializer / "tuned.safetensors",
        "nativeManifestSha256": native_manifest,
        "ompalManifestSha256": ompal_manifest,
        "nativeDataConfigurationSha256": native_config,
        "ompalDataConfigurationSha256": ompal_config,
    }
    for key, path in paths.items():
        path.write_text(json.dumps({"identity": key}))
    config = {key: fingerprint(path) for key, path in paths.items()}
    monkeypatch.setattr(adapt, "NATIVE_DATA_CONFIG", native_config)
    monkeypatch.setattr(adapt, "OMPAL_DATA_CONFIG", ompal_config)
    adapt.validate_inputs(config, initializer, native_manifest, ompal_manifest)
    ompal_manifest.write_text("changed annotations")
    with pytest.raises(ValueError, match="PINNED_INPUT_CHANGED"):
        adapt.validate_inputs(config, initializer, native_manifest, ompal_manifest)


def test_native_feature_swapped_between_ids_is_rejected(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    wrong_features = tmp_path / "second.npz"
    wrong_features.write_bytes(b"valid but from another utterance")
    metadata = {
        "configurationSha256": fingerprint(config),
        "items": [
            {
                "id": "first",
                "file": str(wrong_features),
                "sha256": fingerprint(wrong_features),
                "audio": {},
            }
        ],
    }
    (tmp_path / "cache.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(adapt, "NATIVE_CONFIG", config)
    monkeypatch.setattr(adapt, "_verify_cache_identity", lambda *args: None)
    monkeypatch.setattr(adapt, "_native_manifest", lambda *args: [{"id": "first"}])
    monkeypatch.setattr(adapt, "validate_cached_labels", lambda *args: None)
    with pytest.raises(ValueError, match="NATIVE_PREFIX_CHANGED"):
        adapt._native_items(tmp_path, tmp_path / "manifest.json", {})


def test_initializer_binds_both_cache_metadata_before_feature_or_model_access(tmp_path):
    native, ompal = tmp_path / "native", tmp_path / "ompal"
    for path in (native, ompal):
        path.mkdir()
        (path / "cache.json").write_text(json.dumps({"domain": path.name}))
    parent = {
        "nativeCacheMetadataSha256": fingerprint(native / "cache.json"),
        "calibrationPrefixSha256": fingerprint(ompal / "cache.json"),
    }
    adapt.validate_initializer_caches(parent, native, ompal)
    (native / "cache.json").write_text("{}")
    with pytest.raises(ValueError, match="INITIALIZER_CACHE_CHANGED"):
        adapt.validate_initializer_caches(parent, native, ompal)


def test_explicit_rebuilt_config_cannot_change_fixed_training_budget(tmp_path):
    config = json.loads(adapt.CONFIG.read_text())
    config["initializerMetadataSha256"] = "new-explicit-input"
    path = tmp_path / "independent-config.json"
    path.write_text(json.dumps(config))
    assert adapt.configuration(path)["initializerMetadataSha256"] == "new-explicit-input"
    config["epochs"] = 9
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="PROTOCOL_CHANGED"):
        adapt.configuration(path)
