import pytest

from pinyin_matcher.pretrained_ompal_id_map import build_mapping


def record(text, votes):
    return {
        "text": text,
        "accuracy": [4, 5, 4],
        "fluency": [4, 4, 4],
        "prosody": [4, 4, 4],
        "words": [
            {"text": [text], "phoneme_consonant": votes, "phoneme_vowel": votes, "tone": votes}
        ],
    }


def aggregate(text, label):
    return {
        "text": text,
        "accuracy": 4.33,
        "fluency": 4,
        "prosody": 4,
        "words": [
            {"text": [text], "phoneme_consonant": label, "phoneme_vowel": label, "tone": label}
        ],
    }


def test_complete_block_identity_resolves_colliding_sentence_signatures():
    old = {
        "00204701": record("他", [1, 1, 1]),
        "00204702": record("忙", [0, 0, 1]),
        "00204801": record("他", [1, 1, 1]),
        "00204802": record("忙", [1, 1, 0]),
    }
    current = {
        "00201730": aggregate("他", 1),
        "00201731": aggregate("忙", 0),
        "00202330": aggregate("他", 1),
        "00202331": aggregate("忙", 1),
    }
    mapped = build_mapping(current, old)
    assert mapped["mapping"] == {
        "00201730": "00204701",
        "00201731": "00204702",
        "00202330": "00204801",
        "00202331": "00204802",
    }
    assert mapped["unresolved"] == []


def test_ambiguous_whole_blocks_are_never_assigned_by_equal_filename():
    old = {"00200101": record("他", [1, 1, 1]), "00200201": record("他", [1, 1, 1])}
    current = {"00200101": aggregate("他", 1), "00200201": aggregate("他", 1)}
    mapped = build_mapping(current, old)
    assert mapped["mapping"] == {}
    assert len(mapped["unresolved"]) == 2


def test_ratings_mismatch_or_majority_tie_fails_instead_of_fuzzy_join():
    with pytest.raises(ValueError, match="MISMATCH"):
        build_mapping({"00200101": aggregate("他", 0)}, {"00200101": record("他", [1, 1, 1])})
    with pytest.raises(ValueError, match="TIE"):
        build_mapping({"00200101": aggregate("他", 1)}, {"00200101": record("他", [1, 0])})
