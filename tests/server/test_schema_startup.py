"""Real Uvicorn startup refusal and compatible-backup recovery, on disposable data."""

import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.request import urlopen

from server import storage
from server.backup import backup_database


def test_unknown_schema_stops_real_server_and_compatible_snapshot_recovers(monkeypatch, tmp_path):
    database = tmp_path / "love-pinyin.sqlite3"
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DATABASE_PATH", database)
    env = {**os.environ, "LOVE_PINYIN_DATA_DIR": str(tmp_path)}
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "server.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--no-access-log",
    ]
    root = Path(__file__).resolve().parents[2]

    def healthy_start(label):
        log = tmp_path / f"{label}.log"
        with log.open("w") as output:
            process = subprocess.Popen(command, cwd=root, env=env, stdout=output, stderr=output)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, log.read_text()
                    address = re.search(
                        r"Uvicorn running on (http://127\.0\.0\.1:\d+)", log.read_text()
                    )
                    if address:
                        with urlopen(address[1] + "/api/v1/health", timeout=3) as response:
                            assert response.status == 200
                            assert json.load(response)["storage"] == "sqlite"
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError(f"Server did not become ready: {log.read_text()}")
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.returncode == 0, log.read_text()

    healthy_start("original")
    snapshot = backup_database(tmp_path / "backups")
    with closing(sqlite3.connect(snapshot)) as db:
        original = list(db.iterdump())
    # Represent a newer release with an unknown marker and its own schema/data.
    # This is version-safety fault injection, not a historical-release compatibility claim.
    with closing(sqlite3.connect(database)) as db:
        db.executescript("""
            INSERT INTO schema_migrations VALUES(6,'2026-10-06');
            CREATE TABLE future_only(value TEXT NOT NULL);
            INSERT INTO future_only VALUES('private-future-value');
        """)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    refused = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=15)
    assert refused.returncode != 0
    assert "Unsupported database schema" in refused.stderr
    assert "Application startup failed" in refused.stderr
    assert "Uvicorn running on" not in refused.stderr
    assert "private-future-value" not in refused.stderr
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before

    # Follow the documented stopped-server candidate-check and preserved-file recovery.
    candidate = database.with_suffix(".sqlite3.restore")
    shutil.copyfile(snapshot, candidate)
    os.chmod(candidate, 0o600)
    with closing(sqlite3.connect(f"{candidate.as_uri()}?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        versions = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
        assert versions <= storage.SUPPORTED_SCHEMA_VERSIONS
    preserved = tmp_path / "rejected"
    preserved.mkdir(mode=0o700)
    for path in (
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
    ):
        if path.exists():
            path.rename(preserved / path.name)
    candidate.replace(database)
    healthy_start("recovered")
    with closing(sqlite3.connect(database)) as db:
        assert list(db.iterdump()) == original
    assert hashlib.sha256((preserved / database.name).read_bytes()).hexdigest() == before
