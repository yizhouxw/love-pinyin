import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import sync_standard_audio as setup


def command(path: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def repository(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    command(repo, "init", "-b", "main")
    command(repo, "config", "user.name", "Setup Test")
    command(repo, "config", "user.email", "setup@example.invalid")
    (repo / "a.mp3").write_bytes(b"pinned-fixture")
    command(repo, "add", ".")
    command(repo, "commit", "-m", "pinned")
    pinned = command(repo, "rev-parse", "HEAD")
    (repo / "a.mp3").write_bytes(b"changed-upstream")
    command(repo, "commit", "-am", "new upstream")
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo), str(remote)], check=True, capture_output=True
    )
    command(repo, "remote", "add", "origin", str(remote))
    command(repo, "fetch", "origin")
    command(repo, "branch", "--set-upstream-to=origin/main", "main")
    monkeypatch.setattr(
        setup.source_audio,
        "catalog",
        lambda: {"repository": str(remote).removesuffix(".git"), "commit": pinned, "assets": []},
    )
    monkeypatch.setattr(setup.source_audio, "installed", lambda: False)
    monkeypatch.setattr(setup, "load_curriculum", lambda: {"audioRequirements": []})
    return repo, pinned


def test_git_import_uses_content_pin_instead_of_upstream_head(tmp_path, monkeypatch):
    repo, pinned = repository(tmp_path, monkeypatch)
    imports = []

    def imported(archive, *args, archive_digest):
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_digest
        with zipfile.ZipFile(archive) as data:
            imports.append(data.read(f"PinYinSound-{pinned}/a.mp3"))
        return {"commit": pinned}

    monkeypatch.setattr(setup, "prepare", imported)
    monkeypatch.setattr(setup, "prepare_daily", imported)
    result = setup.sync(repo)
    assert result["commit"] == pinned
    assert imports == [b"pinned-fixture", b"pinned-fixture"]
    assert command(repo, "show", "HEAD:a.mp3") == "changed-upstream"


def test_git_sync_refuses_unknown_origin_and_local_changes(tmp_path, monkeypatch):
    repo, _ = repository(tmp_path, monkeypatch)
    (repo / "a.mp3").write_bytes(b"local-edit")
    with pytest.raises(ValueError, match="local changes"):
        setup.sync(repo)
    assert (repo / "a.mp3").read_bytes() == b"local-edit"
    command(repo, "remote", "set-url", "origin", "https://example.invalid/untrusted.git")
    with pytest.raises(ValueError, match="unexpected Git origin"):
        setup.sync(repo)
