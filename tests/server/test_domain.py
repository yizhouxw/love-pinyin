from datetime import UTC, date, datetime, timedelta

import pytest

from server.domain import Event, calculate_mastery, next_review

BASE = datetime(2026, 9, 1, tzinfo=UTC)


def event(
    index, mode="symbol-choice", correct=True, *, day_offset=None, credited=True, event_id=None
):
    occurred_at = BASE + timedelta(days=index if day_offset is None else day_offset)
    return Event(
        event_id or f"event-{index:02d}",
        mode,
        correct,
        occurred_at,
        credited,
    )


@pytest.mark.parametrize(
    ("events", "required", "expected_status", "sample_size", "correct_count"),
    [
        ([], ["symbol-choice"], "not-started", 0, 0),
        ([event(i) for i in range(4)], ["symbol-choice"], "practicing", 4, 4),
        (
            [event(0, "symbol-choice", True), event(1, "tone-choice", False)]
            + [event(i, "symbol-choice", True) for i in range(2, 5)],
            ["symbol-choice", "tone-choice"],
            "practicing",
            5,
            4,
        ),
        (
            [
                event(i, "symbol-choice", correct)
                for i, correct in enumerate([True] * 6 + [False] * 2)
            ],
            ["symbol-choice"],
            "practicing",
            8,
            6,
        ),
        (
            [event(i, "symbol-choice", correct) for i, correct in enumerate([True] * 7 + [False])],
            ["symbol-choice"],
            "practicing",
            8,
            7,
        ),
    ],
)
def test_mastery_threshold_and_recent_window(
    events, required, expected_status, sample_size, correct_count
):
    result = calculate_mastery(events, required)
    assert result.status == expected_status
    assert result.sample_size == sample_size
    assert result.correct_count == correct_count


def test_five_of_five_with_two_independent_recent_and_all_modes_mastered():
    events = [
        event(0, "symbol-choice"),
        event(1, "tone-choice"),
        event(2, "symbol-choice", False),
        event(3, "blend-choice"),
        event(4, "tone-choice"),
    ]
    result = calculate_mastery(events, ["symbol-choice", "tone-choice", "read-aloud"])
    assert result.status == "mastered"
    assert result.covered_modes == ("blend-choice", "symbol-choice", "tone-choice")
    assert result.required_modes == ("symbol-choice", "tone-choice")


def test_mode_coverage_requires_an_independent_correct_event():
    events = [
        event(0, "symbol-choice"),
        event(1, "tone-choice", False),
        event(2, "symbol-choice"),
        event(3, "symbol-choice"),
        event(4, "symbol-choice"),
    ]
    result = calculate_mastery(events, ["symbol-choice", "tone-choice"])
    assert result.correct_count == 4
    assert result.status == "practicing"


def test_unknown_or_empty_required_mode_set_never_claims_mastery():
    events = [event(i) for i in range(8)]
    for required in ([], ["not-an-objective-mode"], ["read-aloud"]):
        result = calculate_mastery(events, required)
        assert result.status == "practicing"
        assert result.required_modes == ()


def test_mastery_uses_only_latest_eight_valid_credited_events_in_stable_order():
    events = [event(i, correct=False) for i in range(2)] + [
        event(i, correct=True) for i in range(2, 10)
    ]
    result = calculate_mastery(list(reversed(events)), ["symbol-choice"])
    assert result.sample_size == 8
    assert result.correct_count == 8
    assert result.status == "mastered"

    filtered = calculate_mastery(
        [event(10, correct=False, credited=False), event(11, "read-aloud", False)],
        ["symbol-choice"],
    )
    assert filtered.status == "not-started"


def test_same_timestamp_events_use_event_id_as_the_tiebreaker():
    tied = [
        event(0, correct=False, day_offset=0, event_id="b"),
        event(1, correct=True, day_offset=0, event_id="a"),
    ]
    remainder = [event(i, correct=True, day_offset=i + 1) for i in range(2, 5)]
    result = calculate_mastery(tied + remainder, ["symbol-choice"])
    assert result.correct_count == 4
    assert result.status == "mastered"


@pytest.mark.parametrize(
    ("stage", "passed", "expected_stage", "days"),
    [
        (0, True, 1, 3),
        (1, True, 2, 7),
        (2, True, 3, 14),
        (3, True, 3, 14),
        (0, False, 0, 1),
        (3, False, 0, 1),
    ],
)
def test_review_stage_spacing(stage, passed, expected_stage, days):
    completed_on = date(2026, 9, 26)
    assert next_review(stage, completed_on, passed) == (
        expected_stage,
        completed_on + timedelta(days=days),
    )
