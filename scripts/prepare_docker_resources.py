"""Prepare Docker's audio from the catalog's digest-pinned official archive."""

import tempfile
import urllib.request
from pathlib import Path

from scripts.prepare_daily_reading import prepare as prepare_daily
from scripts.prepare_pinyin_source import MAX_ARCHIVE, prepare
from server import source_audio


def main():
    with tempfile.TemporaryDirectory(prefix="docker-audio-") as directory:
        archive = Path(directory) / "source.zip"
        with urllib.request.urlopen(source_audio.catalog()["archiveUrl"], timeout=60) as response:
            data = response.read(MAX_ARCHIVE + 1)
        if len(data) > MAX_ARCHIVE:
            raise ValueError("Pinned source archive too large")
        archive.write_bytes(data)
        # Both imports enforce the registered archive and per-file SHA-256 and decode checks.
        print(prepare(archive, source_audio.SOURCE_DIR))
        print(prepare_daily(archive))


if __name__ == "__main__":
    main()
