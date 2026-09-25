"""Tests for PoC data validation; generated WAVs here are fixtures, never model evidence."""

import hashlib
import stat
import struct
import wave

import pytest

from research.assessment.benchmark import (
    ManifestError,
    _check_manifest,
    _rates,
    _write_private_report,
    evaluate,
)
from server.content import load_curriculum, map_by_id


def _item(**overrides):
    item = {
        "sampleId": "sample_0001",
        "speakerGroupId": "speaker_0001",
        "cohort": "adult-development",
        "targetId": "rt-a",
        "targetClass": "final",
        "deviceClass": "mac-built-in",
        "environmentClass": "quiet",
        "challengeClass": "speech",
        "split": "development",
        "annotatorLabels": ["correct", "correct"],
        "adjudicatedLabel": "correct",
        "consentRef": "consent_01",
        "sha256": "0" * 64,
    }
    return {**item, **overrides}


def _manifest(item):
    return {
        "schemaVersion": 1,
        "datasetId": "test-data",
        "contentVersion": "curriculum-v1",
        "items": [item],
    }


def test_manifest_requires_challenge_audio_to_use_challenge_target():
    row = _item(challengeClass="noise", adjudicatedLabel="uncertain")
    row["annotatorLabels"] = ["uncertain", "uncertain"]
    with pytest.raises(ManifestError, match="challenge target"):
        _check_manifest(_manifest(row), {"rt-a"})


def test_manifest_rejects_challenge_target_for_clear_speech():
    with pytest.raises(ManifestError, match="cannot use the challenge target"):
        _check_manifest(_manifest(_item(targetId="challenge")), {"rt-a"})


def test_manifest_accepts_well_formed_challenge_metadata():
    row = _item(
        targetId="challenge",
        targetClass="syllable",
        challengeClass="speaker-replay",
        annotatorLabels=["uncertain", "uncertain"],
        adjudicatedLabel="uncertain",
    )
    assert _check_manifest(_manifest(row), {"rt-a"}) == [row]


def test_cluster_interval_reflects_repeated_samples_from_the_same_speakers():
    items = []
    predictions = {}
    for speaker, label in (("speaker_A", "correct"), ("speaker_B", "incorrect")):
        for index in range(10):
            sample_id = f"sample_{speaker[-1]}_{index:04}"
            row = _item(
                sampleId=sample_id,
                speakerGroupId=speaker,
                adjudicatedLabel=label,
                annotatorLabels=[label, label],
            )
            items.append(row)
            predictions[sample_id] = {"status": "pass"}

    metrics = _rates(items, predictions)["clearSampleAccuracy"]
    assert metrics["rate"] == 0.5
    assert metrics["speakerClusterCi95"]["speakerClusters"] == 2
    assert metrics["speakerClusterCi95"]["ci95"][0] == 0.0
    assert metrics["speakerClusterCi95"]["ci95"][1] == 1.0
    assert metrics["sampleWilsonCi95"][1] - metrics["sampleWilsonCi95"][0] < 1.0


def test_cluster_interval_is_unavailable_with_one_speaker():
    row = _item()
    metrics = _rates([row], {row["sampleId"]: {"status": "pass"}})["clearSampleAccuracy"]
    interval = metrics["speakerClusterCi95"]
    assert interval["ci95"] is None
    assert interval["speakerClusters"] == 1
    assert "at least two" in interval["reason"]


def test_evaluator_emits_cluster_intervals_without_sample_identifiers(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    target = next(iter(map_by_id("readingTargets").values()))
    target_id = target["id"]
    items = []
    prediction_rows = []
    for index, label in enumerate(("correct", "incorrect")):
        sample_id = f"fixture_{index:04}"
        audio_path = audio_dir / f"{sample_id}.wav"
        with wave.open(str(audio_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(struct.pack("<160h", *([100] * 160)))
        row = _item(
            sampleId=sample_id,
            speakerGroupId=f"speaker_{index:04}",
            cohort="target-age-child",
            targetId=target_id,
            targetClass=target["targetType"],
            split="test",
            adjudicatedLabel=label,
            annotatorLabels=[label, label],
            sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        )
        items.append(row)
        prediction_rows.append({"sampleId": sample_id, "status": "pass"})
    content_version = load_curriculum()["contentVersion"]
    manifest = {
        "schemaVersion": 1,
        "datasetId": "fixture-set",
        "contentVersion": content_version,
        "items": items,
    }
    predictions = {
        "schemaVersion": 1,
        "datasetId": "fixture-set",
        "contentVersion": content_version,
        "split": "test",
        "engineId": "fixture-engine",
        "engineVersion": "test-only",
        "items": prediction_rows,
    }

    report = evaluate(manifest, predictions, audio_dir)

    assert report["reportVersion"] == "poc-evaluator-0.2.0"
    assert report["testMetrics"]["clearSampleAccuracy"]["speakerClusterCi95"]["ci95"] == [
        0.0,
        1.0,
    ]
    assert report["dataset"]["testTargetAgeSpeakers"] == 2
    serialized = str(report)
    assert "fixture_0000" not in serialized
    assert "speaker_0000" not in serialized


def test_adult_test_performance_cannot_mask_child_test_errors(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    target = next(iter(map_by_id("readingTargets").values()))
    items = []
    prediction_rows = []
    cohorts = [("target-age-child", "incorrect")] * 2 + [("adult-development", "correct")] * 30
    for index, (cohort, label) in enumerate(cohorts):
        sample_id = f"sample_{index:04}"
        audio_path = audio_dir / f"{sample_id}.wav"
        with wave.open(str(audio_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(struct.pack("<160h", *([100] * 160)))
        items.append(
            _item(
                sampleId=sample_id,
                speakerGroupId=f"speaker_{index:04}",
                cohort=cohort,
                targetId=target["id"],
                targetClass=target["targetType"],
                split="test",
                adjudicatedLabel=label,
                annotatorLabels=[label, label],
                sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(),
            )
        )
        prediction_rows.append({"sampleId": sample_id, "status": "pass"})
    content_version = load_curriculum()["contentVersion"]
    report = evaluate(
        {
            "schemaVersion": 1,
            "datasetId": "child-mask-fixture",
            "contentVersion": content_version,
            "items": items,
        },
        {
            "schemaVersion": 1,
            "datasetId": "child-mask-fixture",
            "contentVersion": content_version,
            "split": "test",
            "engineId": "fixture-engine",
            "engineVersion": "test-only",
            "items": prediction_rows,
        },
        audio_dir,
    )

    assert report["testMetrics"]["clearSampleAccuracy"]["rate"] >= 0.90
    assert report["targetAgeChildTestMetrics"]["clearSampleAccuracy"]["rate"] == 0.0
    assert report["classifierMetricGates"]["clearSampleAccuracyAtLeast90Percent"] is False
    assert report["classifierMetricGates"]["atLeast30HeldOutTargetAgeSpeakers"] is False


def test_aggregate_report_is_atomically_written_with_private_permissions(tmp_path):
    output = tmp_path / "private" / "report.json"
    output.parent.mkdir(mode=0o700)
    output.write_text('{"old": true}', encoding="utf-8")

    _write_private_report(output, {"aggregate": {"rate": 0.5}})

    assert output.read_text(encoding="utf-8") == '{\n  "aggregate": {\n    "rate": 0.5\n  }\n}\n'
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(output.parent.glob(".assessment-report-*"))
