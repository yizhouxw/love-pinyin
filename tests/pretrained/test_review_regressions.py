"""Methodology regressions; no simulated result is model-quality evidence."""

import json

import numpy as np

from pinyin_matcher.pretrained_experiment import calibrated_rows


def test_expert_rejections_cannot_dilute_counterfactual_neighbor_false_acceptance():
    correct = [{"expertLabel": "unanimous-correct"} for _ in range(10)]
    errors = [
        {"expertLabel": "unanimous-error", "componentExpertLabels": {"onset": "unanimous-error"}}
        for _ in range(990)
    ]
    ps = [np.array([0.01, 0.99]), np.array([0.99, 0.01]), np.array([0.99, 0.01])]
    probabilities = [ps for _ in range(1000)]
    labels = np.zeros((1000, 3), dtype=np.int64)
    report = calibrated_rows(
        probabilities, labels, correct + errors, {"probability": 0.5, "margin": 0}
    )
    # Every correct root is confidently mapped to an incorrect neighboring
    # initial. Adding unrelated, correctly rejected learner errors cannot help.
    assert report["falseAcceptance"] == 1


def test_pitch_abstention_retains_every_clear_correct_root_in_calibration():
    rows = [{"expertLabel": "unanimous-correct", "runtimePitchUnavailable": True}]
    probabilities = [[np.array([0.99, 0.01])] * 3]
    report = calibrated_rows(
        probabilities, np.zeros((1, 3), dtype=np.int64), rows, {"probability": 0.5, "margin": 0}
    )
    assert report["n"] == 1
    assert report["positive"] == {"matched": 0, "retry": 0, "uncertain": 1}
    assert report["abstention"] == 1


def test_unobserved_tone_is_still_a_required_wrong_target():
    from types import SimpleNamespace

    from pinyin_matcher.pretrained_evaluate import compare_targets
    from pinyin_matcher.pretrained_experiment import covered_targets

    row = {
        "id": "root",
        "syllable": "qiong2",
        "onset": "q",
        "rime": "iong",
        "tone": 2,
        "speakerId": "speaker",
        "source": "regression-fixture",
        "parentSha256": "original-audio",
        "split": "calibration",
        "labelProvenance": "interface regression only",
        "expertLabel": "unanimous-correct",
    }
    vocabulary = {"onset": ["q"], "rime": ["iong"], "tone": ["1", "2", "3", "4"]}
    targets = covered_targets(vocabulary, [row])
    assert {f"pm-qiong{tone}" for tone in range(1, 5)} <= {t["id"] for t in targets}
    matcher = SimpleNamespace(
        targets={t["id"]: t for t in targets},
        metadata={"vocabulary": vocabulary, "thresholds": {"probability": 0.9, "margin": 0}},
    )
    result = {
        "status": "retry",
        "internalEvidence": {
            "onset": {"probabilities": [1]},
            "rime": {"probabilities": [1]},
            "tone": {"probabilities": [0.01, 0.01, 0.97, 0.01]},
        },
    }
    wrong = [r for r in compare_targets(row, matcher, result) if r["label"] == "negative"]
    assert len(wrong) == 3
    assert next(r for r in wrong if r["target_id"] == "pm-qiong3")["status"] == "matched"


def test_unknown_source_target_still_tests_supported_wrong_neighbor(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_evaluate as evaluation

    calls = []
    target = {"id": "pm-ma1", "onset": "m", "rime": "a", "tone": 1}

    class Matcher:
        session = object()
        targets = {"pm-ma1": target}
        metadata = {
            "model": "hanziflow",
            "thresholds": {"probability": 0.5, "margin": 0},
            "vocabulary": {"onset": ["m"], "rime": ["a"], "tone": ["1"]},
        }

        def __init__(self, package):
            pass

        def match(self, target_id, wav_bytes, *, evidence=False):
            calls.append(target_id)
            if target_id not in self.targets:
                return {"status": "unavailable", "reason": "TARGET_NOT_TRAINED"}
            return {
                "status": "matched",
                "internalEvidence": {
                    key: {"probabilities": [1.0]} for key in ("onset", "rime", "tone")
                },
            }

    audio = tmp_path / "source.wav"
    audio.write_bytes(b"input is not decoded by the interface-contract fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": []}))
    package = tmp_path / "model"
    package.mkdir()
    (package / "model.json").write_text("{}")
    row = {
        "id": "root",
        "speakerId": "speaker",
        "source": "external",
        "parentSha256": "source-hash",
        "labelProvenance": "fixture contract only",
        "split": "calibration",
        "file": str(audio),
        "syllable": "mx1",
        "onset": "m",
        "rime": "x",
        "tone": 1,
        "expertLabel": "unanimous-correct",
    }
    monkeypatch.setattr(evaluation, "load_matcher", Matcher)
    monkeypatch.setattr(evaluation, "read_rows", lambda *args, **kwargs: [row])
    output = tmp_path / "report.json"
    evaluation.evaluate(manifest, package, output)
    report = json.loads(output.read_text())
    assert "pm-ma1" in calls
    assert report["metrics"]["negative"]["falseAccept"]["count"] == 1


