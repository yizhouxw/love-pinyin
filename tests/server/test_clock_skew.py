from datetime import UTC, datetime, timedelta

import pytest

from server import api_dependencies, storage
from server.content import map_by_id
from server.routes import attempts as attempts_routes
from server.routes import progress as progress_routes
from server.routes import sessions


def _headers(client):
    return {"X-LP-CSRF": client.cookies.get("lp_csrf")}


@pytest.mark.parametrize("resolution", ["discard", "keep-unscored"])
def test_clock_rollback_records_uncredited_attempt_until_parent_resolves(
    paired_client, monkeypatch, resolution
):
    current = datetime.now(UTC).replace(microsecond=0)

    class ControlledDateTime(datetime):
        value = current

        @classmethod
        def now(cls, tz=None):
            return cls.value if tz is None else cls.value.astimezone(tz)

    monkeypatch.setattr(api_dependencies, "datetime", ControlledDateTime)
    monkeypatch.setattr(sessions, "datetime", ControlledDateTime)
    monkeypatch.setattr(attempts_routes, "datetime", ControlledDateTime)
    monkeypatch.setattr(progress_routes, "datetime", ControlledDateTime)

    household_id = paired_client.get("/api/v1/bootstrap").json()["profile"]["id"]
    with storage.transaction() as db:
        db.execute(
            "UPDATE household SET last_observed_at=? WHERE id=?",
            ((current + timedelta(minutes=15)).isoformat(), household_id),
        )

    headers = _headers(paired_client)
    session_response = paired_client.post(
        "/api/v1/sessions", json={"lessonId": "lesson-01"}, headers=headers
    )
    assert session_response.status_code == 200
    task = session_response.json()["tasks"][0]
    question = map_by_id("exercises")[task["exercise"]["id"]]
    answer = paired_client.post(
        f"/api/v1/instances/{task['instanceId']}/answer",
        json={
            "requestId": "clock-pending-answer",
            "answerOptionId": question["answer"]["optionId"],
        },
        headers=headers,
    )
    assert answer.status_code == 200
    assert answer.json()["clockPending"] is True
    assert answer.json()["creditedForMastery"] is False
    progress = paired_client.get("/api/v1/profiles/progress").json()
    assert progress["clockSkewDetected"] is True
    assert progress["pendingClockAttempts"] == 1
    assert (
        next(
            item["sampleSize"]
            for item in progress["mastery"]
            if item["knowledgeId"] == question["primaryKnowledgeId"]
        )
        == 0
    )
    exported_pending = paired_client.get("/api/v1/profiles/export").json()
    assert exported_pending["schemaVersion"] == 5
    assert exported_pending["attempts"][0]["clock_pending"] == 1

    blocked = paired_client.post(
        "/api/v1/profiles/clock-pending/resolve",
        json={"resolution": resolution, "confirmation": "删除待校时练习"},
        headers=headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "CLOCK_NOT_RESTORED"

    ControlledDateTime.value = current + timedelta(minutes=11)
    confirmation = "删除待校时练习" if resolution == "discard" else "保留为不计分练习"
    resolved = paired_client.post(
        "/api/v1/profiles/clock-pending/resolve",
        json={"resolution": resolution, "confirmation": confirmation},
        headers=headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved"] == 1
    progress = paired_client.get("/api/v1/profiles/progress").json()
    assert progress["clockSkewDetected"] is False
    assert progress["pendingClockAttempts"] == 0
    exported_resolved = paired_client.get("/api/v1/profiles/export").json()

    with storage.connect() as db:
        attempt = db.execute(
            "SELECT due_credit,clock_pending FROM attempts WHERE household_id=?",
            (household_id,),
        ).fetchone()
        receipt = db.execute(
            "SELECT COUNT(*) FROM request_receipts WHERE request_id='clock-pending-answer'"
        ).fetchone()[0]
        instance = db.execute(
            "SELECT answered_at FROM exercise_instances WHERE id=?", (task["instanceId"],)
        ).fetchone()
    if resolution == "discard":
        assert attempt is None
        assert receipt == 0
        assert instance["answered_at"] is None
    else:
        assert tuple(attempt) == (0, 0)
        assert receipt == 1
        assert exported_resolved["attempts"][0]["clock_pending"] == 0
