"""Extra standard labels must not silently expand product coverage or phonemes."""

import json

import pytest

from pinyin_matcher.catalog import ROOT, load_catalog, targets_by_id, training_catalog
from pinyin_matcher.data import read_manifest

EXTENSIONS = ROOT / "content/pronunciation-training-extensions-v5.json"


def test_explicit_anchor_labels_preserve_public_coverage_and_phone_heads():
    original = load_catalog()
    expanded = training_catalog(EXTENSIONS)
    assert expanded["pilotIds"] == original["pilotIds"]
    assert expanded["tokens"] == original["tokens"]
    old, new = targets_by_id(original), targets_by_id(expanded)
    assert {key: new[key] for key in old} == old
    assert set(new) - set(old) == {"pm-ni1", "pm-ri1"}
    assert new["pm-ri1"]["phones"] == old["pm-ri4"]["phones"]
    assert new["pm-ni1"]["tone"] == 1
    assert not new["pm-ni1"]["pilot"]


@pytest.mark.parametrize("mutation", ["base", "overwrite", "public", "unknown-prototype"])
def test_invalid_extension_fails_instead_of_mutating_known_targets(tmp_path, mutation):
    data = json.loads(EXTENSIONS.read_text())
    if mutation == "base":
        data["baseCatalogSha256"] = "0" * 64
    elif mutation == "overwrite":
        data["targets"][0]["id"] = "pm-ni3"
    elif mutation == "public":
        data["publicCoverageChanges"] = True
    else:
        data["targets"][0]["prototypeId"] = "absent"
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="TRAINING_CATALOG_EXTENSION"):
        training_catalog(path)


def test_unknown_training_target_requires_an_explicit_bound_catalog(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "cohort": "synthetic",
                "items": [
                    {
                        "id": "test-only-ni1",
                        "targetId": "pm-ni1",
                        "split": "train",
                        "voiceFamilyId": "test-only-family",
                        "referenceRootId": "test-only-reference",
                        "sha256": "a" * 64,
                        "file": "test-only-no-audio.wav",
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="DATASET_REFERENCE_INVALID"):
        read_manifest(manifest, verify_audio=False)
    rows = read_manifest(manifest, verify_audio=False, catalog=training_catalog(EXTENSIONS))
    assert len(rows) == 1
