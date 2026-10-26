"""Provenance tests use numeric fixtures, never pronunciation-quality evidence."""

import hashlib
import json
from copy import deepcopy

import numpy as np
import pytest

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_stress import common_targets, evaluate, prepare, source_lineage


def fixture_sources(tmp_path):
    aliases = native_rime_aliases("hanziflow")
    registry = json.loads((ROOT / "content/pronunciation-pretrained-models.json").read_text())
    schema = next(
        f["sha256"]
        for f in registry["models"]["hanziflow"]["files"]
        if f["path"] == "v2_1_target_schema.json"
    )
    rows = []
    for i in range(4):
        path = tmp_path / f"numeric-fixture-{i}.wav"
        waveform = np.zeros(6400, dtype=np.float32)
        waveform[1000:5000] = 0.15 * np.sin(np.arange(4000) * (0.12 + i * 0.01))
        path.write_bytes(encode_wav(waveform))
        rows.append(
            {
                "id": f"numeric-fixture-{i}",
                "file": str(path),
                "sha256": fingerprint(path),
                "speakerId": "fixture-calibration-speaker",
                "voiceFamilyId": "fixture-family",
                "referenceSourceId": "fixture-reference",
                "split": "calibration",
                "parentSha256": f"fixture-parent-{i}",
                "sourceUtteranceId": f"utterance-{i}",
                "expertLabel": "unanimous-correct",
                "expertRatings": {k: [1, 1, 1] for k in ("onset", "rime", "tone")},
                "componentExpertLabels": {
                    k: "unanimous-correct" for k in ("onset", "rime", "tone")
                },
                "expertAnnotationResolved": True,
                "alignment": {"available": True},
                "labelPolicyFlags": [],
                "numericalQualityFlags": [],
                "onset": "m",
                "rime": "a",
                "tone": i + 1,
            }
        )
    parent = {
        "version": "ompal-three-head-midpoint-v2-model-specific-apical",
        "frozenTestIncluded": False,
        "pipelineSha256": fingerprint(ROOT / "pinyin_matcher/pretrained_ompal_clips.py"),
        "alignerSha256": fingerprint(ROOT / "pinyin_matcher/pretrained_align.py"),
        "alignmentMapping": {
            "model": "hanziflow",
            "aliases": aliases,
            "aliasesSha256": hashlib.sha256(
                json.dumps(aliases, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "upstreamTargetSchemaSha256": schema,
        },
        "items": rows,
    }
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(parent))
    source = deepcopy(parent)
    source.update(
        {
            "version": "ompal-median-ctc-energy-v3",
            "sourceManifestSha256": fingerprint(parent_path),
            "pipelineSha256": fingerprint(ROOT / "pinyin_matcher/pretrained_alignment_v3.py"),
            "configurationSha256": fingerprint(
                ROOT / "content/pronunciation-pretrained-alignment-v3.json"
            ),
        }
    )
    source["items"][0]["bounds"] = {"diagnosticOnly": True}
    source["items"][0]["boundaryV3"] = {"applied": True}
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    return parent, parent_path, source, source_path


def fixture_packages(tmp_path, source_path, count=2):
    result = []
    for i in range(count):
        path = tmp_path / f"package-{i}"
        path.mkdir()
        (path / "model.json").write_text(
            json.dumps(
                {
                    "model": f"fixture-{i}",
                    "manifestSha256": fingerprint(source_path),
                    "coveredTargets": [
                        {"id": f"pm-ma{tone}", "onset": "m", "rime": "a", "tone": tone}
                        for tone in range(1, 5)
                    ],
                }
            )
        )
        result.append(path)
    return result


def test_v3_requires_exact_parent_and_current_boundary_code_and_configuration(tmp_path):
    _, parent, source, _ = fixture_sources(tmp_path)
    with pytest.raises(ValueError, match="PARENT_MANIFEST_REQUIRED"):
        source_lineage(source, None)
    different = tmp_path / "other.json"
    different.write_text("{}")
    with pytest.raises(ValueError, match="PARENT_MANIFEST_DIGEST_MISMATCH"):
        source_lineage(source, None, different)
    good = source_lineage(source, None, parent)
    assert good["unchangedLabelAndLineageRoots"] == 4
    assert good["sourceParentManifestSha256"] == fingerprint(parent)
    for field in ("pipelineSha256", "configurationSha256"):
        changed = {**source, field: "changed"}
        with pytest.raises(ValueError, match="PIPELINE_OR_CONFIGURATION_MISMATCH"):
            source_lineage(changed, None, parent)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expertLabel", "unanimous-error"),
        ("expertRatings", {"tone": [0, 0, 0]}),
        ("componentExpertLabels", {"tone": "unanimous-error"}),
        ("labelPolicyFlags", ["changed"]),
        ("speakerId", "different"),
        ("voiceFamilyId", "different"),
        ("referenceSourceId", "different"),
        ("parentSha256", "different"),
        ("onset", "b"),
        ("rime", "o"),
        ("tone", 4),
        ("split", "train"),
    ],
)
def test_v3_cannot_change_expert_labels_or_source_lineage(tmp_path, field, value):
    _, parent, source, _ = fixture_sources(tmp_path)
    source["items"][0][field] = value
    with pytest.raises(ValueError, match="LABEL_OR_LINEAGE_CHANGED"):
        source_lineage(source, None, parent)


