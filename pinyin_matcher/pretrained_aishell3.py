"""Explicit, pinned AISHELL-3 acquisition for supplementary training only.

This module is an offline preparation command, never imported by inference.
Provided realized pinyin is retained; no Hanzi-to-pinyin conversion is performed.
"""

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import wave
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import write

CONFIG = ROOT / "content/pronunciation-aishell3-data.json"
PARSER_VERSION = "aishell3-provided-alternating-pinyin-v1"


def parse_content(text):
    result = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        name, separator, content = line.partition("\t")
        values = content.split()
        if (
            not separator
            or not re.fullmatch(r"SSB\d+\.wav", name)
            or not values
            or len(values) % 2
            or name in result
            or any(not re.fullmatch(r"[a-z]+[1-5]", p) for p in values[1::2])
        ):
            raise ValueError("AISHELL_PINYIN_SOURCE_INVALID")
        result[name] = {
            "pinyin": values[1::2],
            "lineSha256": hashlib.sha256(line.encode()).hexdigest(),
        }
    return result


def resource_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("AISHELL_RESOURCE_PATH_INVALID")
    return path


def fetch_verified(url, record, destination, *, opener=None):
    """Bound the response, verify its identity, then atomically install it."""
    expected = record["sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or record["bytes"] <= 0:
        raise ValueError("AISHELL_RESOURCE_IDENTITY_INVALID")
    if destination.exists():
        if destination.stat().st_size != record["bytes"] or fingerprint(destination) != expected:
            raise ValueError("AISHELL_EXISTING_RESOURCE_CORRUPT")
        return {"status": "verified-existing", "bytes": record["bytes"]}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "love-pinyin-data-preparation/1"})
    opener = urllib.request.urlopen if opener is None else opener
    digest, received = hashlib.sha256(), 0
    with opener(request, timeout=30) as response, temporary.open("wb") as output:
        while chunk := response.read(min(1024 * 1024, record["bytes"] + 1 - received)):
            received += len(chunk)
            if received > record["bytes"]:
                raise ValueError("AISHELL_RESOURCE_TOO_LARGE")
            output.write(chunk)
            digest.update(chunk)
    if received != record["bytes"] or digest.hexdigest() != expected:
        raise ValueError("AISHELL_RESOURCE_DIGEST_MISMATCH")
    temporary.replace(destination)
    return {"status": "downloaded-verified", "bytes": received}


def verify_pinyin(record, source):
    item = source.get(Path(record["path"]).name)
    if item is None:
        raise ValueError("AISHELL_PINYIN_SOURCE_MISSING")
    if ("pinyin" in record and item["pinyin"] != record["pinyin"]) or item["lineSha256"] != record[
        "pinyinSourceLineSha256"
    ]:
        raise ValueError("AISHELL_PINYIN_SOURCE_MISMATCH")
    return item["pinyin"]


def audio_header(path):
    with wave.open(str(path), "rb") as audio:
        if audio.getcomptype() != "NONE" or audio.getnframes() <= 0:
            raise ValueError("AISHELL_AUDIO_HEADER_INVALID")
        return {
            "sampleRate": audio.getframerate(),
            "channels": audio.getnchannels(),
            "sampleWidthBytes": audio.getsampwidth(),
            "frames": audio.getnframes(),
            "durationSeconds": audio.getnframes() / audio.getframerate(),
        }


