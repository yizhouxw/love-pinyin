"""Train/evaluate experimental pitch-only candidates on frozen source splits.

Calibration selects checkpoints. Test/challenge metrics are diagnostics only and
are never read by checkpoint selection or threshold fitting. No audio is written.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import AudioRejected, decode_wav, features
from pinyin_matcher.catalog import fingerprint, targets_by_id
from pinyin_matcher.contour import contour as contour_v1
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.pitch_v2 import PITCH_FEATURE_VERSION, contour


def prepare(anchors: Path, synthetic: Path, cache: Path, tracker=None) -> tuple[list[dict], dict]:
    """Cache derived numeric features; verify every source waveform digest."""
    cache.mkdir(parents=True, exist_ok=True)
    targets = targets_by_id()
    rows, counts = [], {}
    for source, manifest in [("standard", anchors), ("synthetic", synthetic)]:
        for row in json.loads(manifest.read_text())["items"]:
            target = targets[row["targetId"]]
            if target["tone"] not in [1, 2, 3, 4]:
                continue
            file = (manifest.parent / row["file"]).resolve()
            if (
                not file.is_relative_to(manifest.parent.resolve())
                or fingerprint(file) != row["sha256"]
            ):
                raise ValueError("SOURCE_DIGEST_MISMATCH")
            feature_version = PITCH_FEATURE_VERSION
            if tracker is not None:
                from pinyin_matcher.pitch_swift import PITCH_FEATURE_VERSION as swift_version

                feature_version += swift_version
            key = hashlib.sha256((row["sha256"] + feature_version).encode()).hexdigest()
            cached = cache / (key + ".npz")
            if cached.exists():
                data = np.load(cached)
                v1, v2 = data["v1"], data["v2"]
                swift = data["swift"] if "swift" in data else None
            else:
                samples = decode_wav(file.read_bytes())
                try:
                    v1 = contour_v1(features(samples)[0])
                except AudioRejected:
                    v1 = np.full((32, 2), np.nan, dtype=np.float32)
                try:
                    v2 = contour(samples)[0]
                except AudioRejected:
                    v2 = np.full((32, 4), np.nan, dtype=np.float32)
                swift = None
                if tracker is not None:
                    try:
                        swift = tracker.contour(samples)[0]
                    except AudioRejected:
                        swift = np.full((32, 4), np.nan, dtype=np.float32)
                values = {"v1": v1, "v2": v2}
                if swift is not None:
                    values["swift"] = swift
                np.savez_compressed(cached, **values)
            record = {
                "id": row["id"],
                "source": source,
                "generator": row.get("generator", "licensed-standard"),
                "voiceFamilyId": row.get("voiceFamilyId"),
                "split": row["split"],
                "targetId": row["targetId"],
                "tone": target["tone"] - 1,
                "base": target["phones"],
                "v1": v1,
                "v2": v2,
            }
            if swift is not None:
                record["swift"] = swift
            rows.append(record)
            for version in ["v1", "v2"] + (["swift"] if swift is not None else []):
                counter = source + ":" + row["split"] + ":" + version
                counts.setdefault(counter, {"roots": 0, "usable": 0})
                counts[counter]["roots"] += 1
                counts[counter]["usable"] += int(np.isfinite(record[version]).all())
    return rows, counts


def train(
    rows: list[dict],
    version: str,
    cohort: str,
    output: Path,
    epochs: int = 300,
    architecture: str = "flat",
) -> dict:
    """Fit an unchanged MLP recipe; choose solely by frozen calibration loss."""
    import torch
    from torch import nn

    torch.set_num_threads(1)
    torch.manual_seed(3182026)
    rng = np.random.default_rng(3182026)
    if version not in ["v1", "v2", "v2-shape", "swift"]:
        raise ValueError("UNKNOWN_FEATURE_VERSION")

    def selected(split):
        included = [
            row
            for row in rows
            if row["split"] == split
            and (
                row["source"] == "standard"
                or cohort == "combined"
                or (cohort == "ma" and row["targetId"] in [f"pm-ma{n}" for n in range(1, 5)])
            )
            and np.isfinite(row[version.split("-")[0]]).all()
        ]
        x = np.stack([row[version.split("-")[0]] for row in included])
        if version == "v2-shape":
            x = x[:, :, :2]
        y = np.asarray([row["tone"] for row in included], dtype=np.int64)
        weights = np.zeros(len(y), dtype=np.float32)
        # Equal source and tone mass prevents the mostly-tone-one pilot corpus
        # from overwhelming trusted four-tone anchors during training/selection.
        for source in {row["source"] for row in included}:
            for tone in range(4):
                indices = [
                    i
                    for i, row in enumerate(included)
                    if row["source"] == source and row["tone"] == tone
                ]
                weights[indices] = 1 / max(len(indices), 1)
        weights *= len(weights) / weights.sum()
        return included, x, y, weights

    _, x, y, w = selected("train")
    calibration_rows, cx, cy, cw = selected("calibration")

    class PitchModel(nn.Module):
        def __init__(self):
            super().__init__()
            size = x.shape[1] * x.shape[2] if architecture == "flat" else 8 * x.shape[2]
            self.layers = nn.Sequential(
                nn.Flatten(),
                nn.Linear(size, 64),
                nn.SiLU(),
                nn.Dropout(0.15),
                nn.Linear(64, 32),
                nn.SiLU(),
                nn.Linear(32, 4),
            )

        def forward(self, value):
            if architecture == "smooth":
                value = torch.nn.functional.avg_pool1d(value.transpose(1, 2), 4).transpose(1, 2)
            logits = self.layers(value)
            unsupported = torch.full_like(logits[:, :1], -30)
            return torch.cat([unsupported, logits, unsupported], dim=1)

    model = PitchModel()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002, weight_decay=0.01)
    loss_fn = nn.CrossEntropyLoss(reduction="none", label_smoothing=0.02)
    output.mkdir(parents=True, exist_ok=True)
    best_loss, best_epoch = float("inf"), 0
    history = []
    for epoch in range(epochs):
        model.train()
        for batch in np.array_split(rng.permutation(len(x)), max(1, int(np.ceil(len(x) / 64)))):
            values = x[batch].copy()
            positions = np.linspace(0, 1, 32)
            for i in range(len(values)):
                warped = positions ** rng.uniform(0.85, 1.15)
                for channel in range(values.shape[-1]):
                    values[i, :, channel] = np.interp(warped, positions, values[i, :, channel])
                values[i, :, 0] += rng.normal(0, 0.005, 32)
                values[i, :, 1] = np.gradient(values[i, :, 0])
            loss = (
                loss_fn(model(torch.from_numpy(values))[:, 1:5], torch.from_numpy(y[batch]))
                * torch.from_numpy(w[batch])
            ).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            logits = model(torch.from_numpy(cx))[:, 1:5]
            losses = loss_fn(logits, torch.from_numpy(cy))
            validation = float((losses * torch.from_numpy(cw)).mean())
            predictions = logits.argmax(1).numpy()
            metrics = {
                source: float(
                    np.mean(
                        predictions[[r["source"] == source for r in calibration_rows]]
                        == cy[[r["source"] == source for r in calibration_rows]]
                    )
                )
                for source in {r["source"] for r in calibration_rows}
            }
        history.append({"epoch": epoch + 1, "calibrationLoss": validation, "bySource": metrics})
        if validation < best_loss:
            best_loss, best_epoch = validation, epoch + 1
            torch.save(model.state_dict(), output / "state.pt")
    model.load_state_dict(torch.load(output / "state.pt", weights_only=True))
    model.eval()
    torch.onnx.export(
        model,
        (torch.from_numpy(cx[:1]),),
        output / "pitch.onnx",
        input_names=["contour"],
        output_names=["tone"],
        dynamic_axes={"contour": {0: "batch"}, "tone": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    if version == "swift":
        from pinyin_matcher.pitch_swift import PITCH_FEATURE_VERSION as feature_version
    else:
        feature_version = PITCH_FEATURE_VERSION if version == "v2" else version
    report = {
        "featureVersion": feature_version,
        "version": version,
        "cohort": cohort,
        "architecture": architecture,
        "file": "pitch.onnx",
        "sha256": fingerprint(output / "pitch.onnx"),
        "parameters": sum(p.numel() for p in model.parameters()),
        "inputShape": list(x.shape[1:]),
        "trainingRoots": len(x),
        "calibrationRoots": len(cx),
        "bestEpoch": best_epoch,
        "calibration": history[best_epoch - 1],
        "history": history,
        "testUsedForSelection": False,
    }
    atomic_json(output / "pitch.json", report)
    return report


def evaluate(rows: list[dict], model: Path) -> dict:
    import onnxruntime as ort

    metadata = json.loads((model / "pitch.json").read_text())
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model / "pitch.onnx"), options, providers=["CPUExecutionProvider"]
    )
    feature = metadata["version"].split("-")[0]
    details = []
    for row in rows:
        value = row[feature]
        if metadata["version"] == "v2-shape":
            value = value[:, :2]
        if not np.isfinite(value).all():
            predicted, confidence = None, None
        else:
            logits = session.run(None, {"contour": value[None]})[0][0, 1:5]
            probabilities = np.exp(logits - logits.max())
            probabilities /= probabilities.sum()
            predicted, confidence = int(probabilities.argmax()), float(probabilities.max())
        details.append(
            {
                "id": row["id"],
                "source": row["source"],
                "generator": row.get("generator"),
                "voiceFamilyId": row.get("voiceFamilyId"),
                "split": row["split"],
                "expected": row["tone"] + 1,
                "predicted": predicted + 1 if predicted is not None else None,
                "confidence": confidence,
            }
        )
    groups = {}
    for source, split in sorted({(r["source"], r["split"]) for r in details}):
        group = [r for r in details if r["source"] == source and r["split"] == split]
        confusion = np.zeros((4, 5), dtype=int)
        for row in group:
            confusion[row["expected"] - 1, row["predicted"] - 1 if row["predicted"] else 4] += 1
        groups[source + ":" + split] = {
            "roots": len(group),
            "correct": sum(r["predicted"] == r["expected"] for r in group),
            "unusable": sum(r["predicted"] is None for r in group),
            "confusionPredicted1234Unavailable": confusion.tolist(),
        }
    generator_groups = {}
    for generator, split in sorted({(r["generator"], r["split"]) for r in details}):
        group = [r for r in details if r["generator"] == generator and r["split"] == split]
        generator_groups[generator + ":" + split] = {
            "roots": len(group),
            "correct": sum(r["predicted"] == r["expected"] for r in group),
            "unusable": sum(r["predicted"] is None for r in group),
            "byTone": {
                str(tone): {
                    "roots": sum(r["expected"] == tone for r in group),
                    "correct": sum(r["predicted"] == tone == r["expected"] for r in group),
                }
                for tone in range(1, 5)
            },
        }
    report = {
        "modelSha256": metadata["sha256"],
        "bySourceSplit": groups,
        "byGeneratorSplit": generator_groups,
        "results": details,
    }
    atomic_json(model / "diagnostic.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anchors", type=Path, default=Path("private/matcher-standard-anchors/manifest.json")
    )
    parser.add_argument(
        "--synthetic", type=Path, default=Path("private/matcher-data/manifest.json")
    )
    parser.add_argument("--cache", type=Path, default=Path("private/matcher-pitch-v2-cache"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", choices=["v1", "v2", "v2-shape", "swift"], default="v2")
    parser.add_argument(
        "--tracker-model", type=Path, default=Path("models/matcher-pitch-swift/model.onnx")
    )
    parser.add_argument("--cohort", choices=["standard", "ma", "combined"], default="standard")
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--architecture", choices=["flat", "smooth"], default="flat")
    args = parser.parse_args()
    started = time.perf_counter()
    tracker = None
    if args.version == "swift":
        from pinyin_matcher.pitch_swift import SwiftPitch

        tracker = SwiftPitch(args.tracker_model)
    examples, counts = prepare(args.anchors, args.synthetic, args.cache, tracker)
    print(
        json.dumps({"counts": counts, "featureSeconds": time.perf_counter() - started}), flush=True
    )
    record = train(examples, args.version, args.cohort, args.output, args.epochs, args.architecture)
    record["anchorDatasetSha256"] = fingerprint(args.anchors)
    record["syntheticManifestSha256"] = fingerprint(args.synthetic)
    atomic_json(args.output / "pitch.json", record)
    print(json.dumps({key: value for key, value in record.items() if key != "history"}), flush=True)
    print(json.dumps(evaluate(examples, args.output)["bySourceSplit"]), flush=True)
