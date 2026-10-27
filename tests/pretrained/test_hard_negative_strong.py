import numpy as np

from pinyin_matcher.pretrained_hard_negative_strong import mask_row, masked_supervision


def test_training_masks_only_flagged_component_and_keeps_calibration_unchanged():
    row = {
        "split": "train",
        "componentExpertLabels": {
            "onset": "unanimous-correct",
            "rime": "unanimous-error",
            "tone": "unanimous-correct",
        },
        "alignmentFlags": ["WEAK_CTC_SUPPORT:tone"],
    }
    masked = mask_row(row)
    assert masked["componentExpertLabels"] == {
        "onset": "unanimous-correct",
        "rime": "unanimous-error",
        "tone": "ambiguous",
    }
    assert row["componentExpertLabels"]["tone"] == "unanimous-correct"
    calibration = {**row, "split": "calibration"}
    np.testing.assert_array_equal(masked_supervision([row, calibration]), [[1, 0, -1], [1, 0, 1]])


def test_overlapping_boundaries_mask_every_component_without_fallback():
    row = {
        "split": "train",
        "alignmentFlags": ["HEAD_BOUNDARY_OVERLAP"],
        "componentExpertLabels": {k: "unanimous-correct" for k in ("onset", "rime", "tone")},
    }
    np.testing.assert_array_equal(masked_supervision([row]), [[-1, -1, -1]])
