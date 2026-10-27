"""Verify a frozen experiment before any reserved speech is opened.

Plans bind the complete executable pipeline, dependency lock, source configuration
and every CPU-package file. Derived manifests must retain the frozen source and
all annotated roots; a split string or a syntactically valid digest is insufficient.
Only metadata and already frozen resources are read by these checks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_metrics import GATE_LIMITS, MIN_ROOTS, MIN_SPEAKERS


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def pipeline_files() -> list[Path]:
    directory = ROOT / "pinyin_matcher"
    return sorted(
        {
            *directory.glob("pretrained_*.py"),
            directory / "audio.py",
            directory / "catalog.py",
            directory / "pitch_swift.py",
            directory / "pitch_v2.py",
        }
    )


def protocol_files() -> list[Path]:
    """Bind every versioned protocol used by this research pipeline."""
    content = ROOT / "content"
    return sorted(
        {
            *content.glob("pronunciation-pretrained-*.json"),
            *content.glob("pronunciation-ompal-*.json"),
            *content.glob("pronunciation-aishell3-*.json"),
            *content.glob("pronunciation-eduhk-*.json"),
            *(ROOT / "resources/licenses").glob("SenseVoice-*.txt"),
            *(ROOT / "resources/licenses").glob("Charsiu-MIT.txt"),
            *(ROOT / "resources/licenses").glob("SwiftF0-MIT.txt"),
        }
    )


def assert_source_splits(rows: list[dict]) -> None:
    """A reserved speaker cannot be opened by relabelling a manifest split."""
    known = {
        "ompal-v1": ("pronunciation-ompal-data.json", "files"),
        "mandi-cmn-wl1": ("pronunciation-pretrained-data.json", "recordings"),
        "aishell3-supplementary-native-2000-v1": ("pronunciation-aishell3-data.json", "files"),
        "eduhk-mandarin-task1-training-v1": ("pronunciation-eduhk-data.json", "files"),
    }
    tables = {}
    for name in {row.get("source") for row in rows} & known.keys():
        filename, collection = known[name]
        config = json.loads((ROOT / "content" / filename).read_text())
        tables[name] = {
            entry["speakerId"]: entry["split"]
            for entry in config[collection]
            if "speakerId" in entry
        }
    for row in rows:
        table = tables.get(row.get("source"))
        if table is not None and table.get(row.get("speakerId")) != row.get("split"):
            raise ValueError("SOURCE_SPEAKER_SPLIT_DOES_NOT_MATCH_PINNED_CONFIGURATION")


def verify_plan(
    path: Path | None, *, source_config: Path | None = None, package: Path | None = None
):
    if path is None:
        raise ValueError("FROZEN_TEST_REQUIRES_EXPLICIT_PLAN")
    plan = json.loads(path.read_text())
    claimed = plan.get("planSha256")
    unsigned = {key: value for key, value in plan.items() if key != "planSha256"}
    if not isinstance(claimed, str) or digest(unsigned) != claimed:
        raise ValueError("FROZEN_TEST_PLAN_SHA_MISMATCH")
    if (
        plan.get("schemaVersion") != 1
        or plan.get("limits") != GATE_LIMITS
        or plan.get("minimumRootsPerStratum") != MIN_ROOTS
        or plan.get("minimumSpeakers") != MIN_SPEAKERS
        or plan.get("lineageDisjoint") is not True
        or plan.get("configSha256") != digest(plan.get("config"))
    ):
        raise ValueError("FROZEN_TEST_PLAN_POLICY_INVALID")
    config = plan["config"]
    if config.get("thresholdsFrozen") is not True or config.get("testAudioNotOpened") is not True:
        raise ValueError("FROZEN_TEST_PLAN_POLICY_INVALID")
    paths = {}
    for field in ("files", "codeFiles", "modelFiles"):
        records = plan.get(field)
        if not isinstance(records, list) or not records:
            raise ValueError("FROZEN_TEST_PLAN_RESOURCE_LIST_REQUIRED")
        paths[field] = set()
        for record in records:
            resource = Path(record["path"])
            if not resource.is_absolute():
                raise ValueError("FROZEN_RESOURCE_ABSOLUTE_PATH_REQUIRED")
            resource = resource.resolve()
            if resource in paths[field] or fingerprint(resource) != record["sha256"]:
                raise ValueError("FROZEN_FILE_CHANGED")
            if resource.stat().st_size != record["sizeBytes"]:
                raise ValueError("FROZEN_FILE_CHANGED")
            paths[field].add(resource)
    if not {p.resolve() for p in pipeline_files()} <= paths["codeFiles"]:
        raise ValueError("FROZEN_EXECUTABLE_PIPELINE_INCOMPLETE")
    required = {
        ROOT / "tools/pinyin-pretrained/uv.lock",
        ROOT / "tools/pinyin-pretrained/pyproject.toml",
        ROOT / "content/pronunciation-targets.json",
        ROOT / "content/pronunciation-pretrained-models.json",
        ROOT / "content/pronunciation-pretrained-experiment.json",
        *protocol_files(),
    }
    if not {p.resolve() for p in required} <= paths["files"]:
        raise ValueError("FROZEN_DEPENDENCY_OR_CONFIGURATION_INCOMPLETE")
    configured_source = Path(config["sourceConfigPath"]).resolve()
    if configured_source not in paths["files"]:
        raise ValueError("FROZEN_SOURCE_CONFIGURATION_UNBOUND")
    if source_config is not None and source_config.resolve() != configured_source:
        raise ValueError("SOURCE_NOT_IN_FROZEN_PLAN")
    if Path(config["trainingManifestPath"]).resolve() not in paths["files"]:
        raise ValueError("FROZEN_TRAINING_MANIFEST_UNBOUND")
    packages = {Path(p).resolve() for p in config["packages"]}
    if not packages or (package is not None and package.resolve() not in packages):
        raise ValueError("MODEL_NOT_IN_FROZEN_PLAN")
    for directory in packages:
        metadata_path = directory / "model.json"
        if metadata_path not in paths["modelFiles"]:
            raise ValueError("MODEL_NOT_IN_FROZEN_PLAN")
        metadata = json.loads(metadata_path.read_text())
        override = metadata.get("pitchOverride")
        if override:
            protocol = ROOT / "content/pronunciation-pretrained-pitch.json"
            license_file = ROOT / "resources/licenses/SwiftF0-MIT.txt"
            if not {protocol.resolve(), license_file.resolve()} <= paths["files"]:
                raise ValueError("FROZEN_PITCH_PROTOCOL_OR_LICENSE_UNBOUND")
            identity = override["sourceIdentity"]
            if (
                identity["protocolSha256"] != fingerprint(protocol)
                or identity["licenseSha256"] != fingerprint(license_file)
                or identity["baseManifestSha256"] != metadata["manifestSha256"]
                or fingerprint(directory / "pitch/model.onnx") != identity["modelSha256"]
                or fingerprint(directory / "pitch/LICENSE") != identity["licenseSha256"]
            ):
                raise ValueError("FROZEN_PITCH_SOURCE_IDENTITY_CHANGED")
            for filename, expected_sha in identity["codeSha256"].items():
                source_code = (ROOT / "pinyin_matcher" / filename).resolve()
                if (
                    source_code not in paths["codeFiles"]
                    or fingerprint(source_code) != expected_sha
                ):
                    raise ValueError("FROZEN_PITCH_FEATURE_CODE_CHANGED")
        resources = metadata.get("packageFiles")
        if not isinstance(resources, dict) or not resources:
            raise ValueError("FROZEN_MODEL_PACKAGE_FILES_REQUIRED")
        actual_resources = {
            path.resolve()
            for path in directory.rglob("*")
            if path.is_file() and path != metadata_path
        }
        declared_resources = {(directory / relative).resolve() for relative in resources}
        if actual_resources != declared_resources:
            raise ValueError("FROZEN_MODEL_PACKAGE_FILE_INVENTORY_CHANGED")
        for relative, record in resources.items():
            resource = (directory / relative).resolve()
            if not resource.is_relative_to(directory) or resource not in paths["modelFiles"]:
                raise ValueError("FROZEN_MODEL_PACKAGE_INCOMPLETE")
            if fingerprint(resource) != record["sha256"]:
                raise ValueError("FROZEN_MODEL_PACKAGE_CHANGED")
    return plan


def verify_source_manifest(data: dict, plan_path: Path, plan: dict) -> None:
    """Validate prepared utterance identities before decoding reserved audio."""
    config_path = Path(plan["config"]["sourceConfigPath"])
    if data.get("frozenPlanSha256") != fingerprint(plan_path):
        raise ValueError("DERIVED_MANIFEST_NOT_BOUND_TO_FROZEN_PLAN")
    if data.get("frozenTestIncluded") is not True or data.get("configSha256") != fingerprint(
        config_path
    ):
        raise ValueError("DERIVED_MANIFEST_SOURCE_CONFIGURATION_MISMATCH")
    source = json.loads(config_path.read_text())
    if source.get("datasetId") == "ompal-v1":
        inventory = {
            row["sourcePath"]: row for row in plan["config"]["reservedAnnotationInventory"]
        }
        expected = {entry["path"]: entry for entry in source["files"] if "split" in entry}
        if set(inventory) != {key for key, entry in expected.items() if entry["split"] == "test"}:
            raise ValueError("FROZEN_RESERVED_ANNOTATION_INVENTORY_INCOMPLETE")
        utterances = data.get("utterances")
        if not isinstance(utterances, list) or len(utterances) != len(expected):
            raise ValueError("FROZEN_SOURCE_UTTERANCE_COVERAGE_CHANGED")
        observed = set()
        for row in utterances:
            key = row.get("sourcePath")
            entry = expected.get(key)
            if key in observed or entry is None:
                raise ValueError("FROZEN_SOURCE_UTTERANCE_ID_INVALID")
            observed.add(key)
            if (
                row.get("speakerId") != entry["speakerId"]
                or row.get("voiceFamilyId") != entry["speakerId"]
                or row.get("referenceSourceId") != entry["speakerId"]
                or row.get("source") != "ompal-v1"
                or row.get("split") != entry["split"]
                or row.get("sourceGitBlobSha1") != entry["gitBlobSha1"]
                or row.get("id") != "ompal-" + Path(key).stem
            ):
                raise ValueError("FROZEN_SOURCE_UTTERANCE_LINEAGE_MISMATCH")
            if row["split"] == "test" and (
                row.get("words") != inventory[key]["words"] or row.get("id") != inventory[key]["id"]
            ):
                raise ValueError("FROZEN_RESERVED_ANNOTATION_CHANGED")
        for field, name in (
            ("pinyinPolicySha256", "pronunciation-ompal-policy.json"),
            ("detailIdMappingSha256", "pronunciation-ompal-detail-id-map.json"),
        ):
            if data.get(field) != fingerprint(ROOT / "content" / name):
                raise ValueError("FROZEN_SOURCE_ANNOTATION_POLICY_CHANGED")


def verify_test_manifest(manifest: Path, plan_path: Path, *, package: Path | None = None) -> dict:
    """Check the complete derivation and root inventory without reading WAVs."""
    plan = verify_plan(plan_path, package=package)
    data = json.loads(manifest.read_text())
    if (
        data.get("frozenPlanSha256") != fingerprint(plan_path)
        or data.get("frozenTestIncluded") is not True
    ):
        raise ValueError("DERIVED_MANIFEST_NOT_BOUND_TO_FROZEN_PLAN")
    config_path = Path(plan["config"]["sourceConfigPath"])
    source = json.loads(config_path.read_text())
    rows = data.get("items")
    if not isinstance(rows, list):
        raise ValueError("FROZEN_TEST_ITEMS_REQUIRED")
    if source.get("datasetId") == "ompal-v1":
        utterance_path = Path(data["utterancesManifestPath"])
        if fingerprint(utterance_path) != data["utterancesManifestSha256"]:
            raise ValueError("FROZEN_PARENT_MANIFEST_CHANGED")
        utterances = json.loads(utterance_path.read_text())
        verify_source_manifest(utterances, plan_path, plan)
        if (
            data.get("utterancesConfigSha256") != fingerprint(config_path)
            or data.get("pipelineSha256")
            != fingerprint(ROOT / "pinyin_matcher/pretrained_ompal_clips.py")
            or data.get("alignerSha256") != fingerprint(ROOT / "pinyin_matcher/pretrained_align.py")
        ):
            raise ValueError("FROZEN_CLIP_DERIVATION_CHANGED")
        expected = {
            word["id"]: (utterance, word)
            for utterance in utterances["utterances"]
            for word in utterance["words"]
        }
        if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
            raise ValueError("FROZEN_TEST_ANNOTATED_ROOT_COVERAGE_CHANGED")
        for row in rows:
            parent, word = expected[row["id"]]
            if (
                row["parentSha256"] != parent["sha256"]
                or row["sourceUtteranceId"] != parent["id"]
                or row["speakerId"] != parent["speakerId"]
                or row.get("voiceFamilyId") != parent["voiceFamilyId"]
                or row.get("referenceSourceId") != parent["referenceSourceId"]
                or row.get("sourcePath") != parent["sourcePath"]
                or row.get("sourceGitBlobSha1") != parent["sourceGitBlobSha1"]
                or row["split"] != parent["split"]
                or any(row.get(key) != value for key, value in word.items())
            ):
                raise ValueError("FROZEN_TEST_ROOT_OR_LABEL_CHANGED")
    else:
        if data.get("configSha256") != fingerprint(config_path):
            raise ValueError("DERIVED_MANIFEST_SOURCE_CONFIGURATION_MISMATCH")
        recordings = {r["speakerId"]: r for r in source["recordings"]}
        inventory = {r["id"]: r for r in plan["config"]["reservedAnnotationInventory"]}
        if {r["id"] for r in rows if r["split"] == "test"} != set(inventory):
            raise ValueError("FROZEN_TEST_ANNOTATED_ROOT_COVERAGE_CHANGED")
        seen = set()
        for row in rows:
            record = recordings.get(row["speakerId"])
            if record is None or (
                row["split"] != record["split"]
                or row["parentSha256"] != record["wav"]["sha256"]
                or row["annotationSha256"] != record["grid"]["sha256"]
            ):
                raise ValueError("FROZEN_TEST_ROOT_OR_LABEL_CHANGED")
            seen.add(row["speakerId"])
            if row["split"] == "test" and any(
                row.get(key) != value for key, value in inventory[row["id"]].items()
            ):
                raise ValueError("FROZEN_RESERVED_ANNOTATION_CHANGED")
        if seen != set(recordings):
            raise ValueError("FROZEN_SOURCE_UTTERANCE_COVERAGE_CHANGED")
    return plan
