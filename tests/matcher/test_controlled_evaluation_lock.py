"""Test-only model bytes/speech fixtures exercise freeze guards, never accuracy."""

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import controlled_generation as controlled
from pinyin_matcher.catalog import fingerprint

PROJECT_ROOT = controlled.ROOT


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    project = tmp_path / "project"
    content = project / "content"
    content.mkdir(parents=True)
    config = json.loads((PROJECT_ROOT / "content/pronunciation-contrast-training.json").read_text())
    for index, row in enumerate(config["definitions"]):
        if (row.get("standardSource") or {}).get("allocation") == "blind":
            row["standardSource"]["sourceSha256"] = hashlib.sha256(
                f"test-only-standard-source-{index}".encode()
            ).hexdigest()
    configuration = content / "configuration.json"
    configuration.write_text(json.dumps(config))
    for name in ["pronunciation-training.json", "pronunciation-models.json"]:
        (content / name).write_bytes((PROJECT_ROOT / "content" / name).read_bytes())
    model = project / "model"
    model.mkdir()
    for name in ["acoustic.onnx", "pitch.onnx", "targets.json"]:
        (model / name).write_bytes(("test-only-not-real-model-" + name).encode())
    thresholds = {"minimumContentMargin": 0.5, "minimumToneProbability": 0.8}
    metadata = {
        "version": "test-only",
        "file": "acoustic.onnx",
        "sha256": fingerprint(model / "acoustic.onnx"),
        "catalogFile": "targets.json",
        "catalogSha256": fingerprint(model / "targets.json"),
        "coveredTargetIds": ["pm-ni3"],
        "thresholds": thresholds,
        "calibrationPassed": True,
        "pitchTone": {"file": "pitch.onnx", "sha256": fingerprint(model / "pitch.onnx")},
    }
    (model / "model.json").write_text(json.dumps(metadata))
    original_model = project / "calibrated-candidate"
    shutil.copytree(model, original_model)
    original_metadata = json.loads((original_model / "model.json").read_text())
    original_metadata["calibrationPassed"] = False
    (original_model / "model.json").write_text(json.dumps(original_metadata))
    (project / "collection.json").write_text(
        json.dumps({"modelMetadataSha256": fingerprint(original_model / "model.json")})
    )
    calibration = project / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "calibrationPassed": True,
                "thresholds": thresholds,
                "trainingLineageCheck": {"complete": True, "overlapRawUnitIds": [], "errors": []},
            }
        )
    )
    monkeypatch.setattr(controlled, "ROOT", project)
    code = {"test-only-code": "a" * 64}
    monkeypatch.setattr(controlled, "_generation_code_snapshot", lambda: dict(code))
    # No fake model is accepted by production: bypass ONNX loading only inside this test.
    from pinyin_matcher import inference

    monkeypatch.setattr(inference, "PinyinMatcher", lambda path: argparse.Namespace(session=True))
    return argparse.Namespace(
        project=project,
        configuration=configuration,
        config=config,
        model=model,
        original_model=original_model,
        calibration=calibration,
        output=project / "evaluation",
        lock_path=project / "evaluation-lock.json",
        code=code,
    )


def lock(prepared):
    return controlled.create_evaluation_lock(
        prepared.model,
        prepared.configuration,
        prepared.calibration,
        prepared.output,
        prepared.lock_path,
        calibration_model=prepared.original_model,
    )


def args(prepared, snapshot, **changes):
    values = dict(
        engine="qwen",
        model=prepared.model,
        source=prepared.project / "source",
        output=prepared.output,
        modes=["character"],
        bases=None,
        persona_ids=None,
        suffix=controlled.EVALUATION_SUFFIX,
        configuration=Path(snapshot["configuration"]["file"]),
        source_pool="locked-evaluation",
        repetitions=1,
        threads=4,
        tts_device="mps",
        limit=None,
        references_only=True,
        evaluation_lock=prepared.lock_path,
    )
    return argparse.Namespace(**(values | changes))


def test_plain_blind_source_access_stops_before_source_file_read(prepared, monkeypatch):
    row = next(
        r
        for r in prepared.config["definitions"]
        if (r.get("standardSource") or {}).get("allocation") == "blind"
    )
    monkeypatch.setattr(
        controlled, "fingerprint", lambda path: pytest.fail("blind source was read")
    )
    with pytest.raises(ValueError, match="BLIND_STANDARD_SOURCE_ACCESS_FORBIDDEN"):
        controlled.standard_source(row, prepared.output)


