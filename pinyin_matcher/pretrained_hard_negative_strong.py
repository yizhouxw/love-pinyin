"""Hard negatives with pre-existing weak-alignment components masked in training."""

import argparse
import json
from pathlib import Path

from pinyin_matcher import pretrained_factorized as original
from pinyin_matcher import pretrained_hard_negative as hard
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import write

CONFIG = ROOT / "content/pronunciation-pretrained-hard-negative-strong.json"
WEAK = {
    "onset": "WEAK_CTC_SUPPORT:initial",
    "rime": "WEAK_CTC_SUPPORT:final",
    "tone": "WEAK_CTC_SUPPORT:tone",
}


def mask_row(row):
    if row.get("split") != "train":
        return row
    flags = set(row.get("alignmentFlags") or [])
    labels = dict(row.get("componentExpertLabels") or {})
    if not labels:
        return row
    for component, flag in WEAK.items():
        if flag in flags or "HEAD_BOUNDARY_OVERLAP" in flags:
            labels[component] = "ambiguous"
    return {**row, "componentExpertLabels": labels}


def masked_rows(manifest):
    return [mask_row(row) for row in _base_training_rows(manifest)]


_base_training_rows = hard.training_rows
_base_supervision = original.supervision


def masked_supervision(rows):
    return _base_supervision([mask_row(row) for row in rows])


def run(action, manifest, output, *, cache=None, evidence=None):
    old_config, old_rows, old_supervision = hard.CONFIG, hard.training_rows, original.supervision
    try:
        hard.CONFIG, hard.training_rows, original.supervision = (
            CONFIG,
            masked_rows,
            masked_supervision,
        )
        if action == "prepare":
            result = hard.prepare(manifest, output)
            result["alignmentMaskCodeSha256"] = fingerprint(Path(__file__))
            result["maskPolicy"] = "Existing source alignment flags; train only, never calibration."
            write(output / "metadata.json", result)
            return result
        metadata = json.loads((evidence / "metadata.json").read_text())
        if metadata.get("alignmentMaskCodeSha256") != fingerprint(Path(__file__)):
            raise ValueError("ALIGNMENT_MASK_CODE_CHANGED")
        result = hard.train(manifest, cache, evidence, output)
        path = output / "model.json"
        metadata = json.loads(path.read_text())
        metadata["alignmentMaskCodeSha256"] = fingerprint(Path(__file__))
        metadata["alignmentMaskPolicy"] = (
            "Source WEAK_CTC_SUPPORT component; overlap all components; train only."
        )
        write(path, metadata)
        return result
    finally:
        hard.CONFIG, hard.training_rows, original.supervision = (
            old_config,
            old_rows,
            old_supervision,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare")
    for key in ("manifest", "output"):
        prepare.add_argument("--" + key, type=Path, required=True)
    train = actions.add_parser("train")
    for key in ("manifest", "cache", "evidence", "output"):
        train.add_argument("--" + key, type=Path, required=True)
    args = vars(parser.parse_args())
    print(json.dumps(run(**args), ensure_ascii=False))


if __name__ == "__main__":
    main()
