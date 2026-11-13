"""Build fixed cross-platform rule cases with expected values from the Python service."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from deploy.ios.prepare import classroom_contract
from server.content import load_curriculum
from server.domain import Event, calculate_mastery, order_options
from server.game_adaptation import plan_game, settings_for
from server.game_levels import freeze_run, level_for
from server.game_policy import GAMES, POLICY, empty_clock, transition


def fixtures() -> dict:
    mastery = []
    for count in (0, 4, 5, 8, 10):
        for wrong in ([], [0], [count - 1], [count - 2, count - 1]):
            records = [
                {
                    "id": f"event-{i:02}",
                    "mode": ("tone-choice", "symbol-choice")[i % 2],
                    "firstCorrect": i not in wrong,
                    "credit": i != 8,
                    "at": 1800000000 + i,
                }
                for i in range(count)
            ]
            for required in ([], ["tone-choice", "symbol-choice"], ["read-aloud"]):
                result = asdict(
                    calculate_mastery(
                        [
                            Event(
                                r["id"],
                                r["mode"],
                                r["firstCorrect"],
                                datetime.fromtimestamp(r["at"], UTC),
                                r["credit"],
                            )
                            for r in records
                        ],
                        required,
                    )
                )
                expected = {
                    "status": result["status"],
                    "sampleSize": result["sample_size"],
                    "correctCount": result["correct_count"],
                    "accuracy": result["accuracy"],
                    "coveredModes": result["covered_modes"],
                    "requiredModes": result["required_modes"],
                }
                mastery.append({"records": records, "required": required, "expected": expected})
    clocks = []
    midnight = datetime(2026, 11, 13, 16, tzinfo=UTC).timestamp()
    state = empty_clock()
    # Fractional time, midnight, expired lease, rollback, session cap, break and daily cap.
    for at, action in [
        (midnight - 3.5, "heartbeat"),
        (midnight + 4, "heartbeat"),
        (midnight + 7.25, "pause"),
        (midnight + 7.25, "heartbeat"),
        (midnight + 100, "status"),
        (midnight + 80, "heartbeat"),
    ]:
        next_state, expected = transition(state, at, 1, 2, action)
        clocks.append(
            {
                "state": state,
                "at": at,
                "session": 1,
                "daily": 2,
                "action": action,
                "expectedState": next_state,
                "expected": expected,
            }
        )
        state = next_state
    state = empty_clock()
    for offset in list(range(0, 65, 4)) + [660, 664, 720, 800, 86400]:
        at = midnight + offset
        next_state, expected = transition(state, at, 1, 1, "heartbeat")
        clocks.append(
            {
                "state": state,
                "at": at,
                "session": 1,
                "daily": 1,
                "action": "heartbeat",
                "expectedState": next_state,
                "expected": expected,
            }
        )
        state = next_state
    options = [{"id": key, "label": key} for key in ("a", "b", "c", "d")]
    orders = [
        {"id": key, "options": options, "expected": order_options(options, key)}
        for key in ("legacy", "op1_000000000000000000000001", "op1_abcdef123456789012345678")
    ]
    bundled = classroom_contract(load_curriculum())
    lesson = bundled["lessons"][0]
    questions = {row["exercise"]["id"]: row["exercise"] for row in bundled["eligible"]}
    games = []
    for game_id, game in GAMES.items():
        eligible = [questions[qid] for qid in lesson["exerciseIds"] if qid in questions]
        eligible = [
            q
            for q in eligible
            if q["type"] in game["modes"]
            and q.get("audioRef")
            and all(not o.get("pictureId") and not o.get("writing") for o in q["options"])
        ]
        eligible.sort(key=lambda q: q["type"] != game["mode"])
        settings = settings_for({}, "auto", "auto")
        games.append(
            {
                "gameId": game_id,
                "lessonId": lesson["id"],
                "count": 7,
                "selected": plan_game(eligible, [], {}, lesson["id"], limit=7),
                "settings": settings,
                "route": freeze_run(
                    level_for(game_id, None, settings["level"]),
                    [{"instanceId": f"task-{i}"} for i in range(7)],
                ),
            }
        )
    return {
        "mastery": mastery,
        "clocks": clocks,
        "orders": orders,
        "policy": POLICY,
        "games": games,
    }


if __name__ == "__main__":
    output = Path("deploy/android/app/src/androidTest/assets/contracts.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixtures(), ensure_ascii=False, indent=2) + "\n")
