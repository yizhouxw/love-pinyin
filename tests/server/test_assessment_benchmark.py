"""Tests for PoC data validation; generated WAVs here are fixtures, never model evidence."""

import hashlib
import stat
import struct
import wave
from datetime import UTC, datetime

import pytest

from research.assessment.benchmark import (
    ManifestError,
    _check_authorizations,
    _check_manifest,
    _rates,
    _study_coverage,
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
        "annotations": [
            {"reviewerRef": "reviewer_01", "label": "correct"},
            {"reviewerRef": "reviewer_02", "label": "correct"},
        ],
        "adjudicatedLabel": "correct",
        "adjudicatorRef": None,
        "consentRef": "consent_01",
        "sha256": "0" * 64,
    }
    return {**item, **overrides}


def _manifest(item):
    return {
        "schemaVersion": 2,
        "datasetId": "test-data",
        "contentVersion": "curriculum-v1",
        "items": [item],
    }


def _authorization_register(items, dataset_id="test-data"):
    cohorts_by_ref = {item["consentRef"]: item["cohort"] for item in items}
    return {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "records": [
            {
                "consentRef": consent_ref,
                "cohort": cohort,
                "purpose": "retained-poc-audio-evaluation",
                "approved": True,
                "expiresAt": "2099-01-01T00:00:00Z",
                "evidenceSha256": "a" * 64,
            }
            for consent_ref, cohort in cohorts_by_ref.items()
        ],
    }


def test_manifest_requires_challenge_audio_to_use_challenge_target():
    row = _item(challengeClass="noise", adjudicatedLabel="uncertain")
    row["annotations"] = [
        {"reviewerRef": "reviewer_01", "label": "uncertain"},
        {"reviewerRef": "reviewer_02", "label": "uncertain"},
    ]
    with pytest.raises(ManifestError, match="challenge target"):
        _check_manifest(_manifest(row), {"rt-a"})


def test_authorization_register_must_match_scope_cohort_and_expiry():
    row = _item(cohort="target-age-child")
    manifest = _manifest(row)
    authorizations = _authorization_register([row])
    now = datetime(2026, 9, 26, tzinfo=UTC)

    assert _check_authorizations(authorizations, manifest, [row], now=now)["consent_01"]

    invalid = {**authorizations, "schemaVersion": True}
    with pytest.raises(ManifestError, match="schemaVersion 1"):
        _check_authorizations(invalid, manifest, [row], now=now)

    invalid = {**authorizations, "records": [{**authorizations["records"][0], "approved": False}]}
    with pytest.raises(ManifestError, match="not approved"):
        _check_authorizations(invalid, manifest, [row], now=now)

    invalid = {
        **authorizations,
        "records": [{**authorizations["records"][0], "purpose": "commercial-product-training"}],
    }
    with pytest.raises(ManifestError, match="does not permit retained PoC audio evaluation"):
        _check_authorizations(invalid, manifest, [row], now=now)

    invalid = {**authorizations, "datasetId": "other-dataset"}
    with pytest.raises(ManifestError, match="different dataset"):
        _check_authorizations(invalid, manifest, [row], now=now)

    invalid = {
        **authorizations,
        "records": [{**authorizations["records"][0], "cohort": "adult-development"}],
    }
    with pytest.raises(ManifestError, match="cohort does not match"):
        _check_authorizations(invalid, manifest, [row], now=now)

    invalid = {
        **authorizations,
        "records": [{**authorizations["records"][0], "expiresAt": "2020-01-01T00:00:00Z"}],
    }
    with pytest.raises(ManifestError, match="has expired"):
        _check_authorizations(invalid, manifest, [row], now=now)


def test_manifest_rejects_challenge_target_for_clear_speech():
    with pytest.raises(ManifestError, match="cannot use the challenge target"):
        _check_manifest(_manifest(_item(targetId="challenge")), {"rt-a"})


def test_manifest_accepts_well_formed_challenge_metadata():
    row = _item(
        targetId="challenge",
        targetClass="syllable",
        challengeClass="speaker-replay",
        annotations=[
            {"reviewerRef": "reviewer_01", "label": "uncertain"},
            {"reviewerRef": "reviewer_02", "label": "uncertain"},
        ],
        adjudicatedLabel="uncertain",
    )
    assert _check_manifest(_manifest(row), {"rt-a"}) == [row]


def test_too_short_recording_is_an_uncertain_challenge_and_near_neighbor_is_incorrect():
    uncertain_annotations = [
        {"reviewerRef": "reviewer_01", "label": "uncertain"},
        {"reviewerRef": "reviewer_02", "label": "uncertain"},
    ]
    too_short = _item(
        targetId="challenge",
        targetClass="syllable",
        challengeClass="too-short",
        annotations=uncertain_annotations,
        adjudicatedLabel="uncertain",
    )
    assert _check_manifest(_manifest(too_short), {"rt-a"}) == [too_short]

    near_neighbor = _item(
        challengeClass="near-neighbor",
        adjudicatedLabel="incorrect",
        annotations=[
            {"reviewerRef": "reviewer_01", "label": "incorrect"},
            {"reviewerRef": "reviewer_02", "label": "incorrect"},
        ],
    )
    assert _check_manifest(_manifest(near_neighbor), {"rt-a"}) == [near_neighbor]

    near_neighbor["annotations"] = [
        {"reviewerRef": "reviewer_01", "label": "correct"},
        {"reviewerRef": "reviewer_02", "label": "incorrect"},
    ]
    near_neighbor["adjudicatorRef"] = "reviewer_03"
    near_neighbor["adjudicatedLabel"] = "uncertain"
    with pytest.raises(ManifestError, match="near-neighbor sample must be adjudicated incorrect"):
        _check_manifest(_manifest(near_neighbor), {"rt-a"})

    too_short_rates = _rates([too_short], {too_short["sampleId"]: {"status": "uncertain"}})
    assert too_short_rates["challengeRejection"]["too-short"]["rate"] == 1
    near_neighbor["adjudicatedLabel"] = "incorrect"
    neighbor_rates = _rates([near_neighbor], {near_neighbor["sampleId"]: {"status": "pass"}})
    assert neighbor_rates["falsePassOnIncorrect"]["rate"] == 1


