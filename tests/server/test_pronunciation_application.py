"""Control-flow fixtures prove application boundaries, never real acoustic accuracy."""

import io
import wave
from copy import deepcopy

import pytest

from server import pronunciation, storage
from server.profile_backup import _restore_backup, _validate_backup

TARGET = "rt-01-a1"


def audio():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 4000)
    return buffer.getvalue()


def headers(client, request_id="test-request-0001"):
    return {
        "Content-Type": "audio/wav",
        "X-LP-CSRF": client.cookies.get("lp_csrf"),
        "X-LP-Request-Id": request_id,
    }


def post(client, target=TARGET, request_id="test-request-0001", payload=None):
    return client.post(
        f"/api/v1/pronunciation/{target}/assess",
        content=audio() if payload is None else payload,
        headers=headers(client, request_id),
    )


def fixture_engine(monkeypatch, status="matched"):
    monkeypatch.setattr(
        pronunciation,
        "evaluate",
        lambda target, payload: {
            "evidence": "acoustic",
            "toneAssessed": False,
            "status": status,
            "reason": "insufficient-evidence" if status == "uncertain" else None,
            "recognizedPinyin": None
            if status == "uncertain"
            else "ā"
            if status == "matched"
            else "é",
        },
    )


def test_default_unavailable_no_audio_or_false_record(paired_client):
    result = post(paired_client).json()
    assert result["match"]["status"] == "unavailable"
    assert result["match"]["evidence"] == "none"
    assert result["recognition"]["recognizedPinyin"] is None
    assert result["saved"] is False
    assert paired_client.get(f"/api/v1/pronunciation/{TARGET}/history").json()["items"] == []
    with storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pronunciation_attempts").fetchone()[0] == 0


@pytest.mark.parametrize("target", [TARGET, "day-01-s1-i1"])
def test_trusted_results_history_idempotency_and_backup(paired_client, monkeypatch, target):
    fixture_engine(monkeypatch)
    first = post(paired_client, target).json()
    assert first["saved"] is True
    assert post(paired_client, target).json() == first
    fixture_engine(monkeypatch, "retry")
    assert post(paired_client, target, "test-request-0002").status_code == 200
    fixture_engine(monkeypatch, "uncertain")
    assert post(paired_client, target, "test-request-0003").status_code == 200
    history = paired_client.get(f"/api/v1/pronunciation/{target}/history").json()
    assert history["counts"] == {"matched": 1, "retry": 1, "uncertain": 1}
    assert len(history["items"]) == 3
    assert paired_client.get("/api/v1/profiles/progress").json()["attemptCount"] == 0
    backup = paired_client.get("/api/v1/profiles/export").json()
    assert len(backup["pronunciationAttempts"]) == 3
    validated = _validate_backup(backup)
    with storage.transaction() as db:
        household_id = db.execute("SELECT id FROM household").fetchone()[0]
        _restore_backup(
            db, household_id, db.execute("SELECT id FROM devices LIMIT 1").fetchone()[0], validated
        )
    assert paired_client.get(f"/api/v1/pronunciation/{target}/history").json() == history
    response = paired_client.request(
        "DELETE",
        "/api/v1/profiles/data",
        json={"confirmation": "删除我的学习记录"},
        headers={"X-LP-CSRF": paired_client.cookies.get("lp_csrf")},
    )
    assert response.status_code == 200
    assert paired_client.get(f"/api/v1/pronunciation/{target}/history").json()["items"] == []


def test_target_binding_auth_csrf_and_pcm_limits(paired_client, monkeypatch):
    fixture_engine(monkeypatch)
    assert post(paired_client).status_code == 200
    assert post(paired_client, "rt-01-e2").status_code == 409
    assert post(paired_client, "unknown").status_code == 404
    assert post(paired_client, payload=b"invalid").status_code == 422
    assert post(paired_client, payload=b"x" * 960_045).status_code == 413
    url = f"/api/v1/pronunciation/{TARGET}/assess"
    assert (
        paired_client.post(
            url, content=audio(), headers={"X-LP-Request-Id": "test-12345"}
        ).status_code
        == 403
    )
    assert (
        paired_client.post(
            url,
            content=audio(),
            headers={**headers(paired_client), "Origin": "https://foreign.invalid"},
        ).status_code
        == 403
    )
    paired_client.cookies.clear()
    assert paired_client.get(f"/api/v1/pronunciation/{TARGET}/history").status_code == 401


def test_guest_and_mock_never_write_family_results(paired_client, monkeypatch):
    fixture_engine(monkeypatch)
    result = paired_client.post(
        f"/api/v1/guest/pronunciation/{TARGET}/assess",
        content=audio(),
        headers={"Content-Type": "audio/wav", "X-LP-Request-Id": "guest-request-1"},
    ).json()
    assert result["match"]["status"] == "matched" and result["saved"] is False
    with storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pronunciation_attempts").fetchone()[0] == 0
    monkeypatch.setattr(pronunciation, "evaluate", lambda *args: {"evidence": "mock"})
    with pytest.raises(RuntimeError, match="Development evidence"):
        post(paired_client)


@pytest.mark.parametrize(
    "field,value", [("evidence", "mock"), ("status", []), ("reason", {}), ("targetId", "unknown")]
)
def test_backup_rejects_forged_evidence_and_unknown_targets(
    paired_client, monkeypatch, field, value
):
    fixture_engine(monkeypatch)
    post(paired_client)
    backup = paired_client.get("/api/v1/profiles/export").json()
    invalid = deepcopy(backup)
    invalid["pronunciationAttempts"][0]["match"][field] = value
    with pytest.raises(Exception) as error:
        _validate_backup(invalid)
    assert getattr(error.value, "status_code", None) == 422


def test_daily_catalog_retains_initial_and_blending_task_semantics():
    assert pronunciation.targets()["day-03-s1-i1"]["task"] == "initial"
    assert pronunciation.targets()["day-06-s3-i1"]["task"] == "blend"
    assert pronunciation.targets()["rt-02-v1"]["task"] == "final"
