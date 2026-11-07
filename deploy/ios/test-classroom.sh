#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
xcrun swiftc deploy/ios/{ClassroomStore,Classroom,ClassroomGames,ClassroomSmoke}.swift -lsqlite3 -o "$stage/smoke"
"$stage/smoke" build/ios/Resources/Data/classroom.json "$stage" > "$stage/result.json"
uv run --locked python - "$stage/result.json" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from server.content import map_by_id
from server.domain import Event, calculate_mastery, order_options, plan_practice

result = json.loads(Path(sys.argv[1]).read_text())
bundled = json.loads(Path("build/ios/Resources/Data/classroom.json").read_text())
lesson = map_by_id("lessons")[result["lesson"]]
eligible = {item["exercise"]["id"] for item in bundled["eligible"]}
assert result["selected"] == plan_practice([qid for qid in lesson["exerciseIds"] if qid in eligible], [])
question = map_by_id("exercises")[result["question"]]
assert result["options"] == [row["id"] for row in order_options(question["options"], result["instance"])]
expected = calculate_mastery(
    [Event("test", question["type"], False, datetime(2026, 11, 6, 16, 1, tzinfo=UTC))],
    map_by_id("knowledgeItems")[question["primaryKnowledgeId"]]["requiredModes"],
)
assert result["mastery"]["status"] == expected.status
assert result["mastery"]["sampleSize"] == expected.sample_size
assert result["mastery"]["correctCount"] == expected.correct_count
assert result["mastery"]["requiredModes"] == list(expected.required_modes)
print("Swift SQLite recovery, answer replay, hints, skips and round counts passed; Python selection, option order and mastery match")
PY
