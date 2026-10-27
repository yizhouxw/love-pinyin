"""Separate acoustic phone identity from expert-supervised component validity.

Exported logits yield a normalized full-class identity/validity product. Absolute
validity is deliberately not claimed by this initial readout-only ablation.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import (
    arrays,
    calibrate,
    covered_targets,
    read_rows,
    supervision,
    write,
)
from pinyin_matcher.pretrained_features import configuration

CONFIG = ROOT / "content/pronunciation-pretrained-factorized.json"
COMPONENTS = ("onset", "rime", "tone")


def factorized_configuration():
    config = json.loads(CONFIG.read_text())
    if (
        config["seed"] != 3182026
        or config["maximumEpochs"] != 120
        or config["cpuThreads"] != 2
        or config["validityLossWeight"] != 1.0
        or config["finalTestUsed"]
    ):
        raise ValueError("FACTORIZED_PROTOCOL_CHANGED")
    return config


class FactorizedHeads(nn.Module):
    def __init__(self, dimensions, counts, *, hidden=256, dropout=0.2, pitch_dimensions=68):
        super().__init__()
        if len(counts) != 3 or min(counts) < 2:
            raise ValueError("FACTORIZED_COMPONENT_CLASSES_REQUIRED")

        def branch(width, count):
            return nn.Sequential(
                nn.Linear(width, hidden),
                nn.LayerNorm(hidden),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden, count),
            )

        widths = [dimensions, dimensions, dimensions + pitch_dimensions]
        self.identity = nn.ModuleList(
            [branch(width, count) for width, count in zip(widths, counts, strict=True)]
        )
        self.validity = nn.ModuleList(
            [branch(width, count) for width, count in zip(widths, counts, strict=True)]
        )

    def separate(self, acoustic, pitch):
        inputs = (acoustic, acoustic, torch.cat((acoustic, pitch), -1))
        return (
            tuple(head(x) for head, x in zip(self.identity, inputs, strict=True)),
            tuple(head(x) for head, x in zip(self.validity, inputs, strict=True)),
        )

    def forward(self, acoustic, pitch):
        identities, validities = self.separate(acoustic, pitch)
        return tuple(
            identity.log_softmax(-1) + F.logsigmoid(validity)
            for identity, validity in zip(identities, validities, strict=True)
        )


def factorized_loss(identities, validities, labels, annotations, *, validity_weight=1.0):
    """Normalize other-class negatives per root, without labelling actual errors."""
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
            current = validity[correct]
            truth = labels[correct, index]
            positive = F.softplus(-current.gather(1, truth[:, None])[:, 0])
            other_mask = ~F.one_hot(truth, current.shape[1]).bool()
            other_negative = F.softplus(current)[other_mask].reshape(len(truth), -1).mean(1)
            groups.append(((positive + other_negative) * 0.5).mean())
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


def acoustic_derivative(cache, cache_metadata):
    """Keep original encoders valid; bind the explicitly supported native70 parent."""
    identity_path = cache / "identity.json"
    identity = json.loads(identity_path.read_text())
    if cache_metadata["cacheIdentitySha256"] != fingerprint(identity_path):
        raise ValueError("FACTORIZED_CACHE_IDENTITY_CHANGED")
    if identity.get("intermediateProbe"):
        raise ValueError("FACTORIZED_INTERMEDIATE_PROBE_UNSUPPORTED")
    derivative = identity.get("derivative")
    if derivative is None:
        return None
    if derivative.get("architecture") != "sensevoice-70-native-sequence-v1":
        raise ValueError("FACTORIZED_DERIVATIVE_ARCHITECTURE_UNSUPPORTED")
    from pinyin_matcher.pretrained_sensevoice import FILES, REVISION

    source = Path(cache_metadata["modelDirectory"])
    if fingerprint(source / "tuned.json") != derivative["metadataSha256"]:
        raise ValueError("FACTORIZED_DERIVATIVE_METADATA_CHANGED")
    metadata = json.loads((source / "tuned.json").read_text())
    if (
        metadata["architecture"] != derivative["architecture"]
        or metadata["sourceRevision"] != derivative["sourceRevision"]
        or derivative["sourceRevision"] != REVISION
        or metadata["parentWeightSha256"] != derivative["parentWeightSha256"]
        or derivative["parentWeightSha256"] != FILES["model.pt"]
        or metadata["sourceWeightsSha256"] != FILES["model.pt"]
        or metadata["files"]["tuned.safetensors"]["sha256"] != derivative["weightSha256"]
    ):
        raise ValueError("FACTORIZED_DERIVATIVE_PARENT_MISMATCH")
    for name, record in metadata["files"].items():
        path = (source / name).resolve()
        if not path.is_relative_to(source.resolve()) or fingerprint(path) != record["sha256"]:
            raise ValueError("FACTORIZED_DERIVATIVE_RESOURCE_CHANGED")
    return derivative


def train(manifest: Path, cache: Path, output: Path, *, name="sensevoice"):
    if output.exists():
        raise ValueError("FACTORIZED_OUTPUT_EXISTS")
    protocol, config = factorized_configuration(), configuration()
    if config["seed"] != protocol["seed"] or config["maximumEpochs"] != protocol["maximumEpochs"]:
        raise ValueError("FACTORIZED_BASE_BUDGET_MISMATCH")
    cache_metadata = json.loads((cache / "cache.json").read_text())
    if cache_metadata["manifestSha256"] != fingerprint(manifest) or cache_metadata["model"] != name:
        raise ValueError("FACTORIZED_CACHE_MANIFEST_MISMATCH")
    derivative = acoustic_derivative(cache, cache_metadata)
    rows = read_rows(manifest)
    train_all = [r for r in rows if r["split"] == "train"]
    train_rows = [
        r for r in train_all if not r.get("numericalQualityFlags") and not r.get("labelPolicyFlags")
    ]
    cal_rows = [r for r in rows if r["split"] == "calibration"]
    if not train_rows or not cal_rows:
        raise ValueError("FACTORIZED_TRAIN_CALIBRATION_REQUIRED")
    vocab = {key: sorted({str(r[key]) for r in train_rows}) for key in COMPONENTS}
    x, pitch, labels = arrays(train_rows, cache, vocab)
    cx, cp, cl = arrays(cal_rows, cache, vocab)
    annotations, cal_annotations = supervision(train_rows), supervision(cal_rows)
    mean, scale = x.mean(0), np.maximum(x.std(0), 0.1)
    pitch_mean, pitch_scale = pitch.mean(0), np.maximum(pitch.std(0), 0.1)
    x, cx = (x - mean) / scale, (cx - mean) / scale
    pitch, cp = (pitch - pitch_mean) / pitch_scale, (cp - pitch_mean) / pitch_scale
    torch.manual_seed(protocol["seed"])
    rng = np.random.default_rng(protocol["seed"])
    torch.set_num_threads(protocol["cpuThreads"])
    head = FactorizedHeads(
        x.shape[1],
        [len(vocab[k]) for k in COMPONENTS],
        hidden=config["hiddenSize"],
        dropout=config["dropout"],
    )
    optimizer = torch.optim.AdamW(
        head.parameters(), lr=config["learningRate"], weight_decay=config["weightDecay"]
    )
    x, pitch, labels, annotations = map(torch.from_numpy, (x, pitch, labels, annotations))
    ctx, cpt, clt, cat = map(torch.from_numpy, (cx, cp, cl, cal_annotations))
    best, checkpoint, selected_epoch = float("inf"), None, None
    history = []
    started = time.perf_counter()
    for epoch in range(protocol["maximumEpochs"]):
        head.train()
        permutation = rng.permutation(len(x))
        epoch_losses = []
        for start in range(0, len(x), config["batchSize"]):
            index = torch.tensor(permutation[start : start + config["batchSize"]])
            identity, validity = head.separate(x[index], pitch[index])
            loss, identity_loss, validity_loss = factorized_loss(
                identity,
                validity,
                labels[index],
                annotations[index],
                validity_weight=protocol["validityLossWeight"],
            )
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(head.parameters(), 5)
            optimizer.step()
            epoch_losses.append([float(v.detach()) for v in (loss, identity_loss, validity_loss)])
        head.eval()
        with torch.inference_mode():
            identity, validity = head.separate(ctx, cpt)
            cal_loss, identity_cal, validity_cal = factorized_loss(identity, validity, clt, cat)
            combined = head(ctx, cpt)
            positive = (cat == 1).all(1) & (clt >= 0).all(1)
            all_correct = (torch.stack([o.argmax(-1) for o in combined], 1) == clt).all(1)
        train_losses = np.mean(epoch_losses, axis=0).tolist()
        row = {
            "epoch": epoch + 1,
            "loss": train_losses[0],
            "identityLoss": train_losses[1],
            "validityLoss": train_losses[2],
            "calibrationLoss": float(cal_loss),
            "identityCalibrationLoss": float(identity_cal),
            "validityCalibrationLoss": float(validity_cal),
            "cachedPositiveArgmaxAllCorrectDiagnostic": int((all_correct & positive).sum()),
            "cachedPositiveRoots": int(positive.sum()),
        }
        history.append(row)
        if float(cal_loss) < best:
            best, selected_epoch = float(cal_loss), epoch + 1
            checkpoint = {key: value.detach().clone() for key, value in head.state_dict().items()}
        if (epoch + 1) % 20 == 0:
            print(json.dumps(row), flush=True)
    head.load_state_dict(checkpoint)
    head.eval()
    with torch.inference_mode():
        probabilities = [v.softmax(-1).numpy() for v in head(ctx, cpt)]
    calibration = calibrate(list(zip(*probabilities, strict=True)), cl, rows=cal_rows)
    output.mkdir(parents=True)
    torch.save(checkpoint, output / "heads.pt")
    with torch.inference_mode():
        torch.onnx.export(
            head,
            (torch.zeros(1, len(mean)), torch.zeros(1, len(pitch_mean))),
            str(output / "heads.onnx"),
            input_names=["acoustic", "pitch"],
            output_names=["initial", "final", "tone"],
            dynamic_axes={
                k: {0: "batch"} for k in ("acoustic", "pitch", "initial", "final", "tone")
            },
            opset_version=17,
            dynamo=False,
        )
    np.savez(
        output / "normalization.npz",
        mean=mean,
        scale=scale,
        pitch_mean=pitch_mean,
        pitch_scale=pitch_scale,
    )
    metadata = {
        "schemaVersion": 1,
        "model": name,
        "variant": "factorized-identity-validity",
        "acousticProbe": None,
        "acousticDerivative": derivative,
        "pitchOverride": None,
        "representation": "pool5-v1",
        "representationCodeSha256": None,
        "vocabulary": vocab,
        "dimensions": len(mean),
        "configuration": config,
        "factorizedConfiguration": protocol,
        "factorizedConfigurationSha256": fingerprint(CONFIG),
        "selectedEpoch": selected_epoch,
        "selectedComponentEpochs": None,
        "checkpointSelection": protocol["checkpointSelection"],
        "trainRows": len(train_rows),
        "calibrationRows": len(cal_rows),
        "trainingNumericalExclusions": sum(bool(r.get("numericalQualityFlags")) for r in train_all),
        "trainingPolicyExclusions": sum(bool(r.get("labelPolicyFlags")) for r in train_all),
        "trainingTotalExclusions": len(train_all) - len(train_rows),
        "trainSpeakers": len({r["speakerId"] for r in train_rows}),
        "calibrationSpeakers": len({r["speakerId"] for r in cal_rows}),
        "manifestSha256": fingerprint(manifest),
        "cacheMetadataSha256": fingerprint(cache / "cache.json"),
        "headSha256": fingerprint(output / "heads.pt"),
        "headCodeSha256": fingerprint(Path(__file__)),
        "headOnnxSha256": fingerprint(output / "heads.onnx"),
        "normalizationSha256": fingerprint(output / "normalization.npz"),
        "thresholds": calibration["selected"]["threshold"],
        "testUsed": False,
        "trainingSeconds": time.perf_counter() - started,
        "experimental": True,
        "toneAssessed": False,
        "coveredComponents": vocab,
        "coveredTargets": covered_targets(vocab, train_rows),
        "trainingTargetSyllables": sorted({r["syllable"] for r in train_rows}),
        "compositionalTargetsOutsideTrainingAreExperimental": True,
    }
    write(output / "model.json", metadata)
    write(output / "training.json", history)
    write(output / "calibration.json", calibration)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("manifest", "cache", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument(
        "--name",
        choices=(
            "sensevoice",
            "tencent-zh-base",
            "tencent-zh-tail-v1",
            "tencent-zh-raw",
            "chinese-xlsr-asr",
        ),
        default="sensevoice",
    )
    args = parser.parse_args()
    result = train(args.manifest, args.cache, args.output, name=args.name)
    print(json.dumps({k: result[k] for k in ("variant", "selectedEpoch", "trainingSeconds")}))


if __name__ == "__main__":
    main()
