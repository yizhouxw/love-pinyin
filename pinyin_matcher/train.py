"""Offline training, independent calibration, CPU export and held-out evaluation."""

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import FEATURE_VERSION, decode_wav, features
from pinyin_matcher.catalog import CATALOG, ROOT, fingerprint, load_catalog, targets_by_id
from pinyin_matcher.data import AUGMENT_VERSION, augment, dataset_digest, read_manifest
from pinyin_matcher.generate import atomic_json


def merge_manifests(inputs: list[Path], output: Path):
    rows, rejected, quarantined, sources = [], [], [], []
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for source in inputs:
        for row in read_manifest(source):
            original = (source.parent / row["file"]).resolve()
            if not original.is_relative_to(output.parent):
                raise ValueError("MERGED_AUDIO_MUST_BE_INSIDE_DATASET")
            rows.append({**row, "file": str(original.relative_to(output.parent))})
        rejected.extend(json.loads(source.read_text()).get("rejected", []))
        for row in json.loads(source.read_text()).get("quarantined", []):
            original = (source.parent / row["file"]).resolve()
            if not original.is_relative_to(output.parent):
                raise ValueError("MERGED_AUDIO_MUST_BE_INSIDE_DATASET")
            quarantined.append({**row, "file": str(original.relative_to(output.parent))})
        sources.append({"file": str(source), "sha256": fingerprint(source)})
    atomic_json(
        output,
        {
            "version": 1,
            "cohort": "synthetic",
            "labelProvenance": "tts-intended",
            "items": rows,
            "rejected": rejected,
            "quarantined": quarantined,
            "sources": sources,
        },
    )
    read_manifest(output)


def prepare(manifest: Path, cache: Path):
    rows = read_manifest(manifest)
    cache.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for index, row in enumerate(rows):
        configuration = fingerprint(ROOT / "content/pronunciation-training.json")[:12]
        path = cache / (
            row["sha256"]
            + "-"
            + FEATURE_VERSION
            + "-"
            + AUGMENT_VERSION
            + "-"
            + configuration
            + ".npz"
        )
        if path.exists():
            with np.load(path, allow_pickle=False) as saved:
                arrays[row["id"]] = [saved[key] for key in sorted(saved.files)]
        else:
            samples = decode_wav((manifest.parent / row["file"]).read_bytes())
            versions = [features(samples)[0]]
            if row["split"] == "train":
                versions.extend(
                    features(augment(samples, row["seed"] + repeat), check=False)[0]
                    for repeat in range(3)
                )
            arrays[row["id"]] = versions
            np.savez_compressed(path, **{f"v{i}": array for i, array in enumerate(versions)})
        if index % 100 == 0:
            print(json.dumps({"prepared": index, "of": len(rows)}), flush=True)
    atomic_json(
        cache / "ready.json",
        {
            "datasetSha256": dataset_digest(manifest),
            "samples": len(rows),
            "featureVersion": FEATURE_VERSION,
        },
    )
    return rows, arrays


