"""Fresh configured families and explicit source counts replace hard-coded IDs."""

import copy
import json

import pytest
from test_controlled_evaluation_lock import args, lock
from test_controlled_evaluation_lock import prepared as prepared

from pinyin_matcher import controlled_generation as controlled


def use_fresh_families(prepared, *, reduce_sources=False):
    config = copy.deepcopy(prepared.config)
    new_ids = [f"voice-{i}" for i in range(36, 40)]
    old_personas = {r["id"]: r for r in config["additionalPersonas"]}
    config["historicalEvaluationPersonaIds"] = config["blindTestPersonaIds"]
    config["blindTestPersonaIds"] = new_ids
    for old, new in zip(range(32, 36), new_ids, strict=True):
        config["additionalPersonas"].append({**old_personas[f"voice-{old}"], "id": new})
    if reduce_sources:
        retained = {"pm-ni3", "pm-he1", "pm-xi1", "pm-chi1", "pm-ri4"}
        for row in config["definitions"]:
            source = row.get("standardSource") or {}
            if source.get("allocation") == "blind" and row["id"] not in retained:
                source["allocation"] = "train"
    prepared.configuration.write_text(json.dumps(config))
    return config


@pytest.mark.parametrize("reduce_sources", [False, True])
def test_configured_four_fresh_families_preserve_exact_source_cross_product(
    prepared, reduce_sources
):
    config = use_fresh_families(prepared, reduce_sources=reduce_sources)
    snapshot = lock(prepared)
    plan = snapshot["generationPlan"]
    count = 5 if reduce_sources else 13
    assert plan["expectedStandardRoots"] == count
    assert plan["expectedWaveforms"] == count * 4
    assert {r["id"] for r in plan["personas"]} == set(config["blindTestPersonaIds"])
    assert len({r["id"] for r in plan["units"]}) == count * 4
    assert not prepared.output.exists()
    for persona in plan["personas"]:
        assert persona["referenceSeed"] == config["seed"] + int(persona["id"][-2:])


@pytest.mark.parametrize(
    "invalid", ["duplicate", "train", "calibration", "history", "old-test", "split", "missing"]
)
def test_reused_nonunique_or_unallocated_test_family_is_refused(prepared, invalid):
    config = use_fresh_families(prepared)
    first = config["blindTestPersonaIds"][0]
    if invalid == "duplicate":
        config["blindTestPersonaIds"][1] = first
    elif invalid == "train":
        config["trainPersonaIds"].append(first)
    elif invalid == "calibration":
        config["calibrationPersonaIds"].append(first)
    elif invalid == "history":
        config["historicalEvaluationPersonaIds"].append(first)
    elif invalid == "old-test":
        config["excludedPreviousTestPersonaIds"].append(first)
    elif invalid == "missing":
        config["additionalPersonas"] = [r for r in config["additionalPersonas"] if r["id"] != first]
    else:
        next(r for r in config["additionalPersonas"] if r["id"] == first)["split"] = "train"
    prepared.configuration.write_text(json.dumps(config))
    with pytest.raises(
        ValueError, match="FROZEN_EVALUATION_SOURCE_OR_FAMILY_SET_INVALID|MUST_HAVE_TEST_SPLIT"
    ):
        lock(prepared)
    assert not prepared.lock_path.exists()


def test_fresh_family_reference_already_generated_before_lock_is_refused(prepared):
    use_fresh_families(prepared, reduce_sources=True)
    reference = prepared.project / "private/matcher-data/references/voice-36.wav"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"fixture already generated, never scored")
    with pytest.raises(ValueError, match="EVALUATION_REFERENCE_ALREADY_EXISTS_BEFORE_LOCK"):
        lock(prepared)


def test_original_training_family_cannot_be_redeclared_as_fresh_test(prepared):
    config = use_fresh_families(prepared)
    config["blindTestPersonaIds"][0] = "voice-01"
    persona = next(r for r in config["additionalPersonas"] if r["id"] == "voice-36")
    persona["id"] = "voice-01"
    prepared.configuration.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="FROZEN_EVALUATION_SOURCE_OR_FAMILY_SET_INVALID"):
        lock(prepared)


def test_old_families_cannot_be_substituted_after_new_plan_is_frozen(prepared):
    use_fresh_families(prepared, reduce_sources=True)
    snapshot = lock(prepared)
    with pytest.raises(ValueError, match="TRAIN_OR_CALIBRATION_FAMILIES_ONLY"):
        controlled.generate(
            args(prepared, snapshot, persona_ids=[f"voice-{i}" for i in range(32, 36)])
        )


def v5_config():
    return json.loads(
        (controlled.ROOT / "content/pronunciation-contrast-training-v5.json").read_text()
    )


def test_v5_releases_only_explicit_standard_roots_and_reserves_five_public_parents():
    config = v5_config()
    definitions = controlled.acoustic_v5_definitions(config)
    released = {r["id"] for r in definitions}
    assert released == {
        "pm-ni1",
        "pm-ni2",
        "pm-he2",
        "pm-he4",
        "pm-xi2",
        "pm-xi3",
        "pm-xi4",
        "pm-chi3",
        "pm-ri1",
        "pm-lv2",
    }
    reserved = {
        r["id"]
        for r in config["definitions"]
        if (r.get("standardSource") or {}).get("allocation") == "blind"
    }
    assert reserved == {"pm-ni3", "pm-he1", "pm-xi1", "pm-chi1", "pm-ri4"}
    assert not released & reserved
    assert all(r["phoneticCoverageExtension"] for r in definitions)
    assert all(r["standardSource"]["pitchTrainingEligible"] is False for r in definitions)
    assert config["blindTestPersonaIds"] == [f"voice-{i}" for i in range(36, 40)]
    assert config["historicalEvaluationPersonaIds"] == [f"voice-{i}" for i in range(32, 36)]


@pytest.mark.parametrize("invalid", ["wrong-source", "duplicate", "pitch-allowed", "reserved"])
def test_v5_training_cannot_admit_undeclared_or_reserved_sources(invalid):
    config = v5_config()
    extension = config["acousticOnlyExtensionV5"]
    if invalid == "wrong-source":
        extension["selectedSources"][0]["sourceSha256"] = "wrong-parent"
    elif invalid == "duplicate":
        extension["selectedSources"].append(copy.deepcopy(extension["selectedSources"][0]))
    elif invalid == "pitch-allowed":
        extension["selectedSources"][0]["pitchTrainingEligible"] = True
    else:
        key = extension["selectedSources"][0]["targetId"]
        next(r for r in config["definitions"] if r["id"] == key)["standardSource"]["allocation"] = (
            "blind"
        )
    with pytest.raises(ValueError, match="ACOUSTIC_V5_"):
        controlled.acoustic_v5_definitions(config)
