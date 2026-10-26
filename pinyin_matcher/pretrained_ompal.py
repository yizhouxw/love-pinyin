"""Explicit preparation of pinned OMPAL adult expert-annotated speech.

Expert component judgments are ground-truth correctness evidence. Expected
pinyin is a separately flagged lexical policy; no ASR or model prediction
becomes the actual pronunciation label. This module never fabricates boundaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_data import fetch_bytes

REVISION = "c3aaa9e892e4b1c2a25b637401f52f6e35b53e74"
BASE = f"https://raw.githubusercontent.com/phantomhsieh/OMPAL-corpus/{REVISION}/"
CONFIG = ROOT / "content/pronunciation-ompal-data.json"
COMPONENT_FIELDS = {"onset": "phoneme_consonant", "rime": "phoneme_vowel", "tone": "tone"}
SOURCE_FILES = (
    "README.md",
    "LICENSE",
    "native_scores.json",
    "non-native_scores.json",
    "non-native_scores-detail.json",
)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def speaker_split(speakers: list[str]) -> dict[str, str]:
    natives = [s for s in speakers if s.startswith("SPEAKER01")]
    learners = sorted(
        (s for s in speakers if s.startswith("SPEAKER02")),
        key=lambda x: hashlib.sha256(f"ompal-v1:{x}".encode()).hexdigest(),
    )
    if len(natives) != 3 or len(learners) != 46:
        raise ValueError("OMPAL_EXPECTED_3_NATIVE_46_LEARNERS")
    result = {s: "diagnostic" for s in natives}
    result.update(
        {
            s: "train" if i < 28 else "calibration" if i < 36 else "test"
            for i, s in enumerate(learners)
        }
    )
    return result


def blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def download(entry: dict, directory: Path) -> Path:
    path = directory / entry["path"]
    if not path.resolve().is_relative_to(directory.resolve()) or not entry["url"].startswith(BASE):
        raise ValueError("OMPAL_SOURCE_PATH_INVALID")
    if path.exists():
        payload = path.read_bytes()
    else:
        payload = fetch_bytes(entry["url"])
    if len(payload) != entry["bytes"] or blob_sha1(payload) != entry["gitBlobSha1"]:
        raise ValueError(f"OMPAL_PINNED_BLOB_MISMATCH:{entry['path']}")
    if entry.get("sha256") and hashlib.sha256(payload).hexdigest() != entry["sha256"]:
        raise ValueError("OMPAL_SHA256_MISMATCH")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return path


def snapshot(tree_path: Path, output: Path, directory: Path) -> dict:
    if output.exists():
        raise ValueError("OMPAL_SNAPSHOT_ALREADY_EXISTS")
    tree = json.loads(tree_path.read_text())
    if tree["sha"] != REVISION or tree.get("truncated"):
        raise ValueError("OMPAL_PINNED_TREE_REQUIRED")
    files = [x for x in tree["tree"] if x["path"].endswith(".wav") or x["path"] in SOURCE_FILES]
    if sum(x["path"].endswith(".wav") for x in files) != 1850:
        raise ValueError("OMPAL_EXPECTED_1850_WAV_FILES")
    speakers = sorted({x["path"].split("/")[1] for x in files if x["path"].endswith(".wav")})
    splits = speaker_split(speakers)
    entries = [
        {
            "path": x["path"],
            "bytes": x["size"],
            "gitBlobSha1": x["sha"],
            "url": BASE + x["path"],
            **(
                {"speakerId": x["path"].split("/")[1], "split": splits[x["path"].split("/")[1]]}
                if x["path"].endswith(".wav")
                else {}
            ),
        }
        for x in files
    ]
    for entry in entries:
        if "split" not in entry:
            path = download(entry, directory / "raw")
            entry["sha256"] = fingerprint(path)
    result = {
        "schemaVersion": 1,
        "datasetId": "ompal-v1",
        "revision": REVISION,
        "source": "https://github.com/phantomhsieh/OMPAL-corpus",
        "license": "CC-BY-4.0",
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "citation": (
            "Hsieh et al. 2025. OMPAL: Bridging Speech and Learning with an Open-Source "
            "Mandarin Pronunciation Assessment Corpus for Global Learners. Interspeech "
            "2025, 2415-2419. DOI10.21437/Interspeech.2025-983."
        ),
        "speakerSplitPolicy": (
            "SHA256(ompal-v1:speakerId) order; "
            "28learnertrain,8learnercalibration,10frozenlearner test;3native speakers "
            "diagnostic references only. Frozen audio not downloaded by default."
        ),
        "annotationPolicy": (
            "Non-native detailed raw expert ratings only. All three available ratings "
            "must agree per component; one record with fewer raters is ambiguous for "
            "that component. Native aggregate reference scores do not imply unanimous "
            "expert votes."
        ),
        "expectedPinyinPolicy": (
            "Lexical pinyin supplied by separate pinned policy; ambiguity, tone sandhi, "
            "neutral tones and multi-character word labels retained with explicit "
            "unassessable flags. Model alignment may supply boundaries only, never "
            "override expert correctness or lexical policy."
        ),
        "waveformIntegrity": (
            "Fixed commit + Git blob SHA1 checked before saving. Actual SHA256 for "
            "downloaded WAVs recorded in utterance manifest; unopened frozen-test SHA256"
            " unavailable until explicit preparation."
        ),
        "files": entries,
    }
    write_json(output, result)
    return result


def expert_component(values) -> str:
    if (
        not isinstance(values, list)
        or len(values) != 3
        or any(str(x) not in {"0", "1"} for x in values)
    ):
        return "ambiguous"
    if all(str(x) == "1" for x in values):
        return "unanimous-correct"
    if all(str(x) == "0" for x in values):
        return "unanimous-error"
    return "ambiguous"


def expert_word(word: dict, *, reference: bool) -> dict:
    raw = {key: word[field] for key, field in COMPONENT_FIELDS.items()}
    if reference:
        return {
            "expertRatings": raw,
            "expertLabel": "native-reference-aggregate",
            "componentExpertLabels": {key: "reference-aggregate" for key in raw},
            "expertRaterCount": None,
        }
    labels = {key: expert_component(values) for key, values in raw.items()}
    label = (
        "unanimous-correct"
        if all(x == "unanimous-correct" for x in labels.values())
        else "unanimous-error"
        if "unanimous-error" in labels.values()
        else "ambiguous"
    )
    return {
        "expertRatings": raw,
        "expertLabel": label,
        "componentExpertLabels": labels,
        "expertRaterCount": {
            key: len(values) if isinstance(values, list) else None for key, values in raw.items()
        },
    }


def annotated_words(entry, native, detailed, aggregate, mapping) -> list[dict]:
    """Public annotation-only derivation; never opens an audio file."""
    from pinyin_matcher.pretrained_ompal_policy import annotate_prompt

    utterance_id = Path(entry["path"]).stem
    reference = entry["speakerId"].startswith("SPEAKER01")
    scores = (native if reference else aggregate)[utterance_id]
    detailed_id = mapping.get(utterance_id) if not reference else None
    detailed_record = detailed.get(detailed_id) if detailed_id is not None else None
    policy = annotate_prompt(scores["text"], scores["words"])
    if detailed_record is not None and (
        detailed_record["text"] != scores["text"]
        or len(detailed_record["words"]) != len(scores["words"])
    ):
        raise ValueError("OMPAL_DETAIL_MAPPING_TEXT_MISMATCH")
    if len(policy) != len(scores["words"]):
        raise ValueError("OMPAL_POLICY_MUST_RETAIN_EVERY_WORD")
    return [
        {
            "id": f"ompal-{utterance_id}-w{index:03d}",
            "index": index,
            **lexical,
            **(
                expert_word(detailed_record["words"][index], reference=False)
                if detailed_record is not None
                else expert_word(word, reference=reference)
            ),
            "expertDetailedRecordId": detailed_id,
            "expertAnnotationResolved": reference or detailed_record is not None,
        }
        for index, (word, lexical) in enumerate(zip(scores["words"], policy, strict=True))
    ]


def frozen_annotations(config: dict, raw: Path) -> tuple[list[dict], list[Path]]:
    """Freeze reserved expert/lexical labels before downloading reserved WAVs."""
    paths = []
    for entry in config["files"]:
        if entry["path"] in {
            "native_scores.json",
            "non-native_scores.json",
            "non-native_scores-detail.json",
        }:
            path = raw / entry["path"]
            if fingerprint(path) != entry["sha256"]:
                raise ValueError("OMPAL_FROZEN_ANNOTATION_DIGEST_MISMATCH")
            paths.append(path)
    native = json.loads((raw / "native_scores.json").read_text())
    detailed = json.loads((raw / "non-native_scores-detail.json").read_text())
    aggregate = json.loads((raw / "non-native_scores.json").read_text())
    mapping = json.loads((ROOT / "content/pronunciation-ompal-detail-id-map.json").read_text())[
        "mapping"
    ]
    inventory = [
        {
            "id": "ompal-" + Path(entry["path"]).stem,
            "sourcePath": entry["path"],
            "speakerId": entry["speakerId"],
            "gitBlobSha1": entry["gitBlobSha1"],
            "words": annotated_words(entry, native, detailed, aggregate, mapping),
        }
        for entry in config["files"]
        if entry.get("split") == "test"
    ]
    return inventory, paths


def prepare(
    config_path: Path, directory: Path, *, include_frozen_test=False, frozen_plan=None, workers=12
) -> dict:
    if not 1 <= workers <= 16:
        raise ValueError("OMPAL_WORKER_COUNT_INVALID")
    config = json.loads(config_path.read_text())
    if include_frozen_test:
        from pinyin_matcher.pretrained_freeze import verify_plan

        verify_plan(frozen_plan, source_config=config_path)
    selected = [
        x
        for x in config["files"]
        if "split" not in x or include_frozen_test or x["split"] != "test"
    ]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(download, entry, directory / "raw"): entry for entry in selected}
        for index, job in enumerate(as_completed(pending), 1):
            job.result()
            if index % 100 == 0:
                print(json.dumps({"downloaded": index, "selectedFiles": len(selected)}), flush=True)
    raw = directory / "raw"
    native = json.loads((raw / "native_scores.json").read_text())
    detailed = json.loads((raw / "non-native_scores-detail.json").read_text())
    aggregate = json.loads((raw / "non-native_scores.json").read_text())
    mapping_path = ROOT / "content/pronunciation-ompal-detail-id-map.json"
    mapping = json.loads(mapping_path.read_text())["mapping"] if mapping_path.exists() else {}
    if mapping_path.exists():
        from pinyin_matcher.pretrained_ompal_id_map import build_mapping

        verified_mapping = build_mapping(aggregate, detailed)
        if verified_mapping["mapping"] != mapping or verified_mapping["unresolved"]:
            raise ValueError("OMPAL_DETAIL_ID_MAPPING_INTEGRITY_MISMATCH")
    utterances = []
    for entry in selected:
        if "split" not in entry:
            continue
        utterance_id = Path(entry["path"]).stem
        reference = entry["speakerId"].startswith("SPEAKER01")
        scores = (native if reference else aggregate)[utterance_id]
        words = annotated_words(entry, native, detailed, aggregate, mapping)
        path = raw / entry["path"]
        utterances.append(
            {
                "id": f"ompal-{utterance_id}",
                "utteranceId": utterance_id,
                "file": str(path.resolve()),
                "sha256": fingerprint(path),
                "speakerId": entry["speakerId"],
                "voiceFamilyId": entry["speakerId"],
                "referenceSourceId": entry["speakerId"],
                "split": entry["split"],
                "source": "ompal-v1",
                "sourcePath": entry["path"],
                "sourceGitBlobSha1": entry["gitBlobSha1"],
                "text": scores["text"],
                "labelProvenance": (
                    "Original detailed per-component expert correctness votes; model may "
                    "determine clip boundaries only, never actual phoneme labels."
                ),
                "words": words,
            }
        )
    result = {
        "schemaVersion": 1,
        "datasetId": "ompal-v1",
        "configSha256": fingerprint(config_path),
        "revision": REVISION,
        "license": config["license"],
        "citation": config["citation"],
        "frozenTestIncluded": include_frozen_test,
        "frozenPlanSha256": fingerprint(frozen_plan) if include_frozen_test else None,
        "detailIdMappingSha256": fingerprint(mapping_path) if mapping_path.exists() else None,
        "pinyinPolicySha256": fingerprint(ROOT / "content/pronunciation-ompal-policy.json"),
        "reservedSpeakers": sorted(
            {x["speakerId"] for x in config["files"] if x.get("split") == "test"}
        ),
        "utterances": utterances,
    }
    output = directory / (
        "utterances-with-frozen-test.json"
        if include_frozen_test
        else "utterances-train-calibration.json"
    )
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--tree", type=Path, required=True)
    snap.add_argument("--output", type=Path, default=CONFIG)
    snap.add_argument("--directory", type=Path, default=ROOT / "private/pretrained-matcher/ompal")
    prep = sub.add_parser("prepare")
    prep.add_argument("--config", type=Path, default=CONFIG)
    prep.add_argument("--directory", type=Path, default=ROOT / "private/pretrained-matcher/ompal")
    prep.add_argument("--include-frozen-test", action="store_true")
    prep.add_argument("--frozen-plan", type=Path)
    prep.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    data = (
        snapshot(args.tree, args.output, args.directory)
        if args.action == "snapshot"
        else prepare(
            args.config,
            args.directory,
            include_frozen_test=args.include_frozen_test,
            frozen_plan=args.frozen_plan,
            workers=args.workers,
        )
    )
    print(
        json.dumps(
            {
                "sourceFiles": len(data.get("files", [])),
                "utterances": len(data.get("utterances", [])),
                "frozenTestIncluded": data.get("frozenTestIncluded", False),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
