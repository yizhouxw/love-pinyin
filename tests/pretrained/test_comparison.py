"""Numerical comparison contracts; fixtures make no pronunciation quality claim."""

import json

import numpy as np
import pytest

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_comparison import (
    DIMENSIONS,
    FEATURE_NAMES,
    WIDTH,
    build_arrays,
    calibration_counts,
    counterfactual_targets,
    evidence_features,
)

VOCAB = {
    "initial": {"<blank>": 0, "<unk>": 1, "ZERO": 2, "m": 3, "b": 4},
    "final": {"<blank>": 0, "<unk>": 1, "a": 2, "v": 3, "e": 4},
    "tone": {"<blank>": 0, "<unk>": 1, "T1": 2, "T2": 3, "T5": 4},
}
TARGET = {"onset": "m", "rime": "a", "tone": 1}


def logits(path):
    result = np.full((len(path), 5), -10.0)
    result[np.arange(len(path)), path] = 10
    return result


def evidence(initial=(0, 3, 0)):
    return {
        "native_initial": logits(initial),
        "native_final": logits([0, 2, 0]),
        "native_tone": logits([0, 2, 0]),
    }


def test_features_preserve_all_native_unknown_multiple_and_outside_competitors():
    unknown = evidence_features(evidence((0, 1, 0)), VOCAB, TARGET, aliases={})
    index = {name: offset for offset, name in enumerate(FEATURE_NAMES)}
    assert unknown.shape == (DIMENSIONS,) == (157,)
    assert unknown[index["unknownMass"]] > 0.999
    assert unknown[index["expectedMass"]] < 0.001
    outside = evidence_features(evidence((0, 4, 0)), VOCAB, TARGET, aliases={})
    assert outside[index["bestOtherMass"]] > 0.999
    assert outside[index["expectedMass"]] < 0.001
    repeated = evidence_features(evidence((3, 0, 3)), VOCAB, TARGET, aliases={})
    assert repeated[index["multipleMass"]] > 0.999
    assert repeated[index["greedyRepeatedExpected"]] == 1
    assert repeated[index["greedyExactlyExpected"]] == 0


def test_changing_expected_onset_only_changes_post_encoder_onset_comparison():
    native = evidence()
    before = {key: value.copy() for key, value in native.items()}
    a = evidence_features(native, VOCAB, TARGET, aliases={})
    b = evidence_features(native, VOCAB, {**TARGET, "onset": "b"}, aliases={})
    assert not np.allclose(a[:WIDTH], b[:WIDTH])
    np.testing.assert_array_equal(a[WIDTH:], b[WIDTH:])
    for key in before:
        np.testing.assert_array_equal(before[key], native[key])


def test_unsupported_target_is_not_conditioned_into_known_phone():
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        evidence_features(evidence(), VOCAB, {**TARGET, "rime": "unsupported"}, aliases={})
    features = evidence_features(evidence(), VOCAB, {**TARGET, "rime": "ü"}, aliases={"ü": "v"})
    assert np.isfinite(features).all()


def catalogue():
    return [
        TARGET,
        {**TARGET, "onset": "b"},
        {**TARGET, "rime": "e"},
        *({**TARGET, "tone": tone} for tone in [2, 3, 4]),
    ]


def test_counterfactuals_change_exactly_one_component_and_include_all_four_tones():
    result = counterfactual_targets(TARGET, catalogue())
    assert {int(target["tone"]) for target, component in result if component == 2} == {2, 3, 4}
    for target, component in result:
        changes = [key for key in TARGET if str(target[key]) != str(TARGET[key])]
        assert changes == [["onset", "rime", "tone"][component]]


