"""Offline four-tone contrast training; phonetic content is never a tone input."""

import argparse
import json
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import decode_wav, features
from pinyin_matcher.catalog import ROOT, fingerprint, targets_by_id
from pinyin_matcher.contour import PITCH_FEATURE_VERSION, contour
from pinyin_matcher.data import dataset_digest
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.train import calibrate, prepare


def train(manifest: Path, cache: Path, output: Path, standard_anchors: Path | None = None):
    import torch
    from torch import nn

    config = json.loads((ROOT / "content/pronunciation-pitch.json").read_text())
    rng = np.random.default_rng(config["seed"])
    torch.manual_seed(config["seed"])
    torch.set_num_threads(1)
    if standard_anchors:
        source = json.loads(standard_anchors.read_text())
        if source.get("cohort") != "licensed-PinYinSound-standard-anchors-not-child":
            raise ValueError("STANDARD_ANCHOR_MANIFEST_REQUIRED")
        rows = source["items"]
        arrays = {}
        for row in rows:
            file = (standard_anchors.parent / row["file"]).resolve()
            if (
                not file.is_relative_to(standard_anchors.parent.resolve())
                or fingerprint(file) != row["sha256"]
            ):
                raise ValueError("STANDARD_ANCHOR_DIGEST_MISMATCH")
            arrays[row["id"]] = [features(decode_wav(file.read_bytes()))[0]]
    else:
        rows, arrays = prepare(manifest, cache)
    targets = targets_by_id()
    selected = (
        rows
        if standard_anchors
        else [r for r in rows if r["targetId"] in config["contrastTargetIds"]]
    )

    def examples(split):
        values, labels = [], []
        for row in selected:
            if row["split"] != split:
                continue
            for value in arrays[row["id"]] if split == "train" else arrays[row["id"]][:1]:
                try:
                    values.append(contour(value))
                except ValueError:
                    continue
                labels.append(targets[row["targetId"]]["tone"] - 1)
        if set(labels) != {0, 1, 2, 3}:
            raise ValueError("INDEPENDENT_FOUR_TONE_CONTRAST_REQUIRED")
        return np.stack(values), np.asarray(labels, dtype=np.int64)

    x, y = examples("train")
    cx, cy = examples("calibration")

    class PitchModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Flatten(),
                nn.Linear(64, config["hiddenSize"]),
                nn.SiLU(),
                nn.Dropout(0.15),
                nn.Linear(config["hiddenSize"], 32),
                nn.SiLU(),
                nn.Linear(32, 4),
            )

        def forward(self, value):
            logits = self.layers(value)
            unsupported = torch.full_like(logits[:, :1], -30)
            return torch.cat([unsupported, logits, unsupported], dim=1)

    model = PitchModel()
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learningRate"], weight_decay=0.01)
    weights = len(y) / np.bincount(y, minlength=4) / 4
    loss_fn = nn.CrossEntropyLoss(
        weight=torch.tensor(weights, dtype=torch.float32), label_smoothing=0.02
    )
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "pitch-state.pt"
    best = float("inf")
    history = []
    for epoch in range(config["epochs"]):
        model.train()
        for batch in np.array_split(
            rng.permutation(len(y)), max(1, int(np.ceil(len(y) / config["batchSize"])))
        ):
            values = x[batch].copy()
            positions = np.linspace(0, 1, 32)
            for i in range(len(values)):
                warped = positions ** rng.uniform(*config["timeWarpExponent"])
                values[i, :, 0] = np.interp(warped, positions, values[i, :, 0])
                values[i, :, 0] += rng.normal(0, config["relativePitchNoiseOctaves"], 32)
                values[i, :, 1] = np.gradient(values[i, :, 0])
            loss = loss_fn(model(torch.from_numpy(values))[:, 1:5], torch.from_numpy(y[batch]))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            logits = model(torch.from_numpy(cx))[:, 1:5]
            validation = float(loss_fn(logits, torch.from_numpy(cy)))
            accuracy = float((logits.argmax(1) == torch.from_numpy(cy)).float().mean())
        history.append(
            {"epoch": epoch + 1, "calibrationLoss": validation, "calibrationToneAccuracy": accuracy}
        )
        if validation < best:
            best = validation
            torch.save(model.state_dict(), checkpoint)
            best_epoch = epoch + 1
    model.load_state_dict(torch.load(checkpoint, weights_only=True))
    model.eval()
    destination = output / "pitch.onnx"
    torch.onnx.export(
        model,
        (torch.from_numpy(cx[:1]),),
        destination,
        input_names=["contour"],
        output_names=["tone"],
        dynamic_axes={"contour": {0: "batch"}, "tone": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    metadata = {
        "file": destination.name,
        "sha256": fingerprint(destination),
        "featureVersion": PITCH_FEATURE_VERSION,
        "parameters": sum(p.numel() for p in model.parameters()),
        "trainingCohort": "licensed-standard-tone-anchors"
        if standard_anchors
        else "synthetic-ma-four-tones",
        "anchorDatasetSha256": fingerprint(standard_anchors) if standard_anchors else None,
        "datasetSha256": dataset_digest(manifest),
        "trainingRoots": sum(r["split"] == "train" for r in selected),
        "trainingExposures": len(x),
        "calibrationRoots": len(cx),
        "bestEpoch": best_epoch,
        "calibrationToneAccuracy": history[best_epoch - 1]["calibrationToneAccuracy"],
        "configuration": config,
    }
    atomic_json(output / "pitch.json", metadata)
    atomic_json(output / "pitch-training.json", {"history": history})
    print(json.dumps(metadata))
    return metadata


def attach(model: Path, pitch: Path):
    import shutil

    metadata = json.loads((model / "model.json").read_text())
    record = json.loads((pitch / "pitch.json").read_text())
    if record["datasetSha256"] != metadata["datasetSha256"]:
        raise ValueError("PITCH_TRAINING_DATASET_MISMATCH")
    if fingerprint(pitch / record["file"]) != record["sha256"]:
        raise ValueError("PITCH_MODEL_DIGEST_MISMATCH")
    original = model / "model.shared-tone.json"
    if not original.exists():
        atomic_json(original, metadata)
    shutil.copyfile(pitch / record["file"], model / record["file"])
    metadata["pitchTone"] = record
    metadata["version"] = "synthetic-pilot-relative-pitch-v1"
    atomic_json(model / "model.json", metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attach", type=Path)
    parser.add_argument("--standard-anchors", type=Path)
    args = parser.parse_args()
    if args.attach:
        attach(args.attach, args.output)
        rows, arrays = prepare(args.manifest, args.cache_dir)
        calibrate(args.manifest, args.attach, rows, arrays)
    else:
        train(args.manifest, args.cache_dir, args.output, args.standard_anchors)
