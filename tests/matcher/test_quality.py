"""Quality bookkeeping must fail closed without distorting the denominator."""

import json
from pathlib import Path

import pytest

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.quality import (
    build_report,
    coverage_metrics,
    freeze_plan,
    quality_metrics,
    validate_case_semantics,
)


def make_plan(tmp_path: Path, *, usage="unseen", extra_negative=False):
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.onnx").write_bytes(b"test-only snapshot, never passed to inference")
    (model / "model.json").write_text(
        json.dumps(
            {
                "version": "test-only",
                "file": "model.onnx",
                "coveredTargetIds": ["pm-ma1", "pm-ma2"],
                "thresholds": {"minimumScore": -1},
            }
        )
    )
    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "cal",
                        "split": "calibration",
                        "sha256": "cal-only",
                        "voiceFamilyId": "cal-only",
                    },
                    {"id": "diagnostic", "split": "test", "sha256": "test-is-not-calibration"},
                ]
            }
        )
    )
    cases = []
    for expected, prefix in [(True, "positive"), (False, "negative")]:
        for index in range(20):
            audio = tmp_path / f"{prefix}{index}.wav"
            audio.write_bytes(f"{prefix}{index}".encode())
            cases.append(
                {
                    "id": f"{prefix}{index}",
                    "source": "synthetic",
                    "case": "clean" if expected else "tone",
                    "unitId": f"{prefix}{index}",
                    "targetId": "pm-ma1",
                    "expectedMatch": expected,
                    "clearAudio": True,
                    "file": audio.name,
                    "sha256": fingerprint(audio),
                    "generator": "test-engine",
                    "voiceFamilyId": "test-only-family",
                }
            )
    if extra_negative:
        cases.extend(
            [
                {**cases[20], "id": f"easy{index}", "targetId": f"other-{index}"}
                for index in range(100)
            ]
        )
    manifest = tmp_path / "cases.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sources": {"synthetic": {"usage": usage, "labelProvenance": "test-only-fixture"}},
                "cases": cases,
            }
        )
    )
    plan = freeze_plan(
        model, manifest, calibration_manifests=[calibration], output=tmp_path / "freeze.json"
    )
    return plan, manifest, calibration


def results_for(plan):
    return [
        {"id": row["id"], "status": "matched" if row["expectedMatch"] else "retry", "reason": None}
        for row in plan["cases"]
    ]


def test_all_results_and_explicit_unavailable_are_in_quality_denominator(tmp_path):
    plan, _, _ = make_plan(tmp_path)
    records = results_for(plan)
    for row in records[:5]:
        row["status"] = "unavailable"
        row["reason"] = "TARGET_NOT_TRAINED"
    report = build_report(plan, records)
    abstention = report["overall"]["gates"]["clearPositiveAbstention"]
    assert abstention["count"] == 5
    assert abstention["denominator"] == 20
    assert abstention["rate"] == 0.25
    assert not report["qualityPassed"]
    assert report["bySource"]["synthetic"]["positiveStatuses"]["unavailable"] == 5


def test_exact_original_limits_are_inclusive_and_never_relaxed(tmp_path):
    plan, _, _ = make_plan(tmp_path)
    records = results_for(plan)
    for row in records[:2]:
        row["status"] = "retry"
    for row in records[2:6]:
        row["status"] = "uncertain"
    records[20]["status"] = "matched"
    report = build_report(plan, records)
    assert report["qualityPassed"]
    assert report["limits"] == {
        "negativeFalseAcceptance": 0.05,
        "positiveExplicitRejection": 0.10,
        "clearPositiveAbstention": 0.20,
    }


def test_unseen_declaration_cannot_rescue_previously_diagnosed_cohort(tmp_path):
    plan, _, _ = make_plan(tmp_path, usage="diagnostic")
    report = build_report(plan, results_for(plan))
    assert not report["qualityPassed"]
    assert "DIAGNOSTIC_COHORT_CANNOT_ESTABLISH_QUALITY" in report["blockers"]


def test_easy_negative_pairs_do_not_dilute_hard_audio_unit_failure(tmp_path):
    plan, _, _ = make_plan(tmp_path, extra_negative=True)
    records = results_for(plan)
    records[20]["status"] = "matched"
    records[21]["status"] = "matched"
    report = build_report(plan, records)
    gate = report["overall"]["gates"]["negativeFalseAcceptance"]
    assert report["overall"]["negativePairs"] == 120
    assert gate["count"] == 2
    assert gate["denominator"] == 20
    assert gate["rate"] == 0.10
    assert not report["qualityPassed"]


def test_missing_results_are_unavailable_and_diagnostic_coverage_cannot_disappear(tmp_path):
    plan, _, _ = make_plan(tmp_path)
    report = build_report(plan, results_for(plan)[5:])
    assert report["missingResults"] == 5
    assert report["overall"]["reasonCounts"]["EVALUATION_RESULT_MISSING"] == 5
    assert not report["qualityPassed"]


def test_model_answer_cannot_change_frozen_expected_label_or_source(tmp_path):
    plan, _, _ = make_plan(tmp_path)
    records = results_for(plan)
    records[0].update({"expectedMatch": False, "source": "ignored", "unitId": "ignored"})
    report = build_report(plan, records)
    assert report["results"][0]["expectedMatch"] is True
    assert report["results"][0]["source"] == "synthetic"
    assert report["results"][0]["unitId"] == "positive0"
    plan["limits"]["clearPositiveAbstention"] = 1
    with pytest.raises(ValueError, match="DIGEST"):
        build_report(plan, records)


