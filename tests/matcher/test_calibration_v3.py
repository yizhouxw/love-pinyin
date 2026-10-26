"""Collector fixtures verify control flow and counts, never pronunciation validity."""

import json
from pathlib import Path

import numpy as np

from pinyin_matcher import calibration_v3
from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import fingerprint, targets_by_id
from pinyin_matcher.decision_v3 import decide

THRESHOLDS = {
    "minimumContentMargin": 0.5,
    "maximumFreeCtcAdvantage": 0.05,
    "minimumToneProbability": 0.65,
}


class CollectorFixture:
    def __init__(self, *, error=None):
        self.targets = targets_by_id()
        self.metadata = {"coveredTargetIds": ["pm-ma1", "pm-ba1", "pm-zi1"]}
        self.calls = 0
        self.error = error

    def _branch_evidence(self, acoustic, samples, target_id):
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "targetPhones": self.targets[target_id]["phones"],
            "targetTone": self.targets[target_id]["tone"],
            "predictedPhones": self.targets["pm-ma1"]["phones"],
            "predictedTone": 1,
            "contentMargin": 2.0,
            "freeCtcAdvantage": 0.0,
            "toneProbability": 0.9,
            "pitchReliable": True,
        }


def audio_row(tmp_path, *, target="pm-ma1", suffix="1", silence=False):
    path = tmp_path / (suffix + ".wav")
    sample = (
        np.zeros(6400)
        if silence
        else 0.1 * np.sin(np.arange(6400) * 2 * np.pi * (220 + int(suffix)) / 16000)
    )
    path.write_bytes(encode_wav(sample.astype(np.float32)))
    return {
        "id": "fixture-" + suffix,
        "targetId": target,
        "generator": "test-only",
        "sourceRootId": "parent-" + suffix,
        "voiceFamilyId": "fixture-family",
        "split": "calibration",
        "path": str(path),
        "file": path.name,
        "sha256": fingerprint(path),
        "manifest": str(tmp_path / "manifest.json"),
    }


def test_raw_wav_runs_once_and_countertargets_do_not_increase_root_count(tmp_path, monkeypatch):
    row = audio_row(tmp_path)
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [row])
    matcher = CollectorFixture()
    records, collection = calibration_v3.collect_records(
        matcher, [(Path("same.json"), "speech"), (Path("same.json"), "speech")]
    )
    assert matcher.calls == collection["uniqueRawWaveformsInferred"] == 1
    assert len([r for r in records if r["expectedMatch"]]) == 1
    assert len([r for r in records if r["case"] == "tone"]) == 3
    assert len({r["unitId"] for r in records}) == 1
    assert collection["coverage"]["rawAudioUnits"] == 1
    assert collection["publicPositiveTargetIds"] == ["pm-ma1"]


def test_nonpublic_actual_reading_only_supplies_explicit_negative_queries(tmp_path, monkeypatch):
    row = audio_row(tmp_path, target="pm-ma2")
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [row])
    records, collection = calibration_v3.collect_records(
        CollectorFixture(), [(Path("cal.json"), "speech")]
    )
    assert records
    assert not any(r["expectedMatch"] for r in records)
    assert collection["publicPositiveTargetIds"] == []
    assert any(r["targetId"] == "pm-ma1" and r["case"] == "tone" for r in records)


def test_audio_rejection_is_uncertain_and_remains_a_positive_trial(tmp_path, monkeypatch):
    row = audio_row(tmp_path, silence=True)
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [row])
    matcher = CollectorFixture()
    records, _ = calibration_v3.collect_records(matcher, [(Path("cal.json"), "speech")])
    positive = next(r for r in records if r["expectedMatch"])
    assert matcher.calls == 0
    assert positive["available"] is True
    assert "audioRejectionReason" in positive
    assert decide(positive, THRESHOLDS)["status"] == "uncertain"


def test_model_errors_are_unavailable_without_dropping_the_positive(tmp_path, monkeypatch):
    row = audio_row(tmp_path)
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [row])
    records, _ = calibration_v3.collect_records(
        CollectorFixture(error=RuntimeError("fixture failure")), [(Path("cal.json"), "speech")]
    )
    positive = next(r for r in records if r["expectedMatch"])
    assert decide(positive, THRESHOLDS)["status"] == "unavailable"


