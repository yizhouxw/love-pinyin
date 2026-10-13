import hashlib
from pathlib import Path

import pytest

from scripts import asr_model, fetch_asr_model


def pin_fixture(monkeypatch):
    monkeypatch.setattr(asr_model, "MODEL_SIZE", 3)
    monkeypatch.setattr(asr_model, "MODEL_SHA256", hashlib.sha256(b"abc").hexdigest())
    monkeypatch.setattr(fetch_asr_model, "MODEL_SIZE", 3)


def test_model_setup_reuses_only_a_verified_existing_model(tmp_path, monkeypatch):
    pin_fixture(monkeypatch)
    destination = tmp_path / "model.bin"
    destination.write_bytes(b"abc")
    monkeypatch.setattr(
        fetch_asr_model.subprocess, "run", lambda *a, **k: pytest.fail("unexpected network")
    )
    assert fetch_asr_model.install(destination) == destination
    destination.write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA-256"):
        fetch_asr_model.install(destination)
    assert destination.read_bytes() == b"bad"


def test_model_setup_checks_download_before_publishing_and_cleans_failure(tmp_path, monkeypatch):
    pin_fixture(monkeypatch)
    destination = tmp_path / "model.bin"

    def downloaded(args, **kwargs):
        assert "--insecure" not in args
        Path(args[args.index("--output") + 1]).write_bytes(b"bad")

    monkeypatch.setattr(fetch_asr_model.subprocess, "run", downloaded)
    with pytest.raises(ValueError, match="SHA-256"):
        fetch_asr_model.install(destination)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(
        fetch_asr_model.subprocess,
        "run",
        lambda args, **kwargs: Path(args[args.index("--output") + 1]).write_bytes(b"abc"),
    )
    assert fetch_asr_model.install(destination).read_bytes() == b"abc"
