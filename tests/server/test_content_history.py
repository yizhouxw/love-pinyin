from copy import deepcopy
from datetime import date, timedelta

import pytest

from server import content, learning_state, profile_backup, storage
from server.content_history import archived_exercises, revision_index
from server.routes import resources, sessions
from tests.server.test_guest_access import operate, snapshot
from tests.server.test_profile_import import confirm, preview

OLD = "2026.10.05.10"


def headers(client):
    return {"X-LP-CSRF": client.cookies.get("lp_csrf")}


def historical_backup(client, monkeypatch, legacy_ids=True):
    current = content.load_curriculum()
    older = deepcopy(current)
    older["contentVersion"] = OLD
    older["exercises"] = list(archived_exercises(OLD).values())
    ids = {q["id"] for q in older["exercises"]}
    for lesson in older["lessons"]:
        lesson["exerciseIds"] = [qid for qid in lesson["exerciseIds"] if qid in ids]
    with monkeypatch.context() as patch:
        if legacy_ids:
            # Reproduce IDs produced by the historical application, before ordering v1.
            patch.setattr(sessions, "OPTION_ORDER_V1_PREFIX", "")
        patch.setattr(content, "load_curriculum", lambda: older)
        for module in (learning_state, profile_backup, resources, sessions):
            patch.setattr(module, "load_curriculum", lambda: older)
        household = storage.ensure_household(OLD)
        with storage.transaction() as db:
            db.execute("UPDATE household SET selected_lesson_id='lesson-14'")
            db.execute(
                "INSERT INTO review_plans VALUES(?,?,?,?,?)",
                (
                    household["id"],
                    "rule-front-back-nasal",
                    0,
                    (date.today() - timedelta(days=1)).isoformat(),
                    storage.now_iso(),
                ),
            )
        session = client.post(
            "/api/v1/reviews/rule-front-back-nasal/sessions", json={}, headers=headers(client)
        )
        assert session.status_code == 200, session.text
        assert [t["exercise"]["id"] for t in session.json()["tasks"]] == ["q-14-06", "q-14-30"]
        first = session.json()["tasks"][0]
        response = client.post(
            f"/api/v1/instances/{first['instanceId']}/answer",
            json={"requestId": "history-first-answer", "answerOptionId": "a"},
            headers=headers(client),
        )
        assert response.status_code == 200 and response.json()["correct"]
        backup = client.get("/api/v1/profiles/export").json()
    storage.ensure_household(current["contentVersion"])
    return backup


def test_registered_snapshots_have_valid_hashes_and_current_question_identity():
    rows = revision_index()
    assert len(rows) >= 10
    for row in rows:
        assert archived_exercises(row["contentVersion"])
    current = content.load_curriculum()
    if current["contentVersion"] in {r["contentVersion"] for r in rows}:
        assert archived_exercises(current["contentVersion"]) == content.map_by_id("exercises")


@pytest.mark.parametrize("export_after_upgrade", [False, True])
def test_old_and_mixed_backup_restore_original_question_and_result(
    paired_client, monkeypatch, export_after_upgrade
):
    client = paired_client
    old = historical_backup(client, monkeypatch)
    backup = client.get("/api/v1/profiles/export").json() if export_after_upgrade else old
    before = client.get("/api/v1/profiles/progress").json()
    result = preview(client, backup)
    assert result.status_code == 200, result.text
    assert client.get("/api/v1/profiles/progress").json() == before
    assert confirm(client, result.json()).status_code == 200
    resumed = client.get("/api/v1/sessions/current").json()
    assert resumed["contentVersion"] == OLD
    assert next(iter(resumed["results"].values()))["correct"]
    second = resumed["tasks"][1]
    assert second["exercise"]["options"][1]["label"] == "in / ing"
    assert content.map_by_id("exercises")["q-14-30"]["options"][1]["label"] == "en / eng"
    answer = client.post(
        f"/api/v1/instances/{second['instanceId']}/answer",
        json={"requestId": "history-second-answer", "answerOptionId": "b"},
        headers=headers(client),
    )
    assert answer.status_code == 200 and answer.json()["correct"]
    exported = client.get("/api/v1/profiles/export").json()
    assert len(exported["attempts"]) == 2
    assert exported["sessions"][0]["contentVersion"] == OLD
    assert exported["contentVersion"] == content.load_curriculum()["contentVersion"]
    assert preview(client, exported).status_code == 200


