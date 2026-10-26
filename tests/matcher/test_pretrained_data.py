"""Real corpus preparation must preserve boundaries, labels and speaker lineage."""

import json
from copy import deepcopy

import pytest

from pinyin_matcher.pretrained_data import assign_speakers, parse_textgrid, prepare, word_windows


def textgrid():
    return """File type = "ooTextFile"
Object class = "TextGrid"
item []:
    item [1]:
        name = "words"
        intervals [1]:
            xmin = 0
            xmax = 0.9
            text = ""
        intervals [2]:
            xmin = 0.9
            xmax = 0.93
            text = "八"
        intervals [3]:
            xmin = 2.0
            xmax = 2.4
            text = "拔"
    item [2]:
        name = "phones"
        intervals [1]:
            xmin = 0.9
            xmax = 0.91
            text = "b"
        intervals [2]:
            xmin = 0.91
            xmax = 0.93
            text = "a1"
        intervals [3]:
            xmin = 2.0
            xmax = 2.4
            text = "a2"
"""


def test_word_windows_preserve_tiny_mfa_interval_but_do_not_clip_to_it():
    tiers = parse_textgrid(textgrid())
    windows = word_windows(tiers, {"八": {}, "拔": {}}, 3)
    assert windows[0]["wordInterval"] == {"start": 0.9, "end": 0.93, "label": "八"}
    assert windows[0]["windowStart"] == 0
    assert windows[0]["windowEnd"] == pytest.approx((0.915 + 2.2) / 2)
    assert windows[1]["windowStart"] == windows[0]["windowEnd"]
    assert windows[1]["windowEnd"] == 3
    assert [p["label"] for p in windows[0]["phoneIntervals"]] == ["b", "a1"]
    with pytest.raises(ValueError, match="LABEL_UNKNOWN"):
        word_windows(tiers, {"八": {}}, 3)


def test_speaker_split_is_order_independent_and_has_reserved_untouched_cohort():
    speakers = [f"test-only-speaker-{i}" for i in range(26)]
    first = assign_speakers(speakers)
    assert first == assign_speakers(list(reversed(speakers)))
    assert list(first.values()).count("train") == 16
    assert list(first.values()).count("calibration") == 4
    assert list(first.values()).count("test") == 6
    with pytest.raises(ValueError, match="26_ANNOTATED"):
        assign_speakers(speakers[:-1])


def test_default_preparation_never_fetches_frozen_test_audio(tmp_path, monkeypatch):
    config = {
        "recordings": [
            {
                "split": "test",
                "speakerId": "untouched-test",
                "wav": {"name": "secret.wav"},
                "grid": {"name": "secret.TextGrid"},
            },
        ],
        "lexicon": {"name": "lexicon.txt"},
        "license": "test-only",
        "citation": "test-only",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    fetched = []
    monkeypatch.setattr(
        "pinyin_matcher.pretrained_data.download_locked",
        lambda entry, directory: fetched.append(deepcopy(entry)),
    )
    result = prepare(path, tmp_path)
    assert fetched == [{"name": "lexicon.txt"}]
    assert result["items"] == []
    assert result["reservedSpeakers"] == ["untouched-test"]
    assert not result["frozenTestIncluded"]


def test_energy_trim_keeps_local_speech_and_padding_without_remote_noise():
    import numpy as np

    from pinyin_matcher.pretrained_data import trim_corpus_window

    # Numeric waveform fixture tests segmentation only, not pronunciation validity.
    samples = np.zeros(32000, dtype=np.float32)
    samples[7000:9000] = 0.2
    samples[9500:10500] = 0.2  # 31ms internal gap must remain in the same syllable.
    samples[25000:27000] = 0.2  # A remote sound must not extend the local clip.
    trimmed, info = trim_corpus_window(samples, 0.55)
    assert info["startSample"] < 7000
    assert 10500 < info["endSample"] < 13000
    assert len(trimmed) == info["endSample"] - info["startSample"]
    assert info["flags"] == []


def test_no_energy_sample_is_retained_with_explicit_quality_flag():
    import numpy as np

    from pinyin_matcher.pretrained_data import trim_corpus_window

    samples = np.zeros(4000, dtype=np.float32)
    kept, info = trim_corpus_window(samples, 0.1)
    assert len(kept) == len(samples)
    assert info["flags"] == ["NO_ENERGY_COMPONENT"]
