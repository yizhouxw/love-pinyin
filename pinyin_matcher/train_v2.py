"""Masked phonetic pretraining on synthetic roots and licensed standard anchors."""

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import FEATURE_VERSION, decode_wav, features
from pinyin_matcher.catalog import CATALOG, ROOT, fingerprint, load_catalog, targets_by_id
from pinyin_matcher.data import augment, dataset_digest
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.train import prepare, quantize


def validate_combined_splits(rows: list[dict]):
    """Check all input manifests together, including waveform/parent role changes.

    The explicitly same-teacher standard anchors use a phonetic-group split;
    this exception applies only to their shared voice ID, never source audio.
    """
    seen = {}
    for row in rows:
        fields = ["sourceRootId", "sourceSha256", "sourceWavSha256", "parentSha256", "sha256"]
        if row["origin"] != "standard":
            fields.extend(["voiceFamilyId", "referenceRootId", "referenceSha256"])
        if row["origin"] == "foreign":
            fields.append("lexicalRootId")
        for field in fields:
            if value := row.get(field):
                kind = "waveform" if field.endswith("Sha256") or field == "sha256" else field
                key = (kind, value)
                if seen.setdefault(key, row["split"]) != row["split"]:
                    raise ValueError("COMBINED_DATASET_LINEAGE_SPLIT_LEAK")


def contrast_loss(onset, rime, labels, targets, onsets, rimes):
    """Foreign intent only refutes explicit target pairs; it does not label phones.

    An English/French word can share a Mandarin vowel or consonant. Assigning
    both branches an invented unknown transcription would discard that fact.
    """
    import torch

    op, rp = onset.softmax(-1), rime.softmax(-1)
    terms = []
    for i, label in enumerate(labels):
        for key in label.get("againstTargetIds", []):
            target = targets[key]
            probability = op[i, onsets.index(target["onset"])] * rp[i, rimes.index(target["rime"])]
            terms.append(-torch.log1p(-probability.clamp(max=1 - 1e-6)))
    return torch.stack(terms).mean() if terms else onset.sum() * 0


def dataset(
    manifest: Path,
    anchors: Path,
    cache: Path,
    foreign: tuple[Path, ...] = (),
    derived: tuple[Path, ...] = (),
):
    rows, arrays = prepare(manifest, cache)
    rows = [
        {**row, "origin": "synthetic", "path": str(manifest.parent / row["file"])} for row in rows
    ]
    standard = json.loads(anchors.read_text())
    if standard.get("cohort") != "licensed-PinYinSound-standard-anchors-not-child":
        raise ValueError("EXPLICIT_STANDARD_ANCHORS_REQUIRED")
    for index, original in enumerate(standard["items"]):
        path = (anchors.parent / original["file"]).resolve()
        if (
            not path.is_relative_to(anchors.parent.resolve())
            or fingerprint(path) != original["sha256"]
        ):
            raise ValueError("STANDARD_ANCHOR_DIGEST_MISMATCH")
        row = {
            **original,
            "id": "standard-" + original["id"],
            "origin": "standard",
            "generator": "pinyinsound",
            "voiceFamilyId": "pinyinsound-same-source",
            "path": str(path),
            "seed": 420000 + index,
        }
        location = cache / (row["sha256"] + "-standard-v2.npz")
        if location.exists():
            with np.load(location, allow_pickle=False) as saved:
                arrays[row["id"]] = [saved[key] for key in sorted(saved.files)]
        else:
            samples = decode_wav(path.read_bytes())
            versions = [features(samples)[0]]
            if row["split"] == "train":
                versions.extend(
                    features(augment(samples, row["seed"] + i), check=False)[0] for i in range(3)
                )
            np.savez_compressed(location, **{f"v{i}": value for i, value in enumerate(versions)})
            arrays[row["id"]] = versions
        rows.append(row)
    if foreign:
        from pinyin_matcher.foreign_data import read_manifest

        for source in foreign:
            for original in read_manifest(source):
                path = (source.parent / original["file"]).resolve()
                row = {**original, "origin": "foreign", "path": str(path)}
                if row["id"] in arrays:
                    raise ValueError("DUPLICATE_AUDIO_ROOT")
                location = cache / (row["sha256"] + "-foreign-v2.npz")
                if location.exists():
                    with np.load(location, allow_pickle=False) as saved:
                        arrays[row["id"]] = [saved[key] for key in sorted(saved.files)]
                else:
                    samples = decode_wav(path.read_bytes())
                    versions = [features(samples, check=False)[0]]
                    if row["split"] == "train":
                        versions.extend(
                            features(augment(samples, row["seed"] + i), check=False)[0]
                            for i in range(3)
                        )
                    np.savez_compressed(location, **{f"v{i}": x for i, x in enumerate(versions)})
                    arrays[row["id"]] = versions
                rows.append(row)
    if derived:
        from pinyin_matcher.data import read_manifest

        anchor_splits = {row["sourceSha256"]: row["split"] for row in standard["items"]}
        source_targets = {row["sourceSha256"]: row["targetId"] for row in standard["items"]}
        controlled = json.loads((ROOT / "content/pronunciation-contrast-training.json").read_text())
        pilot_calibration = {
            row["standardSource"]["sourceSha256"]: row["id"]
            for row in controlled["definitions"]
            if (row.get("standardSource") or {}).get("allocation") == "calibration"
        }
        source_targets.update(pilot_calibration)
        for source in derived:
            for original in read_manifest(source):
                if (
                    original.get("generationMode") != "vc"
                    or original.get("independentRoot") is not False
                    or not original.get("sourceSha256")
                    or original["split"] not in {"train", "calibration"}
                    or original.get("sourceAllocation") != original["split"]
                    or source_targets.get(original["sourceSha256"]) != original["targetId"]
                    or original["split"] == "train"
                    and anchor_splits.get(original["sourceSha256"]) != "train"
                    or original["sourceSha256"] in anchor_splits
                    and anchor_splits[original["sourceSha256"]] != original["split"]
                ):
                    raise ValueError("DERIVED_STANDARD_SPLIT_OR_PROVENANCE_INVALID")
                row = {
                    **original,
                    "origin": "standard-vc",
                    "path": str((source.parent / original["file"]).resolve()),
                }
                if row["id"] in arrays:
                    raise ValueError("DUPLICATE_AUDIO_ROOT")
                location = cache / (row["sha256"] + "-standard-vc-v2.npz")
                if location.exists():
                    with np.load(location, allow_pickle=False) as saved:
                        arrays[row["id"]] = [saved[key] for key in sorted(saved.files)]
                else:
                    samples = decode_wav(Path(row["path"]).read_bytes())
                    versions = [features(samples, check=False)[0]]
                    if row["split"] == "train":
                        versions.append(features(augment(samples, row["seed"]), check=False)[0])
                    np.savez_compressed(location, **{f"v{i}": x for i, x in enumerate(versions)})
                    arrays[row["id"]] = versions
                rows.append(row)
    validate_combined_splits(rows)
    return rows, arrays


