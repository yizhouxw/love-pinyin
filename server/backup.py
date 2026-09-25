"""Create verified, permission-restricted SQLite backups for the local household server."""

import argparse
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from server import storage

BACKUP_PREFIX = "love-pinyin-"


def backup_database(destination: Path | None = None, keep: int = 7) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    source = storage.DATABASE_PATH
    if not source.is_file():
        raise FileNotFoundError(f"database does not exist: {source}")

    directory = destination or storage.DATA_DIR.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"{BACKUP_PREFIX}{stamp}.sqlite3"
    temporary = directory / f".{target.name}.{secrets.token_hex(8)}.tmp"

    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source, timeout=10)) as source_db:
            with closing(sqlite3.connect(temporary, timeout=10)) as backup_db:
                source_db.backup(backup_db)
                integrity = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise sqlite3.DatabaseError(f"backup integrity check failed: {integrity}")
                migration_table = backup_db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                if not migration_table:
                    raise sqlite3.DatabaseError("backup is missing schema_migrations")
        with temporary.open("r+b") as result:
            os.fsync(result.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        _prune_backups(directory, keep)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _prune_backups(directory: Path, keep: int) -> None:
    backups = sorted(
        (
            path
            for path in directory.iterdir()
            if path.name.startswith(BACKUP_PREFIX)
            and path.name.endswith(".sqlite3")
            and path.is_file()
            and not path.is_symlink()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for old in backups[keep:]:
        old.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a verified local SQLite backup.")
    parser.add_argument("--keep", type=int, default=7, help="number of newest backups to retain")
    args = parser.parse_args()
    path = backup_database(keep=args.keep)
    print(f"Verified backup created: {path}")


if __name__ == "__main__":
    main()
