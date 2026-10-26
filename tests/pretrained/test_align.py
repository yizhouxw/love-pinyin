import itertools

import numpy as np
import pytest
from scipy.special import log_softmax

from pinyin_matcher.pretrained_align import AlignmentUnavailable, align_components, ctc_viterbi
from pinyin_matcher.pretrained_native import native_rime_aliases


def collapse(path):
    return [
        value
        for index, value in enumerate(path)
        if value and (index == 0 or value != path[index - 1])
    ]


@pytest.mark.parametrize("tokens", [[1], [1, 2], [1, 1], [2, 1]])
def test_viterbi_matches_exhaustive_ctc_best_path(tokens):
    logits = np.random.default_rng(18).normal(size=(4, 3))
    log_probs = log_softmax(logits, axis=-1)
    valid = [path for path in itertools.product(range(3), repeat=4) if collapse(path) == tokens]
    expected = max(
        sum(log_probs[index, token] for index, token in enumerate(path)) for path in valid
    )
    actual = ctc_viterbi(logits, tokens)
    assert collapse(actual["path"].tolist()) == tokens
    assert actual["logProbability"] == pytest.approx(expected)
    assert len(actual["wordFrames"]) == len(tokens)


def test_identical_adjacent_labels_require_a_real_blank_frame():
    with pytest.raises(AlignmentUnavailable, match="IMPOSSIBLE"):
        ctc_viterbi(np.zeros((2, 2)), [1, 1])
    aligned = ctc_viterbi(np.array([[0, 8], [8, 0], [0, 8]]), [1, 1])
    assert aligned["path"].tolist() == [1, 0, 1]
    assert aligned["wordFrames"][0].tolist() == [0]
    assert aligned["wordFrames"][1].tolist() == [2]


VOCABULARIES = {
    "initial": {"<blank>": 0, "ZERO": 1, "m": 2, "b": 3},
    "final": {"<blank>": 0, "a": 1, "ii": 2, "v": 3},
    "tone": {"<blank>": 0, "T1": 1, "T2": 2, "T5": 3},
}


def logits(path):
    result = np.full((len(path), 4), -8.0)
    result[np.arange(len(path)), path] = 8
    return result


def test_independent_heads_and_midpoint_partition_preserve_all_words():
    native = {
        "initial": logits([2, 0, 0, 3]),
        "final": logits([0, 1, 1, 0, 0, 2, 2, 0]),
        "tone": logits([1, 1, 0, 2, 2, 0]),
    }
    labels = [
        {"id": "one", "onset": "m", "rime": "a", "tone": 1},
        {"id": "two", "onset": "b", "rime": "i-dental", "tone": 2},
    ]
    result = align_components(
        native, labels, 2.0, vocabularies=VOCABULARIES, aliases={"i-dental": "ii"}
    )
    assert [word["id"] for word in result] == ["one", "two"]
    assert all(word["available"] and word["boundaryOnly"] for word in result)
    assert all(word["correctnessFromForcedAlignment"] is False for word in result)
    assert result[0]["endSeconds"] == result[1]["startSeconds"]
    assert 0 <= result[0]["startSeconds"] < result[0]["endSeconds"] < result[1]["endSeconds"] <= 2
    assert result[1]["heads"]["final"]["token"] == "ii"
    assert result[0]["heads"]["initial"]["frameCount"] == 4
    assert result[0]["heads"]["final"]["frameCount"] == 8


def test_zero_onset_neutral_tone_and_umlaut_are_explicitly_mapped():
    native = {"initial": logits([0, 1, 0]), "final": logits([0, 3, 0]), "tone": logits([0, 3, 0])}
    result = align_components(
        native,
        [{"onset": "", "rime": "ü", "tone": 5}],
        1,
        vocabularies=VOCABULARIES,
        aliases={"ü": "v"},
    )
    assert result[0]["available"]
    assert [result[0]["heads"][key]["token"] for key in ("initial", "final", "tone")] == [
        "ZERO",
        "v",
        "T5",
    ]


@pytest.mark.parametrize(
    "failure", ["missing-head", "nonfinite", "unmapped", "missing-label", "impossible"]
)
def test_any_incomplete_full_alignment_returns_every_word_as_unavailable(failure):
    native = {key: logits([2, 0, 2]) for key in VOCABULARIES}
    labels = [
        {"id": "one", "onset": "m", "rime": "ii", "tone": 2},
        {"id": "two", "onset": "m", "rime": "ii", "tone": 2},
    ]
    if failure == "missing-head":
        native.pop("tone")
    elif failure == "nonfinite":
        native["tone"][0, 0] = np.nan
    elif failure == "unmapped":
        labels[1]["onset"] = "not-a-phone"
    elif failure == "missing-label":
        labels[1]["rime"] = None
    else:
        native["tone"] = logits([2, 2])
    result = align_components(native, labels, 1, vocabularies=VOCABULARIES, aliases={})
    assert [word["id"] for word in result] == ["one", "two"]
    assert all(not word["available"] and word["flags"] for word in result)
    assert all(word["startSeconds"] is None and word["endSeconds"] is None for word in result)


def test_empty_sequence_is_empty_and_invalid_duration_is_explicit():
    assert align_components({}, [], 1) == []
    result = align_components({}, [{"onset": "m", "rime": "a", "tone": 1}], float("nan"))
    assert result[0]["flags"] == ["DURATION_INVALID"]


def test_weak_native_support_stays_boundary_metadata_and_never_becomes_correctness():
    native = {key: logits([0, 0, 0, 0]) for key in VOCABULARIES}
    result = align_components(
        native,
        [{"onset": "m", "rime": "a", "tone": 1}],
        1,
        vocabularies=VOCABULARIES,
        aliases={},
    )
    assert result[0]["available"]
    assert result[0]["alignmentSupport"] == "weak"
    assert result[0]["correctnessFromForcedAlignment"] is False
    assert all(value["nativeArgmaxSupportFrames"] == 0 for value in result[0]["heads"].values())
    assert all(value["flags"] for value in result[0]["heads"].values())


def test_default_alignment_hanzi_apical_tokens_follow_actual_model_schema():
    vocabularies = {
        **VOCABULARIES,
        "final": {"<blank>": 0, "a": 1, "ii": 2, "iii": 3},
    }
    native = {
        "initial": logits([2, 0, 3]),
        "final": logits([2, 0, 3]),
        "tone": logits([1, 0, 2]),
    }
    words = [
        {"onset": "m", "rime": "i-retroflex", "tone": 1},
        {"onset": "b", "rime": "i-dental", "tone": 2},
    ]
    result = align_components(native, words, 1, vocabularies=vocabularies)
    assert all(word["available"] for word in result)
    assert [word["heads"]["final"]["token"] for word in result] == ["ii", "iii"]
    assert native_rime_aliases("charsiu")["i-retroflex"] == "iii"
    assert native_rime_aliases("charsiu")["i-dental"] == "ii"
