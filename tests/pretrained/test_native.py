import itertools

import numpy as np
import pytest

from pinyin_matcher.pretrained_native import (
    native_probabilities,
    native_rime_aliases,
    single_label_ctc,
)


def test_single_ctc_matches_bruteforce_all_paths_and_repeated_phone():
    logits = np.array([[0.2, 0.9, -0.3], [1.0, 0.1, 0.4], [0.2, 0.8, 0.5]])
    p = np.exp(logits) / np.exp(logits).sum(-1, keepdims=True)
    expected = np.zeros(3)
    empty = multi = 0
    for path in itertools.product(range(3), repeat=3):
        collapsed = [k for k, _ in itertools.groupby(path) if k != 0]
        mass = np.prod([p[i, k] for i, k in enumerate(path)])
        if not collapsed:
            empty += mass
        elif len(collapsed) == 1:
            expected[collapsed[0]] += mass
        else:
            multi += mass
    actual, actual_empty, actual_multi = single_label_ctc(logits)
    np.testing.assert_allclose(actual, expected)
    assert actual_empty == pytest.approx(empty)
    assert actual_multi == pytest.approx(multi)
    _, _, repeated = single_label_ctc(np.array([[-20, 20], [20, -20], [-20, 20]]))
    assert repeated > 0.999


def h_vocab():
    return {
        "initial": {"<blank>": 0, "<unk>": 1, "ZERO": 2, "m": 3},
        "final": {"<blank>": 0, "<unk>": 1, "a": 2, "i": 3},
        "tone": {"<blank>": 0, "<unk>": 1, "T1": 2, "T5": 3},
    }


def test_hanziflow_retains_unknown_tone5_and_outside_coverage_mass():
    evidence = {
        "native_initial": np.array([[-20, -20, -20, 20]]),
        "native_final": np.array([[-20, -20, 20, -20]]),
        "native_tone": np.array([[-20, -20, -20, 20]]),
    }
    vocab = {"onset": ["m"], "rime": ["a"], "tone": ["1"]}
    outputs, extra = native_probabilities("hanziflow", evidence, vocab, native_vocab=h_vocab())
    assert outputs[2].sum() < 0.001
    assert extra["forceUncertain"]
    assert extra["componentEvidence"][2]["unmappedMass"] > 0.999
    evidence["native_tone"] = np.array([[-20, 20, -20, -20]])
    _, extra = native_probabilities("hanziflow", evidence, vocab, native_vocab=h_vocab())
    assert extra["forceUncertain"]


def test_hanziflow_blank_cannot_become_zero_onset():
    evidence = {
        "native_" + k: np.array([[20, -20, -20, -20]]) for k in ("initial", "final", "tone")
    }
    outputs, extra = native_probabilities(
        "hanziflow", evidence, {"onset": [""], "rime": ["a"], "tone": ["1"]}, native_vocab=h_vocab()
    )
    assert outputs[0][0] < 0.001
    assert extra["forceUncertain"]


def test_charsiu_special_tokens_multiread_and_full_vocab_mass():
    source = {"phone": {"[PAD]": 0, "[SIL]": 1, "[UNK]": 2, "m": 3, "a1": 4, "i2": 5}}
    vocab = {"onset": ["m"], "rime": ["a"], "tone": ["1"]}
    logits = np.full((30, 6), -20.0)
    logits[:, 1] = 20
    logits[0:4, 1] = -20
    logits[0:4, 3] = 20
    logits[4:8, 1] = -20
    logits[4:8, 4] = 20
    logits[26:30, 1] = -20
    logits[26:30, 4] = 20
    _, extra = native_probabilities("charsiu", {"native_phone": logits}, vocab, native_vocab=source)
    assert extra["multipleRead"]
    assert extra["forceUncertain"]
    logits[26:30, 4] = -20
    logits[26:30, 5] = 20
    outputs, extra = native_probabilities(
        "charsiu", {"native_phone": logits}, vocab, native_vocab=source
    )
    assert outputs[1][0] == pytest.approx(0.5)
    assert extra["unmappedMass"][1] == pytest.approx(0.5)
    logits[:, :] = -20
    logits[:, 2] = 20
    _, extra = native_probabilities("charsiu", {"native_phone": logits}, vocab, native_vocab=source)
    assert extra["forceUncertain"]


def test_sensevoice_has_no_native_phonetic_comparator():
    _, extra = native_probabilities(
        "sensevoice", {}, {"onset": ["m"], "rime": ["a"], "tone": ["1"]}
    )
    assert extra["unavailable"]