def test_lock_creation_freezes_only_metadata_and_plan_without_audio(prepared):
    snapshot = lock(prepared)
    assert len(snapshot["generationPlan"]["sources"]) == 13
    assert len(snapshot["generationPlan"]["units"]) == 52
    assert snapshot["claims"]["realChildAccuracyEstablished"] is False
    assert snapshot["claims"]["isQualityFreeze"] is False
    assert not prepared.output.exists()
    assert (
        Path(snapshot["configuration"]["file"]).read_bytes() == prepared.configuration.read_bytes()
    )
    controlled.validate_evaluation_lock(prepared.lock_path, prepared.configuration, prepared.output)


@pytest.mark.parametrize(
    "which",
    [
        "metadata",
        "acoustic",
        "pitch",
        "catalog",
        "config",
        "calibration",
        "collection",
        "calibration-model",
        "registry",
        "code",
        "lock",
    ],
)
def test_any_bound_mutation_blocks_generation(prepared, which):
    snapshot = lock(prepared)
    paths = {
        "metadata": prepared.model / "model.json",
        "acoustic": prepared.model / "acoustic.onnx",
        "pitch": prepared.model / "pitch.onnx",
        "catalog": prepared.model / "targets.json",
        "config": prepared.configuration,
        "calibration": prepared.calibration,
        "collection": prepared.project / "collection.json",
        "calibration-model": prepared.original_model / "model.json",
        "registry": prepared.project / "content/pronunciation-models.json",
    }
    if which == "code":
        prepared.code["test-only-code"] = "b" * 64
    elif which == "lock":
        snapshot["generationPlan"]["units"] = []
        prepared.lock_path.write_text(json.dumps(snapshot))
    elif which == "metadata":
        value = json.loads(paths[which].read_text())
        value["thresholds"]["minimumToneProbability"] = 0.1
        paths[which].write_text(json.dumps(value))
    else:
        paths[which].write_bytes(paths[which].read_bytes() + b" ")
    with pytest.raises(ValueError):
        controlled.validate_evaluation_lock(
            prepared.lock_path, prepared.configuration, prepared.output
        )
    assert not prepared.output.exists()


def test_output_and_generation_arguments_are_frozen(prepared):
    snapshot = lock(prepared)
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_PLAN_CHANGED"):
        controlled.validate_evaluation_lock(
            prepared.lock_path, prepared.configuration, prepared.output / "other"
        )
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_GENERATION_ARGUMENTS_CHANGED"):
        controlled.generate(args(prepared, snapshot, repetitions=2))


def test_failed_calibration_cannot_create_lock(prepared):
    report = json.loads(prepared.calibration.read_text())
    report["calibrationPassed"] = False
    prepared.calibration.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="PASSED_MATCHING_CALIBRATION_REPORT_REQUIRED"):
        lock(prepared)
    assert not prepared.lock_path.exists()


def test_preexisting_new_voice_reference_refuses_prefreeze(prepared):
    reference = prepared.output / "references/voice-32.wav"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"test-only-existing-file-never-decoded")
    with pytest.raises(ValueError, match="EVALUATION_REFERENCE_ALREADY_EXISTS_BEFORE_LOCK"):
        lock(prepared)


def test_missing_lock_or_plain_mode_cannot_enable_test_families(prepared):
    snapshot = lock(prepared)
    with pytest.raises(ValueError, match="EVALUATION_LOCK_REQUIRED"):
        controlled.generate(args(prepared, snapshot, evaluation_lock=None))
    with pytest.raises(ValueError, match="TRAIN_OR_CALIBRATION_FAMILIES_ONLY"):
        controlled.generate(
            args(
                prepared,
                snapshot,
                source_pool="pilot",
                evaluation_lock=None,
                persona_ids=["voice-32"],
            )
        )


