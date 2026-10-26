"""Frozen evaluation attempts are terminal; fixtures never measure pronunciation."""

import json
from pathlib import Path

import numpy as np
import pytest
from test_controlled_evaluation_lock import (
    _stub_reference_tts,
    args,
    lock,
)
from test_controlled_evaluation_lock import (
    prepared as prepared,
)

from pinyin_matcher import controlled_generation as controlled
from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import fingerprint


@pytest.fixture
def evaluation(prepared, monkeypatch):
    snapshot = lock(prepared)
    waveform = _stub_reference_tts(prepared, monkeypatch)
    controlled.generate(args(prepared, snapshot))
    source = prepared.project / "fixture-source.wav"
    source.write_bytes(encode_wav(waveform))
    monkeypatch.setattr(controlled, "standard_source", lambda *a, **kw: source)
    monkeypatch.setattr(
        controlled,
        "pitch_evidence",
        lambda samples: {"durationSeconds": len(samples) / 16000},
    )
    engines, conversions = [], []

    def engine(*a):
        engines.append(a)
        return object()

    def convert(*a):
        conversions.append(a)
        return waveform, 16000

    monkeypatch.setattr(controlled, "engine_cosy", engine)
    monkeypatch.setattr(controlled, "convert_voice", convert)
    generation_args = args(prepared, snapshot, engine="cosy", references_only=False, modes=["vc"])
    manifest = prepared.output / ("cosy" + controlled.EVALUATION_SUFFIX) / "manifest.json"
    return prepared, snapshot, generation_args, manifest, waveform, engines, conversions


def write_existing(evaluation, **changes):
    _, snapshot, generation_args, manifest, *_ = evaluation
    data = {
        "version": 1,
        "configurationSha256": fingerprint(Path(snapshot["configuration"]["file"])),
        "configuration": json.loads(generation_args.configuration.read_text()),
        "evaluationLockSha256": snapshot["lockSha256"],
        "evaluationGenerationPlan": snapshot["generationPlan"],
        "items": [],
        "diagnostics": [],
        "quarantined": [],
        "rejected": [],
        **changes,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(data))
    return manifest.read_bytes()


@pytest.mark.parametrize(
    "group", ["rejected", "quarantined", "failedGenerationAttempts", "diagnostics"]
)
def test_historical_failure_is_never_erased_retried_or_passed(evaluation, group):
    _, snapshot, generation_args, manifest, _, engines, conversions = evaluation
    before = write_existing(
        evaluation,
        **{
            group: [
                {"id": snapshot["generationPlan"]["units"][0]["id"], "reason": "fixture failure"}
            ]
        },
    )
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_FAILED"):
        controlled.generate(generation_args)
    assert not engines and not conversions
    assert manifest.read_bytes() == before
    assert not json.loads(before).get("evaluationGenerationComplete", False)


@pytest.mark.parametrize("failure", [RuntimeError, TypeError, IndexError, OSError, "quarantine"])
def test_first_failed_attempt_is_saved_and_immediately_terminal(evaluation, monkeypatch, failure):
    _, _, generation_args, manifest, waveform, _, conversions = evaluation

    def fails(*a):
        conversions.append(a)
        if failure != "quarantine":
            raise failure("fixture conversion failed")
        return np.tile(waveform, 3), 16000

    monkeypatch.setattr(controlled, "convert_voice", fails)
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_FAILED"):
        controlled.generate(generation_args)
    saved = json.loads(manifest.read_text())
    group = "quarantined" if failure == "quarantine" else "rejected"
    assert len(saved[group]) == 1
    assert len(conversions) == 1
    assert not saved.get("evaluationGenerationComplete", False)
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_FAILED"):
        controlled.generate(generation_args)
    assert len(conversions) == 1
    assert manifest.read_bytes() == before


def test_interrupted_locked_attempt_cannot_be_redrawn_on_resume(evaluation, monkeypatch):
    _, _, generation_args, manifest, _, _, conversions = evaluation

    def interrupted(*a):
        conversions.append(a)
        raise KeyboardInterrupt("test-only simulated interruption")

    monkeypatch.setattr(controlled, "convert_voice", interrupted)
    with pytest.raises(KeyboardInterrupt):
        controlled.generate(generation_args)
    saved = json.loads(manifest.read_text())
    assert saved["inProgressUnit"]
    assert not saved["evaluationGenerationComplete"]
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_FAILED"):
        controlled.generate(generation_args)
    assert len(conversions) == 1
    assert manifest.read_bytes() == before


