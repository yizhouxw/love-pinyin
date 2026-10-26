"""Coverage lineage/recomparison contracts; no fixtures imply acoustic quality."""

import copy
import hashlib
import json
import os

import pytest

import pinyin_matcher.pretrained_coverage as coverage
from pinyin_matcher.catalog import fingerprint


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def evidence(tone=2):
    tones = [0.01] * 4
    tones[tone - 1] = 0.97
    return {
        "onset": {"probabilities": [1.0]},
        "rime": {"probabilities": [0.99, 0.01]},
        "tone": {"probabilities": tones},
    }


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    rows = [
        {"id": "train", "split": "train", "syllable": "qia1", "onset": "q", "rime": "ia", "tone": 1}
    ]
    for index in range(6):
        rows.append(
            {
                "id": f"root-{index}",
                "split": "calibration",
                "syllable": "qiong2",
                "onset": "q",
                "rime": "iong",
                "tone": 2,
                "speakerId": f"speaker-{index % 2}",
                "source": "explicit-contract-fixture",
                "parentSha256": f"fixture-parent-{index}",
                "expertLabel": "unanimous-correct",
                "labelProvenance": "Synthetic probabilities test code contracts only.",
                "numericalQualityFlags": ["TOO_SHORT"] if index == 3 else [],
            }
        )
    manifest = tmp_path / "manifest.json"
    save(manifest, {"items": rows})
    monkeypatch.setattr(coverage, "read_rows", lambda *_: copy.deepcopy(rows))
    package = tmp_path / "original"
    (package / "encoder").mkdir(parents=True)
    resource = package / "encoder/weights.bin"
    resource.write_bytes(b"Explicit resource digest fixture, never model inference.")
    metadata = {
        "model": "sensevoice",
        "manifestSha256": fingerprint(manifest),
        "thresholds": {"probability": 0.9, "margin": 0.1},
        "vocabulary": {"onset": ["q"], "rime": ["iong", "ia"], "tone": ["1", "2", "3", "4"]},
        "coveredTargets": [
            {"id": "pm-qiong1", "form": "whole-syllable", "onset": "q", "rime": "iong", "tone": 1}
        ],
        "packageFiles": {
            "encoder/weights.bin": {
                "sha256": fingerprint(resource),
                "bytes": resource.stat().st_size,
            }
        },
    }
    save(package / "model.json", metadata)
    predictions = []
    for index in range(6):
        result = {
            "id": f"root-{index}",
            "syllable": "qiong2",
            "status": "unavailable",
            "reason": "TARGET_NOT_TRAINED",
            "comparisonEvidence": evidence(3 if index in (2, 5) else 2),
        }
        if index == 1:
            result["comparisonEvidence"]["forceUncertain"] = True
        if index == 2:
            result.update(status="uncertain", reason="PITCH_EVIDENCE_UNAVAILABLE")
        if index == 4:
            result.update(status="uncertain", reason="AUDIO_TOO_QUIET")
            result.pop("comparisonEvidence")
        predictions.append(result)
    cpu_report = tmp_path / "actual-cpu.json"
    report = {
        "split": "calibration",
        "rows": 6,
        "manifestSha256": fingerprint(manifest),
        "modelSha256": fingerprint(package / "model.json"),
        "predictions": predictions,
    }
    save(cpu_report, report)
    return {
        "rows": rows,
        "manifest": manifest,
        "package": package,
        "resource": resource,
        "metadata": metadata,
        "cpu": cpu_report,
        "report": report,
        "expanded": tmp_path / "expanded",
        "output": tmp_path / "reassessed.json",
    }


def expand(cohort):
    coverage.expand(cohort["package"], cohort["manifest"], cohort["expanded"])
    return json.loads((cohort["expanded"] / "model.json").read_text())


def test_hardlinked_resources_do_not_overwrite_original_metadata_or_report(cohort):
    source = cohort["package"] / "model.json"
    model_bytes, report_bytes = source.read_bytes(), cohort["cpu"].read_bytes()
    original_sha = hashlib.sha256(model_bytes).hexdigest()
    updated = expand(cohort)
    assert source.read_bytes() == model_bytes
    assert updated["previousModelSha256"] == original_sha
    assert os.stat(source).st_ino != os.stat(cohort["expanded"] / "model.json").st_ino
    assert (
        os.stat(cohort["resource"]).st_ino
        == os.stat(cohort["expanded"] / "encoder/weights.bin").st_ino
    )
    coverage.reassess(cohort["manifest"], cohort["expanded"], cohort["cpu"], cohort["output"])
    output = json.loads(cohort["output"].read_text())
    assert cohort["cpu"].read_bytes() == report_bytes
    assert output["actualCpuResultsSha256"] == fingerprint(cohort["cpu"])
    assert output["originalModelSha256"] == original_sha
    assert output["encoderAndHeadReexecuted"] is False
    assert source.read_bytes() == model_bytes


