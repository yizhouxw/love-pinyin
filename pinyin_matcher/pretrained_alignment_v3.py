"""Separate OMPAL boundary experiment; CTC and energy never supply correctness.

The v2 manifests and WAVs remain intact. Only train/calibration parent WAVs are
opened; diagnostic rows retain their existing absolute file references.
"""

import argparse
import copy
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import read_rows, write
from pinyin_matcher.pretrained_ompal_clips import _read_audio

CONFIG = ROOT / "content/pronunciation-pretrained-alignment-v3.json"


def configuration():
    config = json.loads(CONFIG.read_text())
    if config["finalTestUsed"] or config["correctnessLabelsUsedForBoundaries"]:
        raise ValueError("BOUNDARY_EXPERIMENT_POLICY_INVALID")
    return config


def acoustic_boundaries(samples, rows, config=None):
    """Return shared nonoverlapping cuts and evidence, without looking at labels."""
    config = configuration() if config is None else config
    rate = config["sampleRate"]
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all() or not rows:
        raise ValueError("BOUNDARY_AUDIO_INVALID")
    duration = len(samples) / rate
    anchors = []
    for row in rows:
        centers = []
        for head in row.get("alignment", {}).get("heads", {}).values():
            start, end = head.get("startSeconds"), head.get("endSeconds")
            if (
                head.get("available")
                and isinstance(start, (int, float))
                and isinstance(end, (int, float))
                and np.isfinite([start, end]).all()
                and 0 <= start < end <= duration
            ):
                centers.append((start + end) / 2)
        if not centers:
            raise ValueError("BOUNDARY_CTC_ANCHOR_UNAVAILABLE")
        anchors.append(float(np.median(centers)))
    anchors = np.asarray(anchors)
    if np.any(np.diff(anchors) <= 1 / rate):
        raise ValueError("BOUNDARY_CTC_ANCHORS_NOT_MONOTONIC")
    window = round(rate * config["energyWindowMilliseconds"] / 1000)
    hop = round(rate * config["energyHopMilliseconds"] / 1000)
    energy = uniform_filter1d(samples.astype(np.float64) ** 2, window, mode="constant")[::hop]
    times = np.arange(len(energy)) * hop / rate
    interior, evidence = [], []
    inset = (1 - config["interiorSearchFraction"]) / 2
    for left, right in zip(anchors[:-1], anchors[1:], strict=True):
        midpoint = (left + right) / 2
        indices = np.flatnonzero(
            (times >= left + inset * (right - left)) & (times <= right - inset * (right - left))
        )
        cut, method, ratio = midpoint, "midpoint-no-meaningful-valley", None
        if len(indices):
            anchor_energy = float(np.interp([left, right], times, energy).mean())
            if anchor_energy > config["outerAbsoluteEnergy"]:
                relative = energy[indices] / anchor_energy
                distance = abs(times[indices] - midpoint) / ((right - left) / 2)
                choice = int(np.argmin(relative + config["midpointPenalty"] * distance))
                ratio = float(relative[choice])
                if ratio <= config["maximumValleyToAnchorEnergyRatio"]:
                    cut, method = float(times[indices[choice]]), "acoustic-energy-valley"
        interior.append(cut)
        evidence.append({"cutSeconds": cut, "method": method, "valleyToAnchorEnergyRatio": ratio})

    def outer(anchor, before):
        lower = max(0, anchor - config["outerSearchSeconds"]) if before else anchor
        upper = anchor if before else min(duration, anchor + config["outerSearchSeconds"])
        indices = np.flatnonzero((times >= lower) & (times <= upper))
        if not len(indices):
            return lower if before else upper
        threshold = max(
            float(np.quantile(energy[indices], 0.95)) * config["outerRelativeEnergy"],
            config["outerAbsoluteEnergy"],
        )
        active = indices[energy[indices] > threshold]
        if not len(active):
            return lower if before else upper
        margin = config["outerMarginMilliseconds"] / 1000
        return (
            max(lower, times[active[0]] - margin)
            if before
            else min(upper, times[active[-1]] + margin)
        )

    cuts = np.r_[outer(anchors[0], True), interior, outer(anchors[-1], False)]
    positions = np.rint(cuts * rate).astype(int)
    positions = np.clip(positions, 0, len(samples))
    if np.any(np.diff(positions) <= 0):
        raise ValueError("BOUNDARY_EMPTY_PARTITION")
    return positions, {
        "anchorSeconds": anchors.tolist(),
        "interiorCuts": evidence,
        "outerCutSeconds": [float(cuts[0]), float(cuts[-1])],
        "correctnessFromAlignment": False,
    }


