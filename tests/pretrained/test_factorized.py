import numpy as np
import pytest
import torch

from pinyin_matcher.pretrained_factorized import FactorizedHeads, factorized_loss


def test_original_cache_remains_valid_and_unsupported_derivatives_fail(tmp_path):
    import json

    from pinyin_matcher.catalog import fingerprint
    from pinyin_matcher.pretrained_factorized import acoustic_derivative

    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"model": "original"}))
    metadata = {"cacheIdentitySha256": fingerprint(identity)}
    assert acoustic_derivative(tmp_path, metadata) is None
    identity.write_text(json.dumps({"derivative": {"architecture": "sensevoice-50-ctc-v1"}}))
    with pytest.raises(ValueError, match="CACHE_IDENTITY_CHANGED"):
        acoustic_derivative(tmp_path, metadata)
    metadata["cacheIdentitySha256"] = fingerprint(identity)
    with pytest.raises(ValueError, match="ARCHITECTURE_UNSUPPORTED"):
        acoustic_derivative(tmp_path, metadata)


def test_native70_cache_binds_parent_metadata_and_actual_weights(tmp_path):
    import json

    from pinyin_matcher.catalog import fingerprint
    from pinyin_matcher.pretrained_factorized import acoustic_derivative
    from pinyin_matcher.pretrained_sensevoice import FILES, REVISION

    source = tmp_path / "source"
    source.mkdir()
    weight = source / "tuned.safetensors"
    weight.write_bytes(b"a native70 test checkpoint")
    parent = {
        "architecture": "sensevoice-70-native-sequence-v1",
        "sourceRevision": REVISION,
        "parentWeightSha256": FILES["model.pt"],
        "sourceWeightsSha256": FILES["model.pt"],
        "files": {"tuned.safetensors": {"sha256": fingerprint(weight)}},
    }
    metadata_path = source / "tuned.json"
    metadata_path.write_text(json.dumps(parent))
    derivative = {
        "architecture": parent["architecture"],
        "sourceRevision": REVISION,
        "parentWeightSha256": FILES["model.pt"],
        "metadataSha256": fingerprint(metadata_path),
        "weightSha256": fingerprint(weight),
    }
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"derivative": derivative}))
    metadata = {"cacheIdentitySha256": fingerprint(identity), "modelDirectory": str(source)}
    assert acoustic_derivative(tmp_path, metadata) == derivative
    weight.write_bytes(b"different checkpoint")
    with pytest.raises(ValueError, match="RESOURCE_CHANGED"):
        acoustic_derivative(tmp_path, metadata)
    metadata_path.write_text("changed parent identity")
    with pytest.raises(ValueError, match="METADATA_CHANGED"):
        acoustic_derivative(tmp_path, metadata)


def test_error_and_ambiguous_components_do_not_invent_identity_labels():
    identities = [torch.zeros(3, 4, requires_grad=True) for _ in range(3)]
    validities = [torch.zeros(3, 4, requires_grad=True) for _ in range(3)]
    labels = torch.tensor([[1, 1, 1], [2, 2, 2], [0, 0, 0]])
    annotations = torch.tensor([[1, 1, 1], [0, 0, 0], [-1, -1, -1]])
    loss, _, _ = factorized_loss(identities, validities, labels, annotations)
    loss.backward()
    for identity, validity in zip(identities, validities, strict=True):
        assert identity.grad[0, 1] < 0
        assert identity.grad[1:].abs().sum() == 0
        assert validity.grad[0, 1] < 0
        assert (validity.grad[0, [0, 2, 3]] > 0).all()
        assert validity.grad[1, 2] > 0
        assert validity.grad[1, [0, 1, 3]].abs().sum() == 0
        assert validity.grad[2].abs().sum() == 0


def test_other_class_negative_loss_is_normalized_per_audio_root():
    values = []
    for count in (2, 20):
        identities = [torch.zeros(2, count) for _ in range(3)]
        validities = [torch.zeros(2, count) for _ in range(3)]
        _, _, validity_loss = factorized_loss(
            identities,
            validities,
            torch.zeros((2, 3), dtype=torch.long),
            torch.ones((2, 3), dtype=torch.long),
        )
        values.append(validity_loss)
    torch.testing.assert_close(values[0], values[1])
    torch.testing.assert_close(values[0], torch.tensor(3 * np.log(2), dtype=torch.float32))


def test_validity_objective_cannot_change_identity_parameters():
    head = FactorizedHeads(10, [3, 4, 5], hidden=16, dropout=0)
    acoustic, pitch = torch.randn(2, 10), torch.randn(2, 68)
    identities, validities = head.separate(acoustic, pitch)
    _, _, loss = factorized_loss(
        identities,
        validities,
        torch.zeros((2, 3), dtype=torch.long),
        torch.ones((2, 3), dtype=torch.long),
    )
    loss.backward()
    assert all(p.grad is None for p in head.identity.parameters())
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in head.validity.parameters())


def test_exported_logits_are_full_class_normalized_products_and_match_onnx(tmp_path):
    import onnxruntime as ort

    torch.manual_seed(19)
    head = FactorizedHeads(10, [3, 4, 5], hidden=16, dropout=0.2).eval()
    acoustic, pitch = torch.randn(3, 10), torch.randn(3, 68)
    with torch.inference_mode():
        identities, validities = head.separate(acoustic, pitch)
        outputs = head(acoustic, pitch)
        for identity, validity, output in zip(identities, validities, outputs, strict=True):
            product = identity.softmax(-1) * validity.sigmoid()
            torch.testing.assert_close(output.softmax(-1), product / product.sum(-1, keepdim=True))
    path = tmp_path / "heads.onnx"
    torch.onnx.export(
        head,
        (acoustic, pitch),
        str(path),
        input_names=["acoustic", "pitch"],
        output_names=["initial", "final", "tone"],
        dynamic_axes={k: {0: "batch"} for k in ("acoustic", "pitch", "initial", "final", "tone")},
        opset_version=17,
        dynamo=False,
    )
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    for count in (1, 3):
        actual = session.run(
            None, {"acoustic": acoustic[:count].numpy(), "pitch": pitch[:count].numpy()}
        )
        with torch.inference_mode():
            expected = head(acoustic[:count], pitch[:count])
        for a, b in zip(actual, expected, strict=True):
            np.testing.assert_allclose(a, b.numpy(), rtol=1e-5, atol=1e-6)
