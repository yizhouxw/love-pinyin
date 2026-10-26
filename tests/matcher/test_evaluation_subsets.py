"""Source-specific reporting with explicit missing audio; no actual held-out inference."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import evaluation_subsets as subsets
from pinyin_matcher.audio import decode_wav, encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.quality import _digest, _model_snapshot, freeze_plan


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def pcm(seed):
    samples = np.ones(4000, dtype=np.float32) * 0.1
    for bit in range(16):
        samples[bit] = 0.05 if seed & (1 << bit) else -0.05
    return encode_wav(samples)


@pytest.fixture
def sources(tmp_path, monkeypatch):
    catalog = json.loads((ROOT / "content/pronunciation-targets.json").read_text())
    targets = {r["id"]: r for r in catalog["targets"]}
    model = tmp_path / "model"
    write(model / "targets.json", catalog)
    (model / "acoustic.onnx").write_bytes(b"test-only snapshot; never run")
    used = write(
        tmp_path / "used.json",
        {
            "items": [
                {
                    "id": "train",
                    "split": "train",
                    "sourceRootId": "old-parent",
                    "voiceFamilyId": "voice-00",
                }
            ]
        },
    )
    pitch = write(
        tmp_path / "pitch.json",
        {"items": [{"id": "pitch", "split": "calibration", "sourceSha256": "old-pitch-parent"}]},
    )
    write(
        model / "model.json",
        {
            "version": "fixture",
            "file": "acoustic.onnx",
            "catalogFile": "targets.json",
            "coveredTargetIds": catalog["pilotIds"],
            "thresholds": {},
            "dataProvenance": {
                kind + "Manifest" + suffix: value
                for kind in ("synthetic", "standard")
                for suffix, value in (("Path", str(used)), ("Sha256", fingerprint(used)))
            },
        },
    )
    collection = write(
        tmp_path / "collection.json", {"inputManifestSha256": {str(used): fingerprint(used)}}
    )
    main_output = tmp_path / "main-output"
    plan = {
        "outputDirectory": str(main_output),
        "expectedWaveforms": 20,
        "sources": [],
        "personas": [],
        "units": [],
        "queryPolicy": {"coveredTargetIds": catalog["pilotIds"]},
    }
    retained = ["pm-ni3", "pm-he1", "pm-xi1", "pm-chi1", "pm-ri4"]
    for key in retained:
        plan["sources"].append(
            {
                "targetId": key,
                "phones": targets[key]["phones"],
                "tone": targets[key]["tone"],
                "sourceRootId": "standard-" + key,
                "sourceSha256": "mp3-" + key,
            }
        )
    rows = []
    for voice in [f"voice-{i}" for i in range(36, 40)]:
        reference = main_output / "references" / (voice + ".wav")
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(b"test reference " + voice.encode())
        plan["personas"].append({"id": voice})
        for source in plan["sources"]:
            name = voice + "-" + source["targetId"]
            unit = {
                "id": name,
                "file": "cosy/" + name + ".wav",
                "targetId": source["targetId"],
                "sourceSha256": source["sourceSha256"],
                "voiceFamilyId": voice,
                "seed": len(rows),
            }
            audio = main_output / unit["file"]
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(pcm(len(rows) + 1))
            plan["units"].append(unit)
            rows.append(
                {
                    **unit,
                    "file": audio.name,
                    "sha256": fingerprint(audio),
                    "split": "test",
                    "sourceRootId": source["sourceRootId"],
                    "sourceAllocation": "test",
                    "sourceDeclaredAllocation": "blind",
                    "evaluationLockSha256": "main-lock",
                    "referenceRootId": voice + "-reference",
                    "referenceSha256": fingerprint(reference),
                    "knownStandardRootNewVcFamilyValidation": True,
                    "generatorRevision": "cosy-fixture",
                    "labelProvenance": "test-only fixture",
                }
            )
    base = {
        "modelDirectory": str(model),
        "model": _model_snapshot(model),
        "lockSha256": "main-lock",
        "configuration": {"file": str(tmp_path / "configuration.json")},
        "generationPlan": plan,
        "calibrationCollection": {"file": str(collection)},
    }
    main_lock = write(tmp_path / "main.lock.json", base)
    vc_manifest = write(
        main_output / "cosy/manifest.json",
        {
            "evaluationGenerationComplete": True,
            "evaluationLockSha256": "main-lock",
            "evaluationGenerationPlan": plan,
            "items": rows,
            "rejected": [],
            "quarantined": [],
            "diagnostics": [],
        },
    )
    monkeypatch.setattr(subsets, "validate_evaluation_lock", lambda *a: copy.deepcopy(base))
    foreign_output = tmp_path / "foreign-output"
    foreign_units, foreign_rows = [], []
    for index in range(96):
        unit = {
            "id": "foreign-" + str(index),
            "file": f"qwen/foreign-{index}.wav",
            "againstTargetIds": ["pm-shi1"],
            "voiceFamilyId": f"voice-{36 + index % 4}",
            "referenceRootId": f"voice-{36 + index % 4}-reference",
            "split": "test",
            "sourceRootId": "foreign-text-" + str(index),
            "lexicalRootId": "word-" + str(index),
            "sourceText": "fixture-" + str(index),
            "language": "French",
            "contrastCategory": "fixture-contrast",
            "labelProvenance": "unverified TTS intent",
            "phoneticDifference": "Declared test-only phoneme difference.",
            "seed": index,
        }
        foreign_units.append(unit)
        if index == 95:
            foreign_rows.append(
                {**unit, "generationStatus": "tts-failure", "error": "TTS_TRUNCATED"}
            )
        else:
            audio = foreign_output / unit["file"]
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(pcm(100 + index))
            foreign_rows.append(
                {
                    **unit,
                    "sha256": fingerprint(audio),
                    "generationStatus": "mechanical-failure"
                    if index == 94
                    else "accepted-mechanically",
                }
            )
    leaf = {
        "evaluationLock": {"lockSha256": "main-lock"},
        "planSha256": "foreign-plan",
        "modelDirectory": str(model),
        "model": _model_snapshot(model),
        "qwenInstallation": {"revision": "qwen-fixture"},
        "generationPlan": {"outputDirectory": str(foreign_output), "units": foreign_units},
    }
    foreign_plan = write(tmp_path / "foreign.plan.json", leaf)
    foreign_manifest = write(
        foreign_output / "manifest.json",
        {
            "foreignPlanSha256": "foreign-plan",
            "evaluationLockSha256": "main-lock",
            "qualityManifestReady": False,
            "items": foreign_rows,
        },
    )
    monkeypatch.setattr(subsets, "validate_foreign_plan", lambda *a: copy.deepcopy(leaf))
    return {
        "main_lock": main_lock,
        "vc_manifest": vc_manifest,
        "pitch": pitch,
        "base": base,
        "foreign_plan": foreign_plan,
        "foreign_manifest": foreign_manifest,
        "output": tmp_path / "vc-subset",
        "diagnostic_plan": tmp_path / "foreign.diagnostic.plan.json",
        "diagnostic_report": tmp_path / "foreign.diagnostic.results.json",
        "leaf": leaf,
    }


def build_vc(sources):
    return subsets.build_vc_subset(
        sources["main_lock"],
        sources["vc_manifest"],
        sources["output"],
        exclusion_manifests=[sources["pitch"]],
    )


def freeze_foreign(sources):
    return subsets.create_foreign_diagnostic_plan(
        sources["foreign_plan"], sources["foreign_manifest"], sources["diagnostic_plan"]
    )


def test_vc_subset_has_complete_1280_queries_and_same_fixed_pairs(sources):
    before = sources["vc_manifest"].read_bytes()
    result = build_vc(sources)
    assert len(result["cases"]) == 1280
    assert result["coverage"]["toneNegativeQueries"] == 0
    assert result["coverage"]["caseQueryCounts"] == {
        "clean-positive": 20,
        "near-phoneme": 620,
        "extra-syllable": 640,
    }
    assert result["coverage"]["publicPositiveTargetIds"] == [
        "pm-chi1",
        "pm-he1",
        "pm-ni3",
        "pm-ri4",
        "pm-xi1",
    ]
    assert not result["fullBatchAcceptanceComplete"]
    expected = {
        "pm-chi1": "pm-he1",
        "pm-he1": "pm-ni3",
        "pm-ni3": "pm-ri4",
        "pm-ri4": "pm-xi1",
        "pm-xi1": "pm-chi1",
    }
    extras = [r for r in result["cases"] if r["case"] == "extra-syllable"]
    assert len({r["unitId"] for r in extras}) == 20
    for row in extras:
        assert expected[row["parentTargetIds"][0]] == row["parentTargetIds"][1]
        assert all(row["voiceFamilyId"] in parent for parent in row["parentUnitIds"])
        assert len(row["parentRootIds"]) == 2 and row["secondarySourceSha256"]
        samples = decode_wav((sources["output"] / row["file"]).read_bytes())
        assert len(samples) == 10400 and not np.count_nonzero(samples[4000:6400])
    plan = freeze_plan(
        Path(sources["base"]["modelDirectory"]),
        sources["output"] / "manifest.json",
        calibration_manifests=[Path(r["path"]) for r in result["exclusionManifests"]],
        output=sources["output"] / "quality.freeze.json",
    )
    assert len(plan["cases"]) == 1280
    assert sources["vc_manifest"].read_bytes() == before


@pytest.mark.parametrize("change", ["missing-unit", "historical-failure", "parent-leak"])
def test_vc_subset_cannot_discard_units_failures_or_secondary_parent_leakage(sources, change):
    if change == "parent-leak":
        write(
            sources["pitch"],
            {"items": [{"id": "used", "split": "calibration", "sourceRootId": "standard-pm-he1"}]},
        )
    else:
        data = json.loads(sources["vc_manifest"].read_text())
        if change == "missing-unit":
            data["items"].pop()
        else:
            data["failedGenerationAttempts"] = [{"id": "old-failure"}]
        write(sources["vc_manifest"], data)
    with pytest.raises(ValueError):
        build_vc(sources)
    assert not sources["output"].exists()


def test_foreign_plan_retains_missing_slot_and_runner_matches_only_95_real_wavs(
    sources, monkeypatch
):
    before = sources["foreign_manifest"].read_bytes()
    plan = freeze_foreign(sources)
    assert len(plan["cases"]) == 96 and plan["purpose"] == "diagnostic"
    assert plan["generationCoverage"]["actualWaveformFiles"] == 95
    assert plan["generationCoverage"]["missingWaveforms"] == 1
    missing = next(r for r in plan["cases"] if not r.get("sha256"))
    assert missing["generationFailureReason"] == "TTS_TRUNCATED"
    calls = []

    class FixtureMatcher:
        def __init__(self, model):
            self.model = model

        def match(self, target, payload, **kwargs):
            calls.append((target, payload))
            return {"status": "retry", "reason": "fixture-only; no accuracy claim"}

    from pinyin_matcher import inference

    monkeypatch.setattr(inference, "PinyinMatcher", FixtureMatcher)
    report = subsets.run_foreign_diagnostic(
        sources["diagnostic_plan"], sources["diagnostic_report"]
    )
    assert len(calls) == 95 and len(report["results"]) == 96
    assert report["actualAudioInferenceAttempts"] == 95
    assert report["observedAudioMetrics"]["negativeAudioUnits"] == 95
    assert report["overall"]["negativeAudioUnits"] == 96
    row = next(r for r in report["results"] if r["id"] == missing["id"])
    assert row["status"] == "unavailable" and row["reason"] == "TTS_TRUNCATED"
    assert row["audioInferencePerformed"] is False
    assert report["qualityPassed"] is False and report["purpose"] == "diagnostic"
    assert "FOREIGN_GENERATION_INCOMPLETE" in report["blockers"]
    assert not Path(missing["file"]).exists()
    assert sources["foreign_manifest"].read_bytes() == before


def test_foreign_runner_refuses_confirmatory_relabel_before_inference(sources):
    plan = freeze_foreign(sources)
    plan["purpose"] = "confirmatory"
    plan.pop("freezeSha256")
    plan["freezeSha256"] = _digest(plan)
    write(sources["diagnostic_plan"], plan)
    with pytest.raises(ValueError, match="DIAGNOSTIC_ONLY"):
        subsets.run_foreign_diagnostic(sources["diagnostic_plan"], sources["diagnostic_report"])


@pytest.mark.parametrize("change", ["audio", "source-manifest", "replacement"])
def test_foreign_provenance_change_or_fake_missing_audio_is_rejected(sources, change):
    plan = freeze_foreign(sources)
    if change == "audio":
        Path(plan["cases"][0]["file"]).write_bytes(b"changed")
    elif change == "source-manifest":
        sources["foreign_manifest"].write_text(sources["foreign_manifest"].read_text() + "\n")
    else:
        missing = next(r for r in plan["cases"] if not r.get("sha256"))
        Path(missing["file"]).write_bytes(pcm(999))
    with pytest.raises(ValueError):
        subsets.run_foreign_diagnostic(sources["diagnostic_plan"], sources["diagnostic_report"])
    assert not sources["diagnostic_report"].exists()


def test_foreign_placeholder_or_authored_target_cannot_be_deleted(sources):
    data = json.loads(sources["foreign_manifest"].read_text())
    data["items"].pop()
    write(sources["foreign_manifest"], data)
    with pytest.raises(ValueError, match="COMPLETE_PLANNED_EVALUATION_SET_REQUIRED"):
        freeze_foreign(sources)