@pytest.mark.parametrize("change", ["missing-root", "duplicate-root"])
def test_v3_requires_same_unique_root_ids(tmp_path, change):
    _, parent, source, _ = fixture_sources(tmp_path)
    if change == "missing-root":
        source["items"].pop()
    else:
        source["items"].append(deepcopy(source["items"][0]))
    with pytest.raises(ValueError, match="ROOT_IDENTITIES_CHANGED"):
        source_lineage(source, None, parent)


@pytest.mark.parametrize("where", ["v3", "parent"])
def test_v3_rejects_final_audio_even_when_flag_claims_false(tmp_path, where):
    original, parent, source, _ = fixture_sources(tmp_path)
    if where == "parent":
        original["items"][0]["split"] = "test"
        original["items"][0]["file"] = "MUST_NOT_BE_OPENED"
        parent.write_text(json.dumps(original))
        source["sourceManifestSha256"] = fingerprint(parent)
    else:
        source["items"][0]["split"] = "test"
        source["items"][0]["file"] = "MUST_NOT_BE_OPENED"
    with pytest.raises(ValueError, match="FROZEN_TEST_COHORT"):
        source_lineage(source, None, parent)


def test_single_model_opt_in_is_explicit_recorded_and_keeps_source_binding(tmp_path):
    _, parent, _, source = fixture_sources(tmp_path)
    packages = fixture_packages(tmp_path, source, count=1)
    with pytest.raises(ValueError, match="AT_LEAST_THREE"):
        common_targets(packages, fingerprint(source))
    with pytest.raises(ValueError, match="THIS_SOURCE_MANIFEST"):
        common_targets(packages, "wrong-source", allow_single_model_diagnostic=True)
    data = prepare(
        source,
        packages,
        tmp_path / "stress",
        expected_source_sha=fingerprint(source),
        source_parent_manifest=parent,
        allow_single_model_diagnostic=True,
    )
    assert data["phase"] == "calibration-diagnostic"
    assert data["establishesFinalAcceptance"] is False
    assert data["allowSingleModelDiagnostic"] is True
    assert data["cases"] and len(data["packagesAtPreparation"]) == 1
    saved = tmp_path / "stress/manifest.json"
    data["allowSingleModelDiagnostic"] = False
    saved.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="EXPLICIT_DIAGNOSTIC_OPT_IN"):
        evaluate(saved, packages[0], tmp_path / "never-written.json")


def test_prepared_v3_revalidates_parent_before_loading_any_model(tmp_path):
    _, parent, _, source = fixture_sources(tmp_path)
    packages = fixture_packages(tmp_path, source)
    prepare(
        source,
        packages,
        tmp_path / "stress",
        expected_source_sha=fingerprint(source),
        source_parent_manifest=parent,
        allow_single_model_diagnostic=True,
    )
    parent.write_text("{}")
    with pytest.raises(ValueError, match="PARENT_MANIFEST_DIGEST_MISMATCH"):
        evaluate(tmp_path / "stress/manifest.json", packages[0], tmp_path / "never-written.json")