def test_freeze_rejects_actual_train_or_calibration_lineage_overlap(tmp_path):
    _, manifest, calibration = make_plan(tmp_path)
    data = json.loads(manifest.read_text())
    data["cases"][0]["voiceFamilyId"] = "cal-only"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="LINEAGE"):
        freeze_plan(
            tmp_path / "model",
            manifest,
            calibration_manifests=[calibration],
            output=tmp_path / "new-freeze.json",
        )


def test_frozen_plan_cannot_be_overwritten_or_results_duplicated(tmp_path):
    plan, manifest, calibration = make_plan(tmp_path)
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        freeze_plan(
            tmp_path / "model",
            manifest,
            calibration_manifests=[calibration],
            output=tmp_path / "freeze.json",
        )
    records = results_for(plan)
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        build_report(plan, records + [records[0]])


def test_cross_language_homophone_can_be_positive_but_language_is_not_a_negative_label():
    validate_case_semantics({"case": "clean-positive", "expectedMatch": True, "language": "French"})
    with pytest.raises(ValueError, match="LANGUAGE_LABEL"):
        validate_case_semantics(
            {
                "case": "cross-language-acoustic-mismatch",
                "expectedMatch": False,
                "language": "French",
            }
        )
    validate_case_semantics(
        {
            "case": "cross-language-acoustic-mismatch",
            "expectedMatch": False,
            "mismatchBasis": "phoneme",
            "mismatchDescription": "The final consonant is absent from the requested syllable.",
        }
    )


def test_identical_negative_audio_cannot_be_renamed_as_more_independent_units(tmp_path):
    _, manifest, calibration = make_plan(tmp_path)
    data = json.loads(manifest.read_text())
    data["cases"].append({**data["cases"][20], "id": "renamed", "unitId": "new-unit"})
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="UNIT_IDENTITY"):
        freeze_plan(
            tmp_path / "model",
            manifest,
            calibration_manifests=[calibration],
            output=tmp_path / "new-freeze.json",
        )


def test_non_speech_retry_violates_engineering_contract_even_without_false_acceptance(tmp_path):
    _, manifest, calibration = make_plan(tmp_path)
    data = json.loads(manifest.read_text())
    for row in data["cases"]:
        if not row["expectedMatch"]:
            row["case"] = "non-speech"
    manifest.write_text(json.dumps(data))
    plan = freeze_plan(
        tmp_path / "model",
        manifest,
        calibration_manifests=[calibration],
        output=tmp_path / "noise-freeze.json",
    )
    report = build_report(plan, results_for(plan))
    assert report["overall"]["gates"]["negativeFalseAcceptance"]["passed"]
    contract = report["overall"]["contracts"]["nonSpeechDoesNotJudgeChildWrong"]
    assert contract["count"] == contract["denominator"] == 20
    assert not contract["passed"]
    assert not report["qualityPassed"]


def test_coverage_does_not_turn_derived_voice_or_target_pairs_into_original_roots():
    rows = [
        {
            "source": "synthetic",
            "unitId": f"derived-{i}",
            "sourceRootId": "one-parent",
            "sha256": f"child-{i}",
            "voiceFamilyId": f"voice-{i}",
            "lexicalRootId": "one-word",
        }
        for i in range(3)
    ]
    counts = coverage_metrics(rows + rows)
    assert counts["pairs"] == 6
    assert counts["rawAudioUnits"] == counts["sourceUtteranceRoots"] == 1
    assert counts["evaluatedAudioUnits"] == counts["distinctWaveforms"] == 3
    assert counts["uniqueLexicalRoots"] == 1
    assert counts["voiceFamilies"] == 3
    assert counts["minimumIndependentZeroErrorTrialsForWilson95UpperAtMostFivePercent"] == 73
    assert not counts["independentTrialsEstablished"]


def test_freeze_binds_actual_pitch_tracker_bytes_and_declared_digest(tmp_path):
    _, manifest, calibration = make_plan(tmp_path)
    model = tmp_path / "model"
    tracker = model / "tracker.onnx"
    tracker.write_bytes(b"test-only tracker")
    (model / "pitch.onnx").write_bytes(b"test-only pitch head")
    metadata = json.loads((model / "model.json").read_text())
    metadata["pitchTone"] = {
        "file": "pitch.onnx",
        "tracker": {"file": "tracker.onnx", "sha256": fingerprint(tracker)},
    }
    (model / "model.json").write_text(json.dumps(metadata))
    plan = freeze_plan(
        model,
        manifest,
        calibration_manifests=[calibration],
        output=tmp_path / "tracker-freeze.json",
    )
    assert plan["model"]["files"]["tracker.onnx"] == fingerprint(tracker)
    assert "pitch_swift.py" in plan["evaluationCodeSha256"]
    tracker.write_bytes(b"changed")
    with pytest.raises(ValueError, match="PITCH_TRACKER_DIGEST"):
        freeze_plan(
            model,
            manifest,
            calibration_manifests=[calibration],
            output=tmp_path / "bad-tracker-freeze.json",
        )


def test_parent_roots_use_worst_derivative_and_keep_same_raw_view_for_calibration_and_test():
    rows = [
        {
            "source": "vc",
            "case": "clean-positive",
            "unitId": f"{root}-{voice}",
            "sourceRootId": root,
            "expectedMatch": True,
            "clearAudio": True,
            "status": "matched",
        }
        for root in ["a", "b"]
        for voice in range(4)
    ]
    rows[0]["status"] = "uncertain"
    report = quality_metrics(rows)
    parent = report["gates"]["clearPositiveAbstention"]
    raw = report["rawView"]["gates"]["clearPositiveAbstention"]
    assert (parent["count"], parent["denominator"]) == (1, 2)
    assert (raw["count"], raw["denominator"]) == (1, 8)
    assert not parent["passed"]
    assert raw["passed"]
