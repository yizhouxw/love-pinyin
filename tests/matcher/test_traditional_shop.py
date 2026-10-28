import numpy as np
import pytest

from pinyin_matcher.traditional_shop import (
    comparison,
    dtw_batch,
    metrics,
    score_model,
    serial_models,
)


def test_dtw_and_comparison_exclude_same_voice_family():
    query = np.zeros((20, 16), dtype=np.float32)
    bank = np.zeros((2, 3, 20, 16), dtype=np.float32)
    bank[0, 1:] = 1
    bank[1] = 2
    values = dtw_batch(query, bank.reshape(6, 20, 16))
    assert values[0] == 0 and values[-1] > values[0]
    rows = comparison(
        query, bank, ["source", "other", "third", "x", "y", "z"], [[1], [0]], "source"
    )
    assert rows[0, 1] > 0
    with pytest.raises(ValueError, match="INSUFFICIENT_CROSS_FAMILY"):
        comparison(query, bank, ["source", "source", "other", "x", "y", "z"], [[1], [0]], "source")


def test_exported_classifiers_match_training_predictions():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(120, 8)).astype(np.float32)
    y = (x[:, 0] + x[:, 1] > 0).astype(int)
    models = serial_models(x, y)
    for name in ("svm", "boost"):
        result = score_model(name, x, models[name])
        assert np.isfinite(result).all()
        assert result[y == 1].mean() > result[y == 0].mean()


def test_refusal_stays_in_positive_denominator_and_near_fail_is_root_based():
    scores = np.array([[0.2, 0.9, 0.7], [0.01, 0.2, 0.3], [0.9, 0.8, 0.2]])
    result = metrics(scores, [0, 0, 0], [[1, 2], [1, 2], [1, 2]], 0.5)
    assert result == {
        "roots": 3,
        "correctAccepted": 1,
        "correctExplicitReject": 1,
        "correctAbstention": 1,
        "nearNeighborFalseAccept": 2,
        "nearNeighborRoots": 3,
    }


def test_unavailable_target_and_invalid_audio_do_not_report_child_error(monkeypatch):
    from pinyin_matcher import traditional_shop
    from pinyin_matcher.audio import encode_wav

    model = {"models": {"dtw": {}}, "targets": [{"id": "known"}]}
    monkeypatch.setattr(traditional_shop, "load", lambda package: (model, None))
    missing = traditional_shop.match(None, "dtw", "unknown", b"")
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "TARGET_NOT_TRAINED"
    invalid = traditional_shop.match(None, "dtw", "known", b"not a wave")
    assert invalid["status"] == "uncertain"
    silence = traditional_shop.match(None, "dtw", "known", encode_wav(np.zeros(16000)))
    assert silence["status"] == "uncertain"
