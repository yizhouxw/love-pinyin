"""Explicit Git sync and integrity-checked import of the content-pinned standard audio."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException

from scripts.prepare_daily_reading import prepare as prepare_daily
from scripts.prepare_pinyin_source import prepare
from server import daily_reading, source_audio
from server.content import load_curriculum

ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def sync(repo: Path) -> dict:
    catalog = source_audio.catalog()
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", catalog["repository"] + ".git", str(repo)], check=True, timeout=180
        )
    if git(repo, "remote", "get-url", "origin").removesuffix(".git") != catalog["repository"]:
        raise ValueError("Cached standard audio has an unexpected Git origin")
    if git(repo, "status", "--porcelain"):
        raise ValueError("Cached standard audio has local changes; refusing to overwrite them")
    try:
        git(repo, "pull", "--ff-only")
    except subprocess.SubprocessError:
        git(repo, "cat-file", "-e", catalog["commit"] + "^{commit}")
        print("Upstream sync unavailable; using the existing pinned commit", flush=True)
    git(repo, "cat-file", "-e", catalog["commit"] + "^{commit}")
    targets = {a["id"]: a for a in load_curriculum()["audioRequirements"]}
    ready = source_audio.installed() and all(
        source_audio.available(targets[a["id"]]) for a in catalog["assets"]
    )
    if ready:
        try:
            for asset in daily_reading.load()["assets"]:
                path, digest = daily_reading.registered(asset["id"])
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    ready = False
        except (OSError, HTTPException):
            ready = False
    if ready:
        return {"commit": catalog["commit"], "reused": True}
    with tempfile.TemporaryDirectory(prefix="pinyin-git-") as temporary:
        archive = Path(temporary) / "source.zip"
        git(
            repo,
            "archive",
            "--format=zip",
            f"--prefix=PinYinSound-{catalog['commit']}/",
            f"--output={archive}",
            catalog["commit"],
        )
        # Git ZIP differs from GitHub ZIP; per-member hashes and decode checks remain mandatory.
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        result = prepare(archive, source_audio.SOURCE_DIR, archive_digest=digest)
        prepare_daily(archive, archive_digest=digest)
        return {**result, "transport": "git-archive", "transportSha256": digest}


if __name__ == "__main__":
    print(sync(ROOT / "private" / "upstream" / "PinYinSound"))
