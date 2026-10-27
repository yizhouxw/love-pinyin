import numpy as np

from pinyin_matcher import pretrained_hard_negative_eduhk as eduhk


def test_only_annotated_component_supplies_comparison_supervision():
    row = {
        "source": eduhk.SOURCE,
        "split": "train",
        "onset": "b",
        "rime": "a",
        "tone": 1,
        "componentExpertLabels": {
            "onset": "source-annotated-error",
            "rime": "ambiguous",
            "tone": "ambiguous",
        },
    }
    np.testing.assert_array_equal(eduhk.eduhk_supervision([row]), [[0, -1, -1]])
    row["componentExpertLabels"]["onset"] = "source-provided-realized"
    np.testing.assert_array_equal(eduhk.eduhk_supervision([row]), [[1, -1, -1]])
    row["numericalQualityFlags"] = ["INVALID_AUDIO"]
    np.testing.assert_array_equal(eduhk.eduhk_supervision([row]), [[-1, -1, -1]])


def test_pairs_use_realized_label_and_keep_audio_root_provenance():
    shared = {
        "source": eduhk.SOURCE,
        "split": "train",
        "sourceRootId": "audio-root",
        "sha256": "a" * 64,
        "parentSha256": "b" * 64,
        "speakerId": "s",
        "voiceFamilyId": "f",
        "referenceSourceId": "r",
        "rime": "a",
        "tone": 1,
    }
    realized = {
        **shared,
        "id": "realized",
        "onset": "b",
        "componentExpertLabels": {"onset": "source-provided-realized"},
    }
    expected = {
        **shared,
        "id": "expected",
        "onset": "p",
        "componentExpertLabels": {"onset": "source-annotated-error"},
    }
    pairs = list(eduhk.eduhk_pairs([realized, expected]))
    assert len(pairs) == 1
    assert pairs[0]["sourceRootId"] == "audio-root"
    assert pairs[0]["sourceProvidedActual"] == "b"
    assert pairs[0]["incorrectTarget"] == "p"
    assert "unverified-vad-boundary" in pairs[0]["labelBasis"]