@pytest.mark.parametrize("corrupt", ["header", "session", "instance", "absent-question", "answer"])
def test_history_rejects_unknown_mixed_or_invalid_state_without_writes(
    paired_client, monkeypatch, corrupt
):
    backup = historical_backup(paired_client, monkeypatch)
    before = paired_client.get("/api/v1/profiles/export").json()
    before.pop("exportedAt")
    if corrupt == "header":
        backup["contentVersion"] = "future"
    elif corrupt == "session":
        backup["sessions"][0]["contentVersion"] = "future"
    elif corrupt == "instance":
        backup["exerciseInstances"][0]["content_version"] = "2026.10.05.9"
    elif corrupt == "absent-question":
        backup["exerciseInstances"][0]["exercise_id"] = "q-14-120"
    else:
        backup["attempts"][0]["first_try_correct"] = 0
    assert preview(paired_client, backup).status_code == 422
    after = paired_client.get("/api/v1/profiles/export").json()
    after.pop("exportedAt")
    assert after == before


def test_guest_old_tab_state_upgrades_without_household_writes(paired_client):
    before = snapshot()
    guest = operate(paired_client, "/sessions", method="POST")
    old = guest["state"]
    old["contentVersion"] = old["profile"]["contentVersion"] = OLD
    for row in old["sessions"]:
        row["contentVersion"] = OLD
    for row in old["exerciseInstances"]:
        row["content_version"] = OLD
    resumed = operate(paired_client, "/sessions/current", old)
    assert resumed["state"]["contentVersion"] == content.load_curriculum()["contentVersion"]
    assert resumed["result"]["contentVersion"] == OLD
    task = resumed["result"]["tasks"][0]
    correct = archived_exercises(OLD)[task["exercise"]["id"]]["answer"]["optionId"]
    answered = operate(
        paired_client,
        f"/instances/{task['instanceId']}/answer",
        resumed["state"],
        "POST",
        {"requestId": "old-tab-answer-001", "answerOptionId": correct},
    )
    assert answered["result"]["correct"]
    assert len(operate(paired_client, "/bootstrap", answered["state"])["state"]["attempts"]) == 1
    assert snapshot() == before


def test_corrupt_history_never_falls_back_to_current_questions(monkeypatch, tmp_path):
    import json

    from server import content_history

    original_root = content_history.HISTORY_DIR
    row = next(r for r in revision_index() if r["contentVersion"] == OLD)
    (tmp_path / "index.json").write_text(json.dumps({"version": 1, "revisions": [row]}))
    (tmp_path / row["file"]).write_bytes((original_root / row["file"]).read_bytes() + b" ")
    content_history.revision_index.cache_clear()
    content_history.archived_exercises.cache_clear()
    try:
        monkeypatch.setattr(content_history, "HISTORY_DIR", tmp_path)
        with pytest.raises(ValueError, match="digest mismatch"):
            content_history.exercises_for_revision(OLD)
        assert content_history.revision_order("../curriculum") is None
    finally:
        content_history.revision_index.cache_clear()
        content_history.archived_exercises.cache_clear()


def test_v1_order_restores_from_historical_content_without_using_current_options(
    paired_client, monkeypatch
):
    client = paired_client
    backup = historical_backup(client, monkeypatch, legacy_ids=False)
    frozen = client.get("/api/v1/sessions/current").json()["tasks"]
    assert all(task["instanceId"].startswith("op1_") for task in frozen)
    result = preview(client, backup)
    assert result.status_code == 200
    assert confirm(client, result.json()).status_code == 200
    assert client.get("/api/v1/sessions/current").json()["tasks"] == frozen
    old_labels = {option["id"]: option["label"] for option in frozen[1]["exercise"]["options"]}
    assert old_labels["b"] == "in / ing"
