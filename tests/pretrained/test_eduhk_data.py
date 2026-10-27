import json

import numpy as np
import pytest

from pinyin_matcher import pretrained_eduhk_clips as clips
from pinyin_matcher import pretrained_eduhk_data as data
from pinyin_matcher.pretrained_freeze import assert_source_splits


def test_vad_does_not_force_the_expected_number_of_regions():
    config = json.loads(clips.CONFIG.read_text())
    rate = 16000

    def sample(count):
        signal = np.zeros(rate * (count + 1), dtype=np.float32)
        for i in range(count):
            signal[(i * rate) + 4000 : (i * rate) + 9000] = 0.2
        return signal

    assert len(clips.segments(sample(40), rate, config)[0]) == 40
    assert len(clips.segments(sample(39), rate, config)[0]) == 39


def test_annotation_only_explicit_components_and_ontology_conflicts():
    before = {"parsed": True, "onset": "b", "rime": "a", "tone": 1}
    after = {"parsed": True, "onset": "p", "rime": "a", "tone": 1}
    clear = {
        "declaredCategory": "onset",
        "expectedComponentAudit": before,
        "realizedComponentAudit": after,
    }
    assert clips.replacements([clear])[0] == [("onset", ("b", "a", "1"), ("p", "a", "1"))]
    mismatch = {**clear, "declaredCategory": "rime"}
    assert not clips.replacements([mismatch])[0]
    missing_tone = {**clear, "realizedComponentAudit": {**after, "tone": 0}}
    assert not clips.replacements([missing_tone])[0]


def test_training_source_cannot_relabel_withheld_audio():
    assert not set(data.TRAIN) & set(data.CALIBRATION + data.BLIND)
    assert_source_splits([{"source": clips.SOURCE, "speakerId": "eduhk-38", "split": "train"}])
    with pytest.raises(ValueError, match="SOURCE_SPEAKER_SPLIT"):
        assert_source_splits(
            [{"source": clips.SOURCE, "speakerId": "eduhk-38", "split": "calibration"}]
        )
