"""Explicitly bind rebuilt inputs to the unchanged mixed-sequence training budget."""

import argparse
import json
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint

CONFIG = ROOT / "content/pronunciation-pretrained-sequence-adapt.json"
NATIVE_CONFIG = ROOT / "content/pronunciation-pretrained-native-sequence.json"
DATA_CONFIGS = {
    "nativeDataConfigurationSha256": ROOT / "content/pronunciation-aishell3-data.json",
    "ompalDataConfigurationSha256": ROOT / "content/pronunciation-ompal-data.json",
}


def freeze_inputs(initializer, native_manifest, ompal_manifest, output):
    """Create a new protocol; never update the historical committed experiment."""
    if output.exists() or output.resolve() == CONFIG.resolve():
        raise ValueError("SEQUENCE_ADAPT_PROTOCOL_OUTPUT_EXISTS")
    config = json.loads(CONFIG.read_text())
    parent = json.loads((initializer / "tuned.json").read_text())
    if (
        parent.get("architecture") != "sensevoice-70-native-sequence-v1"
        or parent.get("testUsed") is not False
        or parent.get("configurationSha256") != fingerprint(NATIVE_CONFIG)
        or parent.get("manifestSha256") != fingerprint(ompal_manifest)
        or parent.get("trainingRecipe")
        or parent["files"]["tuned.safetensors"]["sha256"]
        != fingerprint(initializer / "tuned.safetensors")
    ):
        raise ValueError("SEQUENCE_ADAPT_INITIALIZER_PROTOCOL_MISMATCH")
    paths = {
        "initializerMetadataSha256": initializer / "tuned.json",
        "initializerWeightsSha256": initializer / "tuned.safetensors",
        "nativeManifestSha256": native_manifest,
        "ompalManifestSha256": ompal_manifest,
        **DATA_CONFIGS,
    }
    # All budget, loss, sampling and selection fields are copied without change.
    config.update({key: fingerprint(path) for key, path in paths.items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        handle.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return {"configuration": str(output.resolve()), "sha256": fingerprint(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("initializer", "native-manifest", "ompal-manifest", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    print(json.dumps(freeze_inputs(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
