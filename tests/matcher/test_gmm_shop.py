import numpy as np
from sklearn.mixture import GaussianMixture

from pinyin_matcher.gmm_shop import evaluate, hmm_path, log_emission, target_scores


def gaussian(mean):
    return {"weights": [1.0], "means": [[mean]], "variances": [[1.0]]}


def test_gmm_likelihood_matches_sklearn():
    data = np.random.default_rng(19).normal(size=(150, 3))
    model = GaussianMixture(n_components=4, covariance_type="diag", random_state=3).fit(data)
    params = {
        "weights": model.weights_,
        "means": model.means_,
        "variances": model.covariances_,
    }
    np.testing.assert_allclose(log_emission(data, params), model.score_samples(data), atol=1e-10)


def test_left_to_right_viterbi_finds_boundary_without_forced_alignment_truth():
    x = np.array([[-2.0], [-2.0], [-2.0], [2.0], [2.0], [2.0]])
    boundary, score = hmm_path(x, gaussian(-2), gaussian(2))
    assert boundary == 3
    assert np.isfinite(score)


def test_unknown_zero_onset_abstains_and_refusal_keeps_denominator():
    model = {
        "onset": {"b": gaussian(0), "p": gaussian(2)},
        "rime": {"a": gaussian(0), "i": gaussian(2)},
        "tone": {"1": gaussian(0), "2": gaussian(2)},
    }
    targets = [
        {"id": "x", "onset": "", "rime": "a", "tone": 1},
        {"id": "y", "onset": "b", "rime": "a", "tone": 1},
    ]
    scores = target_scores(np.zeros((8, 1)), np.array([0]), targets, model)
    assert scores[0] is None
    result = evaluate([({"expertLabel": "unanimous-correct"}, 0, scores)], targets, 100)
    assert result["correctRoots"] == 1
    assert result["correctUncertain"] == 1
    assert result["nearRoots"] == 1


def test_no_voicing_cannot_produce_a_match(monkeypatch):
    import pytest

    from pinyin_matcher import gmm_shop
    from pinyin_matcher.audio import AudioRejected

    monkeypatch.setattr(gmm_shop, "decode_wav", lambda _: np.zeros(16000))
    monkeypatch.setattr(gmm_shop, "features", lambda _: (np.zeros((30, 68)), {"voicedFrames": 4}))
    with pytest.raises(AudioRejected, match="TONE_INSUFFICIENT_VOICING"):
        gmm_shop.acoustic(b"audio")
