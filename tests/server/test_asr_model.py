from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.asr_model import MODEL_SHA256, MODEL_SIZE, validate_model
from scripts.transcribe_audio_candidates import checked_clip


def test_model_validation_checks_size_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"model fixture")
    monkeypatch.setattr("scripts.asr_model.MODEL_SIZE", len(b"model fixture"))
    monkeypatch.setattr(
        "scripts.asr_model.MODEL_SHA256", hashlib.sha256(b"model fixture").hexdigest()
    )

    validate_model(model)

    assert MODEL_SIZE > 0
    assert len(MODEL_SHA256) == 64


def test_model_validation_rejects_wrong_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"wrong")
    monkeypatch.setattr("scripts.asr_model.MODEL_SIZE", len(b"wrong"))
    monkeypatch.setattr("scripts.asr_model.MODEL_SHA256", "0" * 64)

    with pytest.raises(ValueError, match="SHA-256"):
        validate_model(model)


def test_candidate_path_is_confined_and_digest_verified(tmp_path: Path) -> None:
    root = tmp_path / "candidates"
    root.mkdir()
    clip = root / "clip.wav"
    clip.write_bytes(b"wav")
    digest = hashlib.sha256(b"wav").hexdigest()

    assert checked_clip(root, "clip.wav", digest) == clip.resolve()
    with pytest.raises(ValueError, match="越界"):
        checked_clip(root, "../secret.wav", digest)
    with pytest.raises(ValueError, match="摘要不符"):
        checked_clip(root, "clip.wav", "0" * 64)
