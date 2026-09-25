from datetime import UTC, date, datetime, timedelta

from server import storage
from server.api import _review_recommendations
from server.domain import business_date


def _curriculum():
    return {
        "lessons": [
            {
                "id": "lesson-01",
                "order": 1,
                "title": "第一课",
                "exerciseIds": ["a", "b", "c", "c2"],
            },
            {
                "id": "lesson-02",
                "order": 2,
                "title": "第二课",
                "exerciseIds": ["d", "e", "f", "f2"],
            },
            {"id": "lesson-03", "order": 3, "title": "第三课", "exerciseIds": ["g", "h"]},
        ],
        "knowledgeItems": [
            {"id": "k-a", "lessonId": "lesson-01", "symbol": "ā"},
            {"id": "k-b", "lessonId": "lesson-02", "symbol": "b"},
            {"id": "k-c", "lessonId": "lesson-02", "symbol": "c"},
            {"id": "k-d", "lessonId": "lesson-02", "symbol": "d"},
            {"id": "k-future", "lessonId": "lesson-03", "symbol": "f"},
        ],
        "exercises": [
            {"id": "a", "primaryKnowledgeId": "k-a", "type": "symbol-choice"},
            {"id": "b", "primaryKnowledgeId": "k-a", "type": "tone-choice"},
            {"id": "c", "primaryKnowledgeId": "k-a", "type": "read-aloud"},
            {"id": "c2", "primaryKnowledgeId": "k-a", "type": "symbol-choice"},
            {"id": "d", "primaryKnowledgeId": "k-b", "type": "symbol-choice"},
            {"id": "e", "primaryKnowledgeId": "k-b", "type": "blend-choice"},
            {"id": "f", "primaryKnowledgeId": "k-c", "type": "symbol-choice"},
            {"id": "f2", "primaryKnowledgeId": "k-c", "type": "tone-choice"},
            {"id": "g", "primaryKnowledgeId": "k-future", "type": "symbol-choice"},
            {"id": "h", "primaryKnowledgeId": "k-future", "type": "tone-choice"},
        ],
    }


def test_recommendations_prioritize_overdue_then_lesson_and_id_and_cap_three():
    today = date(2026, 9, 26)
    plans = [
        {"knowledge_id": key, "due_date": (today - timedelta(days=days)).isoformat()}
        for key, days in [("k-b", 2), ("k-d", 2), ("k-a", 5), ("k-c", 2), ("k-future", 20)]
    ]
    curriculum = _curriculum()
    curriculum["knowledgeItems"].append({"id": "k-d", "lessonId": "lesson-02", "symbol": "d"})
    curriculum["exercises"].extend(
        [
            {"id": "d2", "primaryKnowledgeId": "k-d", "type": "symbol-choice"},
            {"id": "e2", "primaryKnowledgeId": "k-d", "type": "tone-choice"},
        ]
    )
    curriculum["lessons"][1]["exerciseIds"].extend(["d2", "e2"])

    result = _review_recommendations(curriculum, "lesson-02", plans, set(), today)

    assert [item["knowledgeId"] for item in result] == ["k-a", "k-b", "k-c"]
    assert [item["overdueDays"] for item in result] == [5, 2, 2]
    assert all("lessonOrder" not in item for item in result)


def test_recommendation_requires_two_uncredited_objective_questions():
    curriculum = _curriculum()
    plan = [{"knowledge_id": "k-a", "due_date": "2026-09-26"}]
    all_credit = {("k-a", "a"), ("k-a", "b")}
    one_credit = {("k-a", "a")}

    assert (
        _review_recommendations(curriculum, "lesson-01", plan, all_credit, date(2026, 9, 26)) == []
    )
    assert [
        item["knowledgeId"]
        for item in _review_recommendations(
            curriculum, "lesson-01", plan, one_credit, date(2026, 9, 26)
        )
    ] == ["k-a"]
    assert _review_recommendations(curriculum, "missing", plan, set(), date(2026, 9, 26)) == []


def test_progress_api_returns_server_prioritized_recommendations(paired_client):
    household_id = paired_client.get("/api/v1/bootstrap").json()["profile"]["id"]
    today = business_date(datetime.now(UTC))
    with storage.transaction() as db:
        db.execute(
            "UPDATE household SET selected_lesson_id='lesson-02' WHERE id=?", (household_id,)
        )
        db.execute(
            """INSERT INTO review_plans(household_id,knowledge_id,stage,due_date,updated_at)
               VALUES(?,?,?,?,?)""",
            (household_id, "k-tone-4", 0, (today - timedelta(days=3)).isoformat(), "2026-09-01"),
        )

    response = paired_client.get("/api/v1/profiles/progress")

    assert response.status_code == 200
    recommendations = response.json()["reviewRecommendations"]
    assert recommendations
    assert recommendations[0]["knowledgeId"] == "k-tone-4"
    assert recommendations[0]["overdueDays"] == 3
    assert len(recommendations) <= 3
