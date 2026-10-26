"""A contour change requires explicit, matching head metadata before assembly."""

import json
from pathlib import Path

import pytest

from pinyin_matcher import assemble_v3
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pitch_swift import COMPONENT_PITCH_FEATURE_VERSION, PITCH_FEATURE_VERSION


def test_assembly_requires_explicit_supported_pitch_version():
    missing = Path("never-open-this-fixture")
    with pytest.raises(TypeError, match="feature_version"):
        assemble_v3.assemble(missing, missing, missing, missing)
    with pytest.raises(ValueError, match="PITCH_FEATURE_VERSION_UNSUPPORTED"):
        assemble_v3.assemble(missing, missing, missing, missing, feature_version="unknown")


def test_assembly_cannot_silently_relabel_v1_head_as_v2(tmp_path, monkeypatch):
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tracker / "model.onnx").write_bytes(b"explicit test tracker fixture")
    monkeypatch.setattr(assemble_v3, "MODEL_SHA256", fingerprint(tracker / "model.onnx"))
    pitch = tmp_path / "pitch.onnx"
    pitch.write_bytes(b"explicit test head fixture")
    pitch.with_suffix(".json").write_text(
        json.dumps(
            {
                "sha256": fingerprint(pitch),
                "inputShape": [32, 4],
                "featureVersion": PITCH_FEATURE_VERSION,
            }
        )
    )
    destination = tmp_path / "uncreated-bundle"
    with pytest.raises(ValueError, match="PITCH_FEATURE_OR_HEAD_BINDING_MISMATCH"):
        assemble_v3.assemble(
            tmp_path / "never-read-acoustic",
            pitch,
            tracker,
            destination,
            feature_version=COMPONENT_PITCH_FEATURE_VERSION,
        )
    assert not destination.exists()
