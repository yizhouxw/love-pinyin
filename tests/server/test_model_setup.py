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


def test_tts_setup_pins_each_file_and_publishes_only_complete_model(tmp_path, monkeypatch):
    import json

    from scripts import fetch_tts_model as tts

    monkeypatch.setattr(tts, "ROOT", tmp_path)
    (tmp_path / "content").mkdir()
    config = {
        "directory": "fixture",
        "revision": "a" * 40,
        "downloadSource": "https://huggingface.co/explicit-test-fixture",
        "files": {
            "model.safetensors": hashlib.sha256(b"abc").hexdigest(),
            "speech_tokenizer/config.json": hashlib.sha256(b"abc").hexdigest(),
        },
        "sizes": {"model.safetensors": 3, "speech_tokenizer/config.json": 3},
    }
    (tmp_path / "content" / "voice-build.json").write_text(json.dumps(config))

    def downloaded(args, **kwargs):
        assert f"/resolve/{config['revision']}/" in args[-1]
        assert "--insecure" not in args
        Path(args[args.index("--output") + 1]).write_bytes(b"bad")

    monkeypatch.setattr(tts.subprocess, "run", downloaded)
    with pytest.raises(ValueError, match="digest mismatch"):
        tts.install()
    assert list((tmp_path / "models" / "qwen3-tts").iterdir()) == []
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **kwargs: Path(args[args.index("--output") + 1]).write_bytes(b"abc"),
    )
    model = tts.install()
    assert (model / "speech_tokenizer/config.json").read_bytes() == b"abc"
    monkeypatch.setattr(tts.subprocess, "run", lambda *a, **k: pytest.fail("unexpected network"))
    assert tts.install() == model
    (model / "model.safetensors").write_bytes(b"bad")
    with pytest.raises(ValueError, match="digest mismatch"):
        tts.install()