def train(
    manifest: Path,
    output: Path,
    *,
    epochs: int | None = None,
    device: str = "auto",
    generators: list[str] | None = None,
    augmentation: bool = True,
    cache_directory: Path | None = None,
    evaluate_test: bool = True,
):
    import torch
    from torch import nn

    from pinyin_matcher.network import AcousticMatcher

    config = json.loads((ROOT / "content/pronunciation-training.json").read_text())
    seed = config["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(4)
    output.mkdir(parents=True, exist_ok=True)
    rows, arrays = prepare(manifest, cache_directory or output / "feature-cache")
    selected_generators = set(generators or ["qwen", "cosy"])
    rows = [row for row in rows if row["generator"] in selected_generators]
    train_rows = [row for row in rows if row["split"] == "train"]
    calibration = [row for row in rows if row["split"] == "calibration"]
    test = [row for row in rows if row["split"] == "test"]
    covered = sorted({row["targetId"] for row in train_rows})
    if len(covered) < 2 or any(
        {row["targetId"] for row in group} != set(covered) for group in (calibration, test)
    ):
        raise ValueError("EVERY_TARGET_NEEDS_INDEPENDENT_CALIBRATION_AND_TEST")
    if {row["generator"] for row in rows} != selected_generators:
        raise ValueError("REQUESTED_GENERATOR_MISSING")
    frozen_catalog = output / "targets.json"
    frozen_catalog.write_bytes(CATALOG.read_bytes())
    directory = load_catalog(frozen_catalog)
    targets = targets_by_id(directory)
    onsets = sorted({targets[key]["onset"] for key in covered})
    rimes = sorted({targets[key]["rime"] for key in covered})
    tokens = directory["tokens"]
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = AcousticMatcher(
        len(tokens),
        len(onsets),
        len(rimes),
        config["hiddenSize"],
        config["blocks"],
        config["expansion"],
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learningRate"], weight_decay=0.01)
    max_epochs = epochs or config["maximumEpochs"]
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, max_epochs)
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    cross = nn.CrossEntropyLoss(label_smoothing=0.02)
    silence_frames = features(np.zeros(2400, dtype=np.float32), check=False)[0][:12]

    def batch(group, training):
        selected = [
            random.choice(arrays[row["id"]]) if training and augmentation else arrays[row["id"]][0]
            for row in group
        ]
        lengths = torch.tensor([len(value) for value in selected], dtype=torch.long)
        value = np.zeros((len(group), int(lengths.max()), 68), dtype=np.float32)
        for i, array in enumerate(selected):
            value[i, : len(array)] = array
        labels = [targets[row["targetId"]] for row in group]
        if training:
            # Teach CTC that additional speech contains additional phones. All
            # source examples stay in train; these pairs are not new root samples.
            for i in range(0, max(0, len(selected) - 1), 5):
                other = (i + 1) % len(selected)
                selected[i] = np.concatenate([selected[i], silence_frames, selected[other]])
                labels[i] = {
                    **labels[i],
                    "phones": labels[i]["phones"] + labels[other]["phones"],
                    "onset": None,
                    "rime": None,
                    "tone": -100,
                }
            lengths = torch.tensor([len(value) for value in selected], dtype=torch.long)
            value = np.zeros((len(group), int(lengths.max()), 68), dtype=np.float32)
            for i, array in enumerate(selected):
                value[i, : len(array)] = array
        return torch.from_numpy(value).to(device), lengths.to(device), labels

    best_loss, best_epoch, history = float("inf"), 0, []
    checkpoint = output / "checkpoint.pt"
    for epoch in range(max_epochs):
        model.train()
        random.shuffle(train_rows)
        losses = []
        started = time.monotonic()
        for start in range(0, len(train_rows), config["batchSize"]):
            group = train_rows[start : start + config["batchSize"]]
            value, lengths, labels = batch(group, True)
            phone, onset, rime, tone = model(value, lengths)
            phone_targets = [tokens.index(token) for item in labels for token in item["phones"]]
            ctc_loss = ctc(
                phone.log_softmax(-1).transpose(0, 1).cpu(),
                torch.tensor(phone_targets),
                lengths.cpu(),
                torch.tensor([len(item["phones"]) for item in labels]),
            )
            onset_loss = cross(
                onset,
                torch.tensor(
                    [
                        onsets.index(item["onset"]) if item["onset"] is not None else -100
                        for item in labels
                    ],
                    device=device,
                ),
            )
            rime_loss = cross(
                rime,
                torch.tensor(
                    [
                        rimes.index(item["rime"]) if item["rime"] is not None else -100
                        for item in labels
                    ],
                    device=device,
                ),
            )
            tone_loss = cross(tone, torch.tensor([item["tone"] for item in labels], device=device))
            loss = 0.5 * ctc_loss.to(device) + onset_loss + rime_loss + 0.7 * tone_loss
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        scheduler.step()
        model.eval()
        total, correct = 0, [0, 0, 0]
        validation_losses = []
        with torch.no_grad():
            for start in range(0, len(calibration), 32):
                group = calibration[start : start + 32]
                value, lengths, labels = batch(group, False)
                _, onset, rime, tone = model(value, lengths)
                expected = [
                    torch.tensor(
                        [
                            onsets.index(item["onset"]) if item["onset"] is not None else -100
                            for item in labels
                        ],
                        device=device,
                    ),
                    torch.tensor(
                        [
                            rimes.index(item["rime"]) if item["rime"] is not None else -100
                            for item in labels
                        ],
                        device=device,
                    ),
                    torch.tensor([item["tone"] for item in labels], device=device),
                ]
                validation_losses.append(
                    sum(
                        float(cross(logits, label).cpu())
                        for logits, label in zip((onset, rime, tone), expected, strict=True)
                    )
                )
                for i, (logits, label) in enumerate(
                    zip((onset, rime, tone), expected, strict=True)
                ):
                    correct[i] += int((logits.argmax(-1) == label).sum().cpu())
                total += len(group)
        score = float(np.mean(validation_losses))
        record = {
            "epoch": epoch + 1,
            "trainLoss": float(np.mean(losses)),
            "calibrationLoss": score,
            "calibrationComponentAccuracy": [n / total for n in correct],
            "seconds": round(time.monotonic() - started, 2),
        }
        history.append(record)
        print(json.dumps(record), flush=True)
        if score < best_loss:
            best_loss, best_epoch = score, epoch + 1
            torch.save(model.cpu().state_dict(), checkpoint)
            model.to(device)
        atomic_json(
            output / "training.json",
            {
                "datasetSha256": dataset_digest(manifest),
                "configuration": config,
                "device": device,
                "bestEpoch": best_epoch,
                "history": history,
                "parameters": sum(p.numel() for p in model.parameters()),
            },
        )
    model.cpu().load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    sample = arrays[calibration[0]["id"]][0]
    onnx_path = output / "acoustic.fp32.onnx"
    torch.onnx.export(
        model,
        (torch.from_numpy(sample[None]), torch.tensor([len(sample)])),
        onnx_path,
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
        "version": "synthetic-pilot-v1",
        "status": "experimental",
        "file": onnx_path.name,
        "sha256": fingerprint(onnx_path),
        "featureVersion": FEATURE_VERSION,
        "catalogSha256": fingerprint(frozen_catalog),
        "catalogFile": "targets.json",
        "datasetSha256": dataset_digest(manifest),
        "coveredTargetIds": covered,
        "onsets": onsets,
        "rimes": rimes,
        "toneEnabled": True,
        "toneValidated": False,
        "thresholds": {"minimumScore": -8, "minimumMargin": 0.5, "minimumCtc": -1},
        "parameters": sum(p.numel() for p in model.parameters()),
        "trainingCohort": "synthetic",
        "generatorSelection": sorted(selected_generators),
        "environmentAugmentation": augmentation,
        "decisionVersion": 2,
    }
    atomic_json(output / "model.json", metadata)
    calibrate(manifest, output, rows, arrays)
    fp32_calibration = json.loads((output / "calibration.json").read_text())
    atomic_json(output / "calibration.fp32.json", fp32_calibration)
    quantize(output, calibration, arrays)
    calibrate(manifest, output, rows, arrays)
    int8_calibration = json.loads((output / "calibration.json").read_text())
    atomic_json(output / "model.int8.json", json.loads((output / "model.json").read_text()))
    atomic_json(output / "calibration.int8.json", int8_calibration)
    # Choose precision on calibration, before exposing test results.
    if int8_calibration["utility"] < fp32_calibration["utility"] - 0.03:
        atomic_json(output / "model.json", json.loads((output / "model.fp32.json").read_text()))
    if evaluate_test:
        evaluate(manifest, output, split="test")


def calibrate(manifest, output, rows, arrays):
    from pinyin_matcher.inference import PinyinMatcher

    matcher = PinyinMatcher(output)
    records = []
    calibration_rows = [row for row in rows if row["split"] == "calibration"]

    def record_scores(row, value, challenge=False):
        scores = matcher._scores(value)
        ordered = sorted(scores, key=lambda key: scores[key]["score"], reverse=True)
        first, second = ordered[:2]
        records.append(
            {
                "correct": first == row["targetId"],
                "challenge": challenge,
                "score": scores[first]["score"],
                "margin": scores[first]["score"] - scores[second]["score"],
                "ctc": scores[first]["ctc"],
                "componentAgreement": scores[first]["componentAgreement"],
                "componentProbability": min(
                    scores[first]["onsetProbability"],
                    scores[first]["rimeProbability"],
                    scores[first]["toneProbability"],
                ),
                "freeCtcAdvantage": scores[first]["freeCtcAdvantage"],
            }
        )

    for index, row in enumerate(calibration_rows):
        record_scores(row, arrays[row["id"]][0])
        if index % 4 == 0:
            other = calibration_rows[(index + 13) % len(calibration_rows)]
            left = decode_wav((manifest.parent / row["file"]).read_bytes())
            right = decode_wav((manifest.parent / other["file"]).read_bytes())
            joined = np.concatenate([left, np.zeros(2400, dtype=np.float32), right])
            value, _ = features(joined)
            record_scores(row, value, challenge=True)
    positive_count = len(calibration_rows)
    challenge_count = len(records) - positive_count
    best = None
    for score in [-8, -4, -2, -1, -0.5]:
        for margin in [0, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3]:
            for ctc in [-3, -1, -0.5, -0.25, -0.1, -0.05]:
                for minimum_component in [0.35, 0.5, 0.65]:
                    for free_advantage in [0.01, 0.05, 0.1]:
                        accepted = [
                            r
                            for r in records
                            if r["score"] >= score
                            and r["margin"] >= margin
                            and r["ctc"] >= ctc
                            and r["componentAgreement"]
                            and r["componentProbability"] >= minimum_component
                            and r["freeCtcAdvantage"] <= free_advantage
                        ]
                        passed = (
                            sum(r["correct"] and not r["challenge"] for r in accepted)
                            / positive_count
                        )
                        wrong = (
                            sum(not r["correct"] and not r["challenge"] for r in accepted)
                            / positive_count
                        )
                        rejected = 1 - sum(not r["challenge"] for r in accepted) / positive_count
                        challenge_pass = sum(r["challenge"] for r in accepted) / max(
                            challenge_count, 1
                        )
                        utility = passed - 5 * wrong - 0.2 * rejected - 3 * challenge_pass
                        if best is None or utility > best[0]:
                            best = (
                                utility,
                                score,
                                margin,
                                ctc,
                                passed,
                                wrong,
                                rejected,
                                challenge_pass,
                                minimum_component,
                                free_advantage,
                            )
    (
        utility,
        score,
        margin,
        ctc,
        passed,
        wrong,
        rejected,
        challenge_pass,
        minimum_component,
        free_advantage,
    ) = best
    metadata = json.loads((output / "model.json").read_text())
    metadata["thresholds"] = {"minimumScore": score, "minimumMargin": margin, "minimumCtc": ctc}
    metadata["thresholds"].update(
        {
            "minimumComponentProbability": minimum_component,
            "maximumFreeCtcAdvantage": free_advantage,
        }
    )
    atomic_json(output / "model.json", metadata)
    atomic_json(
        output / "calibration.json",
        {
            "split": "calibration",
            "samples": positive_count,
            "extraSyllableChallenges": challenge_count,
            "extraSyllableFalsePass": challenge_pass,
            "utility": utility,
            "matchedFraction": passed,
            "wrongCandidateFraction": wrong,
            "uncertainFraction": rejected,
            "thresholds": metadata["thresholds"],
            "datasetSha256": dataset_digest(manifest),
        },
    )


def quantize(output, rows, arrays):
    from onnxruntime.quantization import (
        CalibrationDataReader,
        QuantFormat,
        QuantType,
        quantize_static,
    )
    from onnxruntime.quantization.shape_inference import quant_pre_process

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.iterator = iter(
                sorted(rows, key=lambda row: row["id"])[:: max(1, len(rows) // 128)][:128]
            )

        def get_next(self):
            row = next(self.iterator, None)
            if row is None:
                return None
            value = arrays[row["id"]][0]
            return {"acoustic": value[None], "lengths": np.array([len(value)], dtype=np.int64)}

    destination = output / "acoustic.int8.onnx"
    processed = output / "acoustic.preprocessed.onnx"
    quant_pre_process(str(output / "acoustic.fp32.onnx"), str(processed), auto_merge=True)
    quantize_static(
        str(processed),
        str(destination),
        Reader(),
        quant_format=QuantFormat.QDQ,
        activation_type=QuantType.QInt8,
        weight_type=QuantType.QInt8,
        per_channel=True,
        op_types_to_quantize=["Conv", "MatMul", "Gemm"],
    )
    metadata = json.loads((output / "model.json").read_text())
    metadata.update({"file": destination.name, "sha256": fingerprint(destination)})
    atomic_json(output / "model.fp32.json", json.loads((output / "model.json").read_text()))
    atomic_json(output / "model.json", metadata)


def evaluate(manifest: Path, output: Path, *, split="test"):
    from pinyin_matcher.inference import PinyinMatcher

    matcher = PinyinMatcher(output)
    rows = [row for row in read_manifest(manifest) if row["split"] == split]
    results = []
    for row in rows:
        result = matcher.match(
            row["targetId"], (manifest.parent / row["file"]).read_bytes(), include_evidence=True
        )
        results.append(
            {
                "sampleId": row["id"],
                "targetId": row["targetId"],
                "generator": row["generator"],
                "voiceFamilyId": row["voiceFamilyId"],
                **result,
            }
        )

    def metrics(group):
        count = len(group)
        candidates = [
            (matcher.targets[x["targetId"]], matcher.targets[x["candidateId"]])
            for x in group
            if x.get("candidateId") in matcher.targets
        ]
        return {
            "samples": count,
            "matched": sum(x["status"] == "matched" for x in group),
            "falseRetry": sum(x["status"] == "retry" for x in group),
            "uncertain": sum(x["status"] == "uncertain" for x in group),
            "unavailable": sum(x["status"] == "unavailable" for x in group),
            "candidateTop1Accuracy": sum(a["id"] == b["id"] for a, b in candidates) / max(count, 1),
            "candidateOnsetAccuracy": sum(a["onset"] == b["onset"] for a, b in candidates)
            / max(count, 1),
            "candidateRimeAccuracy": sum(a["rime"] == b["rime"] for a, b in candidates)
            / max(count, 1),
            "candidateToneAccuracy": sum(a["tone"] == b["tone"] for a, b in candidates)
            / max(count, 1),
            "candidateMissing": count - len(candidates),
            "falsePassOnHardestFoil": sum(
                x.get("candidateId") != x["targetId"] and x["status"] == "retry" for x in group
            )
            / max(count, 1),
        }

    report = {
        "split": split,
        "cohort": "synthetic-intended-labels",
        "datasetSha256": dataset_digest(manifest),
        "overall": metrics(results),
        "byGenerator": {
            key: metrics([r for r in results if r["generator"] == key])
            for key in sorted({r["generator"] for r in results})
        },
        "byTarget": {
            key: metrics([r for r in results if r["targetId"] == key])
            for key in sorted({r["targetId"] for r in results})
        },
        "byVoiceFamily": {
            key: metrics([r for r in results if r["voiceFamilyId"] == key])
            for key in sorted({r["voiceFamilyId"] for r in results})
        },
        "p95Milliseconds": float(
            np.percentile([r.get("durationMilliseconds", 0) for r in results], 95)
        ),
        "results": results,
        "realChildAccuracyEstablished": False,
    }
    atomic_json(output / f"evaluation-{split}.json", report)
    print(
        json.dumps({"evaluation": report["overall"], "p95Milliseconds": report["p95Milliseconds"]}),
        flush=True,
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("inputs", nargs="+", type=Path)
    merge.add_argument("--output", type=Path, required=True)
    for action in ["train", "evaluate"]:
        p = sub.add_parser(action)
        p.add_argument("--manifest", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if action == "train":
            p.add_argument("--epochs", type=int)
            p.add_argument("--device", choices=["auto", "cpu", "mps"], default="auto")
            p.add_argument("--generators", nargs="+", choices=["qwen", "cosy"])
            p.add_argument("--no-augmentation", action="store_true")
            p.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    if args.action == "merge":
        merge_manifests(args.inputs, args.output)
    elif args.action == "train":
        train(
            args.manifest,
            args.output,
            epochs=args.epochs,
            device=args.device,
            generators=args.generators,
            augmentation=not args.no_augmentation,
            cache_directory=args.cache_dir,
        )
    else:
        evaluate(args.manifest, args.output)


if __name__ == "__main__":
    main()
