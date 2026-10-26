"""Content/tone separation and calibration must preserve the declared quality gates."""

import copy

import pytest

from pinyin_matcher.decision_v3 import calibrate, decide

THRESHOLDS = {
    "minimumContentMargin": 0.5,
    "maximumFreeCtcAdvantage": 0.05,
    "minimumToneProbability": 0.65,
}
GRID = {key: [value] for key, value in THRESHOLDS.items()}


def evidence(**changes):
    return {
        "targetPhones": ["m", "a"],
        "targetTone": 1,
        "predictedPhones": ["m", "a"],
        "predictedTone": 1,
        "contentMargin": 2,
        "freeCtcAdvantage": 0.001,
        "toneProbability": 0.9,
        "pitchReliable": True,
        **changes,
    }


def calibration_records():
    rows = []
    for expected, prefix in [(True, "positive"), (False, "negative")]:
        for index in range(20):
            rows.append(
                {
                    **evidence(predictedTone=1 if expected else 2),
                    "id": f"{prefix}{index}",
                    "unitId": f"{prefix}{index}",
                    "source": "synthetic-calibration",
                    "generator": "test-only-engine",
                    "case": "clean-positive" if expected else "tone",
                    "split": "calibration",
                    "expectedMatch": expected,
                    "clearAudio": True,
                    "contentCorrect": True,
                }
            )
    return rows


def test_prediction_cannot_read_expected_answer_labels_or_language():
    first = evidence(expectedMatch=True, contentCorrect=True, language="Mandarin")
    second = evidence(expectedMatch=False, contentCorrect=False, language="French")
    assert decide(first, THRESHOLDS) == decide(second, THRESHOLDS)
    assert decide(first, THRESHOLDS)["status"] == "matched"


def test_confident_content_mismatch_does_not_require_reliable_tone_or_other_target_id():
    row = evidence(predictedPhones=["p", "a"], pitchReliable=False, predictedTone=None)
    assert decide(row, THRESHOLDS) == {"status": "retry", "reason": "OTHER_PHONEMES_DETECTED"}


def test_confident_tone_mismatch_does_not_require_exposed_alternative_tone_target():
    assert decide(evidence(predictedTone=3), THRESHOLDS) == {
        "status": "retry",
        "reason": "OTHER_TONE_DETECTED",
    }


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"contentMargin": 0.49}, "CONTENT_CONFIDENCE_INSUFFICIENT"),
        ({"freeCtcAdvantage": 0.051}, "EXTRA_OR_UNSUPPORTED_PHONE_EVIDENCE"),
        ({"toneProbability": 0.64}, "TONE_CONFIDENCE_INSUFFICIENT"),
        ({"pitchReliable": False}, "NO_RELIABLE_TONE_EVIDENCE"),
        ({"predictedPhones": []}, "NO_RELIABLE_PHONE_EVIDENCE"),
    ],
)
def test_separate_branch_abstentions_have_one_explicit_cause(changes, reason):
    assert decide(evidence(**changes), THRESHOLDS) == {"status": "uncertain", "reason": reason}


def test_feasible_calibration_produces_three_thresholds_but_never_claims_test_quality():
    rows = calibration_records()
    original = copy.deepcopy(rows)
    report = calibrate(rows, grid=GRID)
    assert report["calibrationPassed"]
    assert report["thresholds"] == THRESHOLDS
    assert not report["qualityPassed"]
    assert not report["testUsedForCalibration"]
    assert report["groups"]["case:synthetic-calibration/tone"]["negativeAudioUnits"] == 20
    assert rows == original


def test_infeasible_calibration_returns_no_fallback_thresholds_and_counts_pitch_errors():
    rows = calibration_records()
    for row in rows[:5]:
        row["pitchReliable"] = False
    rows[0]["available"] = False
    report = calibrate(rows, grid=GRID)
    assert not report["calibrationPassed"]
    assert not report["qualityPassed"]
    assert report["thresholds"] is None
    assert report["failure"] == "NO_THRESHOLDS_SATISFY_ORIGINAL_QUALITY_LIMITS"
    assert report["groups"]["overall"]["gates"]["clearPositiveAbstention"]["count"] == 5
    assert report["groups"]["overall"]["positiveStatuses"]["unavailable"] == 1