def test_all_four_tones_compare_every_root_and_preserve_all_signal_guards(cohort):
    updated = expand(cohort)
    assert {f"pm-qiong{tone}" for tone in range(1, 5)} <= {
        target["id"] for target in updated["coveredTargets"]
    }
    assert {f"pm-qia{tone}" for tone in range(1, 5)} <= {
        target["id"] for target in updated["coveredTargets"]
    }
    coverage.reassess(cohort["manifest"], cohort["expanded"], cohort["cpu"], cohort["output"])
    result = json.loads(cohort["output"].read_text())
    predictions = {row["id"]: row for row in result["predictions"]}
    assert len(predictions) == result["rows"] == 6
    assert predictions["root-0"]["status"] == "matched"
    assert predictions["root-5"]["status"] == "retry"
    for index in (1, 2, 3, 4):
        assert predictions[f"root-{index}"]["status"] == "uncertain"
        assert "comparisonEvidence" not in predictions[f"root-{index}"]
        assert "internalEvidence" not in predictions[f"root-{index}"]
    assert predictions["root-2"]["reason"] == "PITCH_EVIDENCE_UNAVAILABLE"
    for index in range(6):
        comparisons = [
            row
            for row in result["records"]
            if row["root_id"] == f"root-{index}" and row["error_type"] == "tone"
        ]
        assert {row["target_id"] for row in comparisons} == {"pm-qiong1", "pm-qiong3", "pm-qiong4"}
        if index in (1, 2, 3, 4):
            assert {row["status"] for row in comparisons} == {"uncertain"}
    wrong = next(
        row
        for row in result["records"]
        if row["root_id"] == "root-5" and row["target_id"] == "pm-qiong3"
    )
    assert wrong["status"] == "matched"
    assert result["metrics"]["positive"]["n"] == 6
    assert result["metrics"]["positive"]["accepted"]["count"] == 1
    assert result["metrics"]["positive"]["abstention"]["count"] == 4


@pytest.mark.parametrize("change", ["missing", "different", "escape"])
def test_resource_digest_and_containment_must_match_before_expansion(cohort, change):
    if change == "missing":
        cohort["resource"].unlink()
    elif change == "different":
        cohort["resource"].write_bytes(b"different")
    else:
        outside = cohort["package"].parent / "outside.bin"
        outside.write_bytes(b"outside")
        metadata = cohort["metadata"]
        metadata["packageFiles"] = {"../outside.bin": {"sha256": fingerprint(outside)}}
        save(cohort["package"] / "model.json", metadata)
    with pytest.raises(ValueError, match="SOURCE_PACKAGE_CHANGED"):
        expand(cohort)
    assert not cohort["expanded"].exists()


@pytest.mark.parametrize("field", ["modelSha256", "manifestSha256", "split"])
def test_reassessment_binds_original_cpu_report_model_and_manifest(cohort, field):
    expand(cohort)
    cohort["report"][field] = "wrong"
    save(cohort["cpu"], cohort["report"])
    with pytest.raises(ValueError, match="CPU_SOURCE_OR_MANIFEST"):
        coverage.reassess(cohort["manifest"], cohort["expanded"], cohort["cpu"], cohort["output"])
    assert not cohort["output"].exists()


@pytest.mark.parametrize("change", ["omit", "duplicate", "extra", "count", "target"])
def test_original_cpu_report_cannot_omit_duplicate_or_swap_calibration_roots(cohort, change):
    expand(cohort)
    report = cohort["report"]
    if change == "omit":
        report["predictions"].pop()
    elif change == "duplicate":
        report["predictions"].append(copy.deepcopy(report["predictions"][0]))
    elif change == "extra":
        report["predictions"][-1]["id"] = "not-in-manifest"
    elif change == "count":
        report["rows"] = 5
    else:
        report["predictions"][0]["syllable"] = "qiong3"
    save(cohort["cpu"], report)
    with pytest.raises(ValueError, match="ROOTS|ROOT_TARGET_MISMATCH"):
        coverage.reassess(cohort["manifest"], cohort["expanded"], cohort["cpu"], cohort["output"])


@pytest.mark.parametrize("kind", ["native-comparison", "native-ctc", "evidence-decisions"])
def test_target_conditioned_heads_require_fresh_inference(cohort, kind):
    metadata = expand(cohort)
    if kind == "evidence-decisions":
        cohort["report"]["predictions"][0]["comparisonEvidence"]["targetDecisions"] = {}
        save(cohort["cpu"], cohort["report"])
    else:
        metadata["headKind"] = kind
        save(cohort["expanded"] / "model.json", metadata)
    with pytest.raises(ValueError, match="REQUIRES_FRESH_INFERENCE"):
        coverage.reassess(cohort["manifest"], cohort["expanded"], cohort["cpu"], cohort["output"])


def test_missing_tone_output_cannot_claim_complete_four_tone_coverage(cohort):
    metadata = cohort["metadata"]
    metadata["vocabulary"]["tone"].remove("3")
    save(cohort["package"] / "model.json", metadata)
    with pytest.raises(ValueError, match="ALL_FOUR_TONE_CLASSES"):
        expand(cohort)


@pytest.mark.parametrize(
    "probabilities", [[0.5, 0.5], [float("nan")] * 4, [0.1] * 4, [-0.1, 0.1, 0.5, 0.5]]
)
def test_cached_component_evidence_must_match_fixed_output_classes(cohort, probabilities):
    expand(cohort)
    cohort["report"]["predictions"][0]["comparisonEvidence"]["tone"]["probabilities"] = (
        probabilities
    )
    save(cohort["cpu"], cohort["report"])
    with pytest.raises(ValueError, match="COMPONENT_EVIDENCE_INVALID"):
        coverage.reassess(cohort["manifest"], cohort["expanded"], cohort["cpu"], cohort["output"])
