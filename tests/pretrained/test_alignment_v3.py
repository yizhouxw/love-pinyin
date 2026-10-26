import json

import numpy as np
import pytest

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_alignment_v3 import acoustic_boundaries, prepare


def row_at(center, outlier=None):
    values = [center, center, center if outlier is None else outlier]
    return {
        "alignment": {
            "heads": {
                key: {"available": True, "startSeconds": value - 0.01, "endSeconds": value + 0.01}
                for key, value in zip(("initial", "final", "tone"), values, strict=True)
            }
        }
    }


def test_boundary_uses_energy_valley_and_robust_anchor_without_expert_labels():
    samples = np.ones(16000, dtype=np.float32) * 0.1
    samples[:1600] = 0
    samples[6400:7040] = 0
    samples[14400:] = 0
    rows = [row_at(0.3, 0.8), row_at(0.7)]
    cuts, evidence = acoustic_boundaries(samples, rows)
    assert evidence["anchorSeconds"] == pytest.approx([0.3, 0.7])
    assert 0.4 < cuts[1] / 16000 < 0.44
    assert cuts[0] / 16000 < 0.11
    assert cuts[-1] / 16000 > 0.88
    assert evidence["interiorCuts"][0]["method"] == "acoustic-energy-valley"
    # Arbitrary correctness votes cannot influence where audio is cut.
    rows[0]["expertLabel"] = "unanimous-error"
    rows[1]["expertLabel"] = "unanimous-correct"
    np.testing.assert_array_equal(acoustic_boundaries(samples, rows)[0], cuts)


def test_no_energy_valley_falls_back_to_midpoint_and_rejects_bad_anchors():
    samples = np.ones(16000, dtype=np.float32) * 0.1
    cuts, evidence = acoustic_boundaries(samples, [row_at(0.3), row_at(0.7)])
    assert cuts[1] == 8000
    assert evidence["interiorCuts"][0]["method"] == "midpoint-no-meaningful-valley"
    with pytest.raises(ValueError, match="NOT_MONOTONIC"):
        acoustic_boundaries(samples, [row_at(0.7), row_at(0.3)])


def fixture_manifest(tmp_path):
    samples = np.ones(16000, dtype=np.float32) * 0.1
    samples[:1600] = samples[6400:7040] = samples[14400:] = 0
    parent = tmp_path / "parent.wav"
    parent.write_bytes(encode_wav(samples))
    clip = tmp_path / "clip.wav"
    clip.write_bytes(encode_wav(samples[3200:6400]))
    rows = []
    for index, center in enumerate((0.3, 0.7)):
        rows.append(
            {
                **row_at(center),
                "id": f"word-{index}",
                "index": index,
                "split": "train",
                "source": "numeric-test-fixture",
                "sourceUtteranceId": "utterance",
                "speakerId": "speaker",
                "voiceFamilyId": "speaker",
                "referenceSourceId": "speaker",
                "parentFile": str(parent),
                "parentSha256": fingerprint(parent),
                "file": str(clip),
                "sha256": fingerprint(clip),
                "onset": "b",
                "rime": "a",
                "tone": 1,
                "bounds": {"startSample": 3200, "endSample": 6400},
                "labelPolicyFlags": ["UNCHANGED_LABEL_FLAG"] if index else [],
                "expertLabel": "unanimous-correct" if index else "unanimous-error",
                "expertRatings": {"onset": ["0", "0", "0"]},
                "numericalQualityFlags": ["OLD_NUMERIC_FLAG"],
            }
        )
    # An absent diagnostic file proves that this code does not open its audio.
    rows.append(
        {
            **rows[0],
            "id": "diagnostic",
            "split": "diagnostic",
            "speakerId": "diagnostic",
            "voiceFamilyId": "diagnostic",
            "referenceSourceId": "diagnostic",
            "parentSha256": "1" * 64,
            "sha256": "2" * 64,
            "file": str(tmp_path / "absent-diagnostic.wav"),
        }
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schemaVersion": 1, "items": rows, "frozenTestIncluded": False}))
    return path, rows


def test_prepare_preserves_roots_labels_and_old_evidence_without_reading_diagnostic(tmp_path):
    manifest, original = fixture_manifest(tmp_path)
    output = tmp_path / "v3"
    prepare(manifest, output)
    result = json.loads((output / "manifest.json").read_text())
    assert [r["id"] for r in result["items"]] == [r["id"] for r in original]
    assert result["counts"]["resegmented"] == 2
    for old, new in zip(original[:2], result["items"][:2], strict=True):
        for field in ("expertLabel", "expertRatings", "labelPolicyFlags", "alignment", "split"):
            assert new[field] == old[field]
        assert new["boundaryV3"]["previousBounds"] == old["bounds"]
        assert new["boundaryV3"]["previousNumericalQualityFlags"] == old["numericalQualityFlags"]
        assert new["numericalQualityFlags"] == []
        assert fingerprint(output / new["file"]) == new["sha256"]
    assert result["items"][2]["file"] == original[2]["file"]
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        prepare(manifest, output)


def test_prepare_forbids_test_before_opening_missing_audio_and_checks_parent_digest(tmp_path):
    manifest, rows = fixture_manifest(tmp_path)
    rows[0]["split"] = "test"
    rows[0]["file"] = str(tmp_path / "missing-final.wav")
    manifest.write_text(json.dumps({"items": rows}))
    with pytest.raises(ValueError, match="FORBIDS_FINAL_TEST"):
        prepare(manifest, tmp_path / "no-final")
    manifest, rows = fixture_manifest(tmp_path)
    for row in rows[:2]:
        row["parentSha256"] = "3" * 64
    manifest.write_text(json.dumps({"items": rows}))
    with pytest.raises(ValueError, match="PARENT_DIGEST"):
        prepare(manifest, tmp_path / "bad-parent")
