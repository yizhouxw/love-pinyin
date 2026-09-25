"""Tests for PoC data validation; generated WAVs here are fixtures, never model evidence."""

import pytest

from research.assessment.benchmark import ManifestError, _check_manifest


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