def test_supervision_preserves_expert_error_and_counterfactual_weights_per_audio_root(
    tmp_path, monkeypatch
):
    pytest.importorskip("torch")
    from pinyin_matcher.pretrained_experiment import save_cached

    (tmp_path / "identity.json").write_text(json.dumps({"fixture": True}))
    identity = fingerprint(tmp_path / "identity.json")
    for sha in ("correct", "error"):
        save_cached(
            tmp_path / (sha + ".npz"),
            {**evidence(), "pitch": np.zeros(68, dtype=np.float32)},
            identity,
        )
    correct = {
        **TARGET,
        "sha256": "correct",
        "expertLabel": "unanimous-correct",
        "componentExpertLabels": {key: "unanimous-correct" for key in TARGET},
    }
    wrong = {
        **TARGET,
        "sha256": "error",
        "expertLabel": "unanimous-error",
        "componentExpertLabels": {
            "onset": "unanimous-error",
            "rime": "unanimous-correct",
            "tone": "ambiguous",
        },
    }
    flagged = {
        **correct,
        "sha256": "not-present-in-cache",
        "labelPolicyFlags": ["UNCERTAIN_CONTEXT"],
    }
    monkeypatch.setattr("pinyin_matcher.pretrained_comparison.central_targets", catalogue)
    dataset = build_arrays([correct, wrong, flagged], tmp_path, VOCAB, {})
    actual = [i for i, row in enumerate(dataset["examples"]) if row["kind"] == "expert"]
    np.testing.assert_array_equal(dataset["y"][actual[1]], [0, 1, -1])
    np.testing.assert_array_equal(dataset["y"][actual[2]], [-1, -1, -1])
    cf = [i for i, row in enumerate(dataset["examples"]) if row["kind"] == "counterfactual"]
    assert all(dataset["examples"][i]["rowIndex"] == 0 for i in cf)
    np.testing.assert_allclose(dataset["weights"][cf].sum(0), [1, 1, 1])
    assert all(np.count_nonzero(dataset["y"][i] >= 0) == 1 for i in cf)


def test_calibration_counts_worst_counterfactual_once_and_keeps_abstentions():
    rows = [
        {"expertLabel": "unanimous-correct"},
        {"expertLabel": "unanimous-error", "componentExpertLabels": {"onset": "unanimous-error"}},
        {"expertLabel": "ambiguous"},
        {"expertLabel": "unanimous-correct", "numericalQualityFlags": ["SHORT"]},
    ]
    examples = [{"rowIndex": index, "kind": "expert", "valid": index < 2} for index in range(4)]
    examples += [
        {"rowIndex": 0, "kind": "counterfactual", "component": 2, "valid": True} for _ in range(2)
    ]
    probabilities = np.asarray(
        [[0.99] * 3, [0.5] * 3, [0.9] * 3, [0.99] * 3, [0.99] * 3, [0.01] * 3]
    )
    counts = calibration_counts(
        probabilities, {"examples": examples, "rows": rows}, {"accept": 0.8, "reject": 0.1}
    )
    assert counts["positive"] == {"n": 2, "matched": 1, "explicitReject": 0, "abstention": 1}
    assert counts["negative"]["n"] == 2
    assert counts["negative"]["falseAccept"] == 1
    assert counts["errorStrata"]["tone"]["rate"] == 1
    assert counts["unassessableOriginalRowsRetained"] == 1
    assert not counts["pointEstimateGatePassed"]


def test_easy_counterfactuals_cannot_dilute_real_expert_error_strata():
    rows = [{"expertLabel": "unanimous-correct"} for _ in range(100)]
    rows.append(
        {"expertLabel": "unanimous-error", "componentExpertLabels": {"onset": "unanimous-error"}}
    )
    examples = [{"rowIndex": i, "kind": "expert", "valid": True} for i in range(101)]
    examples.extend(
        {"rowIndex": i, "kind": "counterfactual", "component": 0, "valid": True} for i in range(100)
    )
    probabilities = np.asarray([[0.99] * 3] * 101 + [[0.01] * 3] * 100)
    result = calibration_counts(
        probabilities, {"rows": rows, "examples": examples}, {"accept": 0.8, "reject": 0.1}
    )
    assert result["rates"]["pooledFalseAccept"] < 0.05
    assert result["errorStrata"]["expert-onset"] == {"n": 1, "falseAccept": 1, "rate": 1}
    assert result["rates"]["maximumStratumFalseAccept"] == 1
    assert not result["pointEstimateGatePassed"]