def test_foreign_word_uses_only_named_phonetic_pairs(tmp_path, monkeypatch):
    row = audio_row(tmp_path)
    row.update(
        {
            "againstTargetIds": ["pm-ba1"],
            "language": "English",
            "contrastCategory": "labiodental-fricative",
            "phoneticDifference": "The labiodental fricative differs from the bilabial target.",
            "lexicalRootId": "fixture-word",
        }
    )
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [row])
    records, _ = calibration_v3.collect_records(
        CollectorFixture(), [(Path("foreign.json"), "foreign")]
    )
    assert len(records) == 1
    assert records[0]["targetId"] == "pm-ba1"
    assert records[0]["case"] == "cross-language-acoustic-mismatch"
    assert records[0]["mismatchBasis"] == "phoneme"
    assert not records[0]["expectedMatch"]


def test_non_speech_reuses_one_inference_for_every_public_target(tmp_path, monkeypatch):
    row = audio_row(tmp_path, silence=True)
    row.update({"expectedMatch": False, "clearAudio": False, "case": "non-speech"})
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [row])
    matcher = CollectorFixture()
    records, _ = calibration_v3.collect_records(matcher, [(Path("noise.json"), "non-speech")])
    assert len(records) == len(matcher.metadata["coveredTargetIds"])
    assert {r["targetId"] for r in records} == set(matcher.metadata["coveredTargetIds"])
    assert not any(r["expectedMatch"] or r["clearAudio"] for r in records)
    assert {decide(r, THRESHOLDS)["status"] for r in records} == {"uncertain"}


def test_identical_mechanical_silence_files_do_not_increase_trial_units(tmp_path, monkeypatch):
    first = audio_row(tmp_path, silence=True)
    second = audio_row(tmp_path, suffix="2", silence=True)
    for row in [first, second]:
        row.update({"expectedMatch": False, "clearAudio": False, "case": "non-speech"})
    monkeypatch.setattr(calibration_v3, "_rows", lambda manifest, kind: [first, second])
    records, collection = calibration_v3.collect_records(
        CollectorFixture(), [(Path("noise.json"), "non-speech")]
    )
    assert collection["uniqueRawWaveformsInferred"] == 1
    assert len({r["unitId"] for r in records}) == 1
    assert collection["coverage"]["rawAudioUnits"] == 1


def test_training_provenance_ignores_cal_rows_but_detects_a_changed_derived_parent(tmp_path):
    path = tmp_path / "mixed.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "train",
                        "split": "train",
                        "sha256": "train-wave",
                        "sourceRootId": "train-parent",
                    },
                    {
                        "id": "cal",
                        "split": "calibration",
                        "sha256": "cal-wave",
                        "sourceRootId": "cal-parent",
                    },
                ]
            }
        )
    )
    digest = fingerprint(path)
    metadata = {
        "dataProvenance": {
            "syntheticManifestPath": str(path),
            "syntheticManifestSha256": digest,
            "standardManifestPath": str(path),
            "standardManifestSha256": digest,
            "derivedManifestSha256": {str(path): digest},
        }
    }
    result = calibration_v3.training_lineage_check(
        metadata, [{"unitId": "cal", "sha256": "cal-wave", "sourceRootId": "cal-parent"}]
    )
    assert result["complete"]
    assert not result["overlapRawUnitIds"]
    result = calibration_v3.training_lineage_check(
        metadata,
        [{"unitId": "disguised", "sha256": "new-derived-wave", "parentSha256": "train-wave"}],
    )
    assert result["overlapRawUnitIds"] == ["disguised"]


def test_absent_or_changed_training_metadata_never_claims_the_lineage_check_complete(tmp_path):
    incomplete = calibration_v3.training_lineage_check({}, [])
    assert not incomplete["complete"]
    assert incomplete["missing"]
    path = tmp_path / "input.json"
    path.write_text("{}")
    changed = calibration_v3.training_lineage_check(
        {"dataProvenance": {"derivedManifestSha256": {str(path): "wrong-digest"}}}, []
    )
    assert not changed["complete"]
    assert changed["errors"]