def test_required_study_coverage_is_explicit_and_uses_child_test_conditions():
    rows = [
        _item(cohort="target-age-child", adjudicatedLabel="correct"),
        _item(
            sampleId="sample_initial",
            targetClass="initial",
            cohort="target-age-child",
            adjudicatedLabel="incorrect",
        ),
        _item(
            sampleId="sample_tone",
            targetClass="tone",
            cohort="target-age-child",
            adjudicatedLabel="incorrect",
        ),
    ]
    for index, challenge in enumerate(("silence", "too-short", "noise", "speaker-replay")):
        rows.append(
            _item(
                sampleId=f"sample_challenge_{index}",
                targetId="challenge",
                targetClass="syllable",
                cohort="target-age-child",
                challengeClass=challenge,
                adjudicatedLabel="uncertain",
            )
        )
    rows.append(
        _item(
            sampleId="sample_neighbor",
            cohort="target-age-child",
            challengeClass="near-neighbor",
            adjudicatedLabel="incorrect",
        )
    )

    coverage = _study_coverage(rows)

    assert coverage["complete"]
    assert coverage["missingConditions"] == []
    assert coverage["requiredConditions"]["phoneme-error"]["sampleCount"] == 2
    assert coverage["requiredConditions"]["tone-error"]["sampleCount"] == 1
    assert "sample_neighbor" not in str(coverage)


def test_disagreement_requires_a_distinct_third_adjudicator():
    row = _item(
        annotations=[
            {"reviewerRef": "reviewer_01", "label": "correct"},
            {"reviewerRef": "reviewer_02", "label": "incorrect"},
        ],
        adjudicatedLabel="uncertain",
    )
    with pytest.raises(ManifestError, match="distinct opaque third adjudicator"):
        _check_manifest(_manifest(row), {"rt-a"})

    row["adjudicatorRef"] = "reviewer_03"
    assert _check_manifest(_manifest(row), {"rt-a"}) == [row]


def test_consensus_cannot_be_overruled_and_reviewers_must_be_distinct():
    row = _item(adjudicatedLabel="incorrect")
    with pytest.raises(ManifestError, match="consensus labels must be retained"):
        _check_manifest(_manifest(row), {"rt-a"})

    row = _item(
        annotations=[
            {"reviewerRef": "reviewer_01", "label": "correct"},
            {"reviewerRef": "reviewer_01", "label": "correct"},
        ]
    )
    with pytest.raises(ManifestError, match="two distinct reviewers"):
        _check_manifest(_manifest(row), {"rt-a"})


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
                annotations=[
                    {"reviewerRef": "reviewer_01", "label": label},
                    {"reviewerRef": "reviewer_02", "label": label},
                ],
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
            annotations=[
                {"reviewerRef": "reviewer_01", "label": label},
                {"reviewerRef": "reviewer_02", "label": label},
            ],
            sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        )
        items.append(row)
        prediction_rows.append({"sampleId": sample_id, "status": "pass"})
    content_version = load_curriculum()["contentVersion"]
    manifest = {
        "schemaVersion": 2,
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

    report = evaluate(
        manifest, predictions, audio_dir, _authorization_register(items, "fixture-set")
    )

    assert report["reportVersion"] == "poc-evaluator-0.5.0"
    assert report["testMetrics"]["clearSampleAccuracy"]["speakerClusterCi95"]["ci95"] == [
        0.0,
        1.0,
    ]
    assert report["dataset"]["testTargetAgeSpeakers"] == 2
    assert report["byTargetId"][target_id]["clearSampleAccuracy"]["denominator"] == 2
    assert report["targetAgeChildStudyCoverage"]["complete"] is False
    assert "phoneme-error" in report["targetAgeChildStudyCoverage"]["missingConditions"]
    assert report["classifierMetricGates"]["requiredTargetAgeTestConditionsPresent"] is False
    serialized = str(report)
    assert "fixture_0000" not in serialized
    assert "speaker_0000" not in serialized
    assert "consent_01" not in serialized


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
                consentRef=f"consent_{index:04}",
                targetId=target["id"],
                targetClass=target["targetType"],
                split="test",
                adjudicatedLabel=label,
                annotations=[
                    {"reviewerRef": "reviewer_01", "label": label},
                    {"reviewerRef": "reviewer_02", "label": label},
                ],
                sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(),
            )
        )
        prediction_rows.append({"sampleId": sample_id, "status": "pass"})
    content_version = load_curriculum()["contentVersion"]
    report = evaluate(
        {
            "schemaVersion": 2,
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
        _authorization_register(items, "child-mask-fixture"),
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