def test_authorized_source_only_opens_the_declared_parent(prepared):
    snapshot = lock(prepared)
    row = copy.deepcopy(
        next(
            r
            for r in prepared.config["definitions"]
            if (r.get("standardSource") or {}).get("allocation") == "blind"
        )
    )
    digest = row["standardSource"]["sourceSha256"]
    index = next(i for i, r in enumerate(prepared.config["definitions"]) if r["id"] == row["id"])
    original = prepared.project / "private/pinyinsound/clips" / (digest + ".mp3")
    original.parent.mkdir(parents=True)
    original.write_bytes(f"test-only-standard-source-{index}".encode())
    cached = prepared.output / "standard-sources" / (digest + ".wav")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"test-only-cache-not-decoded")
    assert (
        controlled.standard_source(
            row,
            prepared.output,
            evaluation_lock=prepared.lock_path,
            configuration=prepared.configuration,
        )
        == cached
    )
    row["standardSource"]["sourceSha256"] = "0" * 64
    with pytest.raises(ValueError, match="BLIND_SOURCE_NOT_IN_FROZEN_GENERATION_PLAN"):
        controlled.standard_source(
            row,
            prepared.output,
            evaluation_lock=prepared.lock_path,
            configuration=prepared.configuration,
        )
    assert snapshot["generationPlan"]["expectedStandardRoots"] == 13


def test_cached_reference_requires_matching_lock_and_wave_sha(prepared):
    snapshot = lock(prepared)
    persona = next(p for p in prepared.config["additionalPersonas"] if p["id"] == "voice-32")
    reference = prepared.output / "references/voice-32.wav"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"test-only-reference")
    with pytest.raises(ValueError, match="EVALUATION_REFERENCE_PROVENANCE_REQUIRED"):
        controlled._evaluation_reference_record(reference, persona, snapshot)
    record = {
        "evaluationLockSha256": snapshot["lockSha256"],
        "sha256": fingerprint(reference),
        "persona": persona,
    }
    reference.with_suffix(".json").write_text(json.dumps(record))
    controlled._evaluation_reference_record(reference, persona, snapshot)
    reference.write_bytes(b"changed-test-only-reference")
    with pytest.raises(ValueError, match="EVALUATION_REFERENCE_PROVENANCE_MISMATCH"):
        controlled._evaluation_reference_record(reference, persona, snapshot)


