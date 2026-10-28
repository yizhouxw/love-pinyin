"""MATCH-18 domain adaptation: append expert-correct adult training roots only."""

import argparse
import json
from pathlib import Path

from threadpoolctl import threadpool_limits

from pinyin_matcher import gmm_shop
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import read_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    original = gmm_shop.read_data

    def mixed(manifest):
        native, calibration = original(manifest)
        training = [
            r
            for r in read_rows(manifest, verify_splits=("train",))
            if r.get("source") == "ompal-v1"
            and r["split"] == "train"
            and r.get("expertLabel") == "unanimous-correct"
            and not r.get("labelPolicyFlags")
            and not r.get("numericalQualityFlags")
            and not r.get("placeholder")
        ]
        print(json.dumps({"additionalExpertCorrectTrainingRoots": len(training)}), flush=True)
        return native + training, calibration

    gmm_shop.read_data = mixed
    with threadpool_limits(limits=2):
        result = gmm_shop.train(args.manifest, args.output)
    # Separate identity makes explicit that this is not the native-only run.
    result["adaptationCodeSha256"] = fingerprint(Path(__file__))
    result["trainingPolicy"] = "aishell3 plus expert-unanimous-correct ompal training split"
    (args.output / "adaptation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
