#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
uv run --locked python - "$stage/classroom.json" <<'PYFIXTURE'
import json
import sys
from pathlib import Path

from deploy.ios.prepare import classroom_contract
from server.content import load_curriculum

Path(sys.argv[1]).write_text(json.dumps(classroom_contract(load_curriculum()), ensure_ascii=False))
PYFIXTURE
xcrun swiftc deploy/ios/{ClassroomStore,Classroom,ClassroomGames,GameSmoke}.swift -lsqlite3 -o "$stage/smoke"
"$stage/smoke" "$stage/classroom.json" "$stage" > "$stage/result.json"
uv run --locked python - "$stage/result.json" "$stage/classroom.json" <<'PY'
import json
import sys
from pathlib import Path

from server.game_adaptation import plan_game, settings_for
from server.game_levels import freeze_run, level_for
from server.game_policy import GAMES

result = json.loads(Path(sys.argv[1]).read_text())
bundled = json.loads(Path(sys.argv[2]).read_text())
questions = {row["exercise"]["id"]: row["exercise"] for row in bundled["eligible"]}
for sample in result:
    game_id = sample["game"]
    game = GAMES[game_id]
    lesson = next(lesson for lesson in bundled["lessons"] if lesson["id"] == sample["lesson"])
    eligible = [
        q
        for qid in lesson["exerciseIds"]
        if (q := questions.get(qid))
        and q["type"] in game["modes"]
        and q.get("audioRef")
        and all(not o.get("pictureId") and not o.get("writing") for o in q["options"])
    ]
    eligible.sort(key=lambda q: q["type"] != game["mode"])
    assert sample["selected"] == plan_game(eligible, [], {}, lesson["id"], limit=7)
    assert sample["settings"] == settings_for({}, "auto", "auto")
    route = sample["run"]
    assert route == freeze_run(
        level_for(game_id, None, sample["settings"]["level"]), route["bindings"]
    )
assert {s["game"] for s in result} == set(GAMES)
print("Four Swift game runs match Python selection and routes; pause, clock, restart and scoring passed")
PY