def test_locked_qwen_reference_phase_allows_only_planned_test_families(prepared, monkeypatch):
    snapshot = lock(prepared)
    source = prepared.project / "source/cosyvoice/tokenizer"
    source.mkdir(parents=True)
    (source / "tokenizer.py").write_text("[m][ā]")
    calls = []

    # Pure test fixture: validates orchestration and provenance, not TTS quality.
    def fake_engine(model):
        def synthesize(text, persona, seed):
            calls.append((persona["id"], seed))
            return (0.1 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype(
                np.float32
            ), 16000

        return synthesize

    monkeypatch.setattr(controlled, "engine_qwen", fake_engine)
    monkeypatch.setattr(controlled, "verify_model", lambda *args: {"revision": "test-only"})
    controlled.generate(args(prepared, snapshot))
    assert {key for key, seed in calls} == {f"voice-{i}" for i in range(32, 36)}
    for key, seed in calls:
        reference = prepared.output / "references" / (key + ".wav")
        metadata = json.loads(reference.with_suffix(".json").read_text())
        assert metadata["evaluationLockSha256"] == snapshot["lockSha256"]
        assert metadata["sha256"] == fingerprint(reference)
        assert metadata["persona"]["split"] == "test"
        assert seed == prepared.config["seed"] + int(key[-2:])
    assert not (prepared.output / "standard-sources").exists()


def _stub_reference_tts(prepared, monkeypatch, *, mutate_model=False):
    source = prepared.project / "source/cosyvoice/tokenizer"
    source.mkdir(parents=True, exist_ok=True)
    (source / "tokenizer.py").write_text("[m][ā]")
    waveform = (0.1 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype(np.float32)

    def engine(model):
        def synthesize(text, persona, seed):
            if mutate_model:
                metadata = json.loads((prepared.model / "model.json").read_text())
                metadata["thresholds"]["minimumToneProbability"] = 0.01
                (prepared.model / "model.json").write_text(json.dumps(metadata))
            return waveform, 16000

        return synthesize

    monkeypatch.setattr(controlled, "engine_qwen", engine)
    registry = json.loads((prepared.project / "content/pronunciation-models.json").read_text())
    monkeypatch.setattr(controlled, "verify_model", lambda name, path: registry["generators"][name])
    return waveform


def test_mutating_model_during_reference_generation_stops_before_audio_write(prepared, monkeypatch):
    snapshot = lock(prepared)
    _stub_reference_tts(prepared, monkeypatch, mutate_model=True)
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_MODEL_CHANGED"):
        controlled.generate(args(prepared, snapshot))
    assert not list(prepared.output.rglob("*.wav"))


def test_locked_vc_output_has_explicit_test_split_and_exhaustive_plan(prepared, monkeypatch):
    from pinyin_matcher.audio import encode_wav

    snapshot = lock(prepared)
    waveform = _stub_reference_tts(prepared, monkeypatch)
    controlled.generate(args(prepared, snapshot))
    # Test-only licensed-source stand-ins exercise routing; none is scored.
    cache = prepared.output / "standard-sources"
    cache.mkdir()
    original = prepared.project / "private/pinyinsound/clips"
    original.mkdir(parents=True)
    for index, row in enumerate(prepared.config["definitions"]):
        source = row.get("standardSource") or {}
        if source.get("allocation") != "blind":
            continue
        (original / (source["sourceSha256"] + ".mp3")).write_bytes(
            f"test-only-standard-source-{index}".encode()
        )
        (cache / (source["sourceSha256"] + ".wav")).write_bytes(encode_wav(waveform))
    monkeypatch.setattr(controlled, "engine_cosy", lambda *args: object())
    monkeypatch.setattr(controlled, "convert_voice", lambda *args: (waveform, 16000))
    controlled.generate(
        args(prepared, snapshot, engine="cosy", references_only=False, modes=["vc"])
    )
    manifest = json.loads(
        (prepared.output / ("cosy" + controlled.EVALUATION_SUFFIX) / "manifest.json").read_text()
    )
    assert manifest["evaluationGenerationComplete"] is True
    assert len(manifest["items"]) == 52
    assert {r["id"] for r in manifest["items"]} == {
        r["id"] for r in snapshot["generationPlan"]["units"]
    }
    assert all(r["split"] == "test" and r["sourceAllocation"] == "test" for r in manifest["items"])
    assert all(
        r["sourceDeclaredAllocation"] == "blind" and not r["realChildAccuracyEstablished"]
        for r in manifest["items"]
    )


def test_family_subset_cannot_shrink_frozen_evaluation(prepared):
    snapshot = lock(prepared)
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_FAMILY_SET_CHANGED"):
        controlled.generate(args(prepared, snapshot, persona_ids=["voice-32"]))


@pytest.mark.parametrize("changed", ["swift.onnx", "LICENSE"])
def test_tracker_and_its_license_are_also_bound(prepared, changed):
    for name in ["swift.onnx", "LICENSE"]:
        (prepared.model / name).write_bytes(("test-only-" + name).encode())
    metadata = json.loads((prepared.model / "model.json").read_text())
    metadata["pitchTone"]["tracker"] = {
        "file": "swift.onnx",
        "sha256": fingerprint(prepared.model / "swift.onnx"),
        "licenseFile": "LICENSE",
        "licenseSha256": fingerprint(prepared.model / "LICENSE"),
    }
    (prepared.model / "model.json").write_text(json.dumps(metadata))
    for name in ["swift.onnx", "LICENSE"]:
        shutil.copyfile(prepared.model / name, prepared.original_model / name)
    before = dict(metadata)
    before["calibrationPassed"] = False
    (prepared.original_model / "model.json").write_text(json.dumps(before))
    (prepared.project / "collection.json").write_text(
        json.dumps({"modelMetadataSha256": fingerprint(prepared.original_model / "model.json")})
    )
    lock(prepared)
    (prepared.model / changed).write_bytes(b"changed")
    with pytest.raises(ValueError, match="PITCH_TRACKER"):
        controlled.validate_evaluation_lock(
            prepared.lock_path, prepared.configuration, prepared.output
        )


def test_other_weights_cannot_reuse_a_passing_threshold_report(prepared):
    weights = prepared.model / "acoustic.onnx"
    weights.write_bytes(b"different-test-only-model-weights")
    metadata = json.loads((prepared.model / "model.json").read_text())
    metadata["sha256"] = fingerprint(weights)
    (prepared.model / "model.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="CALIBRATION_MODEL_WEIGHTS_OR_CATALOG_MISMATCH"):
        lock(prepared)
    assert not prepared.lock_path.exists()


def test_collection_must_identify_the_original_calibrated_metadata(prepared):
    collection = prepared.project / "collection.json"
    collection.write_text(json.dumps({"modelMetadataSha256": "0" * 64}))
    with pytest.raises(ValueError, match="CALIBRATION_MODEL_METADATA_MISMATCH"):
        lock(prepared)
