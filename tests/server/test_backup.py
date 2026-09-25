import sqlite3

import pytest

from server import backup, storage


def prepare_database(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "DATABASE_PATH", data_dir / "love-pinyin.sqlite3")
    storage.migrate()
    household = storage.ensure_household("test-content")
    with storage.transaction() as db:
        db.execute(
            "INSERT INTO devices(id,household_id,token_hash,csrf_hash,label,created_at) "
            "VALUES('device-test',?,'token-hash','csrf-hash','测试设备',?)",
            (household["id"], storage.now_iso()),
        )
    return data_dir


def test_backup_is_an_integral_private_snapshot_with_retention(monkeypatch, tmp_path):
    data_dir = prepare_database(monkeypatch, tmp_path)
    backup_dir = tmp_path / "backups"
    first = backup.backup_database(backup_dir, keep=2)
    second = backup.backup_database(backup_dir, keep=2)
    third = backup.backup_database(backup_dir, keep=2)

    assert first != second != third
    assert first.exists() is False
    assert second.exists() is True
    assert third.exists() is True
    assert backup_dir.stat().st_mode & 0o777 == 0o700
    assert second.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(third) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT label FROM devices").fetchone()[0] == "测试设备"
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 4
    assert data_dir.joinpath("love-pinyin.sqlite3").exists()


def test_missing_database_and_invalid_retention_do_not_create_backups(monkeypatch, tmp_path):
    data_dir = tmp_path / "missing-data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "DATABASE_PATH", data_dir / "missing.sqlite3")
    backup_dir = tmp_path / "backups"

    with pytest.raises(FileNotFoundError):
        backup.backup_database(backup_dir)
    assert not backup_dir.exists()

    with pytest.raises(ValueError, match="at least 1"):
        backup.backup_database(backup_dir, keep=0)
    assert not backup_dir.exists()
