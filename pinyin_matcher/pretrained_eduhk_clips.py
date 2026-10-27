"""Generate train-only weakly aligned candidates from licensed real error speech."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import scipy
from scipy.ndimage import binary_closing, binary_opening, label
from scipy.signal import resample_poly

from pinyin_matcher.audio import AudioRejected, encode_wav, quality_check
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_eduhk_data import TRAIN

CONFIG = ROOT / "content/pronunciation-pretrained-eduhk-clips.json"
SOURCE = "eduhk-mandarin-task1-training-v1"
COMPONENTS = ("onset", "rime", "tone")


def segments(samples, rate, config):
    width = rate * config["frameMilliseconds"] // 1000
    if width * 1000 != rate * config["frameMilliseconds"] or len(samples) < width:
        raise ValueError("EDUHK_AUDIO_RATE_INVALID")
    frames = samples[: len(samples) // width * width].reshape(-1, width)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    threshold = max(
        config["minimumRms"],
        float(np.quantile(rms, config["noiseQuantile"])) * config["noiseMultiplier"],
        float(np.quantile(rms, config["signalQuantile"])) * config["signalMultiplier"],
    )
    active = rms > threshold
    active = binary_closing(active, structure=np.ones(config["closeFrames"], dtype=bool))
    active = binary_opening(active, structure=np.ones(config["openFrames"], dtype=bool))
    regions, count = label(active)
    return [
        (int(np.flatnonzero(regions == i)[0]), int(np.flatnonzero(regions == i)[-1]) + 1)
        for i in range(1, count + 1)
    ], threshold


def replacements(annotations):
    result, skipped = set(), Counter()
    for item in annotations:
        before, after = (
            item.get("expectedComponentAudit") or {},
            item.get("realizedComponentAudit") or {},
        )
        if not before.get("parsed") or not after.get("parsed"):
            skipped["unparseable_or_unmarked"] += 1
            continue
        if before.get("tone") not in (1, 2, 3, 4) or after.get("tone") not in (1, 2, 3, 4):
            skipped["tone_not_explicit_four_tone"] += 1
            continue
        changed = [key for key in COMPONENTS if before[key] != after[key]]
        category = item["declaredCategory"]
        for component in changed:
            if category not in {component, "mispronunciation"} and not (
                component == "tone" and category == "suprasegmental"
            ):
                skipped["category_ontology_mismatch"] += 1
                continue
            result.add(
                (
                    component,
                    tuple(str(before[k]) for k in COMPONENTS),
                    tuple(str(after[k]) for k in COMPONENTS),
                )
            )
    return sorted(result), dict(skipped)


def prepare(data_config, parsed, mixed_manifest, baseline, raw_directory, output):
    import soundfile as sf

    if output.exists():
        raise ValueError("EDUHK_CLIPS_OUTPUT_EXISTS")
    protocol = json.loads(CONFIG.read_text())
    fixed = {
        "frameMilliseconds": 10,
        "minimumRms": 0.0025,
        "noiseQuantile": 0.2,
        "noiseMultiplier": 3.0,
        "signalQuantile": 0.95,
        "signalMultiplier": 0.06,
        "closeFrames": 15,
        "openFrames": 6,
        "expectedTaskItems": 40,
        "contextMilliseconds": 40,
        "maximumClipSeconds": 2,
        "audioSplit": "train-only",
        "finalTestUsed": False,
    }
    if any(protocol.get(k) != v for k, v in fixed.items()):
        raise ValueError("EDUHK_CLIPS_PROTOCOL_CHANGED")
    if (
        fingerprint(parsed) != protocol["expectedMetadataSha256"]
        or fingerprint(baseline / "model.json") != protocol["baselineMetadataSha256"]
        or fingerprint(data_config) != protocol["dataConfigurationSha256"]
        or fingerprint(mixed_manifest) != protocol["mixedManifestSha256"]
        or fingerprint(ROOT / "uv.lock") != protocol["rootUvLockSha256"]
    ):
        raise ValueError("EDUHK_CLIPS_INPUT_CHANGED")
    data = json.loads(data_config.read_text())
    if (
        data["metadataSha256"] != fingerprint(parsed)
        or data["audioOutsideTrainingDownloaded"] is not False
    ):
        raise ValueError("EDUHK_CLIPS_SOURCE_UNBOUND")
    inventory = json.loads(parsed.read_text())
    if (
        inventory["splitProposal"]["train"] != TRAIN
        or data["trainingSpeakers"] != TRAIN
        or [item["sourceId"] for item in data["files"]] != TRAIN
    ):
        raise ValueError("EDUHK_CLIPS_TRAIN_SPLIT_CHANGED")
    base = json.loads((baseline / "model.json").read_text())
    targets = {tuple(str(t[c]) for c in COMPONENTS): t for t in base["coveredTargets"]}
    originals = json.loads(mixed_manifest.read_text())
    counts, generated, all_candidates, speech_regions = Counter(), [], [], {}
    output.mkdir(parents=True)
    clips = output / "clips"
    clips.mkdir()
    for recording in data["files"]:
        if (
            recording["split"] != "train"
            or recording["sourceId"] not in TRAIN
            or recording["fileName"] != f"T{recording['sourceId']}_T1.mp3"
        ):
            raise ValueError("EDUHK_CLIPS_NONTRAIN_AUDIO")
        path = raw_directory / recording["fileName"]
        if fingerprint(path) != recording["sha256"]:
            raise ValueError("EDUHK_CLIPS_RAW_AUDIO_CHANGED")
        signal, rate = sf.read(path, dtype="float32")
        if signal.ndim == 2:
            signal = signal.mean(axis=1)
        if signal.ndim != 1 or not np.isfinite(signal).all():
            raise ValueError("EDUHK_CLIPS_AUDIO_INVALID")
        regions, threshold = segments(signal, rate, protocol)
        speaker = recording["sourceId"]
        speech_regions[str(speaker)] = {
            "regions": len(regions),
            "threshold": threshold,
            "rate": rate,
        }
        root_map = {
            r["canonicalTaskIndex"]: r
            for r in inventory["roots"]
            if r["speakerId"] == speaker and r["task"] == 1 and r["canonicalTaskIndex"] is not None
        }
        if any(not r["eligibleAdult"] or r["age"] < 18 for r in root_map.values()):
            raise ValueError("EDUHK_CLIPS_NON_ADULT")
        if len(regions) != protocol["expectedTaskItems"]:
            counts["unalignedRecordings"] += 1
            for index in range(40):
                all_candidates.append(
                    {
                        "id": f"eduhk-{speaker:02d}-task1-{index:03d}",
                        "status": "UNALIGNED_TASK_REGION_COUNT",
                        "regions": len(regions),
                    }
                )
            continue
        counts["alignedCandidatesRecordings"] += 1
        import math

        divisor = math.gcd(rate, 16000)
        wav = resample_poly(signal, 16000 // divisor, rate // divisor).astype(np.float32)
        for index, (start_frame, end_frame) in enumerate(regions):
            root = root_map.get(index)
            previous = regions[index - 1][1] * 160 if index else 0
            following = regions[index + 1][0] * 160 if index + 1 < len(regions) else len(wav)
            start = max(0, previous, start_frame * 160 - 640)
            end = min(len(wav), following, end_frame * 160 + 640)
            candidate = {
                "id": f"eduhk-{speaker:02d}-task1-{index:03d}",
                "startSample": start,
                "endSample": end,
                "boundaryVerified": False,
                "sourceAudioSha256": recording["sha256"],
            }
            if root is None or end <= start or end - start > 32000:
                candidate["status"] = "MISSING_METADATA_OR_INVALID_BOUNDARY"
                counts["unavailableCandidates"] += 1
                all_candidates.append(candidate)
                continue
            chunk = wav[start:end]
            if len(chunk) < 2400:
                chunk = np.pad(chunk, (0, 2400 - len(chunk)))
            try:
                quality_check(chunk)
            except AudioRejected as error:
                candidate["status"] = "NUMERIC_AUDIO_UNASSESSABLE:" + str(error)
                counts["numericAudioUnassessable"] += 1
                all_candidates.append(candidate)
                continue
            clip = clips / (candidate["id"] + ".wav")
            clip.write_bytes(encode_wav(chunk))
            candidate["sha256"], candidate["status"] = (
                fingerprint(clip),
                "CANDIDATE_NOT_HUMAN_VERIFIED",
            )
            edits, skipped = replacements(root["annotations"])
            counts.update(skipped)
            component_values = {}
            for component, expected, realized in edits:
                component_values.setdefault(component, set()).add((expected, realized))
            for component, alternatives in component_values.items():
                if len(alternatives) != 1:
                    counts["conflicting_labels"] += 1
                    continue
                expected, realized = next(iter(alternatives))
                if expected not in targets or realized not in targets:
                    counts["outside_baseline_coverage"] += 1
                    continue
                for kind, values, component_label in (
                    ("expected", expected, "source-annotated-error"),
                    ("realized", realized, "source-provided-realized"),
                ):
                    target = targets[values]
                    labels = {k: "ambiguous" for k in COMPONENTS}
                    labels[component] = component_label
                    row = {
                        "id": candidate["id"] + "-" + component + "-" + kind,
                        "syllable": target["id"][3:],
                        **{k: v for k, v in zip(COMPONENTS, values, strict=True)},
                        "file": str(clip.resolve()),
                        "sha256": candidate["sha256"],
                        "split": "train",
                        "speakerId": recording["speakerId"],
                        "voiceFamilyId": recording["speakerId"],
                        "referenceSourceId": recording["speakerId"],
                        "source": SOURCE,
                        "sourceRootId": candidate["id"],
                        "parentSha256": recording["sha256"],
                        "sourceUtteranceId": recording["fileName"],
                        "labelProvenance": (
                            "source-human-explicit-substitution-machine-vad-unverified-boundary"
                        ),
                        "expertLabel": component_label,
                        "componentExpertLabels": labels,
                        "labelPolicyFlags": [],
                        "numericalQualityFlags": [],
                        "alignmentFlags": ["UNVERIFIED_VAD_ORDER"],
                        "placeholder": False,
                        "durationSeconds": len(chunk) / 16000,
                    }
                    generated.append(row)
                    counts["trainingComparisons"] += 1
                counts["annotatedComponents"] += 1
            all_candidates.append(candidate)
        print(json.dumps({"speaker": speaker, "regions": len(regions), **counts}), flush=True)
    counts["uniqueTrainingAudioRoots"] = len({row["sourceRootId"] for row in generated})
    counts["trainingSpeakerIds"] = len({row["speakerId"] for row in generated})
    source_data = {
        "license": data["license"],
        "source": data["source"],
        "dataConfigurationSha256": fingerprint(data_config),
        "metadataSha256": fingerprint(parsed),
        "protocolSha256": fingerprint(CONFIG),
        "generatorSha256": fingerprint(Path(__file__)),
        "sourceRecordingCount": len(data["files"]),
        "counts": dict(counts),
        "speechRegionDiagnostics": speech_regions,
        "candidateRootCount": len(all_candidates),
        "sourceSplit": "train",
        "audioOutsideTrainingDownloaded": False,
        "finalTestRead": False,
        "decoder": {
            "soundfile": sf.__version__,
            "libsndfile": sf.__libsndfile_version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "rootUvLockSha256": fingerprint(ROOT / "uv.lock"),
        },
        "limitation": (
            "Expert listening applies to the task recording; candidate segment ordering "
            "and boundaries have not been independently verified."
        ),
    }
    (output / "candidates.json").write_text(
        json.dumps({"items": all_candidates}, ensure_ascii=False, indent=2) + "\n"
    )
    originals["items"].extend(generated)
    originals["datasetId"] = "ompal-aishell3-eduhk-train-v1"
    originals["license"] = (
        "OMPAL CC BY 4.0; AISHELL-3 Apache-2.0; EdUHK research with acknowledgement"
    )
    originals["eduhkTrainingSource"] = source_data
    originals["counts"]["words"] = len(originals["items"])
    originals["counts"]["bySplit"]["train"] += len(generated)
    (output / "manifest.json").write_text(
        json.dumps(originals, ensure_ascii=False, indent=2) + "\n"
    )
    return source_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("data-config", "parsed", "mixed-manifest", "baseline", "raw-directory", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == "__main__":
    main()
