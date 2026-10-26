"""Case construction checks metadata and full denominators, never model efficacy."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import evaluation_cases as builder
from pinyin_matcher.audio import decode_wav, encode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.quality import freeze_plan


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    used = write(
        tmp_path / "used.json",
        {
            "items": [
                {
                    "id": "train",
                    "split": "train",
                    "sha256": "old-train-wave",
                    "sourceRootId": "old-train-parent",
                    "voiceFamilyId": "voice-00",
                },
                {"id": "test-ignored", "split": "test", "voiceFamilyId": "voice-32"},
            ]
        },
    )
    pitch = write(
        tmp_path / "pitch.json",
        {
            "items": [
                {"id": "pitch", "split": "calibration", "sourceSha256": "old-pitch-parent"},
            ]
        },
    )
    collection = write(
        tmp_path / "collection.json",
        {
            "inputManifestSha256": {str(used): fingerprint(used)},
        },
    )
    targets = [
        {"id": "ma1", "pinyin": "mā", "phones": ["m", "a"], "tone": 1},
        {"id": "ma2", "pinyin": "má", "phones": ["m", "a"], "tone": 2},
        {"id": "ma3", "pinyin": "mǎ", "phones": ["m", "a"], "tone": 3},
        {"id": "ba1", "pinyin": "bā", "phones": ["b", "a"], "tone": 1},
    ]
    for target in targets:
        target["form"] = "whole-syllable"
    covered = ["ma1", "ma2", "ba1"]
    model = tmp_path / "model"
    catalog = write(
        model / "targets.json",
        {
            "version": 1,
            "tokens": ["<blank>", "m", "a", "b"],
            "pilotIds": covered,
            "targets": targets,
        },
    )
    write(
        model / "model.json",
        {
            "version": "fixture-only",
            "file": "model.onnx",
            "catalogFile": catalog.name,
            "coveredTargetIds": covered,
            "thresholds": {},
            "dataProvenance": {
                kind + "Manifest" + suffix: value
                for kind in ("synthetic", "standard")
                for suffix, value in (("Path", str(used)), ("Sha256", fingerprint(used)))
            },
        },
    )
    (model / "model.onnx").write_bytes(b"test snapshot; no inference")
    vc_directory = tmp_path / "vc"
    plan = {
        "outputDirectory": str(vc_directory),
        "queryPolicy": {"coveredTargetIds": covered},
        "sources": [],
        "units": [],
        "personas": [],
    }
    for target in (targets[0], targets[2], targets[3]):
        plan["sources"].append(
            {
                "targetId": target["id"],
                "phones": target["phones"],
                "tone": target["tone"],
                "sourceRootId": "root-" + target["id"],
                "sourceSha256": "original-" + target["id"],
            }
        )
    vc_rows = []
    for voice in ("voice-32", "voice-33"):
        reference = vc_directory / "references" / (voice + ".wav")
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(b"fixture reference " + voice.encode())
        plan["personas"].append({"id": voice})
        for source in plan["sources"]:
            name = voice + "-" + source["targetId"]
            unit = {
                "id": name,
                "file": "cosy/" + name + ".wav",
                "seed": 10,
                "voiceFamilyId": voice,
                "targetId": source["targetId"],
                "sourceSha256": source["sourceSha256"],
            }
            plan["units"].append(unit)
            audio = vc_directory / unit["file"]
            audio.parent.mkdir(parents=True, exist_ok=True)
            samples = np.sin(np.arange(4000) * (0.04 + len(vc_rows) * 0.001)) * 0.1
            audio.write_bytes(encode_wav(samples.astype(np.float32)))
            vc_rows.append(
                {
                    **unit,
                    "file": audio.name,
                    "sha256": fingerprint(audio),
                    "split": "test",
                    "sourceRootId": source["sourceRootId"],
                    "sourceAllocation": "test",
                    "sourceDeclaredAllocation": "blind",
                    "evaluationLockSha256": "base-lock",
                    "referenceRootId": voice + "-reference",
                    "referenceSha256": fingerprint(reference),
                    "knownStandardRootNewVcFamilyValidation": True,
                    "generatorRevision": "cosy-fixed-revision",
                    "labelProvenance": "fixture-only",
                }
            )
    base = {
        "configuration": {"file": str(tmp_path / "config.json")},
        "generationPlan": plan,
        "lockSha256": "base-lock",
        "modelDirectory": str(model),
        "model": {"coveredTargetIds": covered},
        "calibrationCollection": {"file": str(collection)},
    }
    lock = write(tmp_path / "lock.json", base)
    vc_manifest = write(
        vc_directory / "cosy/manifest.json",
        {
            "evaluationGenerationComplete": True,
            "evaluationLockSha256": "base-lock",
            "evaluationGenerationPlan": plan,
            "items": vc_rows,
            "quarantined": [],
            "rejected": [],
        },
    )
    foreign_directory = tmp_path / "foreign"
    units, rows = [], []
    for index, voice in enumerate(("voice-32", "voice-33")):
        unit = {
            "id": "foreign-" + voice,
            "voiceFamilyId": voice,
            "file": "qwen/" + voice + ".wav",
            "split": "test",
            "referenceRootId": voice + "-reference",
            "sourceRootId": "foreign-text-theme",
            "lexicalRootId": "theme",
            "againstTargetIds": ["ba1"],
            "sourceText": "theme",
            "language": "English",
            "contrastCategory": "dental-fricative",
            "phoneticDifference": "Intended /θ/ differs from /b/.",
            "seed": 20 + index,
        }
        audio = foreign_directory / unit["file"]
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(encode_wav(np.ones(3000 + index, dtype=np.float32) * 0.1))
        units.append(unit)
        rows.append(
            {
                **unit,
                "sha256": fingerprint(audio),
                "generationStatus": "mechanical-failure" if index else "accepted-mechanically",
            }
        )
    leaf = {
        "evaluationLock": {"lockSha256": "base-lock"},
        "planSha256": "leaf-plan",
        "qwenInstallation": {"revision": "qwen-fixed-revision"},
        "generationPlan": {"outputDirectory": str(foreign_directory), "units": units},
    }
    leaf_path = write(tmp_path / "leaf.json", leaf)
    foreign_manifest = write(
        foreign_directory / "manifest.json",
        {
            "qualityManifestReady": True,
            "foreignPlanSha256": "leaf-plan",
            "evaluationLockSha256": "base-lock",
            "items": rows,
        },
    )
    monkeypatch.setattr(builder, "validate_evaluation_lock", lambda *args: copy.deepcopy(base))
    monkeypatch.setattr(builder, "validate_foreign_plan", lambda *args: copy.deepcopy(leaf))
    return {
        "evaluation_lock": lock,
        "vc_manifest": vc_manifest,
        "foreign_plan": leaf_path,
        "foreign_manifest": foreign_manifest,
        "output": tmp_path / "cases",
        "exclusion_manifests": [pitch],
    }


def test_all_public_queries_and_only_authored_foreign_pairs_are_kept(inputs):
    result = builder.build_cases(**inputs)
    assert result["coverage"]["totalQueries"] == 6 * 3 + 6 * 3 + 2
    assert result["coverage"]["positiveQueries"] == 4
    assert result["coverage"]["publicPositiveTargetIds"] == ["ba1", "ma1"]
    assert {r["targetId"] for r in result["cases"]} == {"ma1", "ma2", "ba1"}
    assert not result["claims"]["modelInferencePerformedByBuilder"]
    assert result["claims"]["standardRootsHistoricallyKnown"]
    foreign = [r for r in result["cases"] if r["source"] == builder.FOREIGN_SOURCE]
    assert len(foreign) == 2
    assert {r["generationStatus"] for r in foreign} == {
        "accepted-mechanically",
        "mechanical-failure",
    }
    assert {r["generatorRevision"] for r in foreign} == {"qwen-fixed-revision"}
    assert all(r["contrastCategory"] == "dental-fricative" for r in foreign)
    # The real quality freeze can consume the copied audio and lineage unchanged.
    plan = freeze_plan(
        Path(json.loads(inputs["evaluation_lock"].read_text())["modelDirectory"]),
        inputs["output"] / "manifest.json",
        calibration_manifests=inputs["exclusion_manifests"],
        output=inputs["output"] / "quality.freeze.json",
    )
    assert len(plan["cases"]) == 38


def test_extra_pairing_is_fixed_same_family_and_preserves_both_parents(inputs):
    result = builder.build_cases(**inputs)
    extras = [r for r in result["cases"] if r["case"] == "extra-syllable"]
    assert len(extras) == 18
    for row in extras:
        assert all(row["voiceFamilyId"] in name for name in row["parentUnitIds"])
        assert row["parentRootIds"][0] != row["parentRootIds"][1]
        assert row["parentTargetIds"][0][:2] != row["parentTargetIds"][1][:2]
        assert row["secondaryParentSha256"]
        samples = decode_wav((inputs["output"] / row["file"]).read_bytes())
        assert len(samples) == 4000 * 2 + builder.GAP_SAMPLES
        assert np.count_nonzero(samples[4000:6400]) == 0
    with pytest.raises(ValueError, match="OUTPUT_MUST_BE_NEW"):
        builder.build_cases(**inputs)


@pytest.mark.parametrize(
    "field", ["sourceRootId", "sourceSha256", "referenceSha256", "voiceFamilyId"]
)
def test_parent_and_reference_leakage_blocks_before_output(inputs, field):
    vc = json.loads(inputs["vc_manifest"].read_text())
    # This is the second parent's source for ba1; single-parent-only checking is insufficient.
    value = vc["items"][0][field]
    pitch = inputs["exclusion_manifests"][0]
    write(pitch, {"items": [{"id": "used-parent", "split": "calibration", field: value}]})
    with pytest.raises(ValueError, match="LINEAGE_LEAKAGE"):
        builder.build_cases(**inputs)
    assert not inputs["output"].exists()


@pytest.mark.parametrize("change", ["remove", "duplicate", "pending", "missing-wav", "changed-wav"])
def test_foreign_missing_or_changed_attempt_cannot_shrink_denominator(inputs, change):
    data = json.loads(inputs["foreign_manifest"].read_text())
    row = data["items"][-1]
    if change == "remove":
        data["items"].pop()
    elif change == "duplicate":
        data["items"].append(copy.deepcopy(row))
    elif change == "pending":
        row["generationStatus"] = "pending"
    else:
        path = inputs["foreign_manifest"].parent / row["file"]
        if change == "missing-wav":
            path.unlink()
        else:
            path.write_bytes(b"changed")
    write(inputs["foreign_manifest"], data)
    with pytest.raises(ValueError):
        builder.build_cases(**inputs)
    assert not inputs["output"].exists()


def test_foreign_language_does_not_add_unplanned_negative_targets(inputs):
    data = json.loads(inputs["foreign_manifest"].read_text())
    data["items"][0]["againstTargetIds"].append("ma1")
    write(inputs["foreign_manifest"], data)
    with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
        builder.build_cases(**inputs)


def test_vc_incomplete_set_and_changed_parent_cannot_be_used(inputs):
    data = json.loads(inputs["vc_manifest"].read_text())
    data["items"][0]["sourceSha256"] = "wrong-parent"
    write(inputs["vc_manifest"], data)
    with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
        builder.build_cases(**inputs)


def test_exclusion_digest_change_blocks_construction(inputs):
    base = json.loads(inputs["evaluation_lock"].read_text())
    model = json.loads((Path(base["modelDirectory"]) / "model.json").read_text())
    Path(model["dataProvenance"]["standardManifestPath"]).write_text("changed")
    with pytest.raises(ValueError, match="EXCLUSION_MANIFEST_CHANGED"):
        builder.build_cases(**inputs)


def test_unsafe_audio_path_is_rejected_before_copy(inputs):
    data = json.loads(inputs["vc_manifest"].read_text())
    data["items"][0]["file"] = "../references/voice-32.wav"
    write(inputs["vc_manifest"], data)
    with pytest.raises(ValueError, match="PATH_INVALID"):
        builder.build_cases(**inputs)
    assert not inputs["output"].exists()
