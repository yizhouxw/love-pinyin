"""Frozen-test integrity contracts; numeric metadata fixtures are not quality evidence."""

import json

import pytest

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_metrics import freeze


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def chain(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_freeze as guard

    monkeypatch.setattr(guard, "ROOT", tmp_path)
    for name in (
        "audio.py",
        "catalog.py",
        "pretrained_ompal_clips.py",
        "pretrained_align.py",
        "pitch_swift.py",
        "pitch_v2.py",
    ):
        p = tmp_path / "pinyin_matcher" / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("# frozen fixture executable\n")
    required = [
        "tools/pinyin-pretrained/uv.lock",
        "tools/pinyin-pretrained/pyproject.toml",
        "content/pronunciation-targets.json",
        "content/pronunciation-pretrained-models.json",
        "content/pronunciation-pretrained-experiment.json",
        "content/pronunciation-ompal-policy.json",
        "content/pronunciation-ompal-detail-id-map.json",
    ]
    files = [save(tmp_path / name, {"fixture": name}) for name in required]
    entries, utterances = [], []
    for index, split in enumerate(("train", "test")):
        speaker = "speaker-" + split
        source_path = f"wav/{speaker}/00{index}.wav"
        word = {
            "id": f"ompal-00{index}-w000",
            "onset": "m",
            "rime": "a",
            "tone": 1,
            "expertLabel": "unanimous-correct",
            "labelPolicyFlags": [],
        }
        entries.append(
            {
                "path": source_path,
                "speakerId": speaker,
                "split": split,
                "gitBlobSha1": str(index) * 40,
            }
        )
        utterances.append(
            {
                "id": f"ompal-00{index}",
                "sourcePath": source_path,
                "sourceGitBlobSha1": str(index) * 40,
                "sha256": str(index) * 64,
                "speakerId": speaker,
                "voiceFamilyId": speaker,
                "referenceSourceId": speaker,
                "split": split,
                "source": "ompal-v1",
                "words": [word],
            }
        )
    config = save(tmp_path / "content/source.json", {"datasetId": "ompal-v1", "files": entries})
    training = save(tmp_path / "training.json", {"items": []})
    files += [config, training]
    package = tmp_path / "package"
    graph = package / "encoder/graph.onnx"
    graph.parent.mkdir(parents=True)
    graph.write_bytes(b"frozen graph fixture")
    metadata = save(
        package / "model.json",
        {"packageFiles": {"encoder/graph.onnx": {"sha256": fingerprint(graph)}}},
    )
    reserved = [{**utterances[1], "gitBlobSha1": entries[1]["gitBlobSha1"]}]
    plan = freeze(
        [
            {"root_id": str(i), "speakerId": row["speakerId"], "split": row["split"]}
            for i, row in enumerate(utterances)
        ],
        files=files,
        code_files=guard.pipeline_files(),
        model_files=[metadata, graph],
        config={
            "packages": [str(package)],
            "sourceConfigPath": str(config),
            "trainingManifestPath": str(training),
            "reservedAnnotationInventory": reserved,
            "thresholdsFrozen": True,
            "testAudioNotOpened": True,
        },
    )
    plan_path = save(tmp_path / "plan.json", plan)
    source_data = {
        "frozenPlanSha256": fingerprint(plan_path),
        "frozenTestIncluded": True,
        "configSha256": fingerprint(config),
        "pinyinPolicySha256": fingerprint(tmp_path / "content/pronunciation-ompal-policy.json"),
        "detailIdMappingSha256": fingerprint(
            tmp_path / "content/pronunciation-ompal-detail-id-map.json"
        ),
        "utterances": utterances,
    }
    source_manifest = save(tmp_path / "source-manifest.json", source_data)
    items = [
        {
            **row,
            **row["words"][0],
            "sourceUtteranceId": row["id"],
            "parentSha256": row["sha256"],
            "file": "NEVER_OPEN_MISSING_FINAL_AUDIO.wav",
        }
        for row in utterances
    ]
    clip_data = {
        "frozenPlanSha256": fingerprint(plan_path),
        "frozenTestIncluded": True,
        "utterancesManifestPath": str(source_manifest),
        "utterancesManifestSha256": fingerprint(source_manifest),
        "utterancesConfigSha256": fingerprint(config),
        "pipelineSha256": fingerprint(tmp_path / "pinyin_matcher/pretrained_ompal_clips.py"),
        "alignerSha256": fingerprint(tmp_path / "pinyin_matcher/pretrained_align.py"),
        "items": items,
    }
    clips = save(tmp_path / "clips.json", clip_data)
    return guard, plan_path, config, package, graph, source_manifest, clips


def test_complete_frozen_chain_validates_without_reading_missing_final_audio(chain):
    guard, plan, _, package, _, _, clips = chain
    assert guard.verify_test_manifest(clips, plan, package=package)["lineageDisjoint"]


def test_undeclared_encoder_resource_cannot_escape_frozen_hash_inventory(chain):
    guard, plan, _, package, _, _, clips = chain
    # Adapters consume tuned.json/config files as well as the declared graph.
    # A package cannot hide a new transitive resource outside packageFiles.
    save(package / "encoder/tuned.json", {"files": {"unbound-weight": "fixture"}})
    with pytest.raises(ValueError, match="FROZEN_MODEL_PACKAGE_FILE_INVENTORY_CHANGED"):
        guard.verify_test_manifest(clips, plan)


@pytest.mark.parametrize(
    "mutation", ["threshold", "code", "model", "missing-model-file", "dependency"]
)
def test_plan_detects_changed_policy_code_model_or_lock_before_audio(chain, mutation):
    guard, plan_path, _, _, graph, _, clips = chain
    if mutation == "threshold":
        plan = json.loads(plan_path.read_text())
        plan["limits"]["negativeFalseAcceptance"] = 0.5
        save(plan_path, plan)
    elif mutation == "code":
        (guard.ROOT / "pinyin_matcher/audio.py").write_text("# changed decoder")
    elif mutation == "model":
        graph.write_bytes(b"substituted acoustic graph")
    elif mutation == "dependency":
        (guard.ROOT / "tools/pinyin-pretrained/uv.lock").write_text("changed dependency")
    else:
        plan = json.loads(plan_path.read_text())
        plan["modelFiles"] = [
            record for record in plan["modelFiles"] if record["path"] != str(graph)
        ]
        plan["planSha256"] = guard.digest({k: v for k, v in plan.items() if k != "planSha256"})
        save(plan_path, plan)
    with pytest.raises(ValueError, match="FROZEN"):
        guard.verify_test_manifest(clips, plan_path)


@pytest.mark.parametrize(
    "mutation", ["different-plan", "omitted-root", "swapped-speaker", "changed-label"]
)
def test_derived_manifest_cannot_replace_or_drop_reserved_roots(chain, mutation):
    guard, plan, _, _, _, source, clips = chain
    data = json.loads(clips.read_text())
    if mutation == "different-plan":
        data["frozenPlanSha256"] = "0" * 64
    elif mutation == "omitted-root":
        data["items"] = data["items"][:-1]
    elif mutation == "swapped-speaker":
        data["items"][-1]["speakerId"] = "speaker-train"
    else:
        parent = json.loads(source.read_text())
        parent["utterances"][-1]["words"][0]["tone"] = 4
        save(source, parent)
        data["utterancesManifestSha256"] = fingerprint(source)
        data["items"][-1]["tone"] = 4
    save(clips, data)
    with pytest.raises(ValueError, match="FROZEN|MANIFEST"):
        guard.verify_test_manifest(clips, plan)


def test_four_test_entrypoints_reject_fake_plan_before_download_or_audio(tmp_path, monkeypatch):
    import pinyin_matcher.pretrained_data as mandi
    import pinyin_matcher.pretrained_evaluate as evaluation
    import pinyin_matcher.pretrained_experiment as experiment
    import pinyin_matcher.pretrained_ompal as ompal
    import pinyin_matcher.pretrained_ompal_clips as clipping

    config = save(tmp_path / "config.json", {})
    plan = save(tmp_path / "fake-plan.json", {"planSha256": "a" * 64})

    def forbidden(*args, **kwargs):
        pytest.fail("A reserved-audio operation ran before validating its plan")

    monkeypatch.setattr(ompal, "download", forbidden)
    monkeypatch.setattr(mandi, "download_locked", forbidden)
    monkeypatch.setattr(experiment, "read_rows", forbidden)
    monkeypatch.setattr(evaluation, "read_rows", forbidden)
    monkeypatch.setattr(clipping, "_read_audio", forbidden)
    attempts = [
        lambda: ompal.prepare(config, tmp_path, include_frozen_test=True, frozen_plan=plan),
        lambda: mandi.prepare(config, tmp_path, include_frozen_test=True, frozen_plan=plan),
        lambda: experiment.cache_features(
            "hanziflow", tmp_path, config, tmp_path, device="cpu", test=True, frozen_plan=plan
        ),
        lambda: evaluation.evaluate(
            config, tmp_path, tmp_path / "out.json", split="test", frozen_plan=plan
        ),
        lambda: clipping.prepare_clips(
            config, tmp_path, include_frozen_test=True, frozen_plan=plan
        ),
    ]
    for attempt in attempts:
        with pytest.raises(ValueError, match="PLAN_SHA"):
            attempt()


def test_reserved_expert_inventory_is_generated_without_audio_download(monkeypatch):
    import pinyin_matcher.pretrained_ompal as ompal

    def forbidden(*args, **kwargs):
        pytest.fail("Public annotation derivation must never download audio")

    monkeypatch.setattr(ompal, "download", forbidden)
    aggregate = {
        "42": {
            "text": "他",
            "words": [{"text": ["他"], "phoneme_consonant": 1, "phoneme_vowel": 1, "tone": 1}],
        }
    }
    detail = {
        "old": {
            "text": "他",
            "words": [
                {
                    "text": ["他"],
                    "phoneme_consonant": [1, 1, 1],
                    "phoneme_vowel": [1, 1, 1],
                    "tone": [0, 0, 0],
                }
            ],
        }
    }
    words = ompal.annotated_words(
        {"path": "42.wav", "speakerId": "SPEAKER02001"}, {}, detail, aggregate, {"42": "old"}
    )
    assert words[0]["expectedPinyin"] == "ta1"
    assert words[0]["componentExpertLabels"]["tone"] == "unanimous-error"


def test_reserved_speaker_cannot_bypass_gate_by_renaming_test_split(chain):
    guard, _, config, _, _, _, _ = chain
    save(guard.ROOT / "content/pronunciation-ompal-data.json", json.loads(config.read_text()))
    with pytest.raises(ValueError, match="SPLIT_DOES_NOT_MATCH"):
        guard.assert_source_splits(
            [{"source": "ompal-v1", "speakerId": "speaker-test", "split": "calibration"}]
        )


def test_pitch_package_cannot_freeze_without_protocol_and_license_bindings(chain):
    guard, plan_path, _, package, _, _, _ = chain
    path = package / "model.json"
    metadata = json.loads(path.read_text())
    metadata["pitchOverride"] = {"sourceIdentity": {"modelSha256": "fixture"}}
    save(path, metadata)
    plan = json.loads(plan_path.read_text())
    for record in plan["modelFiles"]:
        if record["path"] == str(path):
            record["sha256"], record["sizeBytes"] = fingerprint(path), path.stat().st_size
    plan["planSha256"] = guard.digest({k: v for k, v in plan.items() if k != "planSha256"})
    save(plan_path, plan)
    with pytest.raises(ValueError, match="FROZEN_PITCH_PROTOCOL_OR_LICENSE_UNBOUND"):
        guard.verify_plan(plan_path)
