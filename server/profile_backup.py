"""Backup validation, version migration and transactional restoration."""

import json
import secrets
from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException

from server.content import load_curriculum, map_by_id
from server.content_history import compatible_revision, exercises_for_revision
from server.domain import (
    business_date,
)
from server.game_policy import GAMES, POLICY, empty_clock, validate_clock
from server.learning_state import _public_exercise
from server.playback_settings import GAP, gap_tenths

IMPORT_MAX_BYTES = 1_048_576


IMPORT_MAX_ATTEMPTS = 50_000


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise HTTPException(422, detail={"code": code})


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _parse_datetime(value: object, code: str) -> datetime:
    _require(isinstance(value, str), code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, detail={"code": code}) from None
    _require(parsed.tzinfo is not None, code)
    return parsed


def _validate_backup(value: object) -> dict:
    _require(isinstance(value, dict), "BACKUP_INVALID")
    migrated_from = value.get("schemaVersion")
    backup = (
        _migrate_v2_backup(value)
        if migrated_from == 2
        else _migrate_v3_backup(value)
        if migrated_from == 3
        else _migrate_v4_backup(value)
        if migrated_from == 4
        else value
    )
    required = {
        "schemaVersion",
        "contentVersion",
        "masteryRuleVersion",
        "exportedAt",
        "profile",
        "attempts",
        "sessions",
        "skippedInstances",
        "reviewPlans",
        "exerciseInstances",
        "assessmentSummaries",
        "note",
    }
    _require(set(backup) == required, "BACKUP_FIELDS_INVALID")
    _require(backup["schemaVersion"] == 5, "BACKUP_VERSION_UNSUPPORTED")
    curriculum = load_curriculum()
    _require(
        compatible_revision(backup["contentVersion"], curriculum["contentVersion"]),
        "CONTENT_VERSION_UNSUPPORTED",
    )
    _require(backup["masteryRuleVersion"] == 1, "MASTERY_RULE_VERSION_UNSUPPORTED")
    _parse_datetime(backup["exportedAt"], "BACKUP_TIME_INVALID")
    _require(isinstance(backup["note"], str) and len(backup["note"]) <= 160, "BACKUP_INVALID")

    profile = backup["profile"]
    _require(
        isinstance(profile, dict)
        and set(profile) - {"gameState"}
        == {
            "id",
            "selectedLessonId",
            "contentVersion",
            "revision",
            "roundsSinceBreak",
            "settings",
        },
        "BACKUP_PROFILE_INVALID",
    )
    _require(profile["contentVersion"] == backup["contentVersion"], "BACKUP_PROFILE_INVALID")
    _require(profile["selectedLessonId"] in map_by_id("lessons"), "BACKUP_REFERENCE_INVALID")
    _require(
        type(profile["revision"]) is int and profile["revision"] >= 0, "BACKUP_PROFILE_INVALID"
    )
    _require(
        type(profile["roundsSinceBreak"]) is int and 0 <= profile["roundsSinceBreak"] <= 2,
        "BACKUP_PROFILE_INVALID",
    )
    settings_value = profile["settings"]
    _require(
        isinstance(settings_value, dict)
        and set(settings_value) - {"gameSessionMinutes", "gameDailyMinutes"}
        in (
            {"soundEnabled", "reducedMotion"},
            {"soundEnabled", "reducedMotion", "playbackGapSeconds"},
        ),
        "BACKUP_PROFILE_INVALID",
    )
    _require(
        all(type(settings_value[key]) is bool for key in ("soundEnabled", "reducedMotion")),
        "BACKUP_PROFILE_INVALID",
    )
    try:
        gap_tenths(settings_value.get("playbackGapSeconds", GAP["defaultSeconds"]))
    except ValueError:
        _require(False, "BACKUP_PROFILE_INVALID")

    for key, default, maximum in (
        ("gameSessionMinutes", POLICY["sessionMinutes"], POLICY["sessionMaxMinutes"]),
        ("gameDailyMinutes", POLICY["dailyMinutes"], POLICY["dailyMaxMinutes"]),
    ):
        number = settings_value.get(key, default)
        _require(type(number) is int and 1 <= number <= maximum, "BACKUP_PROFILE_INVALID")
    try:
        validate_clock(profile.get("gameState", empty_clock()))
    except (ValueError, TypeError, OverflowError):
        _require(False, "BACKUP_PROFILE_INVALID")

    arrays = (
        "attempts",
        "sessions",
        "skippedInstances",
        "reviewPlans",
        "exerciseInstances",
        "assessmentSummaries",
    )
    _require(all(isinstance(backup[key], list) for key in arrays), "BACKUP_INVALID")
    _require(len(backup["attempts"]) <= IMPORT_MAX_ATTEMPTS, "BACKUP_TOO_MANY_ATTEMPTS")
    sessions = {}
    for row in backup["sessions"]:
        _require(
            isinstance(row, dict)
            and set(row) - {"gameId"}
            == {"id", "contentVersion", "startedAt", "status", "reviewKnowledgeId"},
            "BACKUP_SESSION_INVALID",
        )
        _require(
            isinstance(row["id"], str) and 8 <= len(row["id"]) <= 100 and row["id"] not in sessions,
            "BACKUP_DUPLICATE_ID",
        )
        _require(
            compatible_revision(row["contentVersion"], backup["contentVersion"])
            and row["status"] in {"active", "finished"},
            "BACKUP_SESSION_INVALID",
        )
        _parse_datetime(row["startedAt"], "BACKUP_TIME_INVALID")
        _require(
            row["reviewKnowledgeId"] is None
            or row["reviewKnowledgeId"] in map_by_id("knowledgeItems"),
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row.get("gameId") is None
            or (isinstance(row.get("gameId"), str) and row["gameId"] in GAMES),
            "BACKUP_SESSION_INVALID",
        )
        sessions[row["id"]] = row

    exercises = map_by_id("exercises")
    lessons = map_by_id("lessons")
    instances = {}
    positions_by_session: dict[str, set[int]] = defaultdict(set)
    instance_fields = {
        "id",
        "exercise_id",
        "lesson_id",
        "content_version",
        "created_at",
        "session_id",
        "hint_used",
        "answered_at",
        "position",
    }
    for row in backup["exerciseInstances"]:
        _require(isinstance(row, dict) and set(row) == instance_fields, "BACKUP_INSTANCE_INVALID")
        _require(
            isinstance(row["id"], str)
            and 8 <= len(row["id"]) <= 100
            and row["id"] not in instances,
            "BACKUP_DUPLICATE_ID",
        )
        _require(
            row["exercise_id"] in exercises and row["lesson_id"] in lessons,
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row["exercise_id"] in lessons[row["lesson_id"]]["exerciseIds"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row["session_id"] in sessions
            and row["content_version"] == sessions[row["session_id"]]["contentVersion"],
            "BACKUP_REFERENCE_INVALID",
        )
        historical = exercises_for_revision(row["content_version"]).get(row["exercise_id"])
        _require(
            historical is not None and historical["lessonId"] == row["lesson_id"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(type(row["position"]) is int and row["position"] >= 0, "BACKUP_INSTANCE_INVALID")
        _require(
            row["position"] not in positions_by_session[row["session_id"]],
            "BACKUP_DUPLICATE_ID",
        )
        positions_by_session[row["session_id"]].add(row["position"])
        _require(
            type(row["hint_used"]) is int and row["hint_used"] in (0, 1), "BACKUP_INSTANCE_INVALID"
        )
        _parse_datetime(row["created_at"], "BACKUP_TIME_INVALID")
        if row["answered_at"] is not None:
            _parse_datetime(row["answered_at"], "BACKUP_TIME_INVALID")
        instances[row["id"]] = row
    for positions in positions_by_session.values():
        _require(positions == set(range(len(positions))), "BACKUP_INSTANCE_INVALID")

    attempt_fields = {
        "id",
        "instance_id",
        "exercise_id",
        "knowledge_id",
        "mode",
        "first_try_correct",
        "hint_used",
        "due_credit",
        "clock_pending",
        "occurred_at",
        "business_date",
        "answer_json",
    }
    attempt_ids = set()
    attempted_instances = set()
    _require(isinstance(backup["attempts"], list), "BACKUP_INVALID")
    for row in backup["attempts"]:
        _require(isinstance(row, dict) and set(row) == attempt_fields, "BACKUP_ATTEMPT_INVALID")
        _require(
            isinstance(row["id"], str)
            and 8 <= len(row["id"]) <= 100
            and row["id"] not in attempt_ids,
            "BACKUP_DUPLICATE_ID",
        )
        attempt_ids.add(row["id"])
        original_instance = instances.get(row["instance_id"])
        _require(original_instance is not None, "BACKUP_REFERENCE_INVALID")
        exercise = exercises_for_revision(original_instance["content_version"]).get(
            row["exercise_id"]
        )
        _require(
            bool(exercise)
            and row["knowledge_id"] == exercise["primaryKnowledgeId"]
            and row["mode"] == exercise["type"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            type(row["first_try_correct"]) is int and row["first_try_correct"] in (0, 1),
            "BACKUP_ATTEMPT_INVALID",
        )
        _require(
            type(row["hint_used"]) is int and row["hint_used"] in (0, 1), "BACKUP_ATTEMPT_INVALID"
        )
        _require(
            type(row["due_credit"]) is int and row["due_credit"] in (0, 1), "BACKUP_ATTEMPT_INVALID"
        )
        _require(
            type(row["clock_pending"]) is int and row["clock_pending"] in (0, 1),
            "BACKUP_ATTEMPT_INVALID",
        )
        _require(not row["clock_pending"] or not row["due_credit"], "BACKUP_ATTEMPT_INVALID")
        _require(isinstance(row["business_date"], str), "BACKUP_ATTEMPT_INVALID")
        try:
            date.fromisoformat(row["business_date"])
        except ValueError:
            raise HTTPException(422, detail={"code": "BACKUP_TIME_INVALID"}) from None
        _parse_datetime(row["occurred_at"], "BACKUP_TIME_INVALID")
        _require(
            isinstance(row["answer_json"], str) and len(row["answer_json"]) <= 4096,
            "BACKUP_ATTEMPT_INVALID",
        )
        try:
            answer = json.loads(row["answer_json"], object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, ValueError, RecursionError):
            raise HTTPException(422, detail={"code": "BACKUP_ATTEMPT_INVALID"}) from None
        _require(isinstance(answer, dict) and set(answer) == {"optionId"}, "BACKUP_ATTEMPT_INVALID")
        instance = instances.get(row["instance_id"])
        _require(
            bool(instance)
            and instance["exercise_id"] == row["exercise_id"]
            and instance["answered_at"] is not None,
            "BACKUP_REFERENCE_INVALID",
        )
        _require(row["instance_id"] not in attempted_instances, "BACKUP_DUPLICATE_ID")
        attempted_instances.add(row["instance_id"])
        _require(row["hint_used"] == instance["hint_used"], "BACKUP_ATTEMPT_INVALID")
        answer_option_id = answer["optionId"]
        correct = answer_option_id == exercise.get("answer", {}).get("optionId")
        _require(
            any(option["id"] == answer_option_id for option in exercise.get("options", [])),
            "BACKUP_ATTEMPT_INVALID",
        )
        _require(
            row["first_try_correct"] == int(correct and not row["hint_used"]),
            "BACKUP_ATTEMPT_INVALID",
        )
        local_day = business_date(_parse_datetime(row["occurred_at"], "BACKUP_TIME_INVALID"))
        _require(row["business_date"] == local_day.isoformat(), "BACKUP_TIME_INVALID")

    skipped_ids = set()
    for row in backup["skippedInstances"]:
        _require(
            isinstance(row, dict) and set(row) == {"instanceId", "sessionId", "skippedAt"},
            "BACKUP_SKIP_INVALID",
        )
        _require(
            row["instanceId"] in instances
            and row["sessionId"] == instances[row["instanceId"]]["session_id"],
            "BACKUP_REFERENCE_INVALID",
        )
        _require(
            row["instanceId"] not in skipped_ids
            and instances[row["instanceId"]]["answered_at"] is None,
            "BACKUP_DUPLICATE_ID",
        )
        skipped_ids.add(row["instanceId"])
        _parse_datetime(row["skippedAt"], "BACKUP_TIME_INVALID")

    knowledge = map_by_id("knowledgeItems")
    review_ids = set()
    for row in backup["reviewPlans"]:
        _require(
            isinstance(row, dict)
            and set(row) == {"knowledge_id", "stage", "due_date", "updated_at"},
            "BACKUP_REVIEW_INVALID",
        )
        _require(
            row["knowledge_id"] in knowledge and row["knowledge_id"] not in review_ids,
            "BACKUP_DUPLICATE_ID",
        )
        review_ids.add(row["knowledge_id"])
        _require(type(row["stage"]) is int and 0 <= row["stage"] <= 3, "BACKUP_REVIEW_INVALID")
        try:
            date.fromisoformat(row["due_date"])
        except (TypeError, ValueError):
            raise HTTPException(422, detail={"code": "BACKUP_TIME_INVALID"}) from None
        _parse_datetime(row["updated_at"], "BACKUP_TIME_INVALID")

    targets = map_by_id("readingTargets")
    for row in backup["assessmentSummaries"]:
        _require(
            isinstance(row, dict)
            and set(row) == {"targetId", "status", "summary", "engineVersion", "createdAt"},
            "BACKUP_ASSESSMENT_INVALID",
        )
        _require(
            isinstance(row["targetId"], str) and row["targetId"] in targets,
            "BACKUP_ASSESSMENT_INVALID",
        )
        _require(
            row["status"] in {"scored", "uncertain", "unsupported", "unavailable"},
            "BACKUP_ASSESSMENT_INVALID",
        )
        if row["status"] == "scored":
            _require(
                type(row["summary"].get("score")) in {int, float}
                and 0 <= row["summary"]["score"] <= 100
                and type(row["summary"].get("confidence")) in {int, float}
                and 0 <= row["summary"]["confidence"] <= 1,
                "BACKUP_ASSESSMENT_INVALID",
            )
        else:
            _require("score" not in row["summary"], "BACKUP_ASSESSMENT_INVALID")
        _require(
            isinstance(row["summary"], dict)
            and set(row["summary"])
            <= {"score", "confidence", "dimensions", "reason", "calibrationVersion"},
            "BACKUP_ASSESSMENT_INVALID",
        )
        _require(
            isinstance(row["engineVersion"], str) and len(row["engineVersion"]) <= 100,
            "BACKUP_ASSESSMENT_INVALID",
        )
        _parse_datetime(row["createdAt"], "BACKUP_TIME_INVALID")
    return {
        **backup,
        "contentVersion": curriculum["contentVersion"],
        "profile": {**backup["profile"], "contentVersion": curriculum["contentVersion"]},
    }


def _migrate_v2_backup(value: dict) -> dict:
    expected = {
        "schemaVersion",
        "contentVersion",
        "masteryRuleVersion",
        "exportedAt",
        "profile",
        "attempts",
        "sessions",
        "skippedInstances",
        "reviewPlans",
        "exerciseInstances",
        "assessmentSummaries",
        "note",
    }
    _require(set(value) == expected, "BACKUP_FIELDS_INVALID")
    _require(isinstance(value.get("profile"), dict), "BACKUP_PROFILE_INVALID")
    profile = value["profile"]
    _require(
        set(profile) == {"id", "selectedLessonId", "contentVersion", "revision", "settings"},
        "BACKUP_PROFILE_INVALID",
    )
    _require(
        isinstance(profile["settings"], dict)
        and set(profile["settings"]) == {"soundEnabled", "reducedMotion"}
        and profile["settings"]["reducedMotion"] is False,
        "BACKUP_PROFILE_INVALID",
    )
    _require(isinstance(value.get("sessions"), list), "BACKUP_INVALID")
    _require(isinstance(value.get("exerciseInstances"), list), "BACKUP_INVALID")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in value["exerciseInstances"]:
        _require(isinstance(item, dict) and "position" not in item, "BACKUP_INSTANCE_INVALID")
        _require(isinstance(item.get("session_id"), str), "BACKUP_INSTANCE_INVALID")
        grouped[item["session_id"]].append(item)
    positions = {}
    for items in grouped.values():
        for index, item in enumerate(
            sorted(items, key=lambda row: (row.get("created_at", ""), row.get("id", "")))
        ):
            positions[item["id"]] = index
    migrated = dict(value)
    migrated["schemaVersion"] = 3
    migrated["profile"] = {
        **profile,
        "roundsSinceBreak": 0,
        "settings": {**profile["settings"], "reducedMotion": False},
    }
    migrated["exerciseInstances"] = [
        {**item, "position": positions.get(item.get("id"), -1)}
        for item in value["exerciseInstances"]
    ]
    return _migrate_v3_backup(migrated)


def _migrate_v3_backup(value: dict) -> dict:
    _require(isinstance(value.get("sessions"), list), "BACKUP_INVALID")
    migrated = dict(value)
    migrated["schemaVersion"] = 4
    migrated["sessions"] = [{**session, "reviewKnowledgeId": None} for session in value["sessions"]]
    return _migrate_v4_backup(migrated)


def _migrate_v4_backup(value: dict) -> dict:
    _require(isinstance(value.get("attempts"), list), "BACKUP_INVALID")
    legacy_attempt_fields = {
        "id",
        "instance_id",
        "exercise_id",
        "knowledge_id",
        "mode",
        "first_try_correct",
        "hint_used",
        "due_credit",
        "occurred_at",
        "business_date",
        "answer_json",
    }
    _require(
        all(
            isinstance(attempt, dict) and set(attempt) == legacy_attempt_fields
            for attempt in value["attempts"]
        ),
        "BACKUP_ATTEMPT_INVALID",
    )
    migrated = dict(value)
    migrated["schemaVersion"] = 5
    migrated["attempts"] = [{**attempt, "clock_pending": 0} for attempt in value["attempts"]]
    return migrated


def _restore_backup(db, household_id: str, device_id: str, backup: dict) -> None:
    db.execute(
        "UPDATE household SET game_state_json=? WHERE id=?",
        (json.dumps(backup["profile"].get("gameState", empty_clock())), household_id),
    )
    db.execute("DELETE FROM request_receipts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM attempts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM skipped_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM exercise_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM sessions WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM review_plans WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM assessment_summaries WHERE household_id=?", (household_id,))

    instance_groups: dict[str, list[dict]] = defaultdict(list)
    for instance in backup["exerciseInstances"]:
        instance_groups[instance["session_id"]].append(instance)
    for session in backup["sessions"]:
        tasks = [
            {
                "instanceId": item["id"],
                "exercise": _public_exercise(
                    exercises_for_revision(item["content_version"])[item["exercise_id"]],
                    instance_id=item["id"],
                ),
            }
            for item in sorted(instance_groups[session["id"]], key=lambda row: row["position"])
        ]
        db.execute(
            """INSERT INTO sessions(id,household_id,device_id,content_version,started_at,
               tasks_json,status,review_knowledge_id,game_id) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],
                household_id,
                device_id,
                session["contentVersion"],
                session["startedAt"],
                json.dumps(tasks, ensure_ascii=False),
                session["status"],
                session["reviewKnowledgeId"],
                session.get("gameId"),
            ),
        )
    for item in backup["exerciseInstances"]:
        db.execute(
            """INSERT INTO exercise_instances(id,household_id,exercise_id,lesson_id,
               content_version,created_at,session_id,hint_used,answered_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                item["id"],
                household_id,
                item["exercise_id"],
                item["lesson_id"],
                item["content_version"],
                item["created_at"],
                item["session_id"],
                item["hint_used"],
                item["answered_at"],
            ),
        )
    for item in backup["attempts"]:
        db.execute(
            """INSERT INTO attempts(id,household_id,device_id,instance_id,exercise_id,
               knowledge_id,mode,first_try_correct,hint_used,due_credit,occurred_at,
               business_date,answer_json,clock_pending) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item["id"],
                household_id,
                device_id,
                item["instance_id"],
                item["exercise_id"],
                item["knowledge_id"],
                item["mode"],
                item["first_try_correct"],
                item["hint_used"],
                item["due_credit"],
                item["occurred_at"],
                item["business_date"],
                item["answer_json"],
                item["clock_pending"],
            ),
        )
    for item in backup["skippedInstances"]:
        db.execute(
            "INSERT INTO skipped_instances(instance_id,household_id,skipped_at) VALUES(?,?,?)",
            (item["instanceId"], household_id, item["skippedAt"]),
        )
    for item in backup["reviewPlans"]:
        db.execute(
            """INSERT INTO review_plans(household_id,knowledge_id,stage,due_date,updated_at)
               VALUES(?,?,?,?,?)""",
            (
                household_id,
                item["knowledge_id"],
                item["stage"],
                item["due_date"],
                item["updated_at"],
            ),
        )
    for item in backup["assessmentSummaries"]:
        db.execute(
            """INSERT INTO assessment_summaries(request_id,household_id,target_id,status,
               summary_json,engine_version,created_at) VALUES(?,?,?,?,?,?,?)""",
            (
                secrets.token_urlsafe(18),
                household_id,
                item["targetId"],
                item["status"],
                json.dumps(item["summary"], ensure_ascii=False),
                item["engineVersion"],
                item["createdAt"],
            ),
        )


def _delete_learning_rows(db, household_id: str) -> None:
    db.execute("DELETE FROM request_receipts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM assessment_summaries WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM attempts WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM skipped_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM exercise_instances WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM sessions WHERE household_id=?", (household_id,))
    db.execute("DELETE FROM review_plans WHERE household_id=?", (household_id,))