def test_test_rows_cannot_participate_in_threshold_selection():
    rows = calibration_records()
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="NO_TEST_TUNING"):
        calibrate(rows, grid=GRID)


def test_pooled_five_percent_cannot_hide_generator_failure():
    rows = calibration_records()
    second = [
        {
            **row,
            "id": "second-" + row["id"],
            "unitId": "second-" + row["unitId"],
            "generator": "second-test-engine",
        }
        for row in rows
    ]
    rows[20]["predictedTone"] = rows[21]["predictedTone"] = 1
    report = calibrate(rows + second, grid=GRID)
    assert report["groups"]["overall"]["gates"]["negativeFalseAcceptance"]["rate"] == 0.05
    assert "generator:test-only-engine:negativeFalseAcceptance" in report["blockers"]
    assert report["thresholds"] is None


def test_easy_pair_counts_cannot_dilute_one_hard_negative_unit():
    rows = calibration_records()
    rows[20]["predictedTone"] = rows[21]["predictedTone"] = 1
    rows.extend(
        [{**rows[20], "id": f"easy{index}", "targetPhones": ["b", "a"]} for index in range(100)]
    )
    report = calibrate(rows, grid=GRID)
    gate = report["groups"]["overall"]["gates"]["negativeFalseAcceptance"]
    assert gate["count"] == 2
    assert gate["denominator"] == 20
    assert not report["calibrationPassed"]


def test_cross_language_label_alone_is_not_a_negative_acoustic_label():
    rows = calibration_records()
    rows[20].update({"case": "cross-language-acoustic-mismatch", "language": "English"})
    with pytest.raises(ValueError, match="LANGUAGE_LABEL"):
        calibrate(rows, grid=GRID)
    rows[20].update(
        {
            "mismatchBasis": "phoneme",
            "mismatchDescription": "The final consonant differs from the requested syllable.",
        }
    )
    assert calibrate(rows, grid=GRID)["calibrationPassed"]


def test_nonfinite_model_output_is_unavailable_and_never_passes_as_a_score():
    result = decide(evidence(contentMargin=float("nan")), THRESHOLDS)
    assert result == {"status": "unavailable", "reason": "CONTENT_EVIDENCE_INVALID"}


def test_noise_cannot_be_accepted_as_a_confident_child_error_during_calibration():
    rows = calibration_records()
    rows[20]["case"] = "non-speech"
    report = calibrate(rows, grid=GRID)
    assert report["thresholds"] is None
    assert "overall:nonSpeechDoesNotJudgeChildWrong" in report["blockers"]


def test_far_multisyllable_negatives_cannot_hide_hard_foreign_phonetic_failures():
    rows = calibration_records()
    for row in rows[20:]:
        row.update(
            {
                "case": "cross-language-acoustic-mismatch",
                "language": "English",
                "contrastCategory": "dental-fricative",
                "mismatchBasis": "phoneme",
                "mismatchDescription": "The dental fricative differs from the requested phoneme.",
            }
        )
    far = [
        {
            **row,
            "id": "far-" + row["id"],
            "unitId": "far-" + row["unitId"],
            "contrastCategory": "far-multisyllable",
        }
        for row in rows[20:]
    ]
    rows[20]["predictedTone"] = rows[21]["predictedTone"] = 1
    report = calibrate(rows + far, grid=GRID)
    assert report["groups"]["overall"]["gates"]["negativeFalseAcceptance"]["rate"] == 0.05
    assert "contrast:English/dental-fricative:negativeFalseAcceptance" in report["blockers"]
    assert not report["calibrationPassed"]