def test_native_cache_rejects_empty_nan_or_wrong_class_axis():
    for logits in (np.empty((0, 4)), np.full((2, 4), np.nan), np.zeros((2, 3))):
        with pytest.raises(ValueError):
            native_probabilities(
                "hanziflow",
                {"native_initial": logits, "native_final": logits, "native_tone": logits},
                {"onset": ["m"], "rime": ["a"], "tone": ["1"]},
                native_vocab=h_vocab(),
            )


def test_native_readout_never_modifies_cached_logits():
    logits = np.array([[0.2, 0.9, -0.3], [1.0, 0.1, 0.4]])
    original = logits.copy()
    single_label_ctc(logits)
    np.testing.assert_array_equal(logits, original)


def test_charsiu_unknown_mass_cannot_be_renormalized_into_certain_final():
    source = {"phone": {"[PAD]": 0, "[SIL]": 1, "[UNK]": 2, "m": 3, "a1": 4, "i2": 5}}
    probabilities = np.array([[1e-20, 1e-20, 0.49, 1e-20, 0.51, 1e-20]])
    outputs, evidence = native_probabilities(
        "charsiu",
        {"native_phone": np.log(probabilities)},
        {"onset": [""], "rime": ["a"], "tone": ["1"]},
        native_vocab=source,
    )
    assert outputs[1][0] == pytest.approx(0.51)
    assert outputs[2][0] == pytest.approx(0.51)
    assert evidence["unmappedMass"][1] == pytest.approx(0.49)
    assert evidence["meanUnknownFrameMass"] == pytest.approx(0.49)


@pytest.mark.parametrize("native_final,generic_rime", [("ii", "i-retroflex"), ("iii", "i-dental")])
def test_hanziflow_apical_rimes_follow_its_own_pinned_schema(native_final, generic_rime):
    # H v2_1_target_schema.json defines retroflex=ii/alveolar=iii, the
    # opposite of Charsiu processors.py. This tests mapping, not accuracy.
    source = h_vocab()
    source["final"] = {"<blank>": 0, "<unk>": 1, "ii": 2, "iii": 3}
    final = np.full((1, 4), -20.0)
    final[0, source["final"][native_final]] = 20
    outputs, extra = native_probabilities(
        "hanziflow",
        {
            "native_initial": np.array([[-20, -20, 20, -20]]),
            "native_final": final,
            "native_tone": np.array([[-20, -20, 20, -20]]),
        },
        {"onset": [""], "rime": ["i-retroflex", "i-dental"], "tone": ["1"]},
        native_vocab=source,
    )
    assert outputs[1][["i-retroflex", "i-dental"].index(generic_rime)] > 0.999
    assert not extra["forceUncertain"]


@pytest.mark.parametrize(
    "native_final,generic_rime", [("iii1", "i-retroflex"), ("ii1", "i-dental")]
)
def test_charsiu_apical_rimes_keep_charsiu_processor_semantics(native_final, generic_rime):
    source = {"phone": {"[PAD]": 0, "[SIL]": 1, "[UNK]": 2, "ii1": 3, "iii1": 4}}
    logits = np.full((1, 5), -20.0)
    logits[0, source["phone"][native_final]] = 20
    outputs, extra = native_probabilities(
        "charsiu",
        {"native_phone": logits},
        {"onset": [""], "rime": ["i-retroflex", "i-dental"], "tone": ["1"]},
        native_vocab=source,
    )
    assert outputs[1][["i-retroflex", "i-dental"].index(generic_rime)] > 0.999
    assert not extra["forceUncertain"]


def test_native_aliases_fail_closed_instead_of_reusing_other_model_mapping():
    with pytest.raises(ValueError, match="NATIVE_MODEL_RIME_ALIASES_REQUIRED"):
        native_rime_aliases("hanziflow", {"nativeRimeAliases": native_rime_aliases("charsiu")})
    with pytest.raises(ValueError, match="NATIVE_MODEL_APICAL_ALIAS_SCHEMA_MISMATCH"):
        native_rime_aliases(
            "hanziflow", {"nativeRimeAliasesByModel": {"hanziflow": native_rime_aliases("charsiu")}}
        )
    aliases = native_rime_aliases("hanziflow")
    aliases["i-retroflex"] = "changed"
    assert native_rime_aliases("hanziflow")["i-retroflex"] == "ii"
