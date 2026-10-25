"""Explicit fixed-resource installation. Runtime inference never calls this module."""

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.generate import atomic_json


def verify(directory: Path, record: dict):
    for item in record["files"]:
        file = (directory / item["path"]).resolve()
        if (
            not file.is_relative_to(directory.resolve())
            or file.stat().st_size != item["bytes"]
            or fingerprint(file) != item["sha256"]
        ):
            raise ValueError("RESOURCE_DIGEST_MISMATCH: " + item["path"])


def prepare(generator: str, destination: Path | None = None):
    registry = json.loads((ROOT / "content/pronunciation-models.json").read_text())
    record = registry["generators"][generator]
    directory = destination or ROOT / "models" / ("matcher-" + generator)
    directory.mkdir(parents=True, exist_ok=True)
    for item in record["files"]:
        file = directory / item["path"]
        if not file.resolve().is_relative_to(directory.resolve()):
            raise ValueError("RESOURCE_PATH_INVALID")
        if file.exists():
            if fingerprint(file) == item["sha256"]:
                continue
            raise ValueError("EXISTING_RESOURCE_DIGEST_MISMATCH: " + item["path"])
        file.parent.mkdir(parents=True, exist_ok=True)
        print("Downloading fixed generator resource:", generator, item["path"], flush=True)
        temporary = file.with_name(file.name + ".part")
        url = f"https://huggingface.co/{record['model']}/resolve/{record['revision']}/{item['path']}?download=true"
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as handle:
            copied = 0
            while chunk := response.read(4 * 1024 * 1024):
                copied += len(chunk)
                if copied > item["bytes"]:
                    raise ValueError("RESOURCE_TOO_LARGE")
                handle.write(chunk)
        if temporary.stat().st_size != item["bytes"] or fingerprint(temporary) != item["sha256"]:
            raise ValueError("DOWNLOADED_RESOURCE_DIGEST_MISMATCH")
        temporary.replace(file)
    verify(directory, record)
    atomic_json(directory / "installation.json", record)
    if generator == "cosy":
        source = ROOT / "private/matcher-cosy-source"
        source_record = registry["cosySource"]
        if not source.exists():
            subprocess.run(
                ["git", "clone", "--no-checkout", source_record["repository"], str(source)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "checkout", "--detach", source_record["commit"]],
                check=True,
            )
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != source_record["commit"]:
            raise ValueError("GENERATOR_SOURCE_VERSION_MISMATCH")
        subprocess.run(["git", "-C", str(source), "submodule", "update", "--init"], check=True)
        actual_submodule = subprocess.check_output(
            ["git", "-C", str(source / "third_party/Matcha-TTS"), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual_submodule != source_record["matchaCommit"]:
            raise ValueError("GENERATOR_SUBMODULE_VERSION_MISMATCH")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generator", choices=["qwen", "cosy"])
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(prepare(args.generator, args.destination))
