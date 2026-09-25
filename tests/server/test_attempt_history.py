from server import storage
from server.content import load_curriculum


def _seed_history(
    count: int = 5, prefix: str = "history", only_knowledge_id: str | None = None
) -> tuple[str, list[str]]:
    content = load_curriculum()
    exercise = next(
        row
        for row in content["exercises"]
        if row["type"] in {"symbol-choice", "tone-choice", "blend-choice"}
        and (only_knowledge_id is None or row["primaryKnowledgeId"] == only_knowledge_id)
    )
    knowledge_id = exercise["primaryKnowledgeId"]
    with storage.connect() as db:
        device = db.execute("SELECT id,household_id FROM devices LIMIT 1").fetchone()
    ids = [f"{prefix}-attempt-{index:02d}" for index in range(count)]
    with storage.transaction() as db:
        for index, attempt_id in enumerate(ids):
            session_id = f"{prefix}-session-{index:02d}"
            instance_id = f"{prefix}-instance-{index:02d}"
            occurred_at = f"2026-09-26T00:{index // 2:02d}:00+00:00"
            db.execute(
                """INSERT INTO sessions(id,household_id,device_id,content_version,started_at,
                   tasks_json) VALUES(?,?,?,?,?,?)""",
                (
                    session_id,
                    device["household_id"],
                    device["id"],
                    content["contentVersion"],
                    occurred_at,
                    "[]",
                ),
            )
            db.execute(
                """INSERT INTO exercise_instances(id,household_id,exercise_id,lesson_id,
                   content_version,created_at,session_id) VALUES(?,?,?,?,?,?,?)""",
                (
                    instance_id,
                    device["household_id"],
                    exercise["id"],
                    exercise["lessonId"],
                    content["contentVersion"],
                    occurred_at,
                    session_id,
                ),
            )
            db.execute(
                """INSERT INTO attempts(id,household_id,device_id,instance_id,exercise_id,
                   knowledge_id,mode,first_try_correct,hint_used,due_credit,occurred_at,
                   business_date,answer_json,clock_pending) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id,
                    device["household_id"],
                    device["id"],
                    instance_id,
                    exercise["id"],
                    knowledge_id,
                    exercise["type"],
                    index % 2,
                    0,
                    1,
                    occurred_at,
                    "2026-09-26",
                    "{}",
                    0,
                ),
            )
    return knowledge_id, ids


def test_attempt_history_is_stable_and_cursor_cannot_cross_knowledge_points(paired_client):
    knowledge_id, ids = _seed_history()
    path = f"/api/v1/profiles/knowledge/{knowledge_id}/attempts"
    assert paired_client.get("/api/v1/profiles/progress").json()["attemptCount"] == 5

    first = paired_client.get(path, params={"limit": 2})
    assert first.status_code == 200
    first_page = first.json()
    assert [item["id"] for item in first_page["items"]] == [ids[4], ids[3]]
    assert first_page["hasMore"] is True
    assert first_page["items"][0]["occurredAt"] == "2026-09-26T00:02:00+00:00"
    assert first_page["items"][0]["firstTryCorrect"] is False

    second = paired_client.get(path, params={"limit": 2, "cursor": first_page["nextCursor"]})
    assert second.status_code == 200
    second_page = second.json()
    assert [item["id"] for item in second_page["items"]] == [ids[2], ids[1]]
    assert second_page["hasMore"] is True

    third = paired_client.get(path, params={"limit": 2, "cursor": second_page["nextCursor"]})
    assert third.status_code == 200
    assert [item["id"] for item in third.json()["items"]] == [ids[0]]
    assert third.json()["nextCursor"] is None

    invalid_cursor = paired_client.get(path, params={"cursor": "not-a-cursor"})
    assert invalid_cursor.status_code == 404
    assert invalid_cursor.json()["detail"]["code"] == "ATTEMPT_CURSOR_NOT_FOUND"

    other_knowledge_id = next(
        item["id"]
        for item in load_curriculum()["knowledgeItems"]
        if item["id"] != knowledge_id
        and any(
            row["primaryKnowledgeId"] == item["id"]
            and row["type"] in {"symbol-choice", "tone-choice", "blend-choice"}
            for row in load_curriculum()["exercises"]
        )
    )
    _, other_ids = _seed_history(1, "other", other_knowledge_id)
    crossed_cursor = paired_client.get(path, params={"cursor": other_ids[0]})
    assert crossed_cursor.status_code == 404
    assert crossed_cursor.json()["detail"]["code"] == "ATTEMPT_CURSOR_NOT_FOUND"

    invalid_knowledge = paired_client.get("/api/v1/profiles/knowledge/unknown/attempts")
    assert invalid_knowledge.status_code == 404
    assert invalid_knowledge.json()["detail"]["code"] == "KNOWLEDGE_NOT_FOUND"

    too_many = paired_client.get(path, params={"limit": 51})
    assert too_many.status_code == 422
