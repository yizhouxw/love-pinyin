"""Expert-supervised acoustic target comparison after target-independent encoding.

Native CTC events retain every native competitor, blank, unknown, and multiple
labels. Expert errors train P(expected component is valid), without inventing
the phone that was actually spoken. Counterfactual targets use expert-correct
speech and centrally declared phonetic combinations. No final-test training.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog
from pinyin_matcher.pretrained_features import configuration
from pinyin_matcher.pretrained_native import _probabilities, native_rime_aliases, single_label_ctc

COMPONENTS = ("onset", "rime", "tone")
HEADS = ("initial", "final", "tone")
FEATURE_NAMES = (
    "expectedMass",
    "expectedLogMass",
    "bestOtherMass",
    "bestOtherLogMass",
    "massMargin",
    "logMassMargin",
    "bestAnyMass",
    "expectedIsBest",
    "blankMass",
    "unknownMass",
    "multipleMass",
    "singleLabelMass",
    "eventEntropy",
    "frameMeanEntropy",
    "frameMinEntropy",
    "frameMaxEntropy",
    "expectedFrameMean",
    "expectedFrameMax",
    "expectedArgmaxFraction",
    "bestOtherFrameMax",
    "blankArgmaxFraction",
    "unknownArgmaxFraction",
    "greedyLengthScaled",
    "greedyExactlyExpected",
    "greedyHasUnknown",
    "greedyRepeatedExpected",
    "logFrameCount",
    "greedyContainsExpected",
)
WIDTH = len(FEATURE_NAMES)
PITCH_WIDTH = 68
DIMENSIONS = WIDTH * 3 + PITCH_WIDTH + 5
VERSION = "native-all-class-ctc-validity-v1"


def source_vocabularies(directory: Path | None = None) -> dict:
    directory = directory or ROOT / "models/pinyin-pretrained/hanziflow"
    return {
        head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text()) for head in HEADS
    }


def _tokens(target: dict, aliases: dict) -> tuple[str, str, str]:
    onset, rime, tone = target.get("onset"), target.get("rime"), target.get("tone")
    if onset is None or rime is None or tone is None or isinstance(tone, bool):
        raise ValueError("COMPARISON_TARGET_UNSUPPORTED")
    return (
        str(onset) or "ZERO",
        aliases.get(str(rime), str(rime)),
        "T" + str(tone).removeprefix("T"),
    )


def native_summary(native: dict, vocabularies: dict) -> list[dict]:
    """Reusable evidence independent of the requested target and corpus labels."""
    result = []
    for head in HEADS:
        logits = np.asarray(native.get("native_" + head, native.get(head)))
        table = vocabularies[head]
        probabilities = _probabilities(logits)
        if probabilities.shape[1] != len(table) or set(table.values()) != set(range(len(table))):
            raise ValueError("COMPARISON_NATIVE_VOCABULARY_MISMATCH")
        blank = table["<blank>"]
        unknown = table.get("<unk>")
        scores, empty, multiple = single_label_ctc(logits, blank)
        ids = probabilities.argmax(-1)
        sequence = [
            int(value)
            for index, value in enumerate(ids)
            if value != blank and (index == 0 or value != ids[index - 1])
        ]
        frame_entropy = -(probabilities * np.log(np.maximum(probabilities, 1e-12))).sum(
            -1
        ) / math.log(len(table))
        events = np.r_[scores, empty, multiple]
        result.append(
            {
                "probabilities": probabilities,
                "scores": scores,
                "empty": empty,
                "multiple": multiple,
                "blank": blank,
                "unknown": unknown,
                "ids": ids,
                "sequence": sequence,
                "frameEntropy": frame_entropy,
                "eventEntropy": float(
                    -(events * np.log(np.maximum(events, 1e-12))).sum() / math.log(len(events))
                ),
            }
        )
    return result


def _from_summary(
    summary: list[dict], vocabularies: dict, target: dict, pitch: np.ndarray | None, aliases: dict
) -> np.ndarray:
    tokens = _tokens(target, aliases)
    chunks = []
    for head, item, token in zip(HEADS, summary, tokens, strict=True):
        table = vocabularies[head]
        if token not in table or token in {"<blank>", "<unk>"}:
            raise ValueError("COMPARISON_TARGET_UNSUPPORTED:" + head + ":" + token)
        index = table[token]
        scores, probabilities = item["scores"], item["probabilities"]
        expected = float(scores[index])
        other = scores.copy()
        other[index] = 0
        best_other = float(other.max())
        other_frames = probabilities.copy()
        other_frames[:, index] = 0
        other_frames[:, item["blank"]] = 0
        unknown = item["unknown"]
        sequence = item["sequence"]
        log_expected, log_other = math.log(max(expected, 1e-8)), math.log(max(best_other, 1e-8))
        chunks.append(
            np.asarray(
                [
                    expected,
                    log_expected,
                    best_other,
                    log_other,
                    expected - best_other,
                    log_expected - log_other,
                    float(scores.max()),
                    float(scores.argmax() == index),
                    item["empty"],
                    float(scores[unknown]) if unknown is not None else 0,
                    item["multiple"],
                    float(scores.sum()),
                    item["eventEntropy"],
                    float(item["frameEntropy"].mean()),
                    float(item["frameEntropy"].min()),
                    float(item["frameEntropy"].max()),
                    float(probabilities[:, index].mean()),
                    float(probabilities[:, index].max()),
                    float(np.mean(item["ids"] == index)),
                    float(other_frames.max()),
                    float(np.mean(item["ids"] == item["blank"])),
                    float(np.mean(item["ids"] == unknown)) if unknown is not None else 0,
                    min(len(sequence), 16) / 8,
                    float(sequence == [index]),
                    float(unknown in sequence) if unknown is not None else 0,
                    float(len(sequence) > 1 and all(value == index for value in sequence)),
                    math.log1p(len(probabilities)) / math.log(401),
                    float(index in sequence),
                ],
                dtype=np.float32,
            )
        )
    tone = int(tokens[2][1:])
    if tone not in range(1, 6):
        raise ValueError("COMPARISON_TARGET_TONE_UNSUPPORTED")
    pitch = (
        np.zeros(PITCH_WIDTH, dtype=np.float32)
        if pitch is None
        else np.asarray(pitch, dtype=np.float32)
    )
    if pitch.shape != (PITCH_WIDTH,) or not np.isfinite(pitch).all():
        raise ValueError("COMPARISON_PITCH_INVALID")
    result = np.r_[*chunks, pitch, np.eye(5, dtype=np.float32)[tone - 1]].astype(np.float32)
    if result.shape != (DIMENSIONS,) or not np.isfinite(result).all():
        raise ValueError("COMPARISON_FEATURES_INVALID")
    return result


def evidence_features(
    native: dict, vocabularies: dict, target: dict, *, pitch=None, aliases=None
) -> np.ndarray:
    """157 features; target enters only this post-encoder comparison stage."""
    aliases = native_rime_aliases("hanziflow") if aliases is None else aliases
    return _from_summary(native_summary(native, vocabularies), vocabularies, target, pitch, aliases)


def central_targets() -> list[dict]:
    return [
        target
        for target in load_catalog()["targets"]
        if target["form"] == "whole-syllable" and target["tone"] in range(1, 5)
    ]


def counterfactual_targets(target: dict, catalogue: list[dict]) -> list[tuple[dict, int]]:
    """Known wrong targets for expert-correct speech, not actual wrong-phone labels."""
    base = tuple(str(target[key]) for key in COMPONENTS)
    options = {}
    for candidate in catalogue:
        values = tuple(str(candidate[key]) for key in COMPONENTS)
        changes = [index for index, (a, b) in enumerate(zip(base, values, strict=True)) if a != b]
        if len(changes) == 1:
            options[values] = (dict(zip(COMPONENTS, values, strict=True)), changes[0])
    # All four lexical-tone hypotheses are legal for a corpus-supported base.
    tones = sorted({int(row["tone"]) for row in catalogue if int(row["tone"]) in range(1, 5)})
    for tone in tones:
        if str(tone) != base[2]:
            values = (base[0], base[1], str(tone))
            options[values] = (dict(zip(COMPONENTS, values, strict=True)), 2)
    return [options[key] for key in sorted(options)]


def _eligible(row: dict) -> bool:
    return not (
        row.get("labelPolicyFlags") or row.get("numericalQualityFlags") or row.get("placeholder")
    )


def build_arrays(rows: list[dict], cache: Path, vocabularies: dict, aliases: dict) -> dict:
    from pinyin_matcher.pretrained_experiment import read_cached

    identity = fingerprint(cache / "identity.json")
    catalogue = central_targets()
    x, y, weights, examples = [], [], [], []
    counts = Counter()
    for row_index, row in enumerate(rows):
        target = {key: row[key] for key in COMPONENTS}
        valid, summary, pitch = _eligible(row), None, None
        feature = np.zeros(DIMENSIONS, dtype=np.float32)
        if valid:
            with read_cached(cache / (row["sha256"] + ".npz"), identity) as item:
                if "error" in item:
                    valid = False
                else:
                    try:
                        summary = native_summary(dict(item), vocabularies)
                        pitch = item["pitch"].copy()
                        feature = _from_summary(summary, vocabularies, target, pitch, aliases)
                    except (ValueError, KeyError):
                        valid = False
        known = {"unanimous-correct": 1, "unanimous-error": 0}
        labels = [
            known.get(row.get("componentExpertLabels", {}).get(key), -1) if valid else -1
            for key in COMPONENTS
        ]
        x.append(feature)
        y.append(labels)
        weights.append([float(value >= 0) for value in labels])
        examples.append({"rowIndex": row_index, "kind": "expert", "target": target, "valid": valid})
        counts["expertRows"] += 1
        counts["unavailableOrPredeclaredUnassessable"] += not valid
        if row.get("expertLabel") != "unanimous-correct" or row.get("labelPolicyFlags"):
            continue
        try:
            for head, token in zip(HEADS, _tokens(target, aliases), strict=True):
                if token not in vocabularies[head]:
                    raise ValueError("UNSUPPORTED_TRUTH")
        except (ValueError, KeyError):
            continue
        candidates = counterfactual_targets(target, catalogue)
        accepted = []
        for candidate, component in candidates:
            try:
                cf_feature = (
                    _from_summary(summary, vocabularies, candidate, pitch, aliases)
                    if valid
                    else np.zeros(DIMENSIONS, dtype=np.float32)
                )
            except (ValueError, KeyError):
                continue
            accepted.append((candidate, component, cf_feature))
        per_component = Counter(component for _, component, _ in accepted)
        for candidate, component, cf_feature in accepted:
            labels = [-1, -1, -1]
            sample_weights = [0.0, 0.0, 0.0]
            if valid:
                labels[component] = 0
                sample_weights[component] = 1 / per_component[component]
            x.append(cf_feature)
            y.append(labels)
            weights.append(sample_weights)
            examples.append(
                {
                    "rowIndex": row_index,
                    "kind": "counterfactual",
                    "component": component,
                    "target": candidate,
                    "valid": valid,
                }
            )
            counts["counterfactualComparisons"] += 1
        if row_index % 1000 == 0:
            print(
                json.dumps(
                    {
                        "comparisonRowsPrepared": row_index + 1,
                        "total": len(rows),
                        "examples": len(x),
                    }
                ),
                flush=True,
            )
    return {
        "x": np.asarray(x),
        "y": np.asarray(y, dtype=np.float32),
        "weights": np.asarray(weights, dtype=np.float32),
        "examples": examples,
        "rows": rows,
        "counts": dict(counts),
    }


def classify(probabilities: np.ndarray, threshold: dict) -> str:
    if not np.isfinite(probabilities).all():
        return "uncertain"
    if np.min(probabilities) >= threshold["accept"]:
        return "matched"
    if np.min(probabilities) <= threshold["reject"]:
        return "retry"
    return "uncertain"


def calibration_counts(probabilities: np.ndarray, dataset: dict, threshold: dict) -> dict:
    examples, rows = dataset["examples"], dataset["rows"]
    minimum = probabilities.min(-1)
    statuses = np.where(
        minimum >= threshold["accept"], 0, np.where(minimum <= threshold["reject"], 1, 2)
    )
    valid = np.asarray([example["valid"] for example in examples])
    statuses[~valid] = 2
    original_indices = np.asarray(
        [i for i, example in enumerate(examples) if example["kind"] == "expert"]
    )
    actual = statuses[original_indices]
    positive = np.asarray(
        [
            row.get("expertLabel") == "unanimous-correct" and not row.get("labelPolicyFlags")
            for row in rows
        ]
    )
    negative = np.asarray(
        [
            row.get("expertLabel") == "unanimous-error" and not row.get("labelPolicyFlags")
            for row in rows
        ]
    )
    cf_indices = np.asarray(
        [i for i, example in enumerate(examples) if example["kind"] == "counterfactual"],
        dtype=np.int64,
    )
    roots = np.asarray([examples[i]["rowIndex"] for i in cf_indices], dtype=np.int64)
    has_cf = np.bincount(roots, minlength=len(rows)) > 0
    wrong_accept = np.bincount(roots, weights=(statuses[cf_indices] == 0), minlength=len(rows)) > 0
    all_cf_reject = (
        np.bincount(roots, weights=(statuses[cf_indices] != 1), minlength=len(rows)) == 0
    )
    negative_roots = negative | has_cf
    false_accept = (negative & (actual == 0)) | wrong_accept
    strata = {}
    for component, key in enumerate(COMPONENTS):
        selected_cf = [i for i in cf_indices if examples[i]["component"] == component]
        component_roots = np.asarray([examples[i]["rowIndex"] for i in selected_cf], dtype=np.int64)
        component_cf = np.bincount(component_roots, minlength=len(rows)) > 0
        real_error = np.asarray(
            [
                row.get("componentExpertLabels", {}).get(key) == "unanimous-error"
                and not row.get("labelPolicyFlags")
                for row in rows
            ]
        )
        accepted = (
            np.bincount(component_roots, weights=(statuses[selected_cf] == 0), minlength=len(rows))
            > 0
        )
        mask = real_error | component_cf
        count = int(mask.sum())
        bad = int(((real_error & (actual == 0)) | accepted).sum())
        strata[key] = {"n": count, "falseAccept": bad, "rate": bad / count if count else None}
        for name, cohort, failures in (
            ("expert-" + key, real_error, real_error & (actual == 0)),
            ("counterfactual-" + key, component_cf, accepted),
        ):
            denominator = int(cohort.sum())
            failures = int(failures.sum())
            strata[name] = {
                "n": denominator,
                "falseAccept": failures,
                "rate": failures / denominator if denominator else None,
            }
    for name, cohort, failures in (
        ("expert-any", negative, negative & (actual == 0)),
        ("counterfactual-any", has_cf, wrong_accept),
    ):
        denominator = int(cohort.sum())
        failures = int(failures.sum())
        strata[name] = {
            "n": denominator,
            "falseAccept": failures,
            "rate": failures / denominator if denominator else None,
        }
    n, negatives = int(positive.sum()), int(negative_roots.sum())
    accepted = int((positive & (actual == 0)).sum())
    rejected = int((positive & (actual == 1)).sum())
    abstained = int((positive & (actual == 2)).sum())
    bad = int(false_accept.sum())
    negative_rejected = int(((negative & (actual == 1)) | (has_cf & all_cf_reject)).sum())
    rates = [value["rate"] for value in strata.values() if value["rate"] is not None]
    false_rate = max([bad / negatives if negatives else 1, *rates])
    ratios = [false_rate / 0.05, rejected / max(n, 1) / 0.10, abstained / max(n, 1) / 0.20]
    return {
        "positive": {
            "n": n,
            "matched": accepted,
            "explicitReject": rejected,
            "abstention": abstained,
        },
        "negative": {
            "n": negatives,
            "falseAccept": bad,
            "explicitReject": negative_rejected,
            "abstention": negatives - bad - negative_rejected,
            "expertErrorRoots": int(negative.sum()),
            "counterfactualRoots": int(has_cf.sum()),
            "counterfactualComparisons": len(cf_indices),
        },
        "errorStrata": strata,
        "rates": {
            "maximumStratumFalseAccept": false_rate,
            "pooledFalseAccept": bad / negatives if negatives else None,
            "positiveExplicitReject": rejected / n if n else None,
            "positiveAbstention": abstained / n if n else None,
        },
        "pointEstimateGatePassed": bool(n and negatives and max(ratios) <= 1),
        "maximumNormalizedGateViolation": max(ratios),
        "sumNormalizedGateViolation": sum(ratios),
        "unassessableOriginalRowsRetained": int(len(rows) - positive.sum() - negative.sum()),
    }


def calibration_records(probabilities: np.ndarray, dataset: dict, threshold: dict) -> list[dict]:
    records = []
    for probability, example in zip(probabilities, dataset["examples"], strict=True):
        row = dataset["rows"][example["rowIndex"]]
        if example["kind"] == "counterfactual":
            label, errors = "negative", ["counterfactual-" + COMPONENTS[example["component"]]]
        elif row.get("labelPolicyFlags") or row.get("expertLabel") not in {
            "unanimous-correct",
            "unanimous-error",
        }:
            label, errors = "ambiguous", [None]
        elif row["expertLabel"] == "unanimous-correct":
            label, errors = "positive", [None]
        else:
            label = "negative"
            errors = [
                "expert-" + key
                for key in COMPONENTS
                if row.get("componentExpertLabels", {}).get(key) == "unanimous-error"
            ] or ["expert-unspecified"]
        status = classify(probability, threshold) if example["valid"] else "uncertain"
        for error in errors:
            records.append(
                {
                    "source": row.get("source", "ompal-v1"),
                    "root_id": row["id"],
                    "speaker_id": row["speakerId"],
                    "voice_family": row.get("voiceFamilyId", row["speakerId"]),
                    "label": label,
                    "status": status,
                    "error_type": error,
                    "target": example["target"],
                    "comparisonKind": example["kind"],
                    "expertLabelsUnchanged": True,
                }
            )
    return records


def _network(mean: np.ndarray, std: np.ndarray):
    import torch
    from torch import nn

    class ValidityNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("mean", torch.from_numpy(mean))
            self.register_buffer("std", torch.from_numpy(std))
            self.heads = nn.ModuleList(
                [
                    nn.Sequential(
                        nn.Linear(width, 64),
                        nn.GELU(),
                        nn.Linear(64, 32),
                        nn.GELU(),
                        nn.Linear(32, 1),
                    )
                    for width in (WIDTH, WIDTH, WIDTH + PITCH_WIDTH + 5)
                ]
            )

        def forward(self, features):
            features = (features - self.mean) / self.std
            slices = (features[:, :WIDTH], features[:, WIDTH : WIDTH * 2], features[:, WIDTH * 2 :])
            return torch.cat(
                [head(part) for head, part in zip(self.heads, slices, strict=True)], dim=-1
            )

    return ValidityNetwork()


def train(
    manifest: Path, cache: Path, output: Path, *, model_directory: Path | None = None, epochs=120
) -> dict:
    import torch
    from torch.nn import functional as functional

    from pinyin_matcher.pretrained_experiment import (
        cache_identity,
        covered_targets,
        read_rows,
        write,
    )
    from pinyin_matcher.pretrained_metrics import metrics

    if not 1 <= epochs <= 120:
        raise ValueError("COMPARISON_MAXIMUM_BUDGET_120_EPOCHS")
    identity = json.loads((cache / "identity.json").read_text())
    if identity != cache_identity("hanziflow", model_directory):
        raise ValueError("COMPARISON_BOUND_CACHE_IDENTITY_CHANGED")
    cache_meta = json.loads((cache / "cache.json").read_text())
    if cache_meta["manifestSha256"] != fingerprint(manifest) or cache_meta["testIncluded"]:
        raise ValueError("COMPARISON_CACHE_MUST_BE_COMPLETE_TRAIN_CALIBRATION_ONLY")
    rows = read_rows(manifest)
    training_rows = [row for row in rows if row["split"] == "train"]
    task_vocabulary = {key: sorted({str(row[key]) for row in training_rows}) for key in COMPONENTS}
    vocabularies = source_vocabularies(model_directory)
    aliases = native_rime_aliases("hanziflow")
    sets = {
        split: build_arrays(
            [row for row in rows if row["split"] == split], cache, vocabularies, aliases
        )
        for split in ("train", "calibration")
    }
    training, calibration = sets["train"], sets["calibration"]
    usable = training["weights"].sum(-1) > 0
    if not usable.any():
        raise ValueError("COMPARISON_NO_EXPERT_SUPERVISION")
    mean = training["x"][usable].mean(0).astype(np.float32)
    std = np.maximum(training["x"][usable].std(0), 0.05).astype(np.float32)
    torch.set_num_threads(2)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.manual_seed(configuration()["seed"])
    model = _network(mean, std)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002, weight_decay=0.001)
    tx, ty, tw = (torch.from_numpy(training[key]) for key in ("x", "y", "weights"))
    cx, cy, cw = (torch.from_numpy(calibration[key]) for key in ("x", "y", "weights"))
    positive_weight = ((tw * (ty == 0)).sum(0) / (tw * (ty == 1)).sum(0).clamp(min=1)).clamp(
        min=0.1, max=10
    )

    def loss(logits, labels, weights):
        raw = functional.binary_cross_entropy_with_logits(
            logits, labels.clamp(min=0), pos_weight=positive_weight, reduction="none"
        )
        return ((raw * weights).sum(0) / weights.sum(0).clamp(min=1)).mean()

    best, history = None, []
    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        training_loss = loss(model(tx), ty, tw)
        training_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
        optimizer.step()
        model.eval()
        with torch.inference_mode():
            calibration_loss = float(loss(model(cx), cy, cw))
        record = {
            "epoch": epoch,
            "trainingLoss": float(training_loss.detach()),
            "calibrationLoss": calibration_loss,
        }
        history.append(record)
        if best is None or calibration_loss < best[0]:
            best = (calibration_loss, epoch, copy.deepcopy(model.state_dict()))
        if epoch % 10 == 0:
            print(json.dumps(record), flush=True)
    model.load_state_dict(best[2])
    model.eval()
    with torch.inference_mode():
        probabilities = model(cx).sigmoid().numpy()
    thresholds = []
    for accept in (0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.975):
        for reject in (0.01, 0.025, 0.05, 0.10, 0.20, 0.30, 0.40, 0.49):
            if reject < accept:
                threshold = {"accept": accept, "reject": reject}
                counts = calibration_counts(probabilities, calibration, threshold)
                thresholds.append((counts, threshold))
    counts, threshold = min(
        thresholds,
        key=lambda value: (
            not value[0]["pointEstimateGatePassed"],
            value[0]["maximumNormalizedGateViolation"],
            value[0]["sumNormalizedGateViolation"],
            -value[0]["positive"]["matched"],
        ),
    )
    records = calibration_records(probabilities, calibration, threshold)
    output.mkdir(parents=True, exist_ok=True)
    np.savez(output / "comparison-normalization.npz", mean=mean, std=std)
    torch.save(model.state_dict(), output / "comparison.pt")

    class ProbabilityExport(torch.nn.Module):
        def __init__(self, network):
            super().__init__()
            self.network = network

        def forward(self, features):
            return self.network(features).sigmoid()

    torch.onnx.export(
        ProbabilityExport(model),
        torch.zeros(1, DIMENSIONS),
        str(output / "comparison.onnx"),
        input_names=["features"],
        output_names=["component_validity"],
        dynamic_axes={"features": {0: "batch"}, "component_validity": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    report = {
        "counts": counts,
        "thresholds": threshold,
        "fullDenominatorMetrics": metrics(records),
        "selectedEpoch": best[1],
        "history": history,
        "datasetCounts": {key: value["counts"] for key, value in sets.items()},
        "allExpertLabelsUnchanged": True,
        "counterfactualsAreWrongTargetsNotActualWrongPhoneLabels": True,
        "finalTestRead": False,
    }
    write(output / "calibration.json", report)
    write(output / "calibration-records.json", records)
    metadata = {
        "schemaVersion": 1,
        "version": VERSION,
        "variant": "native-component-validity-mlp",
        "model": "hanziflow",
        "coveredTargets": covered_targets(task_vocabulary, training_rows),
        "dimensions": DIMENSIONS,
        "componentFeatureWidth": WIDTH,
        "pitchWidth": PITCH_WIDTH,
        "componentFeatureNames": list(FEATURE_NAMES),
        "thresholds": threshold,
        "vocabularies": vocabularies,
        "aliases": aliases,
        "manifestSha256": fingerprint(manifest),
        "cacheIdentitySha256": fingerprint(cache / "identity.json"),
        "cacheMetadataSha256": fingerprint(cache / "cache.json"),
        "acousticDerivative": identity.get("derivative"),
        "featureCodeSha256": fingerprint(Path(__file__)),
        "centralCatalogSha256": fingerprint(ROOT / "content/pronunciation-targets.json"),
        "selectedEpoch": best[1],
        "maximumEpochs": epochs,
        "binaryClassPositiveWeights": positive_weight.tolist(),
        "counterfactualWeighting": (
            "Each root contributes at most one total negative weight per changed component; "
            "unrelated component labels remain unknown."
        ),
        "trainingSupervision": (
            "Original unanimous expert correctness1/error0 only. No inferred replacement "
            "phoneme. Ambiguous/policy/numerical rows retained, not trained."
        ),
        "targetInputStage": "After target-independent acoustic encoding only",
        "populationOrChildValidationPassed": False,
        "files": {
            name: {"sha256": fingerprint(output / name), "bytes": (output / name).stat().st_size}
            for name in ("comparison.onnx", "comparison-normalization.npz")
        },
    }
    write(output / "comparison.json", metadata)
    return report


class ComparisonHead:
    """CPU-only comparison probabilities; no acoustic model or download inside."""

    def __init__(self, directory: Path, *, metadata_file="comparison.json"):
        import onnxruntime as ort

        directory = Path(directory)
        self.metadata = json.loads((directory / metadata_file).read_text())
        if self.metadata["featureCodeSha256"] != fingerprint(Path(__file__)):
            raise ValueError("COMPARISON_FEATURE_CODE_MISMATCH")
        for name, expected in self.metadata["files"].items():
            path = (directory / name).resolve()
            if (
                not path.is_relative_to(directory.resolve())
                or fingerprint(path) != expected["sha256"]
            ):
                raise ValueError("COMPARISON_MODEL_DIGEST_MISMATCH")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(directory / "comparison.onnx"), options, providers=["CPUExecutionProvider"]
        )

    def probabilities(self, native: dict, target: dict, *, pitch=None) -> np.ndarray:
        return self.probabilities_prepared(self.prepare(native, pitch=pitch), target)

    def prepare(self, native: dict, *, pitch=None) -> dict:
        """Compute all-class CTC events once, without the expected answer."""
        return {
            "summary": native_summary(native, self.metadata["vocabularies"]),
            "pitch": pitch,
        }

    def probabilities_prepared(self, prepared: dict, target: dict) -> np.ndarray:
        features = _from_summary(
            prepared["summary"],
            self.metadata["vocabularies"],
            target,
            prepared["pitch"],
            self.metadata["aliases"],
        )
        return self.session.run(None, {"features": features[None]})[0][0]

    def probabilities_for_targets(
        self, native: dict, targets: list[dict], *, pitch=None
    ) -> np.ndarray:
        prepared = self.prepare(native, pitch=pitch)
        features = np.stack(
            [
                _from_summary(
                    prepared["summary"],
                    self.metadata["vocabularies"],
                    target,
                    prepared["pitch"],
                    self.metadata["aliases"],
                )
                for target in targets
            ]
        )
        return self.session.run(None, {"features": features})[0]

    def classify(self, native: dict, target: dict, *, pitch=None) -> str:
        return classify(
            self.probabilities(native, target, pitch=pitch), self.metadata["thresholds"]
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--manifest", required=True, type=Path)
    fit.add_argument("--cache", required=True, type=Path)
    fit.add_argument("--output", required=True, type=Path)
    fit.add_argument("--model-directory", "--model", dest="model_directory", type=Path)
    fit.add_argument("--epochs", type=int, default=120)
    args = parser.parse_args()
    report = train(
        args.manifest,
        args.cache,
        args.output,
        model_directory=args.model_directory,
        epochs=args.epochs,
    )
    print(
        json.dumps(
            {
                "selectedEpoch": report["selectedEpoch"],
                "thresholds": report["thresholds"],
                "counts": report["counts"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
