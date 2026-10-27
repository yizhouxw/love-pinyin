import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import pretrained_hard_negative_native as native
from pinyin_matcher.catalog import ROOT
from pinyin_matcher.pretrained_freeze import assert_source_splits


def test_native_pinyin_provenance_and_unknown_component_are_not_expert_votes():
    row = {
        "source": native.SOURCE,
        "split": "train",
        "onset": "b",
        "rime": "a",
        "tone": 1,
        "componentExpertLabels": {
            "onset": "source-provided-realized",
            "rime": "ambiguous",
            "tone": "source-provided-realized",
        },
    }
    np.testing.assert_array_equal(native.mixed_supervision([row]), [[1, -1, 1]])
    row["alignmentFlags"] = ["WEAK_CTC_SUPPORT:initial"]
    row["labelPolicyFlags"] = ["SOURCE_BOUNDARY_UNVERIFIED"]
    np.testing.assert_array_equal(native.mixed_supervision([row]), [[-1, -1, -1]])


def test_native_training_speaker_cannot_be_relabelled_calibration():
    config = json.loads((ROOT / "content/pronunciation-aishell3-data.json").read_text())
    speaker = config["files"][0]["speakerId"]
    assert_source_splits([{"source": native.SOURCE, "speakerId": speaker, "split": "train"}])
    with pytest.raises(ValueError, match="SOURCE_SPEAKER_SPLIT"):
        assert_source_splits(
            [{"source": native.SOURCE, "speakerId": speaker, "split": "calibration"}]
        )


def test_native_pairs_identify_source_label_without_claiming_unanimous_experts():
    shared = {
        "sha256": "a" * 64,
        "parentSha256": "b" * 64,
        "voiceFamilyId": "f",
        "referenceSourceId": "r",
        "speakerId": "s",
    }
    a = {
        **shared,
        "id": "a",
        "source": native.SOURCE,
        "onset": "b",
        "rime": "a",
        "tone": 1,
        "componentExpertLabels": {"onset": "source-provided-realized"},
    }
    b = {
        **shared,
        "id": "b",
        "source": "other",
        "onset": "p",
        "rime": "i",
        "tone": 2,
        "componentExpertLabels": {},
    }
    result = list(native.mixed_pairs([a, b]))
    assert len(result) == 1
    assert result[0]["sourceProvidedActual"] == "b"
    assert result[0]["incorrectTarget"] == "p"
    assert "expertActual" not in result[0]


def test_rebind_and_manifest_binding_preserve_fixed_training_budget(tmp_path, monkeypatch):
    from pinyin_matcher.catalog import fingerprint

    source_config = tmp_path / "initial.json"
    source_config.write_text(
        json.dumps({"seed": 3182026, "maximumEpochs": 120, "mixedManifestSha256": "old"})
    )
    monkeypatch.setattr(native, "CONFIG", source_config)
    clips = tmp_path / "clips.json"
    clips.write_text(
        json.dumps(
            {
                "nativeTrainingSource": {
                    "sourceCorpus": native.SOURCE,
                    "finalTestRead": False,
                    "sourceSpeakers": 20,
                }
            }
        )
    )
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "model.json").write_text(
        json.dumps({"model": "sensevoice", "acousticDerivative": None, "testUsed": False})
    )
    rebound = tmp_path / "rebound.json"
    native.rebind_config(clips, baseline, rebound)
    bound = json.loads(rebound.read_text())
    assert bound["seed"] == 3182026 and bound["maximumEpochs"] == 120
    assert bound["nativeClipManifestSha256"] == fingerprint(clips)
    assert "mixedManifestSha256" not in bound
    monkeypatch.setattr(native, "CONFIG", rebound)
    manifest = tmp_path / "mixed.json"
    manifest.write_text(
        json.dumps(
            {
                "datasetId": "ompal-plus-aishell3-training-clips-v1",
                "nativeClipManifestSha256": fingerprint(clips),
                "baselineMetadataSha256": fingerprint(baseline / "model.json"),
                "mixedManifestCodeSha256": fingerprint(Path(native.__file__)),
            }
        )
    )
    final = tmp_path / "final.json"
    native.bind_manifest(manifest, final)
    assert json.loads(final.read_text())["mixedManifestSha256"] == fingerprint(manifest)
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        native.bind_manifest(manifest, final)
