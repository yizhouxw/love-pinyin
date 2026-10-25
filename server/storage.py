"""Small, transactional SQLite storage for a single household Mac server."""

import json
import os
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from server.game_policy import POLICY, empty_clock
from server.playback_settings import DEFAULT_TENTHS

DATA_DIR = Path(os.environ.get("LOVE_PINYIN_DATA_DIR", "private/data")).expanduser().resolve()
DATABASE_PATH = DATA_DIR / "love-pinyin.sqlite3"
# SQLite migration versions, independent of the portable JSON backup format.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3, 4, 5, 6, 7, 8})
_request_database: ContextVar[sqlite3.Connection | None] = ContextVar(
    "request_database", default=None
)


@contextmanager
def ephemeral_database() -> Iterator[None]:
    """Request-local guest storage; never opens a path or changes the household DB."""
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA temp_store = MEMORY")
    token = _request_database.set(db)
    try:
        migrate()
        yield
    finally:
        _request_database.reset(token)
        db.close()


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now_utc().isoformat(timespec="milliseconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ephemeral = _request_database.get()
    if ephemeral is not None:
        yield ephemeral
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DATA_DIR, 0o700)
    db = sqlite3.connect(DATABASE_PATH, timeout=10, isolation_level=None)
    if DATABASE_PATH.exists():
        os.chmod(DATABASE_PATH, 0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction(immediate: bool = True) -> Iterator[sqlite3.Connection]:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield db
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise


def migrate() -> None:
    with connect() as db:
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone():
            versions = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
            if versions - SUPPORTED_SCHEMA_VERSIONS:
                raise RuntimeError(
                    "Unsupported database schema. 数据库包含本程序不支持的版本；"
                    "请使用匹配的应用版本，或停服后恢复兼容备份。请勿删除迁移记录。"
                )
        db.execute("PRAGMA journal_mode = WAL")
        try:
            # executescript can commit before running. Begin inside the script so
            # all DDL, additive columns and migration markers share one transaction.
            db.executescript("""
            BEGIN EXCLUSIVE;
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS household (
                id TEXT PRIMARY KEY,
                selected_lesson_id TEXT NOT NULL DEFAULT 'lesson-01',
                content_version TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                sound_enabled INTEGER NOT NULL DEFAULT 1,
                reduced_motion INTEGER NOT NULL DEFAULT 0,
                rounds_since_break INTEGER NOT NULL DEFAULT 0,
                last_observed_at TEXT,
                clock_skew_detected INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pairing_codes (
                code_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL,
                used_at TEXT
            );
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE, csrf_hash TEXT NOT NULL, label TEXT NOT NULL,
                is_parent INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, revoked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS exercise_instances (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                exercise_id TEXT NOT NULL, lesson_id TEXT NOT NULL, content_version TEXT NOT NULL,
                created_at TEXT NOT NULL, session_id TEXT NOT NULL,
                hint_used INTEGER NOT NULL DEFAULT 0,
                answered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                device_id TEXT NOT NULL REFERENCES devices(id),
                instance_id TEXT NOT NULL UNIQUE REFERENCES exercise_instances(id),
                exercise_id TEXT NOT NULL, knowledge_id TEXT NOT NULL, mode TEXT NOT NULL,
                first_try_correct INTEGER NOT NULL, hint_used INTEGER NOT NULL,
                due_credit INTEGER NOT NULL,
                occurred_at TEXT NOT NULL, business_date TEXT NOT NULL, answer_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS attempts_household_date
                ON attempts(household_id,business_date,occurred_at);
            CREATE INDEX IF NOT EXISTS attempts_household_knowledge_time
                ON attempts(household_id,knowledge_id,occurred_at DESC,id DESC);
            CREATE TABLE IF NOT EXISTS request_receipts (
                request_id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_plans (
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                knowledge_id TEXT NOT NULL, stage INTEGER NOT NULL, due_date TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(household_id,knowledge_id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                device_id TEXT NOT NULL REFERENCES devices(id), content_version TEXT NOT NULL,
                started_at TEXT NOT NULL, tasks_json TEXT NOT NULL,
                cursor INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS assessment_summaries (
                request_id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL, status TEXT NOT NULL, summary_json TEXT NOT NULL,
                engine_version TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skipped_instances (
                instance_id TEXT PRIMARY KEY REFERENCES exercise_instances(id) ON DELETE CASCADE,
                household_id TEXT NOT NULL REFERENCES household(id) ON DELETE CASCADE,
                skipped_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,CURRENT_TIMESTAMP);
            INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(2,CURRENT_TIMESTAMP);
            """)
            session_columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
            if "review_knowledge_id" not in session_columns:
                db.execute("ALTER TABLE sessions ADD COLUMN review_knowledge_id TEXT")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(household)")}
            if "reduced_motion" not in columns:
                db.execute(
                    "ALTER TABLE household ADD COLUMN reduced_motion INTEGER NOT NULL DEFAULT 0"
                )
            if "playback_gap_tenths" not in columns:
                db.execute(
                    "ALTER TABLE household ADD COLUMN playback_gap_tenths "
                    f"INTEGER NOT NULL DEFAULT {DEFAULT_TENTHS}"
                )
            if "rounds_since_break" not in columns:
                db.execute(
                    "ALTER TABLE household ADD COLUMN rounds_since_break INTEGER NOT NULL DEFAULT 0"
                )
            if "last_observed_at" not in columns:
                db.execute("ALTER TABLE household ADD COLUMN last_observed_at TEXT")
            if "clock_skew_detected" not in columns:
                db.execute(
                    """ALTER TABLE household ADD COLUMN clock_skew_detected
                       INTEGER NOT NULL DEFAULT 0"""
                )
            attempt_columns = {row["name"] for row in db.execute("PRAGMA table_info(attempts)")}
            if "clock_pending" not in attempt_columns:
                db.execute(
                    "ALTER TABLE attempts ADD COLUMN clock_pending INTEGER NOT NULL DEFAULT 0"
                )
            db.execute(
                """INSERT OR IGNORE INTO schema_migrations(version,applied_at)
                   VALUES(3,CURRENT_TIMESTAMP)"""
            )
            db.execute(
                """INSERT OR IGNORE INTO schema_migrations(version,applied_at)
                   VALUES(4,CURRENT_TIMESTAMP)"""
            )
            db.execute(
                """INSERT OR IGNORE INTO schema_migrations(version,applied_at)
                   VALUES(5,CURRENT_TIMESTAMP)"""
            )
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) "
                "VALUES(6,CURRENT_TIMESTAMP)"
            )
            device_columns = {row["name"] for row in db.execute("PRAGMA table_info(devices)")}
            for column in ("model", "pairing_code", "last_connected_at"):
                if column not in device_columns:
                    db.execute(f"ALTER TABLE devices ADD COLUMN {column} TEXT")
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) "
                "VALUES(7,CURRENT_TIMESTAMP)"
            )
            if "game_id" not in session_columns:
                db.execute("ALTER TABLE sessions ADD COLUMN game_id TEXT")
            for column, default in (
                ("game_session_minutes", POLICY["sessionMinutes"]),
                ("game_daily_minutes", POLICY["dailyMinutes"]),
            ):
                if column not in columns:
                    db.execute(
                        f"ALTER TABLE household ADD COLUMN {column} "
                        f"INTEGER NOT NULL DEFAULT {default}"
                    )
            if "game_state_json" not in columns:
                default_clock = json.dumps(empty_clock())
                db.execute(
                    "ALTER TABLE household ADD COLUMN game_state_json "
                    f"TEXT NOT NULL DEFAULT '{default_clock}'"
                )
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) "
                "VALUES(8,CURRENT_TIMESTAMP)"
            )
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise


def ensure_household(content_version: str) -> sqlite3.Row:
    with transaction() as db:
        household = db.execute("SELECT * FROM household ORDER BY created_at LIMIT 1").fetchone()
        if not household:
            db.execute(
                "INSERT INTO household(id,content_version,created_at) VALUES(?,?,?)",
                (secrets.token_urlsafe(18), content_version, now_iso()),
            )
            household = db.execute("SELECT * FROM household LIMIT 1").fetchone()
        elif household["content_version"] != content_version:
            db.execute(
                "UPDATE household SET content_version=?,revision=revision+1 WHERE id=?",
                (content_version, household["id"]),
            )
            household = db.execute(
                "SELECT * FROM household WHERE id=?", (household["id"],)
            ).fetchone()
        return household


def public_profile(row: sqlite3.Row) -> dict:
    return {
        "id": row["profile_id"] if "profile_id" in row.keys() else row["id"],
        "selectedLessonId": row["selected_lesson_id"],
        "contentVersion": row["content_version"],
        "revision": row["revision"],
        "gameState": json.loads(row["game_state_json"]),
        "settings": {
            "gameSessionMinutes": row["game_session_minutes"],
            "gameDailyMinutes": row["game_daily_minutes"],
            "soundEnabled": bool(row["sound_enabled"]),
            "reducedMotion": bool(row["reduced_motion"]),
            "playbackGapSeconds": row["playback_gap_tenths"] / 10,
        },
        "roundsSinceBreak": row["rounds_since_break"],
    }
