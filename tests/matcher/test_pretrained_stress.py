"""Pressure bookkeeping tests numeric transformations, not pronunciation accuracy."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_stress import (
    build_report,
    common_targets,
    load_protocol,
    noise_payload,
    prepare,
    select_sources,
    source_lineage,
)


def numeric_wave(index=0):
    # Deliberate synthetic boundary fixture; never offered as pronunciation truth.
    samples = np.zeros(6400, dtype=np.float32)
    positions = np.arange(4000, dtype=np.float32)
    samples[1000:5000] = 0.15 * np.sin(positions * (0.12 + index * 0.01))
    return samples


def rows_fixture(tmp_path):
    rows = []
    for index in range(4):
        file = tmp_path / f"test-only-{index}.wav"
        payload = encode_wav(numeric_wave(index))
        file.write_bytes(payload)
        rows.append(
            {
                "id": f"test-only-{index}",
                "file": str(file),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "speakerId": "test-only-calibration-speaker",
                "split": "calibration",
                "parentSha256": f"different-test-parent-{index}",
                "expertLabel": "unanimous-correct",
                "expertRatings": {key: [1, 1, 1] for key in ("onset", "rime", "tone")},
                "expertAnnotationResolved": True,
                "alignment": {"available": True},
                "labelPolicyFlags": [],
                "numericalQualityFlags": [],
                "onset": "test-onset",
                "rime": "test-rime",
                "tone": index + 1,
            }
        )
    return rows


def test_source_selection_never_opens_test_or_train_paths_and_is_deterministic(tmp_path):
    rows = rows_fixture(tmp_path)
    targets = {("test-onset", "test-rime", str(i)): f"test-target-{i}" for i in range(1, 5)}
    rows.extend(
        [
            {**rows[0], "split": split, "file": str(tmp_path / "NEVER_OPEN_THIS")}
            for split in ("train", "test")
        ]
    )
    first, stats = select_sources(rows, load_protocol(), targets, tmp_path)
    again, _ = select_sources(list(reversed(rows)), load_protocol(), targets, tmp_path)
    assert [(a["id"], b["id"]) for a, b in first] == [(a["id"], b["id"]) for a, b in again]
    assert stats["anchors"] == 3
    assert all(a["split"] == b["split"] == "calibration" for a, b in first)
    assert all(a["parentSha256"] != b["parentSha256"] and a["tone"] != b["tone"] for a, b in first)


def test_noise_is_reproducible_and_snr_is_measured_without_relabeling_pronunciation():
    first, info = noise_payload(numeric_wave(), -5, 17)
    again, _ = noise_payload(numeric_wave(), -5, 17)
    different, _ = noise_payload(numeric_wave(), -5, 18)
    assert first == again and first != different
    assert info["prePcmMeasuredSnrDb"] == pytest.approx(-5, abs=1e-5)
    assert "actualPinyin" not in info and "pronunciationCorrect" not in info


def report_fixture():
    return {
        "protocol": load_protocol(),
        "cases": [
            {
                "id": "multi-a",
                "kind": "two-syllable",
                "sha256": "same-wave",
                "targetIds": ["test-target-a", "test-target-b"],
                "expectedBehavior": "do-not-match",
            },
            {
                "id": "multi-b",
                "kind": "two-syllable",
                "sha256": "same-wave",
                "targetIds": ["test-target-a"],
                "expectedBehavior": "do-not-match",
            },
            {
                "id": "blank",
                "kind": "omission-silence",
                "sha256": "blank-wave",
                "targetIds": ["test-target-a"],
                "expectedBehavior": "abstain",
            },
        ],
    }


def test_queries_share_actual_waveform_unit_and_missing_outputs_remain_counted():
    data = report_fixture()
    records = [
        {"caseId": "multi-a", "targetId": "test-target-a", "status": "matched"},
        {"caseId": "multi-a", "targetId": "test-target-b", "status": "uncertain"},
        {"caseId": "multi-b", "targetId": "test-target-a", "status": "uncertain"},
    ]
    report = build_report(data, records, model_available=True)
    assert report["plannedQueries"] == 4 and report["missingResults"] == 1
    assert report["actualPayloadUnits"] == 2
    multi = report["byKind"]["two-syllable"]
    assert multi["matchedUnits"]["count"] == multi["matchedUnits"]["denominator"] == 1
    assert report["overallByExpectedBehavior"]["do-not-match"]["actualPayloadUnits"] == 1
    assert report["predictions"][-1]["status"] == "unavailable"
    assert not report["stressChecksPassed"]


def test_silence_explicit_error_and_missing_model_cannot_pass_pressure_check():
    data = report_fixture()
    records = [
        {
            "caseId": c["id"],
            "targetId": target,
            "status": "retry" if c["kind"] == "omission-silence" else "uncertain",
        }
        for c in data["cases"]
        for target in c["targetIds"]
    ]
    report = build_report(data, records, model_available=True)
    assert not report["checks"]["omission-silence:explicitRetry"]
    for row in records:
        row["status"] = "uncertain"
    assert not build_report(data, records, model_available=False)["stressChecksPassed"]
    with pytest.raises(ValueError, match="DUPLICATE_RESULT"):
        build_report(data, records + [deepcopy(records[0])], model_available=True)


def test_preparation_rejects_stale_alignment_before_package_or_audio_loading(tmp_path):
    source = {"frozenTestIncluded": False, "pipelineSha256": "stale-before-schema-fix"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="BOUNDARIES_DO_NOT_MATCH"):
        prepare(
            path,
            [Path("not-read")],
            tmp_path / "out",
            expected_source_sha=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    source["frozenTestIncluded"] = True
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="FROZEN_TEST"):
        prepare(
            path,
            [],
            tmp_path / "out",
            expected_source_sha=hashlib.sha256(path.read_bytes()).hexdigest(),
        )


def test_original_pipeline_snapshot_does_not_bypass_corrected_phone_semantics(tmp_path):
    from pinyin_matcher.pretrained_native import native_rime_aliases

    aliases = native_rime_aliases("hanziflow")
    registry = json.loads((ROOT / "content/pronunciation-pretrained-models.json").read_text())
    schema_sha = next(
        f["sha256"]
        for f in registry["models"]["hanziflow"]["files"]
        if f["path"] == "v2_1_target_schema.json"
    )
    snapshot = tmp_path / "pipeline.py"
    snapshot.write_text("# numeric fixture representing archived preparation code\n")
    source = {
        "version": "ompal-three-head-midpoint-v2-model-specific-apical",
        "pipelineSha256": fingerprint(snapshot),
        "alignerSha256": fingerprint(ROOT / "pinyin_matcher/pretrained_align.py"),
        "alignmentMapping": {
            "model": "hanziflow",
            "aliases": aliases,
            "aliasesSha256": hashlib.sha256(
                json.dumps(aliases, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "upstreamTargetSchemaSha256": schema_sha,
        },
    }
    with pytest.raises(ValueError, match="SNAPSHOT_REQUIRED"):
        source_lineage(source, None)
    assert source_lineage(source, snapshot)["pipelineChangedSincePreparation"]
    source["alignmentMapping"]["aliases"] = {**aliases, "i-dental": "ii"}
    with pytest.raises(ValueError, match="BOUNDARIES_DO_NOT_MATCH"):
        source_lineage(source, snapshot)


def test_optimized_comparison_uses_common_coverage_of_every_one_of_eight_packages(tmp_path):
    packages = []
    ma = {"id": "pm-ma1", "onset": "m", "rime": "a", "tone": 1}
    ba = {"id": "pm-ba1", "onset": "b", "rime": "a", "tone": 1}
    for index in range(8):
        package = tmp_path / str(index)
        package.mkdir()
        (package / "model.json").write_text(
            json.dumps(
                {
                    "model": str(index),
                    "manifestSha256": "fixed-source",
                    "coveredTargets": [ma, ba] if index < 7 else [ma],
                }
            )
        )
        packages.append(package)
    common, records = common_targets(packages, "fixed-source")
    assert common == {("m", "a", "1"): "pm-ma1"}
    assert len(records) == 8
