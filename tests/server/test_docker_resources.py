"""Docker builds must fail before installing incomplete or untrusted source archives."""

import io

import pytest

from scripts import prepare_docker_resources as build


def test_corrupt_download_cannot_enable_source(tmp_path, monkeypatch):
    monkeypatch.setattr(build.source_audio, "SOURCE_DIR", tmp_path / "audio")
    monkeypatch.setattr(build.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="digest"):
        build.main()
    assert not (tmp_path / "audio" / "installation.json").exists()


def test_archive_download_is_bounded(monkeypatch):
    monkeypatch.setattr(build, "MAX_ARCHIVE", 8)
    monkeypatch.setattr(build.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"x" * 9))
    with pytest.raises(ValueError, match="too large"):
        build.main()


def test_network_failure_does_not_fall_back_to_fixtures(monkeypatch):
    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(build.urllib.request, "urlopen", offline)
    with pytest.raises(OSError, match="offline"):
        build.main()
