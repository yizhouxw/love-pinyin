"""Fixed-budget native sequence replay plus isolated expert-event adaptation."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file
from torch import nn

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import calibrate, read_cached, read_rows, write
from pinyin_matcher.pretrained_finetune import _labels, signed_ctc_events
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_native_sequence import (
    COMPONENTS,
    VOCAB_FILES,
    NativeSequenceEvidence,
    _calibration_items,
    _forward,
    _native_manifest,
    calibration,
    sequence_ctc_loss,
    validate_cached_labels,
    vocabularies,
)
from pinyin_matcher.pretrained_native_sequence import (
    CONFIG as NATIVE_CONFIG,
)
from pinyin_matcher.pretrained_native_sequence import (
    DATA_CONFIG as NATIVE_DATA_CONFIG,
)
from pinyin_matcher.pretrained_sensevoice import FILES
from pinyin_matcher.pretrained_tail_finetune import FrozenPrefix, TrainableTail, state_digest

CONFIG = ROOT / "content/pronunciation-pretrained-sequence-adapt.json"
OMPAL_DATA_CONFIG = ROOT / "content/pronunciation-ompal-data.json"


def configuration(path=CONFIG):
    config = json.loads(path.read_text())
    fixed = {
        "seed": 3182026,
        "epochs": 8,
        "batchSizePerDomain": 32,
        "tailLearningRate": 1e-5,
        "headLearningRate": 1e-4,
        "weightDecay": 0.01,
        "gradientClip": 5.0,
        "nativeLossWeight": 0.5,
        "ompalLossWeight": 0.5,
        "finalTestUsed": False,
    }
    if any(config.get(k) != v for k, v in fixed.items()):
        raise ValueError("SEQUENCE_ADAPT_PROTOCOL_CHANGED")
    return config


def balanced_expert_loss(outputs, lengths, targets, annotations):
    """Balance actual positive/negative groups, masking every unknown component."""
    losses, _ = signed_ctc_events(list(outputs), lengths, targets, annotations)
    components = []
    for component in range(3):
        groups = [
            losses[annotations[:, component] == label, component].mean()
            for label in (0, 1)
            if (annotations[:, component] == label).any()
        ]
        if groups:
            components.append(torch.stack(groups).mean())
    return torch.stack(components).mean() if components else losses.sum() * 0


def group_coefficients(annotations):
    """Actual group coefficients before the fixed domain weight, not global balance."""
    counts = np.asarray(
        [[(annotations[:, c] == label).sum() for label in (0, 1)] for c in range(3)]
    )
    present = counts > 0
    components = present.any(axis=1).sum()
    coefficients = np.zeros((3, 2), dtype=np.float64)
    if components:
        for component in range(3):
            if present[component].any():
                coefficients[component, present[component]] = (
                    1 / components / present[component].sum()
                )
    return counts, coefficients


def paired_batches(ompal_count, native_lengths, *, batch_size, seed):
    """Each OMPAL root once; native batches cycle without inventing new roots."""
    if ompal_count <= 0 or not native_lengths or batch_size <= 0:
        raise ValueError("SEQUENCE_ADAPT_EMPTY_SAMPLER")
    rng = np.random.default_rng(seed)
    ompal = rng.permutation(ompal_count).tolist()
    order = sorted(range(len(native_lengths)), key=native_lengths.__getitem__)
    native_batches = [order[i : i + batch_size] for i in range(0, len(order), batch_size)]
    cursor = len(native_batches)
    for start in range(0, ompal_count, batch_size):
        if cursor == len(native_batches):
            rng.shuffle(native_batches)
            cursor = 0
        yield ompal[start : start + batch_size], list(native_batches[cursor])
        cursor += 1


def _verify_cache_identity(cache, metadata, manifest):
    identity = json.loads((cache / "identity.json").read_text())
    if (
        metadata["identitySha256"] != fingerprint(cache / "identity.json")
        or metadata["manifestSha256"] != fingerprint(manifest)
        or metadata["sourceWeightsSha256"] != FILES["model.pt"]
        or metadata.get("testUsed") is not False
        or any(metadata.get(k) != v for k, v in identity.items())
    ):
        raise ValueError("SEQUENCE_ADAPT_CACHE_IDENTITY_MISMATCH")


def _native_items(cache, manifest, native_vocab):
    metadata = json.loads((cache / "cache.json").read_text())
    _verify_cache_identity(cache, metadata, manifest)
    rows = _native_manifest(manifest)
    sources = {r["id"]: r for r in rows}
    validate_cached_labels(metadata, rows, native_vocab, cache)
    if metadata["configurationSha256"] != fingerprint(NATIVE_CONFIG):
        raise ValueError("SEQUENCE_ADAPT_NATIVE_CONFIGURATION_CHANGED")
    items = []
    for row in metadata["items"]:
        path = Path(row["file"])
        audio = row["audio"]
        if (
            path.resolve() != (cache / (row["id"] + ".npz")).resolve()
            or audio["sourceSha256"] != sources[row["id"]]["sha256"]
            or Path(audio["file"]).resolve() != (cache / "audio" / (row["id"] + ".wav")).resolve()
            or fingerprint(Path(audio["file"])) != audio["sha256"]
            or fingerprint(path) != row["sha256"]
        ):
            raise ValueError("SEQUENCE_ADAPT_NATIVE_PREFIX_CHANGED")
        with read_cached(path, metadata["identitySha256"]) as value:
            prefix = torch.from_numpy(value["prefix"].copy())
        items.append({**row, "prefix": prefix})
    return items, metadata


def _ompal_items(cache, manifest, native_vocab):
    metadata = json.loads((cache / "cache.json").read_text())
    _verify_cache_identity(cache, metadata, manifest)
    rows = [r for r in read_rows(manifest) if r["split"] == "train"]
    items, excluded = [], []
    for row in rows:
        if (
            row.get("numericalQualityFlags")
            or row.get("labelPolicyFlags")
            or row.get("placeholder")
        ):
            excluded.append({"id": row["id"], "reason": "PREDECLARED_UNASSESSABLE"})
            continue
        try:
            targets, annotations = _labels(row, native_vocab, native_rime_aliases("hanziflow"))
        except ValueError as error:
            excluded.append({"id": row["id"], "reason": str(error)})
            continue
        # Labels always come from the SHA-bound source manifest, never cache metadata.
        with read_cached(cache / (row["sha256"] + ".npz"), metadata["identitySha256"]) as value:
            prefix = torch.from_numpy(value["prefix"].copy())
        items.append(
            {
                "id": row["id"],
                "speakerId": row["speakerId"],
                "prefix": prefix,
                "targets": targets,
                "annotations": annotations,
            }
        )
    return items, excluded, metadata


def validate_inputs(config, initializer, native_manifest, ompal_manifest):
    paths = {
        "initializerMetadataSha256": initializer / "tuned.json",
        "initializerWeightsSha256": initializer / "tuned.safetensors",
        "nativeManifestSha256": native_manifest,
        "ompalManifestSha256": ompal_manifest,
        "nativeDataConfigurationSha256": NATIVE_DATA_CONFIG,
        "ompalDataConfigurationSha256": OMPAL_DATA_CONFIG,
    }
    if any(config[key] != fingerprint(path) for key, path in paths.items()):
        raise ValueError("SEQUENCE_ADAPT_PINNED_INPUT_CHANGED")


def validate_initializer_caches(parent, native_cache, ompal_cache):
    if parent.get("nativeCacheMetadataSha256") != fingerprint(
        native_cache / "cache.json"
    ) or parent.get("calibrationPrefixSha256") != fingerprint(ompal_cache / "cache.json"):
        raise ValueError("SEQUENCE_ADAPT_INITIALIZER_CACHE_CHANGED")


def _data_record(config_path, manifest, items, excluded, cache):
    source = json.loads(config_path.read_text())
    return {
        "datasetId": source["datasetId"],
        "source": source["source"],
        "revision": source["revision"],
        "license": source["license"],
        "citation": source["citation"],
        "configurationSha256": fingerprint(config_path),
        "manifestSha256": fingerprint(manifest),
        "prefixCacheMetadataSha256": fingerprint(cache / "cache.json"),
        "uniqueTrainingRoots": len(items),
        "uniqueTrainingSpeakers": len({r["speakerId"] for r in items}),
        "rootIds": [r["id"] for r in items],
        "excluded": excluded,
        "finalTestUsed": False,
    }


def _snapshot(tail, heads):
    return {
        **{"tail." + k: v.detach().cpu().clone() for k, v in tail.state_dict().items()},
        **{"heads." + k: v.detach().cpu().clone() for k, v in heads.state_dict().items()},
    }


def _changes(checkpoint, initial):
    return {k: float((v - initial[k]).abs().max()) for k, v in checkpoint.items()}


def train(
    initializer,
    native_cache,
    native_manifest,
    ompal_cache,
    ompal_manifest,
    source,
    output,
    *,
    device,
    config_path=CONFIG,
):
    if output.exists():
        raise ValueError("SEQUENCE_ADAPT_OUTPUT_EXISTS")
    config = configuration(config_path)
    validate_inputs(config, initializer, native_manifest, ompal_manifest)
    validate_initializer_caches(
        json.loads((initializer / "tuned.json").read_text()), native_cache, ompal_cache
    )
    native_vocab = vocabularies(initializer)
    native_items, native_metadata = _native_items(native_cache, native_manifest, native_vocab)
    ompal_items, ompal_excluded, ompal_metadata = _ompal_items(
        ompal_cache, ompal_manifest, native_vocab
    )
    if any(
        native_metadata["nativeVocabularySha256"][name] != fingerprint(initializer / name)
        for name in VOCAB_FILES
    ):
        raise ValueError("SEQUENCE_ADAPT_NATIVE_VOCABULARY_CHANGED")
    cal_rows, cal_items, cal_excluded, _ = _calibration_items(
        ompal_manifest, ompal_cache, native_vocab
    )
    if not native_items or not ompal_items or not cal_items:
        raise ValueError("SEQUENCE_ADAPT_EMPTY_INPUT")
    torch.manual_seed(config["seed"])
    torch.set_num_threads(2)
    evidence = NativeSequenceEvidence(initializer, source=source, device="cpu")
    parent = evidence.metadata
    if parent["manifestSha256"] != fingerprint(ompal_manifest):
        raise ValueError("SEQUENCE_ADAPT_INITIALIZER_SPLIT_CHANGED")
    frozen = state_digest(FrozenPrefix(evidence.encoder))
    if any(m["prefixStateSha256"] != frozen for m in (native_metadata, ompal_metadata)):
        raise ValueError("SEQUENCE_ADAPT_FROZEN_PREFIX_MISMATCH")
    tail, heads = TrainableTail(evidence.encoder).to(device), evidence.heads.to(device)
    tail.requires_grad_(True)
    heads.requires_grad_(True)
    del evidence
    gc.collect()
    initial_checkpoint = _snapshot(tail, heads)
    checkpoint = {k: v.clone() for k, v in initial_checkpoint.items()}
    optimizer = torch.optim.AdamW(
        [
            {"params": heads.parameters(), "lr": config["headLearningRate"]},
            {"params": tail.parameters(), "lr": config["tailLearningRate"]},
        ],
        weight_decay=config["weightDecay"],
    )
    output.mkdir(parents=True)
    shutil.copy2(config_path, output / "adaptation-config.json")
    shutil.copy2(initializer / "tuned.json", output / "initializer-tuned.json")
    data_record = {
        "native": _data_record(
            NATIVE_DATA_CONFIG,
            native_manifest,
            native_items,
            native_metadata["excluded"],
            native_cache,
        ),
        "ompal": _data_record(
            OMPAL_DATA_CONFIG, ompal_manifest, ompal_items, ompal_excluded, ompal_cache
        ),
        "limitation": (
            "Corpus annotations and original segmentation may contain errors; cross-corpus "
            "person overlap and pretraining overlap cannot be disproved; no child validation."
        ),
    }
    data_record["ompal"]["componentAnnotationCounts"] = group_coefficients(
        np.asarray([r["annotations"] for r in ompal_items])
    )[0].tolist()
    write(output / "training-data.json", data_record)
    generic_vocab = parent["vocabulary"]
    initial, _ = calibration(
        tail,
        heads,
        cal_items,
        cal_rows,
        generic_vocab,
        native_vocab,
        device,
        config["batchSizePerDomain"],
    )
    history = [{"epoch": 0, "trainingPerformed": False, **initial}]
    write(output / "training.json", history)
    print(json.dumps(history[-1]), flush=True)
    best, selected = initial["balancedSignedCtcLoss"], 0
    native_lengths = [len(r["prefix"]) for r in native_items]
    exposures = []
    started = time.perf_counter()
    for epoch in range(config["epochs"]):
        tail.train()
        heads.train()
        losses, native_losses, ompal_losses = [], [], []
        native_seen, ompal_seen = Counter(), Counter()
        first_grad = None
        group_batches, group_weights = np.zeros((3, 2), dtype=np.int64), np.zeros((3, 2))
        for ompal_indices, native_indices in paired_batches(
            len(ompal_items),
            native_lengths,
            batch_size=config["batchSizePerDomain"],
            seed=config["seed"] + epoch,
        ):
            native_batch, ompal_batch = (
                [native_items[i] for i in native_indices],
                [ompal_items[i] for i in ompal_indices],
            )
            native_output, native_lengths_batch = _forward(tail, heads, native_batch, device)
            native_loss = (
                sequence_ctc_loss(
                    native_output, native_lengths_batch, [r["targets"] for r in native_batch]
                )
                / 3
            )
            ompal_output, ompal_lengths = _forward(tail, heads, ompal_batch, device)
            ompal_loss = balanced_expert_loss(
                ompal_output,
                ompal_lengths,
                [r["targets"] for r in ompal_batch],
                torch.tensor([r["annotations"] for r in ompal_batch]),
            )
            loss = config["nativeLossWeight"] * native_loss + config["ompalLossWeight"] * ompal_loss
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            if first_grad is None:
                first_grad = {
                    "tail": sum(
                        float(p.grad.abs().sum()) for p in tail.parameters() if p.grad is not None
                    ),
                    "heads": sum(
                        float(p.grad.abs().sum()) for p in heads.parameters() if p.grad is not None
                    ),
                }
            nn.utils.clip_grad_norm_(
                [*tail.parameters(), *heads.parameters()],
                config["gradientClip"],
                error_if_nonfinite=True,
            )
            optimizer.step()
            native_seen.update(r["id"] for r in native_batch)
            ompal_seen.update(r["id"] for r in ompal_batch)
            group_counts, coefficients = group_coefficients(
                np.asarray([r["annotations"] for r in ompal_batch])
            )
            group_batches += group_counts > 0
            group_weights += config["ompalLossWeight"] * coefficients
            losses.append(float(loss.detach()))
            native_losses.append(float(native_loss.detach()))
            ompal_losses.append(float(ompal_loss.detach()))
        result, _ = calibration(
            tail,
            heads,
            cal_items,
            cal_rows,
            generic_vocab,
            native_vocab,
            device,
            config["batchSizePerDomain"],
        )
        record = {
            "epoch": epoch + 1,
            "trainingPerformed": True,
            "pairedBatches": len(losses),
            "trainLoss": float(np.mean(losses)),
            "nativeLoss": float(np.mean(native_losses)),
            "ompalLoss": float(np.mean(ompal_losses)),
            "nativeRootExposures": native_seen.total(),
            "nativeUniqueRoots": len(native_seen),
            "ompalRootExposures": ompal_seen.total(),
            "ompalUniqueRoots": len(ompal_seen),
            "componentGroupPresentBatches": group_batches.tolist(),
            "componentGroupCoefficientSumsIncludingDomainWeight": group_weights.tolist(),
            "firstBatchGradientAbsoluteSums": first_grad,
            **result,
        }
        history.append(record)
        exposures.append(
            {"epoch": epoch + 1, "native": dict(native_seen), "ompal": dict(ompal_seen)}
        )
        if result["balancedSignedCtcLoss"] < best:
            best, selected = result["balancedSignedCtcLoss"], epoch + 1
            checkpoint = _snapshot(tail, heads)
        write(output / "training.json", history)
        write(output / "training-exposures.json", exposures)
        print(json.dumps(record), flush=True)
    last_changes = _changes(_snapshot(tail, heads), initial_checkpoint)
    tail.load_state_dict({k[5:]: v for k, v in checkpoint.items() if k.startswith("tail.")})
    heads.load_state_dict({k[6:]: v for k, v in checkpoint.items() if k.startswith("heads.")})
    result, probabilities = calibration(
        tail,
        heads,
        cal_items,
        cal_rows,
        generic_vocab,
        native_vocab,
        device,
        config["batchSizePerDomain"],
    )
    labels = np.asarray(
        [
            [
                generic_vocab[k].index(str(r[k])) if str(r[k]) in generic_vocab[k] else -1
                for k in COMPONENTS
            ]
            for r in cal_rows
        ]
    )
    summary = calibrate(list(zip(*probabilities, strict=True)), labels, rows=cal_rows)
    save_file(checkpoint, output / "tuned.safetensors")
    resources = [name for name in parent["files"] if name != "tuned.safetensors"]
    for name in resources:
        shutil.copy2(initializer / name, output / name)
    resources += [
        "tuned.safetensors",
        "adaptation-config.json",
        "training-data.json",
        "initializer-tuned.json",
    ]
    metadata = {
        **parent,
        "trainingRecipe": config["experimentId"],
        "adaptationConfiguration": config,
        "adaptationConfigurationSha256": fingerprint(config_path),
        "initializerMetadataSha256": fingerprint(initializer / "tuned.json"),
        "initializerWeightsSha256": fingerprint(initializer / "tuned.safetensors"),
        "initializerImplementationSha256": parent["implementationSha256"],
        "files": {
            name: {"sha256": fingerprint(output / name), "bytes": (output / name).stat().st_size}
            for name in resources
        },
        "trainingUtterances": len(native_items) + len(ompal_items),
        "trainingSpeakers": len({r["speakerId"] for r in native_items})
        + len({r["speakerId"] for r in ompal_items}),
        "trainingCountsByDomain": {
            k: {field: value[field] for field in ("uniqueTrainingRoots", "uniqueTrainingSpeakers")}
            for k, value in data_record.items()
            if k in {"native", "ompal"}
        },
        "calibrationRows": len(cal_rows),
        "calibrationLossRows": len(cal_items),
        "calibrationExclusions": cal_excluded,
        "initialCalibration": initial,
        "selectedEpoch": selected,
        "selectedCalibration": result,
        "trainingSeconds": time.perf_counter() - started,
        "frozenPrefixStateSha256": frozen,
        "frozenPrefixUsedOnlyAsCachedConstant": True,
        "lastEpochTailTensorMaximumChanges": {
            k[5:]: v for k, v in last_changes.items() if k.startswith("tail.")
        },
        "lastEpochHeadTensorMaximumChanges": {
            k[6:]: v for k, v in last_changes.items() if k.startswith("heads.")
        },
        "selectedTailTensorMaximumChanges": {
            k[5:]: v
            for k, v in _changes(checkpoint, initial_checkpoint).items()
            if k.startswith("tail.")
        },
        "selectedHeadTensorMaximumChanges": {
            k[6:]: v
            for k, v in _changes(checkpoint, initial_checkpoint).items()
            if k.startswith("heads.")
        },
        "implementationSha256": fingerprint(Path(__file__)),
        "implementationDependencies": {
            name: fingerprint(Path(__file__).with_name(name))
            for name in (
                "pretrained_native_sequence.py",
                "pretrained_tail_finetune.py",
                "pretrained_finetune.py",
            )
        },
        "trainingHistorySha256": fingerprint(output / "training.json"),
        "trainingExposuresSha256": fingerprint(output / "training-exposures.json"),
        "testUsed": False,
        "qualityEvidence": "Cached prefix calibration only; full CPU export evaluation pending.",
    }
    write(output / "calibration.json", summary)
    write(output / "tuned.json", metadata)
    return {
        k: metadata[k]
        for k in ("trainingRecipe", "selectedEpoch", "trainingSeconds", "trainingUtterances")
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in (
        "initializer",
        "native-cache",
        "native-manifest",
        "ompal-cache",
        "ompal-manifest",
        "source",
        "output",
    ):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    parser.add_argument("--config", dest="config_path", type=Path, default=CONFIG)
    print(json.dumps(train(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
