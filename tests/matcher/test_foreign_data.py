"""Foreign-data bookkeeping fixtures do not claim pronunciation or TTS validity."""

import argparse
import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher import foreign_data
from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.quality import validate_case_semantics


def fixture_config(tmp_path, monkeypatch):
    definitions = []
    for split, word in [("train", "thin"), ("calibration", "thirst"), ("test", "thorn")]:
        definitions.append(
            {
                "id": "en-" + word,
                "lexicalRootId": "en-" + word,
                "language": "English",
                "locale": "en-US",
                "text": word,
                "split": split,
                "contrastCategory": "dental-fricative",
                "againstTargetIds": ["pm-shi1"],
                "phoneticDifference": "The dental fricative differs from the target retroflex.",
                "unknownRelativeToPilot": True,
            }
        )
    config = {
        "version": 1,
        "trainPersonaIds": ["voice-00"],
        "calibrationPersonaIds": ["voice-28"],
        "blindPersonaIds": ["voice-32"],
        "blindGenerationEnabled": False,
        "definitions": definitions,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(foreign_data, "CONFIG", path)
    return path, config


def write_manifest(directory: Path, config_path: Path, config: dict, *, split="train"):
    directory.mkdir()
    definition = next(row for row in config["definitions"] if row["split"] == split)
    index = 0 if split == "train" else 1
    audio = directory / "sample.wav"
    samples = 0.1 * np.sin(np.arange(4000) * 2 * np.pi * (220 + 110 * index) / 16000)
    audio.write_bytes(encode_wav(samples.astype(np.float32)))
    row = {
        "id": f"fixture-{split}",
        "kind": "foreign-contrast",
        "unknownLabel": True,
        "foreignContrastId": definition["id"],
        "lexicalRootId": definition["lexicalRootId"],
        "language": definition["language"],
        "locale": definition["locale"],
        "sourceText": definition["text"],
        "text": definition["text"] + ".",
        "contrastCategory": definition["contrastCategory"],
        "againstTargetIds": definition["againstTargetIds"],
        "phoneticDifference": definition["phoneticDifference"],
        "voiceFamilyId": "voice-00" if split == "train" else "voice-28",
        "referenceRootId": f"reference-{split}",
        "sourceRootId": f"root-{split}",
        "split": split,
        "file": audio.name,
        "sha256": fingerprint(audio),
    }
    data = {
        "version": 1,
        "cohort": "synthetic-explicit-foreign-phonetic-contrasts",
        "configurationSha256": fingerprint(config_path),
        "languageIdentityIsCorrectnessLabel": False,
        "items": [row],
    }
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(data))
    return manifest, data


def test_language_name_cannot_supply_a_missing_phonetic_difference(tmp_path, monkeypatch):
    path, config = fixture_config(tmp_path, monkeypatch)
    manifest, data = write_manifest(tmp_path / "train", path, config)
    data["items"][0]["phoneticDifference"] = " "
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="EXPLICIT_FOREIGN_CONTRAST"):
        foreign_data.read_manifest(manifest)
    validate_case_semantics(
        {"case": "clean-positive", "expectedMatch": True, "language": "English"}
    )


@pytest.mark.parametrize("field", ["language", "sourceText", "againstTargetIds"])
def test_generated_case_must_remain_bound_to_its_explicit_definition(tmp_path, monkeypatch, field):
    path, config = fixture_config(tmp_path, monkeypatch)
    manifest, data = write_manifest(tmp_path / "train", path, config)
    data["items"][0][field] = ["pm-ma1"] if field == "againstTargetIds" else "changed"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="DEFINITION_BINDING"):
        foreign_data.read_manifest(manifest)