def train(
    manifest: Path,
    anchors: Path,
    output: Path,
    cache: Path,
    *,
    epochs=None,
    resume: Path | None = None,
    device="auto",
    foreign: tuple[Path, ...] = (),
    derived: tuple[Path, ...] = (),
    configuration: Path | None = None,
    export_only: bool = False,
):
    import torch
    from torch import nn

    from pinyin_matcher.acoustic_v2 import AcousticMatcherV2

    configuration = configuration or ROOT / "content/pronunciation-training-v2.json"
    config = json.loads(configuration.read_text())
    if resume:
        config["learningRate"] = config.get("fineTuneLearningRate", 0.0002)
    random.seed(config["seed"])
    np.random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    torch.set_num_threads(4)
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    rows, arrays = dataset(manifest, anchors, cache, foreign, derived)
    directory = load_catalog()
    targets = targets_by_id(directory)
    onsets = sorted({target["onset"] for target in targets.values()} | {"<unknown>"})
    rimes = sorted({target["rime"] for target in targets.values()} | {"<unknown>"})
    tokens = directory["tokens"]
    model = AcousticMatcherV2(
        len(tokens),
        len(onsets),
        len(rimes),
        config["hiddenSize"],
        config["blocks"],
        config["expansion"],
    )
    if resume:
        model.load_state_dict(torch.load(resume, map_location="cpu", weights_only=True))
    elif export_only:
        raise ValueError("EXPORT_REQUIRES_EXPLICIT_CHECKPOINT")
    model.to(device)
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(
        output / "run-inputs.json",
        {
            "resumeCheckpointSha256": fingerprint(resume) if resume else None,
            "syntheticManifestPath": str(manifest.resolve()),
            "standardManifestPath": str(anchors.resolve()),
            "syntheticManifestSha256": fingerprint(manifest),
            "standardManifestSha256": fingerprint(anchors),
            "foreignManifestSha256": {str(path): fingerprint(path) for path in foreign},
            "derivedManifestSha256": {str(path): fingerprint(path) for path in derived},
        },
    )
    (output / "targets.json").write_bytes(CATALOG.read_bytes())
    train_rows = [row for row in rows if row["split"] == "train"]
    pool = [
        row
        for row in train_rows
        for _ in range(
            config.get("coverageExtensionSamplingWeight", 24)
            if row.get("phoneticCoverageExtension") and row["origin"] == "standard"
            else config.get("coverageExtensionVcSamplingWeight", 8)
            if row.get("phoneticCoverageExtension") and row["origin"] == "standard-vc"
            else config["standardSamplingWeight"]
            if row["origin"] == "standard"
            else config.get("foreignSamplingWeight", 4)
            if row["origin"] == "foreign"
            else 1
        )
    ]
    calibration = [row for row in rows if row["split"] == "calibration"]
    count = 0 if export_only else epochs or config["epochs"]
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learningRate"], weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, max(count, 1))
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    ce = nn.CrossEntropyLoss(label_smoothing=0.02)
    silence = features(np.zeros(2400, dtype=np.float32), check=False)[0][:12]

    def batch(group, training):
        values = [
            random.choice(arrays[row["id"]]).copy() if training else arrays[row["id"]][0].copy()
            for row in group
        ]
        labels = [
            {
                "phones": [],
                "onset": None,
                "rime": None,
                "tone": -100,
                "againstTargetIds": row["againstTargetIds"],
            }
            if row["origin"] == "foreign"
            else targets[row["targetId"]]
            for row in group
        ]
        if training:
            for value in values:
                if random.random() < 0.6:
                    positions = np.clip(
                        np.arange(64) * random.uniform(*config["vocalTractWarp"]), 0, 63
                    )
                    value[:, :64] = np.stack(
                        [np.interp(positions, np.arange(64), frame) for frame in value[:, :64]]
                    )
            for i in range(0, max(len(values) - 1, 0), 5):
                if not labels[i]["phones"] or not labels[i + 1]["phones"]:
                    continue
                values[i] = np.concatenate([values[i], silence, values[i + 1]])
                labels[i] = {
                    **labels[i],
                    "phones": labels[i]["phones"] + labels[i + 1]["phones"],
                    "onset": None,
                    "rime": None,
                    "tone": -100,
                }
        lengths = torch.tensor([len(value) for value in values], dtype=torch.long)
        result = np.zeros((len(values), int(lengths.max()), 68), dtype=np.float32)
        for i, value in enumerate(values):
            result[i, : len(value), :64] = value[:, :64]
        return torch.from_numpy(result).to(device), lengths.to(device), labels

    history = []
    if export_only:
        torch.save(model.cpu().state_dict(), output / "checkpoint.pt")
        model.to(device)
    best = float("inf")
    best_epoch = 0
    for epoch in range(count):
        started = time.monotonic()
        model.train()
        random.shuffle(pool)
        losses = []
        for start in range(0, len(pool), config["batchSize"]):
            value, lengths, labels = batch(pool[start : start + config["batchSize"]], True)
            phone, onset, rime, tone = model(value, lengths)
            known = [i for i, label in enumerate(labels) if label["phones"]]
            phonetic = (
                ctc(
                    phone[known].log_softmax(-1).transpose(0, 1).cpu(),
                    torch.tensor(
                        [tokens.index(token) for i in known for token in labels[i]["phones"]]
                    ),
                    lengths[known].cpu(),
                    torch.tensor([len(labels[i]["phones"]) for i in known]),
                )
                if known
                else phone.sum() * 0
            )
            onset_labels = torch.tensor(
                [
                    onsets.index(label["onset"]) if label["onset"] is not None else -100
                    for label in labels
                ],
                device=device,
            )
            rime_labels = torch.tensor(
                [
                    rimes.index(label["rime"]) if label["rime"] is not None else -100
                    for label in labels
                ],
                device=device,
            )
            tone_labels = torch.tensor([label["tone"] for label in labels], device=device)
            loss = (
                config["ctcLossWeight"] * phonetic.to(device)
                + (
                    ce(onset[onset_labels != -100], onset_labels[onset_labels != -100])
                    if (onset_labels != -100).any()
                    else onset.sum() * 0
                )
                + (
                    ce(rime[rime_labels != -100], rime_labels[rime_labels != -100])
                    if (rime_labels != -100).any()
                    else rime.sum() * 0
                )
                + contrast_loss(onset, rime, labels, targets, onsets, rimes)
                + config["auxiliaryToneLossWeight"]
                * (
                    ce(tone[tone_labels != -100], tone_labels[tone_labels != -100])
                    if (tone_labels != -100).any()
                    else tone.sum() * 0
                )
            )
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        scheduler.step()
        model.eval()
        validation = []
        correct = [0, 0]
        total = 0
        sources = {}
        with torch.no_grad():
            for start in range(0, len(calibration), 32):
                group = calibration[start : start + 32]
                value, lengths, labels = batch(group, False)
                _, onset, rime, _ = model(value, lengths)
                actual_onset = torch.tensor(
                    [
                        onsets.index(label["onset"]) if label["onset"] is not None else -100
                        for label in labels
                    ],
                    device=device,
                )
                actual_rime = torch.tensor(
                    [
                        rimes.index(label["rime"]) if label["rime"] is not None else -100
                        for label in labels
                    ],
                    device=device,
                )
                valid = actual_onset != -100
                loss = contrast_loss(onset, rime, labels, targets, onsets, rimes)
                if valid.any():
                    loss += ce(onset[valid], actual_onset[valid]) + ce(
                        rime[valid], actual_rime[valid]
                    )
                validation.append(float(loss.cpu()))
                oc = (onset.argmax(-1) == actual_onset).cpu().numpy()
                rc = (rime.argmax(-1) == actual_rime).cpu().numpy()
                correct[0] += int(oc.sum())
                correct[1] += int(rc.sum())
                total += int(valid.sum())
                for i, row in enumerate(group):
                    if row["origin"] == "foreign":
                        continue
                    counter = sources.setdefault(row["origin"], [0, 0, 0])
                    counter[0] += int(oc[i])
                    counter[1] += int(rc[i])
                    counter[2] += 1
        score = float(np.mean(validation))
        record = {
            "epoch": epoch + 1,
            "trainingLoss": float(np.mean(losses)),
            "calibrationContentLoss": score,
            "calibrationOnsetRimeAccuracy": [x / total for x in correct],
            "bySource": sources,
            "seconds": time.monotonic() - started,
        }
        history.append(record)
        print(json.dumps(record), flush=True)
        if score < best:
            best = score
            best_epoch = epoch + 1
            torch.save(model.cpu().state_dict(), output / "checkpoint.pt")
            model.to(device)
        atomic_json(
            output / "training.json",
            {
                "configuration": config,
                "configurationSha256": fingerprint(configuration),
                "bestEpoch": best_epoch,
                "history": history,
                "trainingRoots": len(train_rows),
                "samplingPoolSize": len(pool),
                "calibrationRoots": len(calibration),
                "syntheticManifestSha256": dataset_digest(manifest),
                "standardManifestSha256": fingerprint(anchors),
                "foreignManifestSha256": {str(path): fingerprint(path) for path in foreign},
                "derivedManifestSha256": {str(path): fingerprint(path) for path in derived},
                "device": device,
            },
        )
    model.cpu().load_state_dict(
        torch.load(output / "checkpoint.pt", map_location="cpu", weights_only=True)
    )
    model.eval()
    example = arrays[calibration[0]["id"]][0].copy()
    example[:, 64:] = 0
    torch.onnx.export(
        model,
        (torch.from_numpy(example[None]), torch.tensor([len(example)])),
        output / "acoustic.fp32.onnx",
        input_names=["acoustic", "lengths"],
        output_names=["phones", "onset", "rime", "tone"],
        dynamic_axes={
            "acoustic": {0: "batch", 1: "frames"},
            "lengths": {0: "batch"},
            "phones": {0: "batch", 1: "frames"},
            "onset": {0: "batch"},
            "rime": {0: "batch"},
            "tone": {0: "batch"},
        },
        opset_version=17,
        dynamo=False,
    )
    metadata = {
        "version": "masked-phonetic-v2-unreleased",
        "status": "experimental",
        "file": "acoustic.fp32.onnx",
        "sha256": fingerprint(output / "acoustic.fp32.onnx"),
        "featureVersion": FEATURE_VERSION,
        "catalogFile": "targets.json",
        "catalogSha256": fingerprint(output / "targets.json"),
        "datasetSha256": dataset_digest(manifest),
        "standardDatasetSha256": fingerprint(anchors),
        "dataProvenance": json.loads((output / "run-inputs.json").read_text()),
        "coveredTargetIds": directory["pilotIds"],
        "onsets": onsets,
        "rimes": rimes,
        "toneEnabled": True,
        "toneValidated": False,
        "acousticInput": "mel-only",
        "architecture": "masked-frame-normalized-v2",
        "decisionVersion": 2,
        "thresholds": {"minimumScore": -8, "minimumMargin": 0.5, "minimumCtc": -1},
        "parameters": sum(p.numel() for p in model.parameters()),
    }
    atomic_json(output / "model.json", metadata)
    quant_arrays = {row["id"]: [arrays[row["id"]][0].copy()] for row in calibration}
    for values in quant_arrays.values():
        values[0][:, 64:] = 0
    quantize(output, calibration, quant_arrays)
    atomic_json(output / "model.int8.json", json.loads((output / "model.json").read_text()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--anchors", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--foreign", type=Path, action="append", default=[])
    parser.add_argument("--derived", type=Path, action="append", default=[])
    parser.add_argument("--configuration", type=Path)
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    args = parser.parse_args()
    train(
        args.manifest,
        args.anchors,
        args.output,
        args.cache_dir,
        epochs=args.epochs,
        resume=args.resume,
        device=args.device,
        foreign=tuple(args.foreign),
        derived=tuple(args.derived),
        configuration=args.configuration,
        export_only=args.export_only,
    )
