"""Frozen vocabulary/family barriers for offline foreign contrast generation."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pinyin_matcher.cosy_foreign_data import generate


def test_pilot_vocabulary_cannot_be_reused_as_calibration():
    # Must reject before a model path is needed or any TTS runtime is loaded.
    with pytest.raises(ValueError, match="PILOT_VOCABULARY_IS_TRAIN_ONLY"):
        generate(SimpleNamespace(mode="pilot", split="calibration"))


def test_reserved_blind_voice_cannot_enter_foreign_training():
    with pytest.raises(ValueError, match="FROZEN_TRAIN_OR_CALIBRATION_FAMILIES_REQUIRED"):
        generate(SimpleNamespace(mode="pilot", split="train", persona_ids=["voice-32"]))


def test_optional_actual_foreign_artifacts_preserve_phonetic_pairing_and_sources():
    file = os.environ.get("MATCHER_COSY_FOREIGN_MANIFEST")
    if not file:
        pytest.skip("set MATCHER_COSY_FOREIGN_MANIFEST for actual local artifact verification")
    from pinyin_matcher.foreign_data import read_manifest

    rows = read_manifest(Path(file))
    assert rows
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["sha256"] for row in rows}) == len(rows)
    assert {row["language"] for row in rows} == {"English", "French"}
    assert {row["voiceFamilyId"] for row in rows} == {"voice-00", "voice-10"}
    assert all(row["againstTargetIds"] and row["phoneticDifference"] for row in rows)
    assert not any(row.get("exploratoryDialect") for row in rows)
