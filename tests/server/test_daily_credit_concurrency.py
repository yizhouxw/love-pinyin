from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from fastapi.testclient import TestClient

from server import api, storage
from server.content import map_by_id
from server.main import app


def test_same_exercise_credit_is_atomic_per_shanghai_day_across_devices(paired_client, monkeypatch):
    parent = paired_client
    code = parent.post(
        "/api/v1/pairing-codes", headers={"X-LP-CSRF": parent.cookies.get("lp_csrf")}
    ).json()["code"]
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50002)) as tablet:
        assert (
            tablet.post("/api/v1/pair", json={"code": code, "label": "同题测试平板"}).status_code
            == 200
        )

        # Keep the frozen instant after the fixture's real last-observed time,
        # while staying on the same Asia/Shanghai boundary across run dates.
        utc_day = datetime.now(UTC).date() + timedelta(days=1)
        before_midnight = datetime(utc_day.year, utc_day.month, utc_day.day, 15, 59, 59, tzinfo=UTC)

        class ControlledDateTime(datetime):
            value = before_midnight

            @classmethod
            def now(cls, tz=None):
                return cls.value if tz is None else cls.value.astimezone(tz)

        monkeypatch.setattr(api, "datetime", ControlledDateTime)

        def headers(client):
            return {"X-LP-CSRF": client.cookies.get("lp_csrf")}

        parent_session = parent.post(
            "/api/v1/sessions", json={"lessonId": "lesson-01"}, headers=headers(parent)
        ).json()
        tablet_session = tablet.post(
            "/api/v1/sessions", json={"lessonId": "lesson-01"}, headers=headers(tablet)
        ).json()
        # Freeze another instance before any answer. Normal practice rotates
        # completed questions now; the credit rule still applies to the same
        # frozen exercise when submitted after midnight.
        next_session = parent.post(
            "/api/v1/sessions", json={"lessonId": "lesson-01"}, headers=headers(parent)
        ).json()
        parent_task = parent_session["tasks"][0]
        tablet_task = tablet_session["tasks"][0]
        assert parent_task["exercise"]["id"] == tablet_task["exercise"]["id"]
        exercise_id = parent_task["exercise"]["id"]
        option_id = map_by_id("exercises")[exercise_id]["answer"]["optionId"]
        barrier = Barrier(2)

        def answer(client, task, request_id):
            barrier.wait()
            return client.post(
                f"/api/v1/instances/{task['instanceId']}/answer",
                json={"requestId": request_id, "answerOptionId": option_id},
                headers=headers(client),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(answer, parent, parent_task, "same-day-credit-parent-01")
            second = pool.submit(answer, tablet, tablet_task, "same-day-credit-tablet-01")
            responses = [first.result(), second.result()]
        assert all(response.status_code == 200 for response in responses)
        assert sum(response.json()["creditedForMastery"] for response in responses) == 1

        # UTC 16:00 is the next Asia/Shanghai business day; the same exercise
        # may earn exactly one new credit after that boundary.
        ControlledDateTime.value = before_midnight + timedelta(seconds=1)
        next_task = next_session["tasks"][0]
        assert next_task["exercise"]["id"] == exercise_id
        next_answer = parent.post(
            f"/api/v1/instances/{next_task['instanceId']}/answer",
            json={"requestId": "next-day-credit-parent-01", "answerOptionId": option_id},
            headers=headers(parent),
        )
        assert next_answer.status_code == 200
        assert next_answer.json()["creditedForMastery"] is True

        household_id = parent.get("/api/v1/bootstrap").json()["profile"]["id"]
        with storage.connect() as db:
            rows = db.execute(
                """SELECT business_date,due_credit FROM attempts
                   WHERE household_id=? AND exercise_id=? ORDER BY occurred_at,id""",
                (household_id, exercise_id),
            ).fetchall()
        credits_by_day = defaultdict(int)
        for row in rows:
            credits_by_day[row["business_date"]] += row["due_credit"]
        first_business_day = (before_midnight + timedelta(hours=8)).date()
        next_business_day = first_business_day + timedelta(days=1)
        assert dict(credits_by_day) == {
            first_business_day.isoformat(): 1,
            next_business_day.isoformat(): 1,
        }
