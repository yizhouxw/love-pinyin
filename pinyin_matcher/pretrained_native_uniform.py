"""Uniform-negative control for the same real-speech training supplement."""

import argparse
import json
from pathlib import Path

from pinyin_matcher import pretrained_factorized as original
from pinyin_matcher import pretrained_hard_negative as hard
from pinyin_matcher import pretrained_hard_negative_native as native
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import write


def train(manifest, cache, evidence, output, *, config=native.CONFIG):
    policy = json.loads(config.read_text())
    if fingerprint(manifest) != policy["mixedManifestSha256"]:
        raise ValueError("NATIVE_UNIFORM_MANIFEST_CHANGED")
    prior_pairs, prior_config, prior_supervision = hard.pairs, hard.CONFIG, original.supervision
    try:
        hard.pairs, hard.CONFIG = native.mixed_pairs, config
        recorded = hard.verify(manifest, evidence)
        if recorded.get("mixedPairCodeSha256") != fingerprint(Path(native.__file__)):
            raise ValueError("NATIVE_UNIFORM_PAIR_CODE_CHANGED")
        original.supervision = native.mixed_supervision
        result = original.train(manifest, cache, output)
    finally:
        hard.pairs, hard.CONFIG, original.supervision = prior_pairs, prior_config, prior_supervision
    result["variant"] = "factorized-native-uniform-negative"
    result["nativeSupplementConfigurationSha256"] = fingerprint(config)
    result["nativeTrainingCodeSha256"] = fingerprint(Path(native.__file__))
    result["uniformTrainingCodeSha256"] = fingerprint(Path(__file__))
    result["comparisonEvidenceSha256"] = fingerprint(evidence / "metadata.json")
    result["comparisonPairsSha256"] = recorded["pairsSha256"]
    write(output / "model.json", result)
    return {key: result[key] for key in ("variant", "selectedEpoch", "trainingSeconds")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cache", "evidence", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--config", type=Path, default=native.CONFIG)
    print(json.dumps(train(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
