"""Add real native-speech training clips without changing the evaluation roots."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from pinyin_matcher import pretrained_factorized as original
from pinyin_matcher import pretrained_hard_negative as hard
from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import read_rows, write
from pinyin_matcher.pretrained_native_clips import CONFIG as CLIPS_CONFIG
from pinyin_matcher.pretrained_native_clips import SOURCE, selected_items
from pinyin_matcher.pretrained_native_sequence import (
    _native_manifest,
    _read_pcm,
    validate_cached_labels,
    vocabularies,
)
from pinyin_matcher.pretrained_ompal_policy import _components

CONFIG = ROOT / "content/pronunciation-pretrained-hard-negative-native.json"
BASE_ROWS = hard.training_rows
BASE_PAIRS = hard.pairs
BASE_SUPERVISION = original.supervision


def build_manifest(native_clips, native_manifest, native_cache, ompal_manifest, baseline, output):
    if output.exists():
        raise ValueError("NATIVE_MIX_OUTPUT_EXISTS")
    protocol = json.loads(CONFIG.read_text())
    if (
        fingerprint(native_clips) != protocol["nativeClipManifestSha256"]
        or fingerprint(baseline / "model.json") != protocol["baselineMetadataSha256"]
    ):
        raise ValueError("NATIVE_MIX_FIXED_SOURCE_CHANGED")
    source = _native_manifest(native_manifest)
    cached = json.loads((native_cache / "cache.json").read_text())
    model = ROOT / "models/pinyin-pretrained/hanziflow"
    validate_cached_labels(cached, source, vocabularies(model), native_cache)
    selected = selected_items(cached["items"], 20261027, 25)
    selected_by_id = {item["id"]: item for item in selected}
    old = read_rows(ompal_manifest)
    incoming = read_rows(native_clips)
    if incoming[: len(old)] != old:
        raise ValueError("NATIVE_MIX_OMPAL_ROOTS_CHANGED")
    source_record = json.loads(native_clips.read_text())["nativeTrainingSource"]
    if (
        source_record["generatorSha256"]
        != fingerprint(Path(__file__).with_name("pretrained_native_clips.py"))
        or source_record["configurationSha256"] != fingerprint(CLIPS_CONFIG)
        or source_record["manifestSha256"] != fingerprint(native_manifest)
        or source_record["cacheSha256"] != fingerprint(native_cache / "cache.json")
        or source_record["alignmentModelWeightsSha256"] != fingerprint(model / "model.safetensors")
        or source_record["sourceUtterances"] != len(selected)
        or source_record["sourceSpeakers"] != 20
        or source_record["finalTestRead"] is not False
    ):
        raise ValueError("NATIVE_MIX_SOURCE_PROVENANCE_CHANGED")
    baseline_metadata = json.loads((baseline / "model.json").read_text())
    allowed = {
        tuple(str(item[k]) for k in hard.COMPONENTS) for item in baseline_metadata["coveredTargets"]
    }
    vocab = baseline_metadata["vocabulary"]
    parent_audio = {}
    native, counts = [], Counter()
    for row in incoming[len(old) :]:
        item = selected_by_id.get(row["sourceUtteranceId"])
        index_text = row["id"].removeprefix(row["sourceUtteranceId"] + "-s")
        if item is None or not index_text.isdigit():
            raise ValueError("NATIVE_MIX_UNKNOWN_SOURCE")
        index = int(index_text)
        if index >= len(item["providedPinyin"]):
            raise ValueError("NATIVE_MIX_SYLLABLE_INDEX_INVALID")
        syllable = item["providedPinyin"][index]
        actual = _components(syllable)
        if (
            row["syllable"] != syllable
            or any(row[k] != actual[k] for k in hard.COMPONENTS)
            or row["speakerId"] != item["speakerId"]
            or row["voiceFamilyId"] != item["speakerId"]
            or row["referenceSourceId"] != item["speakerId"]
            or row["source"] != SOURCE
            or row["split"] != "train"
            or row["parentSha256"] != item["audio"]["sourceSha256"]
            or any(
                row["componentExpertLabels"].get(k) != "source-provided-realized"
                for k in hard.COMPONENTS
            )
            or row["alignmentFlags"] != row["alignment"]["flags"]
        ):
            raise ValueError("NATIVE_MIX_LABEL_OR_LINEAGE_CHANGED")
        audio = parent_audio.get(item["id"])
        if audio is None:
            path = Path(item["audio"]["file"])
            if fingerprint(path) != item["audio"]["sha256"]:
                raise ValueError("NATIVE_MIX_PARENT_AUDIO_CHANGED")
            audio = _read_pcm(path, rate=16000)[0]
            parent_audio[item["id"]] = audio
        bounds = row["bounds"]
        if bounds["placeholder"]:
            expected = np.zeros(4000, dtype=np.float32)
        else:
            expected = audio[bounds["startSample"] : bounds["endSample"]]
            expected = np.pad(
                expected, (bounds["zeroPadLeftSamples"], bounds["zeroPadRightSamples"])
            )
        if (
            fingerprint(Path(row["file"])) != row["sha256"]
            or encode_wav(expected) != Path(row["file"]).read_bytes()
        ):
            raise ValueError("NATIVE_MIX_CLIP_CONTENT_CHANGED")
        expected_policy = []
        if actual["tone"] not in (1, 2, 3, 4):
            expected_policy.append("SOURCE_NEUTRAL_TONE_OUTSIDE_FOUR_TONE_EXPERIMENT")
        if row["alignmentFlags"]:
            expected_policy.append("SOURCE_BOUNDARY_UNVERIFIED")
        if row["labelPolicyFlags"] != expected_policy:
            raise ValueError("NATIVE_MIX_QUALITY_FLAGS_CHANGED")
        if tuple(str(row[k]) for k in hard.COMPONENTS) not in allowed or any(
            str(row[k]) not in vocab[k] for k in hard.COMPONENTS
        ):
            row["labelPolicyFlags"].append("OUTSIDE_BASELINE_TARGET_COVERAGE")
        native.append(row)
        counts["total"] += 1
        counts["eligible"] += not bool(
            row["labelPolicyFlags"] or row["numericalQualityFlags"] or row["placeholder"]
        )
        counts["outsideBaselineCoverage"] += (
            "OUTSIDE_BASELINE_TARGET_COVERAGE" in row["labelPolicyFlags"]
        )
    by_source = Counter(row["sourceUtteranceId"] for row in native)
    if set(by_source) != set(selected_by_id) or any(
        by_source[key] != len(item["providedPinyin"]) for key, item in selected_by_id.items()
    ):
        raise ValueError("NATIVE_MIX_SOURCE_WORD_INVENTORY_CHANGED")
    source_header = json.loads(ompal_manifest.read_text())
    result = {
        key: value
        for key, value in source_header.items()
        if key not in ("items", "counts", "elapsedSeconds")
    }
    result["datasetId"] = "ompal-plus-aishell3-training-clips-v1"
    result["license"] = "OMPAL CC BY 4.0; AISHELL-3 Apache-2.0"
    result["headerLineageScope"] = (
        "OMPAL roots retain v2 lineage; additional native roots carry independent lineage."
    )
    result["counts"] = {
        "words": len(old) + len(native),
        "bySplit": dict(Counter(row["split"] for row in old + native)),
        "native": dict(counts),
    }
    result["nativeTrainingSource"] = source_record
    result["nativeClipManifestSha256"] = fingerprint(native_clips)
    result["baselineMetadataSha256"] = fingerprint(baseline / "model.json")
    result["mixedManifestCodeSha256"] = fingerprint(Path(__file__))
    result["items"] = old + native
    write(output, result)
    read_rows(output)
    return {"manifestSha256": fingerprint(output), **dict(counts)}


def mixed_pairs(rows):
    yield from BASE_PAIRS(rows)
    vocab = {key: sorted({str(row[key]) for row in rows}) for key in hard.COMPONENTS}
    for row in sorted(rows, key=lambda item: item["id"]):
        if row.get("source") != SOURCE:
            continue
        for component in hard.COMPONENTS:
            if row["componentExpertLabels"].get(component) != "source-provided-realized":
                continue
            actual = str(row[component])
            for target in vocab[component]:
                if target != actual:
                    yield {
                        "rootId": row["id"],
                        "audioSha256": row["sha256"],
                        "parentSha256": row["parentSha256"],
                        "speakerId": row["speakerId"],
                        "voiceFamilyId": row["voiceFamilyId"],
                        "referenceSourceId": row["referenceSourceId"],
                        "component": component,
                        "sourceProvidedActual": actual,
                        "incorrectTarget": target,
                        "label": "component-mismatch",
                        "labelBasis": "human-listened-source-pinyin-machine-boundary",
                        "sourceSplit": "train",
                    }


def mixed_supervision(rows):
    values = BASE_SUPERVISION(rows)
    for index, row in enumerate(rows):
        if row.get("source") == SOURCE and row["split"] == "train":
            if row.get("labelPolicyFlags") or row.get("numericalQualityFlags"):
                values[index] = -1
            else:
                values[index] = [
                    1 if row["componentExpertLabels"].get(c) == "source-provided-realized" else -1
                    for c in hard.COMPONENTS
                ]
    return values


def run(action, manifest, output, *, cache=None, evidence=None):
    if fingerprint(manifest) != json.loads(CONFIG.read_text()).get("mixedManifestSha256"):
        raise ValueError("NATIVE_MIX_MANIFEST_CHANGED")
    old_config, old_pairs, old_supervision = hard.CONFIG, hard.pairs, original.supervision
    try:
        hard.CONFIG, hard.pairs, original.supervision = CONFIG, mixed_pairs, mixed_supervision
        if action == "prepare":
            result = hard.prepare(manifest, output)
            result["mixedPairCodeSha256"] = fingerprint(Path(__file__))
            result["limitations"] = (
                "OMPAL components use expert votes; AISHELL components use human-listened "
                "source pinyin with machine-estimated boundaries. Pairs share original audio; "
                "source identifiers do not prove distinct people across corpora."
            )
            result["nativeSourceUtterances"] = 500
            result["nativeSourceSpeakerIds"] = 20
            result["nativeTrainingClips"] = json.loads(manifest.read_text())["counts"]["native"][
                "eligible"
            ]
            write(output / "metadata.json", result)
            return result
        data = json.loads((evidence / "metadata.json").read_text())
        if data.get("mixedPairCodeSha256") != fingerprint(Path(__file__)):
            raise ValueError("NATIVE_MIX_PAIR_CODE_CHANGED")
        result = hard.train(manifest, cache, evidence, output)
        path = output / "model.json"
        metadata = json.loads(path.read_text())
        metadata["nativeMixedTrainingCodeSha256"] = fingerprint(Path(__file__))
        metadata["nativeClipManifestSha256"] = json.loads(CONFIG.read_text())[
            "nativeClipManifestSha256"
        ]
        metadata["nativeSourceLicense"] = "Apache-2.0"
        write(path, metadata)
        return result
    finally:
        hard.CONFIG, hard.pairs, original.supervision = old_config, old_pairs, old_supervision


def rebind_config(native_clips, baseline, output):
    if output.exists():
        raise ValueError("NATIVE_MIX_CONFIG_OUTPUT_EXISTS")
    value = json.loads(CONFIG.read_text())
    source = json.loads(native_clips.read_text())["nativeTrainingSource"]
    base = json.loads((baseline / "model.json").read_text())
    if (
        source["sourceCorpus"] != SOURCE
        or source["finalTestRead"] is not False
        or source["sourceSpeakers"] != 20
        or base.get("model") != "sensevoice"
        or base.get("acousticDerivative") is not None
        or base.get("testUsed") is not False
    ):
        raise ValueError("NATIVE_MIX_CONFIG_SOURCE_INVALID")
    value["nativeClipManifestSha256"] = fingerprint(native_clips)
    value["baselineMetadataSha256"] = fingerprint(baseline / "model.json")
    value.pop("mixedManifestSha256", None)
    write(output, value)
    return {"configurationSha256": fingerprint(output)}


def bind_manifest(manifest, output):
    if output.exists():
        raise ValueError("NATIVE_MIX_CONFIG_OUTPUT_EXISTS")
    value = json.loads(CONFIG.read_text())
    source = json.loads(manifest.read_text())
    if (
        source.get("datasetId") != "ompal-plus-aishell3-training-clips-v1"
        or source.get("nativeClipManifestSha256") != value["nativeClipManifestSha256"]
        or source.get("baselineMetadataSha256") != value["baselineMetadataSha256"]
        or source.get("mixedManifestCodeSha256") != fingerprint(Path(__file__))
    ):
        raise ValueError("NATIVE_MIX_CONFIG_MANIFEST_INVALID")
    value["mixedManifestSha256"] = fingerprint(manifest)
    write(output, value)
    return {"configurationSha256": fingerprint(output)}


def main():
    global CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("manifest")
    for key in (
        "native-clips",
        "native-manifest",
        "native-cache",
        "ompal-manifest",
        "baseline",
        "output",
    ):
        build.add_argument("--" + key, type=Path, required=True)
    for action in ("prepare", "train"):
        sub = actions.add_parser(action)
        names = (
            ("manifest", "output")
            if action == "prepare"
            else ("manifest", "cache", "evidence", "output")
        )
        for key in names:
            sub.add_argument("--" + key, type=Path, required=True)
        sub.add_argument("--config", type=Path, default=CONFIG)
    build.add_argument("--config", type=Path, default=CONFIG)
    rebind = actions.add_parser("rebind-config")
    for key in ("native-clips", "baseline", "output"):
        rebind.add_argument("--" + key, type=Path, required=True)
    rebind.add_argument("--config", type=Path, default=CONFIG)
    binding = actions.add_parser("bind-manifest")
    for key in ("manifest", "output"):
        binding.add_argument("--" + key, type=Path, required=True)
    binding.add_argument("--config", type=Path, default=CONFIG)
    args = vars(parser.parse_args())
    action = args.pop("action")
    CONFIG = args.pop("config")
    if action == "manifest":
        result = build_manifest(**args)
    elif action == "rebind-config":
        result = rebind_config(**args)
    elif action == "bind-manifest":
        result = bind_manifest(**args)
    else:
        result = run(action, **args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
