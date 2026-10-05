"""Stable presentation must not let content positions determine learning results."""

from collections import Counter
from copy import deepcopy
from datetime import date, timedelta

import pytest

from server import api, storage
from server.content import map_by_id
from server.domain import order_options


def post(client, path, body=None):
    response = client.post(
        f"/api/v1{path}",
        json=body or {},
        headers={"X-LP-CSRF": client.cookies.get("lp_csrf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("size", [2, 3, 4])
def test_v1_permutations_preserve_assets_and_cover_every_position(size):
    options = [
        {"id": chr(97 + i), "label": f"候选{i}", "pictureId": f"image-{i}"} for i in range(size)
    ]
    original = deepcopy(options)
    if size == 4:
        # Published v1 protocol vector: changing this would reorder restored backups.
        assert [o["id"] for o in order_options(options, "op1_" + "0" * 24)] == ["c", "a", "d", "b"]
    positions = {option["id"]: Counter() for option in options}
    for seed in range(240):
        instance_id = f"op1_{seed:024d}"
        result = order_options(options, instance_id)
        assert result == order_options(list(reversed(options)), instance_id)
        assert result == order_options(result, instance_id)
        assert sorted(result, key=lambda o: o["id"]) == original
        for index, option in enumerate(result):
            positions[option["id"]][index] += 1
    assert options == original
    for counts in positions.values():
        assert set(counts) == set(range(size))
        # Fixed sample, broad bound: catches unchanged/rotated-by-content regressions,
        # without claiming exact uniformity or using random/flaky test inputs.
        assert max(counts.values()) < 240 * 0.65


@pytest.mark.parametrize("instance_id", ["legacy-instance", "a" * 24, "op1_" + "a" * 20])
def test_legacy_ids_keep_authored_order_even_with_matching_prefix(instance_id):
    options = [{"id": "b"}, {"id": "a"}, {"id": "c"}]
    assert order_options(options, instance_id) == options
    assert order_options([], instance_id) == []
    assert order_options(options[:1], instance_id) == options[:1]


@pytest.mark.parametrize("legacy", [False, True])
def test_family_refresh_and_backup_restore_keep_order_and_option_id_score(
    paired_client, monkeypatch, legacy
):
    client = paired_client
    with monkeypatch.context() as patch:
        if legacy:
            patch.setattr(api, "OPTION_ORDER_V1_PREFIX", "")
        session = post(client, "/sessions")
    tasks = session["tasks"]
    authored = map_by_id("exercises")
    for task in tasks:
        expected = order_options(authored[task["exercise"]["id"]]["options"], task["instanceId"])
        assert task["exercise"]["options"] == expected
        assert len(task["instanceId"]) == (24 if legacy else 28)
        assert "answer" not in task["exercise"]
    assert client.get("/api/v1/sessions/current").json()["tasks"] == tasks
    task = tasks[0]
    answer_id = authored[task["exercise"]["id"]]["answer"]["optionId"]
    answer = post(
        client,
        f"/instances/{task['instanceId']}/answer",
        {
            "requestId": "option-order-answer",
            "answerOptionId": answer_id,
        },
    )
    assert answer["correct"] is True
    backup = client.get("/api/v1/profiles/export").json()
    preview = post(client, "/profiles/import-preview", backup)
    post(
        client,
        "/profiles/import",
        {
            "previewToken": preview["previewToken"],
            "sha256": preview["sha256"],
            "expectedRevision": preview["revision"],
        },
    )
    assert client.get("/api/v1/sessions/current").json()["tasks"] == tasks
    assert client.get("/api/v1/profiles/export").json()["attempts"] == backup["attempts"]


def test_review_tasks_freeze_v1_order(paired_client):
    client = paired_client
    household = client.get("/api/v1/bootstrap").json()["profile"]["id"]
    with storage.transaction() as db:
        db.execute("UPDATE household SET selected_lesson_id='lesson-02' WHERE id=?", (household,))
        db.execute(
            "INSERT INTO review_plans(household_id,knowledge_id,stage,due_date,updated_at) "
            "VALUES(?,?,?,?,?)",
            (
                household,
                "k-tone-4",
                0,
                (date.today() - timedelta(days=1)).isoformat(),
                storage.now_iso(),
            ),
        )
    session = post(client, "/reviews/k-tone-4/sessions")
    assert len(session["tasks"]) == 2
    for task in session["tasks"]:
        assert task["instanceId"].startswith("op1_") and len(task["instanceId"]) == 28
        assert task["exercise"]["options"] == order_options(
            map_by_id("exercises")[task["exercise"]["id"]]["options"], task["instanceId"]
        )
    assert client.get("/api/v1/sessions/current").json()["tasks"] == session["tasks"]


def test_guest_reconstruction_keeps_order_without_household_writes(test_client):
    with storage.connect() as db:
        before = list(db.iterdump())

    def operate(path, state=None, method="GET", body=None):
        response = test_client.post(
            "/api/v1/guest/operate",
            json={
                "path": path,
                "state": state,
                "method": method,
                "body": body or {},
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    created = operate("/sessions", method="POST")
    tasks = created["result"]["tasks"]
    for task in tasks:
        assert task["instanceId"].startswith("op1_")
    resumed = operate("/sessions/current", created["state"])
    assert resumed["result"]["tasks"] == tasks
    task = tasks[0]
    correct = map_by_id("exercises")[task["exercise"]["id"]]["answer"]["optionId"]
    answered = operate(
        f"/instances/{task['instanceId']}/answer",
        resumed["state"],
        "POST",
        {
            "requestId": "guest-option-order",
            "answerOptionId": correct,
        },
    )
    assert answered["result"]["correct"] is True
    assert operate("/sessions/current", answered["state"])["result"]["tasks"] == tasks
    with storage.connect() as db:
        assert list(db.iterdump()) == before
