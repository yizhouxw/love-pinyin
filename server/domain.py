"""Deterministic rules for objective practice and spaced review."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

OBJECTIVE_MODES = frozenset({"listen-choice", "symbol-choice", "tone-choice", "blend-choice"})
MASTERY_RULE_VERSION = "mastery-v1"
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class PracticeCompletion:
    exercise_id: str
    occurred_at: datetime


def plan_practice(
    eligible_ids: list[str], completions: list[PracticeCompletion], limit: int = 6
) -> list[str]:
    """Rotate authored tasks by exposure, independently from mastery or correctness."""
    if limit < 1:
        raise ValueError("practice limit must be positive")
    candidates = list(dict.fromkeys(eligible_ids))
    counts = dict.fromkeys(candidates, 0)
    latest: dict[str, float] = {}
    for item in completions:
        if item.exercise_id not in counts:
            continue
        if item.occurred_at.tzinfo is None or item.occurred_at.utcoffset() is None:
            raise ValueError("practice history requires timezone-aware timestamps")
        counts[item.exercise_id] += 1
        latest[item.exercise_id] = max(
            latest.get(item.exercise_id, float("-inf")), item.occurred_at.timestamp()
        )
    # Python's stable sort preserves content order when both history keys tie.
    return sorted(
        candidates,
        key=lambda exercise_id: (counts[exercise_id], latest.get(exercise_id, float("-inf"))),
    )[:limit]


def business_date(instant: datetime) -> date:
    """Return the Shanghai calendar date for an aware timestamp."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("business_date requires a timezone-aware datetime")
    return instant.astimezone(BUSINESS_TIMEZONE).date()


@dataclass(frozen=True)
class Event:
    id: str
    mode: str
    correct: bool
    occurred_at: datetime
    credited: bool = True


@dataclass(frozen=True)
class Mastery:
    status: Literal["not-started", "practicing", "mastered"]
    sample_size: int
    correct_count: int
    accuracy: float | None
    covered_modes: tuple[str, ...]
    required_modes: tuple[str, ...]


def calculate_mastery(events: list[Event], required_modes: list[str]) -> Mastery:
    required = tuple(sorted(set(required_modes) & OBJECTIVE_MODES))
    window = sorted(
        (event for event in events if event.credited and event.mode in OBJECTIVE_MODES),
        key=lambda event: (event.occurred_at, event.id),
    )[-8:]
    if not window:
        return Mastery("not-started", 0, 0, None, (), required)
    correct = sum(event.correct for event in window)
    covered = tuple(sorted({event.mode for event in window if event.correct}))
    mastered = (
        len(window) >= 5
        and correct * 5 >= len(window) * 4
        and all(event.correct for event in window[-2:])
        and bool(required)
        and set(required) <= set(covered)
    )
    return Mastery(
        "mastered" if mastered else "practicing",
        len(window),
        correct,
        correct / len(window),
        covered,
        required,
    )


def next_review(stage: int, completed_on: date, passed: bool) -> tuple[int, date]:
    if not passed:
        return 0, completed_on + timedelta(days=1)
    next_stage = min(stage + 1, 3)
    return next_stage, completed_on + timedelta(days={1: 3, 2: 7, 3: 14}[next_stage])
