"""MATCH-10 application boundary. No experimental model or child audio persistence."""

import json
from functools import lru_cache
from pathlib import Path

from server.content import load_curriculum
from server.daily_reading import load
from server.storage import now_iso, transaction


@lru_cache(maxsize=1)
def targets() -> dict:
    forms = json.loads(
        (
            Path(__file__).resolve().parents[1] / "content" / "pronunciation-practice.json"
        ).read_text()
    )["taskByPronunciationForm"]
    result = {
        row["id"]: {
            "id": row["id"],
            "pinyin": row["pinyin"],
            "task": forms[row["pronunciationForm"]],
        }
        for row in load_curriculum()["readingTargets"]
    }
    for day in load()["days"]:
        for section in day["sections"]:
            for item in section["items"]:
                result[item["id"]] = {
                    "id": item["id"],
                    "pinyin": " ".join(item["syllables"]),
                    "task": "sequence" if len(item["syllables"]) > 1 else "syllable",
                }
    return result


def evaluate(target: dict, payload: bytes) -> dict:
    """Replace only after an acoustic backend passes its separate release gates."""
    return {
        "evidence": "none",
        "toneAssessed": False,
        "status": "unavailable",
        "reason": "not-configured",
        "recognizedPinyin": None,
    }


def assess(target_id: str, request_id: str, payload: bytes, household_id: str | None) -> dict:
    from fastapi import HTTPException

    from server.reading_recognition import decode_pcm

    target = targets().get(target_id)
    if target is None:
        raise HTTPException(404, detail={"code": "PRONUNCIATION_TARGET_NOT_FOUND"})
    # Validate even when the model is unavailable; never pass paths or remote URLs.
    decode_pcm(payload)
    if household_id:
        with transaction() as db:
            row = db.execute(
                "SELECT target_id,result_json FROM pronunciation_attempts "
                "WHERE household_id=? AND request_id=?",
                (household_id, request_id),
            ).fetchone()
            if row:
                if row["target_id"] != target_id:
                    raise HTTPException(409, detail={"code": "PRONUNCIATION_REQUEST_CONFLICT"})
                return json.loads(row["result_json"])
    result = evaluate(target, payload)
    if result["evidence"] not in {"none", "acoustic"}:
        raise RuntimeError("Development evidence cannot enter the product API")
    if result["status"] in {"matched", "retry"} and result["evidence"] != "acoustic":
        raise RuntimeError("A decision requires acoustic evidence")
    context = {
        "contractVersion": 1,
        "requestId": request_id,
        "targetId": target_id,
        "evidence": result["evidence"],
        "toneAssessed": result["toneAssessed"],
    }
    text = result["recognizedPinyin"]
    recognition_status = (
        "recognized"
        if text
        else "unavailable"
        if result["status"] == "unavailable"
        else "uncertain"
    )
    response = {
        "match": {**context, "status": result["status"], "reason": result["reason"]},
        "recognition": {
            **context,
            "status": recognition_status,
            "recognizedPinyin": text,
            "reason": None if text else result["reason"] or "insufficient-evidence",
        },
        "createdAt": now_iso(),
        "saved": bool(household_id and result["evidence"] == "acoustic"),
    }
    if result["evidence"] == "acoustic" and not valid_record(response):
        raise RuntimeError("Invalid acoustic result")
    if response["saved"]:
        with transaction() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO pronunciation_attempts "
                "(household_id,request_id,target_id,result_json,created_at) VALUES(?,?,?,?,?)",
                (household_id, request_id, target_id, json.dumps(response), response["createdAt"]),
            )
            row = db.execute(
                "SELECT target_id,result_json FROM pronunciation_attempts "
                "WHERE household_id=? AND request_id=?",
                (household_id, request_id),
            ).fetchone()
            if row["target_id"] != target_id:
                raise HTTPException(409, detail={"code": "PRONUNCIATION_REQUEST_CONFLICT"})
            if inserted.rowcount:
                db.execute("UPDATE household SET revision=revision+1 WHERE id=?", (household_id,))
            response = json.loads(row["result_json"])
    return response


def valid_record(record: object) -> bool:
    """Validate portable summaries without accepting audio or unbounded arbitrary text."""
    import re
    import unicodedata
    from datetime import datetime

    if not isinstance(record, dict) or set(record) != {
        "match",
        "recognition",
        "createdAt",
        "saved",
    }:
        return False
    match, recognition = record["match"], record["recognition"]
    if not isinstance(match, dict) or not isinstance(recognition, dict):
        return False
    if any(
        not isinstance(value, str)
        for value in (match.get("status"), match.get("evidence"), recognition.get("status"))
    ):
        return False
    if any(
        value is not None and not isinstance(value, str)
        for value in (match.get("reason"), recognition.get("reason"))
    ):
        return False
    context = {"contractVersion", "requestId", "targetId", "evidence", "toneAssessed"}
    if set(match) != context | {"status", "reason"} or set(recognition) != context | {
        "status",
        "reason",
        "recognizedPinyin",
    }:
        return False
    if any(match[key] != recognition[key] for key in context):
        return False
    if (
        type(match["contractVersion"]) is not int
        or match["contractVersion"] != 1
        or match["evidence"] != "acoustic"
        or type(match["toneAssessed"]) is not bool
        or type(record["saved"]) is not bool
        or not isinstance(match["targetId"], str)
        or match["targetId"] not in targets()
        or not isinstance(match["requestId"], str)
        or not re.fullmatch(r"[\w-]{8,80}", match["requestId"])
        or match["status"] not in {"matched", "retry", "uncertain", "unavailable"}
    ):
        return False
    reasons = {
        "unsupported-target",
        "not-configured",
        "invalid-audio",
        "insufficient-evidence",
        "model-unavailable",
        "timeout",
        "busy",
        "network-error",
    }
    if match["status"] in {"matched", "retry"}:
        if match["reason"] is not None:
            return False
    elif match["reason"] not in reasons:
        return False
    if recognition["status"] == "recognized":
        text = recognition["recognizedPinyin"]
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= 500
            or unicodedata.normalize("NFC", text) != text
            or recognition["reason"] is not None
        ):
            return False
    elif (
        recognition["status"] not in {"uncertain", "unavailable"}
        or recognition["recognizedPinyin"] is not None
        or recognition["reason"] not in reasons
    ):
        return False
    try:
        return datetime.fromisoformat(record["createdAt"]).tzinfo is not None
    except (TypeError, ValueError):
        return False
