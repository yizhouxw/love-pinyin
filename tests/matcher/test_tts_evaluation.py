"""Frozen-plan orchestration and query denominators, never TTS pronunciation efficacy."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import tts_evaluation as tts
from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.quality import _model_snapshot, freeze_plan


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def planned(tmp_path, monkeypatch):
    catalog = json.loads((ROOT / "content/pronunciation-targets.json").read_text())
    model = tmp_path / "model"
    write(model / "targets.json", catalog)
    (model / "acoustic.onnx").write_bytes(b"test-only snapshot; never used for inference")
    write(
        model / "model.json",
        {
            "version": "fixture",
            "file": "acoustic.onnx",
            "catalogFile": "targets.json",
            "coveredTargetIds": catalog["pilotIds"],
            "thresholds": {"accept": 0.9},
        },
    )
    installs = {
        engine: {
            "revision": engine + "-fixed-test-revision",
            "files": [{"path": "weights", "sha256": engine + "-fixed-test-digest"}],
        }
        for engine in tts.ENGINES
    }
    registry = write(
        tmp_path / "registry.json",
        {"generators": installs, "cosySource": {"commit": "fixed-test-commit"}},
    )
    base_file = tmp_path / "base.lock.json"
    base_file.write_text("explicit base-validator fixture; not an actual evaluation lock")
    main_output = tmp_path / "main-output"
    base = {
        "lockSha256": "a" * 64,
        "modelDirectory": str(model),
        "model": _model_snapshot(model),
        "calibrationReport": {"file": "test-cal", "sha256": "b" * 64},
        "calibrationCollection": {"file": "test-collection", "sha256": "c" * 64},
        "generatorRegistry": {"file": str(registry), "sha256": fingerprint(registry)},
        "generationPlan": {
            "outputDirectory": str(main_output),
            "personas": [
                {
                    "id": f"voice-{i}",
                    "split": "test",
                    "instruction": "测试合成家族，标准普通话。",
                    "referenceText": "测试参考。",
                    "referenceSeed": i,
                    "referenceFile": f"references/voice-{i}.wav",
                }
                for i in range(36, 40)
            ],
        },
    }
    monkeypatch.setattr(tts, "_base_lock", lambda path: copy.deepcopy(base))
    monkeypatch.setattr(tts, "verify_model", lambda engine, model: copy.deepcopy(installs[engine]))
    source = tmp_path / "cosy-source"
    source.mkdir()
    output = tmp_path / "tts-output"
    path = tmp_path / "tts.plan.json"
    plan = tts.create_tts_plan(base_file, output, path)
    return {
        "plan": plan,
        "path": path,
        "output": output,
        "model": model,
        "base": base,
        "source": source,
        "registry": registry,
    }


def references(planned):
    for row in planned["plan"]["generationPlan"]["units"][:128]:
        path = Path(row["sharedReferenceFile"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture synthetic reference " + row["voiceFamilyId"].encode())
        write(
            path.with_suffix(".json"),
            {
                "evaluationLockSha256": planned["base"]["lockSha256"],
                "sha256": fingerprint(path),
                "persona": row["persona"],
            },
        )


def engines(monkeypatch, *, failure=None):
    calls, initializations = [], []

    def factory(engine):
        def construct(*args):
            initializations.append(engine)

            def synthesize(text, persona, seed, reference):
                calls.append((engine, persona["id"], seed, text, reference))
                if failure == "missing" and len(calls) == 1:
                    raise RuntimeError("explicit missing-WAV fixture")
                if failure == "interrupt" and len(calls) == 1:
                    raise KeyboardInterrupt("explicit interrupted fixture")
                if failure == "mechanical" and len(calls) == 1:
                    return np.zeros(100, dtype=np.float32), 16000
                # PCM bookkeeping fixture, not speech and not evidence of matcher quality.
                samples = np.ones(4000, dtype=np.float32) * 0.1
                for bit in range(32):
                    samples[bit] = 0.05 if seed & (1 << bit) else -0.05
                return samples, 16000

            return synthesize

        return construct

    monkeypatch.setattr(tts, "engine_qwen", factory("qwen"))
    monkeypatch.setattr(tts, "engine_cosy", factory("cosy"))
    return calls, initializations


def generate(planned, engine):
    return tts.generate_tts_evaluation(
        planned["path"], engine, planned["model"], source=planned["source"]
    )


def complete(planned, monkeypatch, *, failure=None):
    references(planned)
    calls, init = engines(monkeypatch, failure=failure)
    generate(planned, "qwen")
    result = generate(planned, "cosy")
    return result, calls, init


def test_plan_is_exact_256_character_attempts_and_no_audio_reads_or_generation(planned):
    plan = tts.validate_tts_plan(planned["path"])
    assert plan == planned["plan"]
    assert not planned["output"].exists()
    assert not list(planned["path"].parent.rglob("*.wav"))
    units = plan["generationPlan"]["units"]
    assert len(units) == len({r["id"] for r in units}) == 256
    assert {r["generator"] for r in units} == {"qwen", "cosy"}
    assert {r["voiceFamilyId"] for r in units} == {f"voice-{i}" for i in range(36, 40)}
    assert all(r["sourceText"].endswith("。") and "[" not in r["sourceText"] for r in units)
    assert not plan["claims"]["actualPhonesAndTonesIndependentlyVerified"]
    assert not plan["claims"]["standardRecordingContentUsed"]


def test_engines_run_separately_with_one_seed_once_and_full_query_placeholders(
    planned, monkeypatch
):
    references(planned)
    calls, initializations = engines(monkeypatch)
    first = generate(planned, "qwen")
    assert len(calls) == 128 and initializations == ["qwen"]
    assert sum(r["generationStatus"] == "pending" for r in first["items"]) == 128
    quality = json.loads((planned["output"] / "quality-manifest.json").read_text())
    assert len(quality["cases"]) == 8192
    assert quality["coverage"]["missingWaveforms"] == 128
    assert not quality["qualityManifestReady"]
    generate(planned, "qwen")
    assert len(calls) == 128 and initializations == ["qwen"]
    second = generate(planned, "cosy")
    assert second["qualityManifestReady"] is True
    assert len(calls) == 256 and initializations == ["qwen", "cosy"]
    assert len({r[:3] for r in calls}) == 256
    final = json.loads((planned["output"] / "quality-manifest.json").read_text())
    assert len(final["cases"]) == 8192
    assert sum(r["expectedMatch"] for r in final["cases"]) == 256
    tone = [r for r in final["cases"] if r["case"] == "tone"]
    assert len(tone) == 96 and len({r["unitId"] for r in tone}) == 32
    assert {r["actualTargetId"] for r in tone} == {f"pm-ma{i}" for i in range(1, 5)}
    assert all(r["contrastCategory"] == "same-syllable-tone" for r in tone)
    assert all(r["generatorRevision"].endswith("fixed-test-revision") for r in final["cases"])
    assert all(r["referenceSha256"] for r in final["cases"])
    assert all(not r["actualPhonesAndToneIndependentlyVerified"] for r in final["cases"])


def test_engine_initialization_failure_is_terminal_for_all_128_placeholders(planned, monkeypatch):
    references(planned)
    init = []

    def broken(model):
        init.append(model)
        raise RuntimeError("explicit engine failure fixture")

    monkeypatch.setattr(tts, "engine_qwen", broken)
    result = generate(planned, "qwen")
    assert sum(r["generationStatus"] == "tts-failure" for r in result["items"]) == 128
    assert not result["qualityManifestReady"]
    generate(planned, "qwen")
    assert len(init) == 1
    quality = json.loads((planned["output"] / "quality-manifest.json").read_text())
    assert len(quality["cases"]) == 8192 and all(r["sha256"] is None for r in quality["cases"])


def test_missing_waveform_stays_in_full_denominator_and_blocks_merge_without_retry(
    planned, monkeypatch
):
    result, calls, initializations = complete(planned, monkeypatch, failure="missing")
    assert len(result["items"]) == 256 and len(calls) == 256
    assert sum(not r.get("sha256") for r in result["items"]) == 1
    assert not result["qualityManifestReady"]
    before = list(calls)
    generate(planned, "qwen")
    assert calls == before and len(initializations) == 2
    quality = planned["output"] / "quality-manifest.json"
    assert len(json.loads(quality.read_text())["cases"]) == 8192
    with pytest.raises(ValueError, match="ALL_256_TTS_WAVEFORMS_REQUIRED"):
        tts.merge_quality_manifests(
            [quality], planned["output"].parent / "merged", tts_plan=planned["path"]
        )


def test_mechanical_failure_wav_is_kept_with_positive_and_wrong_queries(planned, monkeypatch):
    result, calls, _ = complete(planned, monkeypatch, failure="mechanical")
    assert result["qualityManifestReady"] is True
    failures = [r for r in result["items"] if r["generationStatus"] == "mechanical-failure"]
    assert len(failures) == 1 and failures[0]["sha256"]
    row = failures[0]
    assert (planned["output"] / row["file"]).is_file()
    quality = json.loads((planned["output"] / "quality-manifest.json").read_text())
    retained = [r for r in quality["cases"] if r["unitId"] == row["id"]]
    assert len(retained) == 32 and sum(r["expectedMatch"] for r in retained) == 1
    assert all(r["clearAudio"] for r in retained)
    generate(planned, "qwen")
    assert len(calls) == 256


def test_interrupted_attempt_is_durable_and_is_never_redrawn(planned, monkeypatch):
    references(planned)
    calls, _ = engines(monkeypatch, failure="interrupt")
    with pytest.raises(KeyboardInterrupt):
        generate(planned, "qwen")
    data = json.loads((planned["output"] / "manifest.json").read_text())
    first = data["items"][0]
    assert first["generationStatus"] == "attempt-started"
    result = generate(planned, "qwen")
    assert result["items"][0]["generationStatus"] == "interrupted-attempt"
    assert len(calls) == 128 and sum(c[2] == first["seed"] for c in calls) == 1
    assert not result["qualityManifestReady"]


def test_parallel_engine_guard_prevents_another_mps_initialization(planned, monkeypatch):
    references(planned)
    calls, initializations = engines(monkeypatch)
    generate(planned, "qwen")
    (planned["output"] / ".generation.lock").write_text("another process or interrupted operation")
    with pytest.raises(ValueError, match="ENGINE_ALREADY_RUNNING"):
        generate(planned, "cosy")
    assert len(calls) == 128 and initializations == ["qwen"]


def test_missing_main_reference_is_preflight_failure_without_tts_attempt(planned, monkeypatch):
    calls, initializations = engines(monkeypatch)
    with pytest.raises(ValueError, match="MAIN_LOCK_SHARED_REFERENCE_REQUIRED"):
        generate(planned, "qwen")
    assert not calls and not initializations
    data = json.loads((planned["output"] / "manifest.json").read_text())
    assert len(data["items"]) == 256 and all(
        r["generationStatus"] == "pending" for r in data["items"]
    )


def test_model_change_and_rehashed_text_change_fail_before_engine(planned, monkeypatch):
    _, initializations = engines(monkeypatch)
    planned["base"]["model"]["thresholds"]["accept"] = 0.8
    with pytest.raises(ValueError, match="MODEL_OR_CALIBRATION_BINDING_CHANGED"):
        generate(planned, "qwen")
    assert not initializations
    planned["base"]["model"]["thresholds"]["accept"] = 0.9
    plan = json.loads(planned["path"].read_text())
    plan["generationPlan"]["units"][0]["sourceText"] = "changed text"
    plan.pop("planSha256")
    plan["planSha256"] = tts._lock_digest(plan)
    write(planned["path"], plan)
    with pytest.raises(ValueError, match="FROZEN_GENERATION_PLAN_CHANGED"):
        generate(planned, "qwen")
    assert not initializations


@pytest.mark.parametrize("change", ["claims", "code"])
def test_rehashed_plan_cannot_promote_weak_labels_or_change_leaf_code(planned, change):
    plan = json.loads(planned["path"].read_text())
    if change == "claims":
        plan["claims"]["actualPhonesAndTonesIndependentlyVerified"] = True
    else:
        plan["leafCodeSha256"] = "0" * 64
    plan.pop("planSha256")
    plan["planSha256"] = tts._lock_digest(plan)
    write(planned["path"], plan)
    with pytest.raises(ValueError, match="WEAK_LABEL_CLAIMS_CHANGED|EVALUATION_CODE_CHANGED"):
        tts.validate_tts_plan(planned["path"])


def test_safe_merge_preserves_all_sources_categories_and_real_quality_freeze(planned, monkeypatch):
    complete(planned, monkeypatch)
    tts_quality = planned["output"] / "quality-manifest.json"
    other = planned["output"].parent / "vc-cases"
    other.mkdir()
    audio = other / "fixture.wav"
    audio.write_bytes(encode_wav(np.ones(4000, dtype=np.float32) * 0.2))
    cases = [
        {
            "id": "vc-" + str(i),
            "source": "known-standard-new-family",
            "case": case,
            "unitId": "one-vc-unit",
            "file": audio.name,
            "sha256": fingerprint(audio),
            "targetId": target,
            "expectedMatch": positive,
            "clearAudio": True,
            "split": "test",
            "generator": "cosy",
            "contrastCategory": "vc-content",
            "sourceRootId": "known-standard-root",
            "voiceFamilyId": "voice-36",
        }
        for i, (case, target, positive) in enumerate(
            [("clean-positive", "pm-ni3", True), ("near-phoneme", "pm-li3", False)]
        )
    ]
    exclusion = write(
        other / "exclusions.json",
        {"items": [{"id": "cal", "split": "calibration", "sourceRootId": "old-cal-parent"}]},
    )
    other_manifest = write(
        other / "manifest.json",
        {
            "schemaVersion": 1,
            "evaluationLockSha256": planned["base"]["lockSha256"],
            "sources": {
                "known-standard-new-family": {"usage": "unseen", "labelProvenance": "fixture only"}
            },
            "cases": cases,
            "exclusionManifests": [{"path": str(exclusion), "sha256": fingerprint(exclusion)}],
        },
    )
    output = planned["output"].parent / "merged"
    result = tts.merge_quality_manifests(
        [other_manifest, tts_quality], output, tts_plan=planned["path"]
    )
    assert len(result["cases"]) == 8194
    assert result["coverage"]["positiveTargetsBySource"]["known-standard-new-family"] == ["pm-ni3"]
    assert len(result["coverage"]["positiveTargetsBySource"]["pure-tts-new-family-qwen"]) == 32
    assert {r["contrastCategory"] for r in result["cases"]} == {
        "vc-content",
        "public-target-positive",
        "same-syllable-tone",
        "phoneme-mismatch",
    }
    assert all(
        not Path(r["file"]).is_absolute() and ".." not in Path(r["file"]).parts
        for r in result["cases"]
    )
    plan = freeze_plan(
        planned["model"],
        output / "manifest.json",
        calibration_manifests=[exclusion],
        output=output / "quality.freeze.json",
    )
    assert len(plan["cases"]) == 8194


@pytest.mark.parametrize("change", ["drop-query", "extra-query", "policy", "audio"])
def test_merge_cannot_remove_hard_queries_or_inflate_easy_queries(planned, monkeypatch, change):
    complete(planned, monkeypatch)
    quality = planned["output"] / "quality-manifest.json"
    data = json.loads(quality.read_text())
    if change == "drop-query":
        data["cases"].pop()
    elif change == "extra-query":
        data["cases"].append({**data["cases"][0], "id": "invented-easy-query"})
    elif change == "policy":
        data["sources"]["pure-tts-new-family-qwen"]["requireBothClasses"] = False
    else:
        row = data["cases"][0]
        (quality.parent / row["file"]).write_bytes(b"changed waveform")
    write(quality, data)
    with pytest.raises(ValueError):
        tts.merge_quality_manifests(
            [quality], planned["output"].parent / "merged", tts_plan=planned["path"]
        )