def test_family_text_and_lexical_roots_are_disjoint_before_generation(tmp_path, monkeypatch):
    path, config = fixture_config(tmp_path, monkeypatch)
    config["calibrationPersonaIds"] = config["trainPersonaIds"]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="VOICE_FAMILY_SPLIT"):
        foreign_data.configuration()
    config["calibrationPersonaIds"] = ["voice-28"]
    config["definitions"][1]["text"] = "THIN."
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="TEXT_SPLIT"):
        foreign_data.configuration()
    config["definitions"][1]["text"] = "thirst"
    config["definitions"][1]["lexicalRootId"] = config["definitions"][0]["lexicalRootId"]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="LEXICAL_SPLIT"):
        foreign_data.configuration()


def test_parent_audio_cannot_cross_splits_under_a_different_derived_waveform(tmp_path, monkeypatch):
    path, config = fixture_config(tmp_path, monkeypatch)
    train, train_data = write_manifest(tmp_path / "train", path, config)
    calibration, cal_data = write_manifest(tmp_path / "cal", path, config, split="calibration")
    cal_data["items"][0]["parentSha256"] = train_data["items"][0]["sha256"]
    calibration.write_text(json.dumps(cal_data))
    with pytest.raises(ValueError, match="SOURCE_SPLIT_LEAK"):
        foreign_data.audit_manifests([train, calibration])


def test_new_configuration_preserves_explicit_registered_original_configuration(
    tmp_path, monkeypatch
):
    path, config = fixture_config(tmp_path, monkeypatch)
    manifest, _ = write_manifest(tmp_path / "train", path, config)
    archive = path.with_name("pronunciation-foreign-contrast-v1.json")
    archive.write_bytes(path.read_bytes())
    config["version"] = 2
    config["trainPersonaIds"].append("voice-06")
    path.write_text(json.dumps(config))
    assert len(foreign_data.read_manifest(manifest)) == 1
    archive.unlink()
    with pytest.raises(ValueError, match="CONFIGURATION_UNKNOWN"):
        foreign_data.read_manifest(manifest)


def test_derived_voices_environments_and_target_pairs_do_not_become_independent_roots():
    original = {
        "id": "original",
        "sourceRootId": "parent",
        "sha256": "original-hash",
        "lexicalRootId": "word",
        "voiceFamilyId": "voice-a",
        "againstTargetIds": ["a", "b"],
    }
    derivatives = [
        {
            **original,
            "id": f"derived-{i}",
            "sha256": f"child-hash-{i}",
            "parentSha256": "original-hash",
            "voiceFamilyId": f"voice-{i}",
        }
        for i in range(3)
    ]
    counts = foreign_data.lineage_counts([original, *derivatives])
    assert counts["records"] == counts["distinctWaveforms"] == 4
    assert counts["rawAudioUnits"] == counts["sourceUtteranceRoots"] == 1
    assert counts["uniqueLexicalRoots"] == 1
    assert counts["wrongTargetPairs"] == 8
    assert counts["independentRealSpeakers"] == 0


def test_blind_generation_has_no_callable_bypass(tmp_path, monkeypatch):
    fixture_config(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="BLIND_FOREIGN_GENERATION_DISABLED"):
        foreign_data.generate(argparse.Namespace(split="test"))


def test_foreign_engine_config_and_vocabulary_config_have_distinct_bindings(tmp_path, monkeypatch):
    path, config = fixture_config(tmp_path, monkeypatch)
    manifest, data = write_manifest(tmp_path / "train", path, config)
    data["vocabularyConfigurationSha256"] = data["configurationSha256"]
    data["configurationSha256"] = "separate-engine-configuration"
    manifest.write_text(json.dumps(data))
    assert len(foreign_data.read_manifest(manifest)) == 1


@pytest.mark.parametrize(
    "field,value", [("exploratoryDialect", True), ("formalNegativeAllowed", False)]
)
def test_exploratory_dialect_cannot_be_relabelled_into_formal_training(
    tmp_path, monkeypatch, field, value
):
    path, config = fixture_config(tmp_path, monkeypatch)
    manifest, data = write_manifest(tmp_path / "train", path, config)
    data["items"][0][field] = value
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="EXPLICIT_FOREIGN_CONTRAST"):
        foreign_data.read_manifest(manifest)
