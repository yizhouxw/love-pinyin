"""Train with hard component mismatches derived from expert-labelled real speech.

An alternative component is a negative comparison against the same original
recording, never a new utterance or an assertion about an expert-error row.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import torch
from torch.nn import functional as F

from pinyin_matcher import pretrained_factorized as original
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import read_rows, write

CONFIG = ROOT / "content/pronunciation-pretrained-hard-negative.json"
COMPONENTS = ("onset", "rime", "tone")


def training_rows(manifest):
    rows = [
        row
        for row in read_rows(manifest)
        if row["split"] == "train"
        and not row.get("numericalQualityFlags")
        and not row.get("labelPolicyFlags")
    ]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("HARD_NEGATIVE_INVALID_TRAIN_ROOTS")
    return rows


def pairs(rows):
    vocab = {key: sorted({str(row[key]) for row in rows}) for key in COMPONENTS}
    for row in sorted(rows, key=lambda value: value["id"]):
        labels = row.get("componentExpertLabels") or {}
        for component in COMPONENTS:
            if labels.get(component) != "unanimous-correct":
                continue
            actual = str(row[component])
            for target in vocab[component]:
                if target != actual:
                    yield {
                        "rootId": row["id"],
                        "audioSha256": row["sha256"],
                        "parentSha256": row["parentSha256"],
                        "speakerId": row["speakerId"],
                        "voiceFamilyId": row.get("voiceFamilyId"),
                        "referenceSourceId": row.get("referenceSourceId"),
                        "component": component,
                        "expertActual": actual,
                        "incorrectTarget": target,
                        "label": "component-mismatch",
                        "sourceSplit": "train",
                    }


def prepare(manifest, output):
    if output.exists():
        raise ValueError("HARD_NEGATIVE_OUTPUT_EXISTS")
    rows = training_rows(manifest)
    output.mkdir(parents=True)
    counts, roots = Counter(), set()
    path = output / "pairs.jsonl"
    with path.open("x") as stream:
        for item in pairs(rows):
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            counts[item["component"]] += 1
            roots.add(item["rootId"])
    metadata = {
        "schemaVersion": 1,
        "manifestSha256": fingerprint(manifest),
        "configurationSha256": fingerprint(CONFIG),
        "pairsSha256": fingerprint(path),
        "pairCount": sum(counts.values()),
        "pairsByComponent": dict(counts),
        "distinctSourceRoots": len(roots),
        "sourceTrainingRoots": len(rows),
        "speakerCount": len({r["speakerId"] for r in rows if r["id"] in roots}),
        "newRecordings": 0,
        "newSpeakers": 0,
        "finalTestUsed": False,
        "limitations": (
            "Comparisons share original audio and expert labels; "
            "no new independent audio or natural-error labels."
        ),
    }
    write(output / "metadata.json", metadata)
    return metadata


def verify(manifest, directory):
    metadata = json.loads((directory / "metadata.json").read_text())
    if (
        metadata["manifestSha256"] != fingerprint(manifest)
        or metadata["configurationSha256"] != fingerprint(CONFIG)
        or metadata["pairsSha256"] != fingerprint(directory / "pairs.jsonl")
        or metadata["finalTestUsed"] is not False
    ):
        raise ValueError("HARD_NEGATIVE_IDENTITY_MISMATCH")
    expected = pairs(training_rows(manifest))
    count = 0
    with (directory / "pairs.jsonl").open() as stream:
        for line in stream:
            item = json.loads(line)
            if item != next(expected, None):
                raise ValueError("HARD_NEGATIVE_PAIR_CONTENT_MISMATCH")
            count += 1
    if next(expected, None) is not None or count != metadata["pairCount"]:
        raise ValueError("HARD_NEGATIVE_PAIR_INVENTORY_MISMATCH")
    return metadata


def hard_loss(identities, validities, labels, annotations, *, validity_weight=1.0):
    identity_losses, validity_losses = [], []
    for index, (identity, validity) in enumerate(zip(identities, validities, strict=True)):
        known = (annotations[:, index] >= 0) & (labels[:, index] >= 0)
        correct = known & (annotations[:, index] == 1)
        error = known & (annotations[:, index] == 0)
        if correct.any():
            truth = labels[correct, index]
            identity_losses.append(F.cross_entropy(identity[correct], truth))
        groups = []
        if correct.any():
            current, truth = validity[correct], labels[correct, index]
            positive = F.softplus(-current.gather(1, truth[:, None])[:, 0])
            mask = F.one_hot(truth, current.shape[1]).bool()
            other = F.softplus(current).masked_fill(mask, -torch.inf)
            hard = other.topk(min(3, current.shape[1] - 1), dim=1).values.mean(1)
            groups.append(((positive + hard) * 0.5).mean())
        if error.any():
            chosen = validity[error].gather(1, labels[error, index, None])[:, 0]
            groups.append(F.softplus(chosen).mean())
        if groups:
            validity_losses.append(sum(groups) / len(groups))
    zero_identity = sum(value.sum() * 0 for value in identities)
    zero_validity = sum(value.sum() * 0 for value in validities)
    identity_loss = sum(identity_losses, zero_identity)
    validity_loss = sum(validity_losses, zero_validity)
    return identity_loss + validity_weight * validity_loss, identity_loss, validity_loss


def train(manifest, cache, evidence, output):
    metadata = verify(manifest, evidence)
    protocol = json.loads(CONFIG.read_text())
    if protocol["hardNegativeCount"] != 3 or protocol["finalTestUsed"] is not False:
        raise ValueError("HARD_NEGATIVE_PROTOCOL_CHANGED")
    previous_config, previous_loss = original.CONFIG, original.factorized_loss
    try:
        original.CONFIG, original.factorized_loss = CONFIG, hard_loss
        result = original.train(manifest, cache, output)
    finally:
        original.CONFIG, original.factorized_loss = previous_config, previous_loss
    result["variant"] = "factorized-hard-negative"
    result["hardNegativeEvidenceSha256"] = fingerprint(evidence / "metadata.json")
    result["hardNegativePairsSha256"] = metadata["pairsSha256"]
    result["hardNegativePairCount"] = metadata["pairCount"]
    result["hardNegativeSourceRoots"] = metadata["distinctSourceRoots"]
    result["trainingProcedureSha256"] = fingerprint(Path(__file__))
    write(output / "model.json", result)
    return {
        key: result[key]
        for key in ("variant", "selectedEpoch", "trainingSeconds", "hardNegativePairCount")
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    generate = actions.add_parser("prepare")
    generate.add_argument("--manifest", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    fit = actions.add_parser("train")
    for key in ("manifest", "cache", "evidence", "output"):
        fit.add_argument("--" + key, type=Path, required=True)
    values = vars(parser.parse_args())
    action = values.pop("action")
    print(json.dumps((prepare if action == "prepare" else train)(**values), ensure_ascii=False))


if __name__ == "__main__":
    main()
