import sqlite3

import pytest

from server import storage


def test_migration_adds_motion_and_rest_fields_to_an_existing_household(monkeypatch, tmp_path):
    database = tmp_path / "existing.sqlite3"
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DATABASE_PATH", database)
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_migrations VALUES(1,'2026-01-01');
            INSERT INTO schema_migrations VALUES(2,'2026-01-01');
            CREATE TABLE household(
              id TEXT PRIMARY KEY, selected_lesson_id TEXT NOT NULL, content_version TEXT NOT NULL,
              revision INTEGER NOT NULL, sound_enabled INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            INSERT INTO household VALUES('family','lesson-01','v1',4,1,'2026-01-01T00:00:00+00:00');
            """
        )

    storage.migrate()
    with storage.connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(household)")}
        household = db.execute("SELECT * FROM household WHERE id='family'").fetchone()
        version = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert {"reduced_motion", "rounds_since_break"} <= columns
    assert household["reduced_motion"] == 0
    assert household["rounds_since_break"] == 0
    assert version == 4
    with storage.connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
    assert "review_knowledge_id" in columns


def test_failed_migration_rolls_back_schema_columns_and_version(monkeypatch, tmp_path):
    database = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DATABASE_PATH", database)
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_migrations VALUES(1,'2026-01-01');
            INSERT INTO schema_migrations VALUES(2,'2026-01-01');
            CREATE TABLE household(
              id TEXT PRIMARY KEY, selected_lesson_id TEXT NOT NULL, content_version TEXT NOT NULL,
              revision INTEGER NOT NULL, sound_enabled INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            INSERT INTO household VALUES('family','lesson-01','v1',4,1,'2026-01-01T00:00:00+00:00');
            CREATE TABLE sessions(id TEXT PRIMARY KEY, tasks_json TEXT NOT NULL);
            CREATE TRIGGER fail_version_four BEFORE INSERT ON schema_migrations
            WHEN NEW.version=4 BEGIN SELECT RAISE(ABORT,'injected migration failure'); END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected migration failure"):
        storage.migrate()

    with storage.connect() as db:
        versions = [
            row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        household_columns = {row["name"] for row in db.execute("PRAGMA table_info(household)")}
        session_columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
        household = db.execute("SELECT id,revision FROM household").fetchone()
        new_tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
        ).fetchone()

    assert versions == [1, 2]
    assert "reduced_motion" not in household_columns
    assert "rounds_since_break" not in household_columns
    assert "review_knowledge_id" not in session_columns
    assert tuple(household) == ("family", 4)
    assert new_tables is None