def test_native_comparison_target_decisions_preserve_wrong_neighbor_acceptance():
    from pinyin_matcher.pretrained_evaluate import compare_targets

    class Matcher:
        targets = {
            "pm-ma1": {"id": "pm-ma1", "onset": "m", "rime": "a", "tone": 1},
            "pm-ba1": {"id": "pm-ba1", "onset": "b", "rime": "a", "tone": 1},
            "pm-pa1": {"id": "pm-pa1", "onset": "p", "rime": "a", "tone": 1},
        }

    row = {
        "id": "root",
        "speakerId": "speaker",
        "source": "public-contract-fixture",
        "parentSha256": "parent",
        "split": "calibration",
        "labelProvenance": "Interface contract only",
        "syllable": "ma1",
        "onset": "m",
        "rime": "a",
        "tone": 1,
    }
    records = compare_targets(
        row,
        Matcher(),
        {
            "status": "retry",
            "internalEvidence": {"targetDecisions": {"pm-ma1": "retry", "pm-ba1": "matched"}},
        },
    )
    statuses = {record["target_id"]: record["status"] for record in records}
    assert statuses == {"pm-ma1": "retry", "pm-ba1": "matched", "pm-pa1": "uncertain"}


def test_unsupported_truth_comparison_batch_keeps_real_row_neighbors(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_evaluate as evaluation

    calls = []

    class Matcher:
        session = object()
        supports_target_comparison_batch = True
        metadata = {"model": "hanziflow"}
        targets = {
            "pm-ma1": {"id": "pm-ma1", "onset": "m", "rime": "a", "tone": 1},
            "pm-mi1": {"id": "pm-mi1", "onset": "m", "rime": "i", "tone": 1},
            "pm-mx2": {"id": "pm-mx2", "onset": "m", "rime": "x", "tone": 2},
            "pm-ba1": {"id": "pm-ba1", "onset": "b", "rime": "a", "tone": 1},
        }

        def match(self, target_id, data, *, evidence, comparison_target_ids):
            calls.append((target_id, set(comparison_target_ids)))
            if target_id not in self.targets:
                return {"status": "unavailable", "reason": "TARGET_NOT_TRAINED"}
            return {
                "status": "uncertain",
                "internalEvidence": {
                    "targetDecisions": {
                        key: "matched" if key == "pm-mx2" else "uncertain"
                        for key in comparison_target_ids
                    }
                },
            }

    payload = tmp_path / "contract-only.wav"
    payload.write_bytes(b"Not decoded by this interface contract fixture")
    manifest, package = tmp_path / "manifest.json", tmp_path / "package"
    manifest.write_text("{}")
    package.mkdir()
    (package / "model.json").write_text("{}")
    row = {
        "id": "root",
        "speakerId": "speaker",
        "source": "external",
        "parentSha256": "parent",
        "split": "calibration",
        "file": str(payload),
        "labelProvenance": "Interface contract only",
        "syllable": "mx1",
        "onset": "m",
        "rime": "x",
        "tone": 1,
    }
    monkeypatch.setattr(evaluation, "load_matcher", lambda path: Matcher())
    monkeypatch.setattr(evaluation, "read_rows", lambda *args, **kwargs: [row])
    output = tmp_path / "result.json"
    evaluation.evaluate(manifest, package, output)
    expected = {"pm-ma1", "pm-mi1", "pm-mx2"}
    assert calls == [("pm-mx1", expected), ("pm-ma1", expected)]
    records = json.loads(output.read_text())["records"]
    assert next(r for r in records if r["target_id"] == "pm-mx2")["status"] == "matched"
    assert not any(r["target_id"] == "pm-ba1" for r in records)