def test_all_planned_items_cannot_hide_an_earlier_failed_attempt(evaluation):
    _, _, generation_args, manifest, _, _, conversions = evaluation
    controlled.generate(generation_args)
    assert len(conversions) == 52
    data = json.loads(manifest.read_text())
    assert data["evaluationGenerationComplete"] is True
    data["failedGenerationAttempts"] = [{"id": data["items"][0]["id"], "reason": "old failure"}]
    # A legacy manifest with an incorrect complete marker must be rejected intact.
    manifest.write_text(json.dumps(data))
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_FAILED"):
        controlled.generate(generation_args)
    assert len(conversions) == 52
    assert manifest.read_bytes() == before


def test_successful_partial_run_resumes_only_never_attempted_units(evaluation):
    _, _, generation_args, manifest, _, _, conversions = evaluation
    controlled.generate(generation_args)
    data = json.loads(manifest.read_text())
    retained = data["items"][:3]
    data["items"] = retained
    data.pop("evaluationGenerationComplete")
    manifest.write_text(json.dumps(data))
    before = {r["id"]: r["sha256"] for r in retained}
    conversions.clear()
    controlled.generate(generation_args)
    saved = json.loads(manifest.read_text())
    assert len(conversions) == 49
    assert saved["evaluationGenerationComplete"] is True
    assert {r["id"]: r["sha256"] for r in saved["items"] if r["id"] in before} == before


def test_ordinary_exploration_retains_its_resume_behavior(evaluation):
    prepared, snapshot, _, _, waveform, _, conversions = evaluation
    reference = prepared.output / "references/voice-28.wav"
    reference.write_bytes(encode_wav(waveform))
    generation_args = args(
        prepared,
        snapshot,
        engine="cosy",
        references_only=False,
        modes=["vc"],
        source_pool="pilot",
        evaluation_lock=None,
        persona_ids=["voice-28"],
        suffix="-ordinary-resume",
        limit=2,
    )
    first = next(
        row
        for row in prepared.config["definitions"]
        if (row.get("standardSource") or {}).get("allocation") == "calibration"
    )
    failed_id = "controlled-cosy-voice-28-" + first["id"] + "-vc-0"
    manifest = prepared.output / "cosy-ordinary-resume/manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "configurationSha256": fingerprint(generation_args.configuration),
                "items": [],
                "diagnostics": [],
                "quarantined": [],
                "rejected": [{"id": failed_id, "reason": "ordinary old failure"}],
            }
        )
    )
    controlled.generate(generation_args)
    controlled.generate(generation_args)
    data = json.loads(manifest.read_text())
    assert len(conversions) == 4
    assert len(data["items"]) == 4
    assert data["rejected"] == [{"id": failed_id, "reason": "ordinary old failure"}]


@pytest.mark.parametrize("stage", ["engine", "reference"])
def test_locked_reference_or_engine_failure_is_durable_and_cannot_be_retried(
    prepared, monkeypatch, stage
):
    snapshot = lock(prepared)
    _stub_reference_tts(prepared, monkeypatch)
    calls = []

    def broken_engine(model):
        calls.append("engine")
        if stage == "engine":
            raise RuntimeError("fixture engine initialization failure")

        def broken_reference(*a):
            calls.append("reference")
            raise RuntimeError("fixture reference failure")

        return broken_reference

    monkeypatch.setattr(controlled, "engine_qwen", broken_engine)
    with pytest.raises(RuntimeError, match="fixture"):
        controlled.generate(args(prepared, snapshot))
    manifest = prepared.output / ("qwen" + controlled.EVALUATION_SUFFIX) / "manifest.json"
    data = json.loads(manifest.read_text())
    assert len(data["rejected"]) == 1
    assert data["evaluationGenerationComplete"] is False
    assert not list(prepared.output.rglob("*.wav"))
    before = manifest.read_bytes()
    previous_calls = list(calls)
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_FAILED"):
        controlled.generate(args(prepared, snapshot))
    assert calls == previous_calls
    assert manifest.read_bytes() == before
