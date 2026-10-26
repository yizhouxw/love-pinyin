"""Explicit preparation of pinned, speaker-isolated real adult Mandarin data.

ManDi word labels describe intended corpus readings, not expert judgments that
all pronunciation components are correct. MFA intervals are preserved for audit;
wide neighboring-word windows prevent bad short alignments from clipping speech.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from pathlib import Path

import numpy as np
from scipy.signal import convolve, resample_poly

from .audio import encode_wav
from .catalog import ROOT, fingerprint

CONFIG = ROOT / "content/pronunciation-pretrained-data.json"
OSF_ROOT = "https://api.osf.io/v2/nodes/fgv4w/files/osfstorage/"
FOLDERS = {
    "wav": "61e1eee8c99ebd0387018081",
    "grid": "61e1eed295a0300336ed42be",
    "lexicon": "61e1f09353349e03345f9617",
}
SOURCE = "mandi-cmn-wl1"


def fetch_bytes(url: str) -> bytes:
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (OSError, TimeoutError, HTTPException) as error:
            last = error
    raise RuntimeError(f"PUBLIC_DATA_DOWNLOAD_FAILED: {url}") from last


def list_folder(folder: str) -> list[dict]:
    url = f"{OSF_ROOT}{folder}/?page%5Bsize%5D=100"
    result = []
    while url:
        data = json.loads(fetch_bytes(url))
        result.extend(data["data"])
        url = data["links"]["next"]
    return result


def locked_file(item: dict) -> dict:
    attr = item["attributes"]
    sha = attr["extra"]["hashes"]["sha256"]
    if not sha:
        raise ValueError("UPSTREAM_DATA_SHA_MISSING")
    return {
        "name": attr["name"],
        "fileId": item["id"],
        "version": attr["current_version"],
        "bytes": attr["size"],
        "sha256": sha,
        "url": f"{item['links']['download']}?version={attr['current_version']}",
        "modified": attr["date_modified"],
    }


def assign_speakers(speakers: list[str]) -> dict[str, str]:
    """Freeze speaker grouping before looking at audio/model outputs."""
    ordered = sorted(speakers, key=lambda s: hashlib.sha256(f"mandi-v1:{s}".encode()).hexdigest())
    if len(ordered) != 26:
        raise ValueError("MANDI_EXPECTED_26_ANNOTATED_SPEAKERS")
    return {
        speaker: "train" if i < 16 else "calibration" if i < 20 else "test"
        for i, speaker in enumerate(ordered)
    }


def snapshot(output: Path) -> dict:
    """Explicit network metadata snapshot; never silently change an old lock."""
    if output.exists():
        raise ValueError("DATA_SNAPSHOT_ALREADY_EXISTS")
    with ThreadPoolExecutor(max_workers=3) as pool:
        wavs, grids, lexicons = list(pool.map(list_folder, FOLDERS.values()))
    wavs = [x for x in wavs if x["attributes"]["name"].endswith("_CMN_WL1.wav")]
    grid_map = {x["attributes"]["name"]: x for x in grids}
    missing = [
        locked_file(x)
        for x in wavs
        if x["attributes"]["name"].removesuffix(".wav") + ".TextGrid" not in grid_map
    ]
    wavs = [
        x for x in wavs if x["attributes"]["name"].removesuffix(".wav") + ".TextGrid" in grid_map
    ]
    speakers = [x["attributes"]["name"].removesuffix("_CMN_WL1.wav") for x in wavs]
    assignments = assign_speakers(speakers)
    recordings = []
    for wav in sorted(wavs, key=lambda x: x["attributes"]["name"]):
        name = wav["attributes"]["name"]
        speaker = name.removesuffix("_CMN_WL1.wav")
        grid = grid_map.get(name.removesuffix(".wav") + ".TextGrid")
        if grid is None:
            raise ValueError(f"MANDI_WORD_GRID_MISSING:{speaker}")
        recordings.append(
            {
                "speakerId": speaker,
                "split": assignments[speaker],
                "wav": locked_file(wav),
                "grid": locked_file(grid),
            }
        )
    lexicon = next(x for x in lexicons if x["attributes"]["name"] == "mandarin_wl1.txt")
    labels = json.loads((ROOT / "content/pronunciation-mandi-labels.json").read_text())["labels"]
    result = {
        "schemaVersion": 1,
        "datasetId": SOURCE,
        "snapshotDate": "2026-10-26",
        "source": "https://osf.io/fgv4w/",
        "license": "CC-BY-NC-3.0",
        "licenseUrl": "https://creativecommons.org/licenses/by-nc/3.0/",
        "citation": (
            "Liang Zhao and Eleanor Chodroff. 2022. The ManDi Corpus: A Spoken Corpus of"
            " Mandarin Regional Dialects. LREC 2022, pp. 1985-1990."
        ),
        "paper": "https://aclanthology.org/2022.lrec-1.213/",
        "labelProvenance": (
            "Native adult reading of the corpus Standard Mandarin WL1 task; intended "
            "phonetic lexicon labels, MFA word/phone boundaries; not independently "
            "expert-verified segment/tone correctness."
        ),
        "splitPolicy": (
            "SHA256(mandi-v1:speakerId) ordering before model/audio inspection; first16 "
            "train, next4 calibration, remaining6 frozen test; 10 of36 recordings lack "
            "public word grids, so allocation reduced before downloading audio; never "
            "split recordings of same speaker."
        ),
        "frozenTestPolicy": (
            "Preparation excludes test audio unless --include-frozen-test. Freeze all "
            "model and calibration parameters before opening this cohort. After any "
            "diagnostic use, reserve a new external cohort for further acceptance."
        ),
        "coverage": (
            "Lexicon has 11 syllables x four lexical tones; observed train/calibration "
            "recordings contain 10 bases x four tones, with cai1-4 absent. Native adult "
            "speakers with regional "
            "Mandarin backgrounds performing the CMN task. No children, lexical neutral "
            "tones, tone sandhi, isolated initial/final tasks, or broad minimal "
            "segmental pairs."
        ),
        "lexicon": locked_file(lexicon),
        "labels": labels,
        "nonLexicalWordLabels": ["sounding"],
        "recordings": recordings,
        "unavailableAnnotations": missing,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def parse_textgrid(text: str) -> dict[str, list[dict]]:
    """Parse the long text TextGrid form used in the pinned corpus."""
    tiers = {}
    for block in re.split(r"\n\s*item \[\d+\]:", text)[1:]:
        name = re.search(r'name = "((?:[^"]|"")*)"', block)
        if name is None:
            continue
        intervals = []
        for part in re.split(r"intervals \[\d+\]:", block)[1:]:
            match = re.search(
                r'xmin = ([\d.eE+-]+)\s+xmax = ([\d.eE+-]+)\s+text = "((?:[^"]|"")*)"', part
            )
            if not match:
                raise ValueError("TEXTGRID_INTERVAL_INVALID")
            start, end = float(match[1]), float(match[2])
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
                raise ValueError("TEXTGRID_INTERVAL_INVALID")
            intervals.append({"start": start, "end": end, "label": match[3].replace('""', '"')})
        tiers[name[1]] = intervals
    if "words" not in tiers or "phones" not in tiers:
        raise ValueError("MANDI_TEXTGRID_TIERS_MISSING")
    return tiers


def word_windows(
    tiers: dict, labels: dict, duration: float, nonlexical: tuple[str, ...] = ()
) -> list[dict]:
    words = [x for x in tiers["words"] if x["label"] not in ("", "sil", "spn", "<unk>")]
    if any(x["label"] not in labels and x["label"] not in nonlexical for x in words):
        raise ValueError("MANDI_WORD_LABEL_UNKNOWN")
    centers = [(x["start"] + x["end"]) / 2 for x in words]
    result = []
    for i, word in enumerate(words):
        if word["label"] in nonlexical:
            continue
        # MFA can produce 30ms words; midpoint context safely contains the full
        # utterance without claiming that its forced-aligned boundary is correct.
        left = (centers[i - 1] + centers[i]) / 2 if i else 0
        right = (centers[i] + centers[i + 1]) / 2 if i + 1 < len(words) else duration
        phones = [
            x for x in tiers["phones"] if x["end"] > word["start"] and x["start"] < word["end"]
        ]
        result.append(
            {
                "wordIndex": i,
                "wordInterval": word,
                "phoneIntervals": phones,
                "windowStart": left,
                "windowEnd": right,
            }
        )
    return result


def download_locked(entry: dict, directory: Path) -> Path:
    path = directory / entry["name"]
    if path.exists():
        if fingerprint(path) != entry["sha256"]:
            raise ValueError(f"PINNED_DATA_DIGEST_MISMATCH:{path}")
        return path
    payload = fetch_bytes(entry["url"])
    if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
        raise ValueError(f"UPSTREAM_DATA_DIGEST_MISMATCH:{entry['name']}")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def read_recording(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(path.read_bytes()), "rb") as reader:
        if reader.getsampwidth() != 2 or reader.getcomptype() != "NONE":
            raise ValueError("MANDI_WAV_PCM16_REQUIRED")
        channels, rate = reader.getnchannels(), reader.getframerate()
        samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(
            np.float32
        )
        samples = samples.reshape(-1, channels).mean(axis=1) / 32768
    return samples, rate


def trim_corpus_window(samples: np.ndarray, anchor_seconds: float) -> tuple[np.ndarray, dict]:
    """Energy component around the corpus word anchor, never model predictions.

    Preserve 80ms on both sides for quiet initial consonants; short internal gaps
    join creaky or interrupted voicing. Every waveform is retained with flags.
    """
    energy = convolve(samples * samples, np.ones(320) / 320, mode="same")
    threshold = max(float(energy.max()) * 0.015, float(np.percentile(energy, 20)) * 16, 4e-6)
    active = np.flatnonzero(energy > threshold)
    flags = []
    if not len(active):
        return samples, {
            "startSample": 0,
            "endSample": len(samples),
            "flags": ["NO_ENERGY_COMPONENT"],
            "energyThreshold": threshold,
        }
    boundaries = np.flatnonzero(np.diff(active) > 1920) + 1
    groups = np.split(active, boundaries)
    anchor = round(anchor_seconds * 16000)

    def distance(group):
        return max(int(group[0]) - anchor, anchor - int(group[-1]), 0)

    selected = min(groups, key=distance)
    separation = distance(selected) / 16000
    if separation > 0.5:
        flags.append("ENERGY_COMPONENT_FAR_FROM_WORD_ANCHOR")
    start, end = max(0, int(selected[0]) - 1280), min(len(samples), int(selected[-1]) + 1281)
    duration = (end - start) / 16000
    if not 0.15 <= duration <= 4:
        flags.append("DURATION_OUTSIDE_PREDECLARED_015_TO_4_SECONDS")
    return samples[start:end], {
        "startSample": start,
        "endSample": end,
        "flags": flags,
        "anchorDistanceSeconds": separation,
        "energyThreshold": threshold,
        "energyComponents": len(groups),
    }


def prepare(
    config_path: Path,
    directory: Path,
    *,
    include_frozen_test: bool = False,
    frozen_plan: Path | None = None,
) -> dict:
    config = json.loads(config_path.read_text())
    if include_frozen_test:
        from pinyin_matcher.pretrained_freeze import verify_plan

        verify_plan(frozen_plan, source_config=config_path)
    selected = [r for r in config["recordings"] if include_frozen_test or r["split"] != "test"]
    entries = [config["lexicon"]] + [r[k] for r in selected for k in ("wav", "grid")]
    raw = directory / "raw"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda x: download_locked(x, raw), entries))
    items, diagnostics = [], []
    for recording in selected:
        samples, rate = read_recording(raw / recording["wav"]["name"])
        tiers = parse_textgrid((raw / recording["grid"]["name"]).read_text())
        windows = word_windows(
            tiers, config["labels"], len(samples) / rate, tuple(config["nonLexicalWordLabels"])
        )
        counts = {}
        for window in windows:
            char = window["wordInterval"]["label"]
            counts[char] = counts.get(char, 0) + 1
            item_id = f"{SOURCE}-{recording['speakerId']}-{window['wordIndex']:03d}"
            start = max(0, round(window["windowStart"] * rate))
            end = min(len(samples), round(window["windowEnd"] * rate))
            wave_samples = samples[start:end]
            divisor = math.gcd(rate, 16000)
            converted = resample_poly(wave_samples, 16000 // divisor, rate // divisor).astype(
                np.float32
            )
            anchor = (
                window["wordInterval"]["start"] + window["wordInterval"]["end"]
            ) / 2 - start / rate
            converted, trim = trim_corpus_window(converted, anchor)
            path = directory / "clips" / recording["split"] / f"{item_id}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encode_wav(converted))
            items.append(
                {
                    "id": item_id,
                    "file": str(path.resolve()),
                    "sha256": fingerprint(path),
                    "split": recording["split"],
                    "speakerId": recording["speakerId"],
                    "voiceFamilyId": recording["speakerId"],
                    "referenceSourceId": recording["speakerId"],
                    "source": SOURCE,
                    "labelProvenance": config["labelProvenance"],
                    "corpusCharacter": char,
                    **config["labels"][char],
                    "durationSeconds": len(converted) / 16000,
                    "numericalQualityFlags": trim["flags"],
                    "parentSha256": recording["wav"]["sha256"],
                    "parentFile": recording["wav"]["name"],
                    "annotationSha256": recording["grid"]["sha256"],
                    "extraction": {
                        **window,
                        "method": "neighbor-word-midpoints+anchor-energy-component-trim80ms-v2",
                        "trim": trim,
                        "clipStartSeconds": start / rate + trim["startSample"] / 16000,
                        "clipEndSeconds": start / rate + trim["endSample"] / 16000,
                    },
                }
            )
        diagnostics.append(
            {
                "speakerId": recording["speakerId"],
                "wordCount": len(windows),
                "labelCounts": counts,
                "missingLabels": sorted(set(config["labels"]) - set(counts)),
                "nonLexicalIntervals": [
                    x for x in tiers["words"] if x["label"] in config["nonLexicalWordLabels"]
                ],
            }
        )
    result = {
        "schemaVersion": 1,
        "source": SOURCE,
        "configSha256": fingerprint(config_path),
        "license": config["license"],
        "citation": config["citation"],
        "frozenTestIncluded": include_frozen_test,
        "frozenPlanSha256": fingerprint(frozen_plan) if include_frozen_test else None,
        "reservedSpeakers": [r["speakerId"] for r in config["recordings"] if r["split"] == "test"],
        "items": items,
        "recordingDiagnostics": diagnostics,
    }
    manifest = directory / (
        "manifest-with-frozen-test.json"
        if include_frozen_test
        else "manifest-train-calibration.json"
    )
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def frozen_annotations(config: dict, raw: Path) -> tuple[list[dict], list[Path]]:
    """Public TextGrid labels only; download no reserved waveform."""
    inventory, files = [], []
    for recording in config["recordings"]:
        if recording["split"] != "test":
            continue
        path = download_locked(recording["grid"], raw)
        files.append(path)
        tiers = parse_textgrid(path.read_text())
        # Word-index policy is identical to word_windows; duration affects only
        # extraction edges, never this pre-audio label/root inventory.
        duration = max(interval["end"] for interval in tiers["words"])
        for window in word_windows(
            tiers, config["labels"], duration, tuple(config["nonLexicalWordLabels"])
        ):
            char = window["wordInterval"]["label"]
            inventory.append(
                {
                    "id": f"{SOURCE}-{recording['speakerId']}-{window['wordIndex']:03d}",
                    "speakerId": recording["speakerId"],
                    "corpusCharacter": char,
                    "parentSha256": recording["wav"]["sha256"],
                    "annotationSha256": recording["grid"]["sha256"],
                    **config["labels"][char],
                }
            )
    return inventory, files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--output", type=Path, default=CONFIG)
    prep = sub.add_parser("prepare")
    prep.add_argument("--config", type=Path, default=CONFIG)
    prep.add_argument("--directory", type=Path, default=ROOT / "private/pretrained-matcher/data")
    prep.add_argument("--include-frozen-test", action="store_true")
    prep.add_argument("--frozen-plan", type=Path)
    args = parser.parse_args()
    data = (
        snapshot(args.output)
        if args.command == "snapshot"
        else prepare(
            args.config,
            args.directory,
            include_frozen_test=args.include_frozen_test,
            frozen_plan=args.frozen_plan,
        )
    )
    print(
        json.dumps(
            {
                "recordings": len(data.get("recordings", [])),
                "items": len(data.get("items", [])),
                "frozenTestIncluded": data.get("frozenTestIncluded", False),
            }
        )
    )


if __name__ == "__main__":
    main()
