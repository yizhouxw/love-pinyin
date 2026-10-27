"""Explicit, digest-checked installation; never imported by inference."""

import argparse
import json
import time
from pathlib import Path

import requests

from pinyin_matcher.catalog import ROOT, fingerprint

REGISTRY = ROOT / "content/pronunciation-pretrained-models.json"


def prepare(name: str, destination: Path | None = None) -> dict:
    record = json.loads(REGISTRY.read_text())["models"][name]
    directory = destination or ROOT / "models/pinyin-pretrained" / name
    directory.mkdir(parents=True, exist_ok=True)
    for item in record["files"]:
        path = (directory / item["path"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("RESOURCE_PATH_INVALID")
        if path.exists():
            if path.stat().st_size == item["sizeBytes"] and fingerprint(path) == item["sha256"]:
                continue
            raise ValueError("EXISTING_RESOURCE_DIGEST_MISMATCH: " + item["path"])
        if not item.get("url"):
            raise ValueError("DERIVED_RESOURCE_REQUIRES_LOCAL_TRAINING: " + item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        for attempt in range(4):
            try:
                print("download", name, item["path"], flush=True)
                with requests.get(item["url"], stream=True, timeout=(30, 120)) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as output:
                        copied = 0
                        for chunk in response.iter_content(4 * 1024 * 1024):
                            copied += len(chunk)
                            if copied > item["sizeBytes"]:
                                raise ValueError("RESOURCE_TOO_LARGE")
                            output.write(chunk)
                if (
                    temporary.stat().st_size != item["sizeBytes"]
                    or fingerprint(temporary) != item["sha256"]
                ):
                    raise ValueError("DOWNLOADED_RESOURCE_DIGEST_MISMATCH")
                temporary.replace(path)
                break
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
    (directory / "installation.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify(name: str, directory: Path) -> dict:
    record = json.loads(REGISTRY.read_text())["models"][name]
    for item in record["files"]:
        path = (directory / item["path"]).resolve()
        if not path.is_relative_to(directory.resolve()) or fingerprint(path) != item["sha256"]:
            raise ValueError("RESOURCE_DIGEST_MISMATCH: " + item["path"])
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.name, args.destination), ensure_ascii=False))