def clip_audio(samples, start, end, config):
    clip = samples[start:end].copy()
    count = len(clip)
    rate = config["sampleRate"]
    rms = float(np.sqrt(np.mean(clip**2)))
    flags = []
    if count < rate * config["minimumAcousticSeconds"]:
        flags.append("ACOUSTIC_CONTENT_UNDER_80MS")
    if count > rate * config["maximumClipSeconds"]:
        flags.append("WORD_CLIP_OVER_FOUR_SECONDS")
    if rms < 1e-5:
        flags.append("NO_AUDIO_ENERGY")
    if float(np.mean(abs(clip) >= 0.99)) > 0.05:
        flags.append("CLIPPED_AUDIO")
    padding = max(0, round(rate * config["minimumClipSeconds"]) - count)
    left, right = padding // 2, padding - padding // 2
    return (
        np.pad(clip, (left, right)),
        {
            "startSample": int(start),
            "endSample": int(end),
            "startSeconds": start / rate,
            "endSeconds": end / rate,
            "originalDurationSeconds": count / rate,
            "zeroPadLeftSamples": left,
            "zeroPadRightSamples": right,
            "placeholder": False,
            "rms": rms,
        },
        flags,
    )


def prepare(manifest, output):
    if output.exists():
        raise ValueError("BOUNDARY_OUTPUT_ALREADY_EXISTS")
    original = json.loads(manifest.read_text())
    if original.get("frozenTestIncluded") or any(r["split"] == "test" for r in original["items"]):
        raise ValueError("BOUNDARY_EXPERIMENT_FORBIDS_FINAL_TEST")
    rows = read_rows(manifest)
    config = configuration()
    grouped = defaultdict(list)
    for row in rows:
        if row["split"] in {"train", "calibration"}:
            grouped[row["sourceUtteranceId"]].append(row)
    result = {r["id"]: copy.deepcopy(r) for r in rows}
    output.mkdir(parents=True)
    (output / "clips").mkdir()
    fallback, modes = Counter(), Counter()
    for source_id, group in grouped.items():
        group.sort(key=lambda r: r["index"])
        parents = {(r["parentFile"], r["parentSha256"], r["split"]) for r in group}
        if len(parents) != 1:
            raise ValueError("BOUNDARY_PARENT_IDENTITY_INCONSISTENT")
        path, expected, _ = next(iter(parents))
        if fingerprint(Path(path)) != expected:
            raise ValueError("BOUNDARY_PARENT_DIGEST_MISMATCH")
        samples = _read_audio(Path(path))
        try:
            cuts, evidence = acoustic_boundaries(samples, group, config)
        except ValueError as error:
            fallback[str(error)] += len(group)
            for row in group:
                result[row["id"]]["boundaryV3"] = {
                    "applied": False,
                    "reason": str(error),
                    "retainedV2": True,
                }
            continue
        modes.update(item["method"] for item in evidence["interiorCuts"])
        for index, row in enumerate(group):
            new = result[row["id"]]
            clip, bounds, flags = clip_audio(samples, cuts[index], cuts[index + 1], config)
            destination = output / "clips" / (row["id"] + ".wav")
            destination.write_bytes(encode_wav(clip))
            new.update(
                {
                    "file": str(destination.relative_to(output)),
                    "sha256": fingerprint(destination),
                    "bounds": bounds,
                    "numericalQualityFlags": flags,
                    "placeholder": False,
                    "durationSeconds": len(clip) / config["sampleRate"],
                    "boundaryV3": {
                        "applied": True,
                        "sourceUtteranceId": source_id,
                        "previousBounds": row["bounds"],
                        "previousNumericalQualityFlags": row.get("numericalQualityFlags", []),
                        "previousClipSha256": row["sha256"],
                        "anchorSeconds": evidence["anchorSeconds"][index],
                        "leftCut": evidence["interiorCuts"][index - 1] if index else None,
                        "rightCut": evidence["interiorCuts"][index]
                        if index < len(group) - 1
                        else None,
                        "correctnessFromAlignment": False,
                    },
                }
            )
    output_rows = [result[r["id"]] for r in rows]
    report = {
        **{k: v for k, v in original.items() if k not in {"items", "counts"}},
        "version": config["version"],
        "sourceManifestSha256": fingerprint(manifest),
        "configurationSha256": fingerprint(CONFIG),
        "pipelineSha256": fingerprint(Path(__file__)),
        "boundaryPolicy": (
            "Median CTC event anchors; acoustic energy valley partitions; "
            "bounded outer envelope. Not phonetic truth."
        ),
        "counts": {
            "words": len(output_rows),
            "bySplit": dict(Counter(r["split"] for r in output_rows)),
            "resegmented": sum(r.get("boundaryV3", {}).get("applied", False) for r in output_rows),
            "fallbackRetainedV2": dict(fallback),
            "interiorCutMethods": dict(modes),
            "numericallyFlagged": sum(bool(r.get("numericalQualityFlags")) for r in output_rows),
            "policyFlagged": sum(bool(r.get("labelPolicyFlags")) for r in output_rows),
        },
        "items": output_rows,
    }
    write(output / "manifest.json", report)
    return {k: v for k, v in report.items() if k != "items"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manifest, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
