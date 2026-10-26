"""Only metadata and explicit fake-engine fixtures; never generate reserved TTS."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import foreign_evaluation as foreign
from pinyin_matcher.catalog import fingerprint


@pytest.fixture
def planned(tmp_path, monkeypatch):
    config = tmp_path / "configuration.json"
    config.write_bytes(foreign.CONFIG.read_bytes())
    monkeypatch.setattr(foreign, "CONFIG", config.resolve())
    registry = tmp_path / "registry.json"
    install = {"revision": "fixed-test-revision", "files": [{"path": "test", "sha256": "f" * 64}]}
    registry.write_text(json.dumps({"generators": {"qwen": install}}))
    base_file = tmp_path / "base-lock.json"
    base_file.write_text("explicit test-only base validator fixture")
    base = {
        "lockSha256": "a" * 64,
        "model": {"thresholds": {"accept": 0.9}, "files": {"model.onnx": "b" * 64}},
        "modelDirectory": str(tmp_path / "fixed-model"),
        "calibrationReport": {"file": "test-cal", "sha256": "c" * 64},
        "calibrationCollection": {"file": "test-collection", "sha256": "d" * 64},
        "generatorRegistry": {"file": str(registry), "sha256": fingerprint(registry)},
        "generationPlan": {
            "personas": [
                {"id": f"voice-{i}", "split": "test", "instruction": "测试音色，标准普通话。"}
                for i in range(32, 36)
            ]
        },
    }
    monkeypatch.setattr(foreign, "_base_lock", lambda path: copy.deepcopy(base))
    monkeypatch.setattr(foreign, "verify_model", lambda engine, model: copy.deepcopy(install))
    model = tmp_path / "tts-model"
    model.mkdir()
    plan_path = tmp_path / "foreign-plan.json"
    output = tmp_path / "uncreated-audio"
    plan = foreign.create_foreign_plan(base_file, config, output, plan_path)
    return plan, plan_path, output, model, base, config


def test_metadata_plan_is_exactly_heldout_paired_96_without_audio(planned):
    plan, path, output, _, _, _ = planned
    assert not output.exists()
    assert foreign.validate_foreign_plan(path) == plan
    units = plan["generationPlan"]["units"]
    assert len(units) == 96
    assert len({u["id"] for u in units}) == 96
    assert len({u["lexicalRootId"] for u in units}) == 24
    assert {u["voiceFamilyId"] for u in units} == {f"voice-{i}" for i in range(32, 36)}
    assert {u["language"] for u in units} == {"English", "French"}
    assert all(u["againstTargetIds"] and u["phoneticDifference"] for u in units)
    assert all(u["persona"]["language"] == u["language"] and u["split"] == "test" for u in units)
    assert not list(path.parent.rglob("*.wav"))


def test_mutated_model_or_foreign_words_fail_before_engine(planned, monkeypatch):
    _, path, _, model, base, config = planned
    called = []
    monkeypatch.setattr(foreign, "engine_qwen", lambda directory: called.append(directory))
    base["model"]["thresholds"]["accept"] = 0.8
    with pytest.raises(ValueError, match="MODEL_OR_CALIBRATION_BINDING"):
        foreign.generate_foreign_evaluation(path, model)
    assert not called
    base["model"]["thresholds"]["accept"] = 0.9
    config.write_text(config.read_text() + "\n")
    with pytest.raises(ValueError, match="CONFIGURATION_CHANGED"):
        foreign.generate_foreign_evaluation(path, model)
    assert not called


def test_rehashed_mutated_unit_is_rejected_against_frozen_configuration(planned):
    plan, path, _, _, _, _ = planned
    plan["generationPlan"]["units"][0]["againstTargetIds"] = ["pm-ma1"]
    plan.pop("planSha256")
    plan["planSha256"] = foreign._lock_digest(plan)
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="GENERATION_PLAN_CHANGED"):
        foreign.validate_foreign_plan(path)


def test_engine_initialization_failure_preserves_all_96_attempts(planned, monkeypatch):
    _, path, output, model, _, _ = planned

    def broken_engine(directory):
        raise RuntimeError("explicit test engine failure")

    monkeypatch.setattr(foreign, "engine_qwen", broken_engine)
    result = foreign.generate_foreign_evaluation(path, model)
    assert len(result["items"]) == 96
    assert {row["generationStatus"] for row in result["items"]} == {"tts-failure"}
    assert result["qualityManifestReady"] is False
    quality = json.loads((output / "quality-manifest.json").read_text())
    assert len(quality["cases"]) == 96
    assert quality["qualityManifestReady"] is False
    assert all(row["sha256"] is None for row in quality["cases"])


def test_mechanical_failures_kept_and_missing_waveform_never_dropped(planned, monkeypatch):
    _, path, output, model, _, _ = planned
    calls = []

    def fake_engine(directory):
        def synthesize(text, persona, seed):
            calls.append(seed)
            if len(calls) == 1:
                raise RuntimeError("explicit fixture missing waveform")
            return np.zeros(100, dtype=np.float32), 16000

        return synthesize

    monkeypatch.setattr(foreign, "engine_qwen", fake_engine)
    result = foreign.generate_foreign_evaluation(path, model)
    assert len(calls) == 96
    assert len(result["items"]) == 96
    assert sum(row["generationStatus"] == "mechanical-failure" for row in result["items"]) == 95
    assert len(list(output.rglob("*.wav"))) == 95
    assert not result["qualityManifestReady"]
    assert len(json.loads((output / "quality-manifest.json").read_text())["cases"]) == 96
    # Terminal failures cannot silently be regenerated with a different draw.
    foreign.generate_foreign_evaluation(path, model)
    assert len(calls) == 96


def test_changed_saved_audio_and_preexisting_output_are_rejected(planned, monkeypatch):
    plan, path, output, model, _, config = planned
    output.mkdir()
    with pytest.raises(ValueError, match="OUTPUT_WITHOUT_MANIFEST"):
        foreign.generate_foreign_evaluation(path, model)
    with pytest.raises(ValueError, match="PLAN_AND_OUTPUT_MUST_BE_NEW"):
        foreign.create_foreign_plan(Path(plan["evaluationLock"]["file"]), config, output, path)
