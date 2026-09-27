"""Pinned, manually installed local ASR model metadata and helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

MODEL_REPO = "ggerganov/whisper.cpp"
MODEL_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
MODEL_FILENAME = "ggml-small.bin"
MODEL_SHA256 = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
MODEL_SIZE = 487_601_967
MODEL_LICENSE = "MIT"
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{MODEL_FILENAME}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_model(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"本地模型文件不存在: {path}")
    if path.stat().st_size != MODEL_SIZE:
        raise ValueError(f"模型大小不符: {path.stat().st_size} != {MODEL_SIZE}")
    actual = sha256_file(path)
    if actual != MODEL_SHA256:
        raise ValueError(f"模型 SHA-256 不符: {actual}")
