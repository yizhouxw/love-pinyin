"""Explicit research-only download of fixed adult EdUHK training recordings."""

import argparse
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pinyin_matcher.catalog import fingerprint

PARSED_SHA = "23e6e45a02f5c0c2f402a238f456c69d2ce4cb929479bc86784e47eb6b9efb34"
AUDIT_SHA = "d1a3654ea634e0933aed56d60717b877553aae1a866c17c3102c4de582aa5ef4"
TRAIN = [38, 6, 7, 37, 35, 20, 24, 22, 14, 5, 10, 19, 30, 31, 27, 26]
CALIBRATION = [36, 18, 40, 32, 13, 16, 39, 29, 1, 15, 9, 21]
BLIND = [11, 4, 12, 8, 28, 17, 3, 2, 33, 34]
ABOUT = "https://lml-elearning.eduhk.hk/about_g.aspx"
BASE = "https://lml-elearning.eduhk.hk/audio/record/"


def request(url, *, method="GET", headers=None):
    headers = {"User-Agent": "LovePinyinResearch/1.0", **(headers or {})}
    with urllib.request.urlopen(
        urllib.request.Request(url, method=method, headers=headers), timeout=60
    ) as response:
        return response.read() if method == "GET" else None, dict(response.headers.items())


def snapshot(parsed, audit, directory, output_config):
    if output_config.exists():
        raise ValueError("EDUHK_CONFIG_OUTPUT_EXISTS")
    if fingerprint(parsed) != PARSED_SHA or fingerprint(audit) != AUDIT_SHA:
        raise ValueError("EDUHK_SOURCE_METADATA_CHANGED")
    data = json.loads(parsed.read_text())
    splits = data["splitProposal"]
    audit_data = json.loads(audit.read_text())
    if (
        splits != {"train": TRAIN, "calibration": CALIBRATION, "new_blind": BLIND}
        or audit_data["preAudioSplitProposal"]["allocation"] != splits
        or audit_data["preAudioSplitProposal"]["seed"] != 3182026
    ):
        raise ValueError("EDUHK_SPEAKER_SPLIT_CHANGED")
    roots = [r for r in data["roots"] if r["task"] == 1 and r["speakerId"] in TRAIN]
    if any(not r["eligibleAdult"] or r["age"] < 18 for r in roots):
        raise ValueError("EDUHK_NON_ADULT_TRAIN_ROOT")
    urls = {}
    for row in roots:
        expected = BASE + f"T{row['speakerId']}_T1.mp3"
        if row["sourceAudioUrl"] != expected:
            raise ValueError("EDUHK_AUDIO_SOURCE_CHANGED")
        urls[row["speakerId"]] = expected
    if set(urls) != set(TRAIN):
        raise ValueError("EDUHK_TRAIN_INVENTORY_INCOMPLETE")
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / "raw"
    raw.mkdir(exist_ok=True)
    records = []
    for speaker in TRAIN:
        url = urls[speaker]
        _, headers = request(url, method="HEAD")
        length = int(headers.get("Content-Length", 0))
        if length <= 0 or length > 10_000_000:
            raise ValueError("EDUHK_SOURCE_LENGTH_INVALID")
        records.append(
            {
                "speakerId": f"eduhk-{speaker:02d}",
                "sourceId": speaker,
                "url": url,
                "bytes": length,
                "etag": headers.get("ETag"),
                "lastModified": headers.get("Last-Modified"),
                "split": "train",
            }
        )
    plan = {
        "schemaVersion": 1,
        "metadataSha256": PARSED_SHA,
        "auditSha256": AUDIT_SHA,
        "source": ABOUT,
        "license": "Research use with suitable acknowledgement; product rights not verified.",
        "seed": 3182026,
        "trainingSpeakers": TRAIN,
        "withheldCalibrationSpeakers": CALIBRATION,
        "withheldBlindSpeakers": BLIND,
        "files": records,
        "audioOutsideTrainingDownloaded": False,
    }
    (directory / "download-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    )

    def acquire(record):
        path = raw / f"T{record['sourceId']}_T1.mp3"
        headers = {"If-Match": record["etag"]} if record["etag"] else {}
        payload, response = request(record["url"], headers=headers)
        if len(payload) != record["bytes"] or (
            record["etag"] and response.get("ETag") != record["etag"]
        ):
            raise ValueError("EDUHK_SOURCE_REVISION_CHANGED")
        sha = hashlib.sha256(payload).hexdigest()
        if path.exists() and fingerprint(path) != sha:
            raise ValueError("EDUHK_EXISTING_AUDIO_CHANGED")
        if not path.exists():
            path.write_bytes(payload)
        return {**record, "sha256": sha, "fileName": path.name}

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(acquire, records))
    plan["files"] = files
    plan["metadataSourceUrl"] = (
        "https://lml-elearning.eduhk.hk/ViewTaskOneAndTwo_g.aspx?id={speakerId}"
    )
    plan["retrievalMethod"] = (
        "HEAD-pinned ETag and size followed by explicit GET and SHA256; train Task1 only."
    )
    output_config.parent.mkdir(parents=True, exist_ok=True)
    with output_config.open("x") as stream:
        stream.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    (directory / "manifest.json").write_text(
        json.dumps(
            {**plan, "configurationSha256": fingerprint(output_config)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return {
        "recordings": len(files),
        "bytes": sum(f["bytes"] for f in files),
        "configurationSha256": fingerprint(output_config),
    }


def prepare(config, directory):
    data = json.loads(config.read_text())
    if (
        data["trainingSpeakers"] != TRAIN
        or data["withheldCalibrationSpeakers"] != CALIBRATION
        or data["withheldBlindSpeakers"] != BLIND
        or data["metadataSha256"] != PARSED_SHA
        or [r["sourceId"] for r in data["files"]] != TRAIN
        or data["audioOutsideTrainingDownloaded"] is not False
    ):
        raise ValueError("EDUHK_PINNED_SOURCE_INVALID")
    directory.mkdir(parents=True, exist_ok=True)
    for record in data["files"]:
        if (
            record["url"] != BASE + f"T{record['sourceId']}_T1.mp3"
            or record["split"] != "train"
            or record["fileName"] != f"T{record['sourceId']}_T1.mp3"
            or record["speakerId"] != f"eduhk-{record['sourceId']:02d}"
        ):
            raise ValueError("EDUHK_PINNED_URL_INVALID")
        path = directory / "raw" / record["fileName"]
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            payload, _ = request(record["url"])
            if hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError("EDUHK_SOURCE_SHA_MISMATCH")
            path.write_bytes(payload)
        if fingerprint(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise ValueError("EDUHK_LOCAL_AUDIO_SHA_MISMATCH")
    return {"recordings": len(data["files"]), "configurationSha256": fingerprint(config)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    first = commands.add_parser("snapshot")
    for key in ("parsed", "audit", "directory", "output-config"):
        first.add_argument("--" + key, type=Path, required=True)
    replay = commands.add_parser("prepare")
    for key in ("config", "directory"):
        replay.add_argument("--" + key, type=Path, required=True)
    args = vars(parser.parse_args())
    action = args.pop("action")
    print(json.dumps((snapshot if action == "snapshot" else prepare)(**args), ensure_ascii=False))


if __name__ == "__main__":
    main()
