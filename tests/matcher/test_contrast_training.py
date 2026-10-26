"""Explicit pair negatives must not invent a foreign phone transcription."""

import pytest

torch = pytest.importorskip("torch")

from pinyin_matcher.train_v2 import contrast_loss, validate_combined_splits  # noqa: E402


def test_foreign_pair_loss_only_refutes_named_target_and_has_finite_gradient():
    onsets, rimes = ["m", "sh", "v"], ["a", "i-retroflex", "in"]
    targets = {"pm-shi1": {"onset": "sh", "rime": "i-retroflex"}}
    label = [{"againstTargetIds": ["pm-shi1"]}]
    wrong = torch.tensor([[0.0, 7.0, 0.0]], requires_grad=True)
    wrong_rime = torch.tensor([[0.0, 7.0, 0.0]], requires_grad=True)
    loss = contrast_loss(wrong, wrong_rime, label, targets, onsets, rimes)
    loss.backward()
    assert torch.isfinite(loss)
    assert torch.isfinite(wrong.grad).all()
    assert wrong.grad[0, 1] > 0
    # Sharing the named rime is allowed when the consonant refutes the pair.
    other = torch.tensor([[0.0, 0.0, 7.0]])
    assert contrast_loss(other, wrong_rime, label, targets, onsets, rimes) < loss / 100


def test_known_phone_samples_do_not_receive_foreign_contrast_loss():
    heads = torch.zeros((1, 3), requires_grad=True)
    loss = contrast_loss(heads, heads, [{"phones": ["I_m", "F_a"]}], {}, [], [])
    assert float(loss.detach()) == 0
    loss.backward()
    assert torch.equal(heads.grad, torch.zeros_like(heads))


@pytest.mark.parametrize(
    "field", ["voiceFamilyId", "referenceRootId", "referenceSha256", "sourceSha256"]
)
def test_combined_manifests_cannot_leak_family_reference_or_standard_parent(field):
    rows = [
        {"origin": "synthetic", "split": "train", field: "shared"},
        {"origin": "standard-vc", "split": "calibration", field: "shared"},
    ]
    with pytest.raises(ValueError, match="COMBINED_DATASET_LINEAGE_SPLIT_LEAK"):
        validate_combined_splits(rows)


def test_standard_teacher_voice_exception_does_not_allow_parent_wave_leak():
    rows = [
        {"origin": "standard", "split": "train", "voiceFamilyId": "teacher", "sha256": "a"},
        {"origin": "standard", "split": "calibration", "voiceFamilyId": "teacher", "sha256": "b"},
    ]
    validate_combined_splits(rows)
    rows.append({"origin": "standard-vc", "split": "calibration", "sourceWavSha256": "a"})
    with pytest.raises(ValueError, match="LINEAGE_SPLIT_LEAK"):
        validate_combined_splits(rows)
