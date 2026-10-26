"""Install a verified, minimal local inference bundle; never downloads a model."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.inference import PinyinMatcher


def bundle_path(directory: Path, name: str) -> Path:
    """Inference bundles are flat; reject path traversal before any copy."""
    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("BUNDLE_FILENAME_INVALID")
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("BUNDLE_PATH_ESCAPE")
    return path


def install(source: Path, destination: Path) -> dict:
    matcher = PinyinMatcher(source)
    if matcher.session is None:
        raise ValueError(matcher.problem)
    if not matcher.metadata.get("pitchTone"):
        raise ValueError("INDEPENDENT_TONE_BRANCH_REQUIRED_FOR_INSTALLATION")
    if destination.exists():
        existing = PinyinMatcher(destination)
        if existing.session is not None and existing.metadata == matcher.metadata:
            return existing.capabilities()
        raise ValueError("EXISTING_MODEL_BUNDLE_DIFFERS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".matcher-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        files = {"model.json", matcher.metadata["file"], matcher.metadata["catalogFile"]}
        if matcher.metadata.get("pitchTone"):
            files.add(matcher.metadata["pitchTone"]["file"])
            tracker = matcher.metadata["pitchTone"].get("tracker")
            if tracker:
                files.add(tracker["file"])
                license_path = (source / tracker["licenseFile"]).resolve()
                if (
                    not license_path.is_relative_to(source.resolve())
                    or fingerprint(license_path) != tracker["licenseSha256"]
                ):
                    raise ValueError("PITCH_TRACKER_LICENSE_DIGEST_MISMATCH")
                files.add(tracker["licenseFile"])
        for name in files:
            shutil.copyfile(bundle_path(source, name), bundle_path(staging, name))
        atomic_json(
            staging / "provenance.json",
            {
                "trainingCohort": "synthetic-intended-labels",
                "realChildAccuracyEstablished": False,
                "modelSha256": matcher.metadata["sha256"],
                "datasetSha256": matcher.metadata["datasetSha256"],
                "dataProvenance": matcher.metadata.get("dataProvenance"),
                "generators": json.loads((ROOT / "content/pronunciation-models.json").read_text()),
                "standardAudioSource": json.loads((ROOT / "content/pinyin-source.json").read_text())
                | {"assets": []},
            },
        )
        verified = PinyinMatcher(staging)
        if verified.session is None:
            raise ValueError(verified.problem)
        staging.rename(destination)
    return matcher.capabilities()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.source, args.destination), ensure_ascii=False))