def prepare(output, *, config_path=CONFIG, workers=4):
    if not 1 <= workers <= 8:
        raise ValueError("AISHELL_WORKERS_OUT_OF_BOUNDS")
    config = json.loads(config_path.read_text())
    if (
        not re.fullmatch(r"[a-f0-9]{40}", config["revision"])
        or config.get("parserVersion") != PARSER_VERSION
        or config["selection"]["calibrationOrFinalTestUsed"]
        or any(
            r["split"] != "train"
            or r["sourceSplit"] != "train"
            or not r["path"].startswith("train/wav/")
            for r in config["files"]
        )
        or len({r["id"] for r in config["files"]}) != len(config["files"])
    ):
        raise ValueError("AISHELL_TRAINING_ONLY_POLICY_VIOLATION")
    identity = fingerprint(config_path)
    output.mkdir(parents=True, exist_ok=True)
    identity_path = output / "source.json"
    if identity_path.exists() and json.loads(identity_path.read_text())["configSha256"] != identity:
        raise ValueError("AISHELL_SOURCE_CONFIG_CHANGED")
    write(identity_path, {"configSha256": identity, "revision": config["revision"]})
    base = config["downloadBase"] + config["revision"] + "/"
    metadata = []
    for record in config["metadataFiles"]:
        destination = resource_path(output / "metadata", record["localName"])
        status = fetch_verified(base + record["path"], record, destination)
        data = destination.read_bytes()
        git_sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if git_sha != record["gitBlobId"]:
            raise ValueError("AISHELL_METADATA_GIT_BLOB_MISMATCH")
        metadata.append({"path": record["path"], "sha256": record["sha256"], **status})
    pinyin = parse_content((output / "metadata/train-content.txt").read_text())
    records = [{**r, "pinyin": verify_pinyin(r, pinyin)} for r in config["files"]]
    started = time.perf_counter()

    def download(record):
        destination = resource_path(output / "raw", record["path"])
        for attempt in range(2):
            try:
                state = fetch_verified(base + record["path"], record, destination)
                return {
                    **record,
                    **state,
                    "file": str(destination),
                    "audio": audio_header(destination),
                }
            except (OSError, ValueError, wave.Error) as error:
                if isinstance(error, ValueError) or attempt == 1:
                    return {**record, "status": "failed", "error": str(error)}
                time.sleep(0.5)

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(download, record) for record in records]
        for future in as_completed(futures):
            result = future.result()
            results[result["id"]] = result
            if len(results) % 25 == 0:
                print(
                    json.dumps(
                        {
                            "completed": len(results),
                            "planned": len(config["files"]),
                            "failed": sum(r["status"] == "failed" for r in results.values()),
                            "elapsedSeconds": time.perf_counter() - started,
                        }
                    ),
                    flush=True,
                )
    ordered = [results[r["id"]] for r in config["files"]]
    successful = [r for r in ordered if r["status"] != "failed"]
    report = {
        "schemaVersion": 1,
        "datasetId": config["datasetId"],
        "configSha256": identity,
        "revision": config["revision"],
        "license": config["license"],
        "licenseSources": config["licenseSources"],
        "citation": config["citation"],
        "annotation": config["annotation"],
        "pipelineSha256": fingerprint(Path(__file__)),
        "trainingOnly": True,
        "workers": workers,
        "finalTestRead": False,
        "metadata": metadata,
        "complete": len(successful) == len(ordered),
        "plannedFiles": len(ordered),
        "verifiedFiles": len(successful),
        "failedFiles": len(ordered) - len(successful),
        "verifiedBytes": sum(r["bytes"] for r in successful),
        "durationSeconds": sum(r["audio"]["durationSeconds"] for r in successful),
        "speakerCount": len({r["speakerId"] for r in successful}),
        "toneCounts": dict(Counter(p[-1] for r in successful for p in r["pinyin"])),
        "distinctPinyinSyllables": len({p for r in successful for p in r["pinyin"]}),
        "elapsedSeconds": time.perf_counter() - started,
        "previousAcquisitionRuns": [
            {
                "file": str(path),
                "sha256": fingerprint(path),
                **{
                    key: value
                    for key, value in json.loads(path.read_text()).items()
                    if key != "records"
                },
            }
            for path in sorted(output.glob("acquisition-*-interrupted.json"))
        ],
        "files": ordered,
    }
    write(output / "manifest.json", report)
    return {k: v for k, v in report.items() if k != "files"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    report = prepare(args.output, workers=args.workers)
    print(json.dumps(report, ensure_ascii=False))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
