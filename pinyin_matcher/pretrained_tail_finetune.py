"""Train six original SenseVoice TP layers using a frozen 64-layer prefix.

Caches retain all four contextual prompts and exact lengths. No target reaches
any encoder layer, and cached training is not a full CPU quality evaluation.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file
from torch import nn

from pinyin_matcher.audio import decode_wav, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import (
    calibrate,
    read_cached,
    read_rows,
    save_cached,
    supervision,
    write,
)
from pinyin_matcher.pretrained_factorized import FactorizedHeads, factorized_loss
from pinyin_matcher.pretrained_features import pitch_vector, pool_frames
from pinyin_matcher.pretrained_sensevoice import FILES, REVISION, SenseVoiceFeatures

CONFIG = ROOT / "content/pronunciation-pretrained-tail-finetune.json"
PROMPTS = [3, 1, 2, 15]
COMPONENTS = ("onset", "rime", "tone")
ARCHITECTURE = "sensevoice-70-factorized-tail-v1"


def configuration():
    config = json.loads(CONFIG.read_text())
    fixed = {
        "seed": 3182026,
        "retainedEncoderLayers": 70,
        "frozenEncoderLayers": 64,
        "trainableTaskEncoderLayers": 6,
        "warmupEpochs": 2,
        "fineTuneEpochs": 10,
        "batchSize": 32,
        "cacheBatchSize": 32,
        "tailLearningRate": 1e-5,
        "headLearningRate": 1e-3,
        "prompts": PROMPTS,
        "dither": 0,
        "finalTestUsed": False,
    }
    if any(config[k] != value for k, value in fixed.items()):
        raise ValueError("TAIL_FINETUNE_PROTOCOL_CHANGED")
    return config


class FrozenPrefix(nn.Module):
    def __init__(self, encoder):
        super().__init__()
        self.main = nn.ModuleList([*encoder.encoders0, *encoder.encoders])
        self.after_norm = encoder.after_norm
        self.task = nn.ModuleList(list(encoder.tp_encoders[:14]))
        self.requires_grad_(False)

    def forward(self, x, lengths):
        positions = torch.arange(1, x.shape[1] + 1, device=x.device, dtype=x.dtype)
        scales = torch.exp(
            torch.arange(280, device=x.device, dtype=x.dtype) * (-math.log(10000) / 279)
        )
        phase = positions[:, None] * scales[None]
        x = x * math.sqrt(512) + torch.cat((phase.sin(), phase.cos()), -1)[None]
        mask = (torch.arange(x.shape[1], device=x.device)[None] < lengths[:, None])[:, None]
        for layer in self.main:
            x = layer(x, mask)
        x = self.after_norm(x)
        for layer in self.task:
            x = layer(x, mask)
        return x


class TrainableTail(nn.Module):
    def __init__(self, encoder):
        super().__init__()
        self.layers = nn.ModuleList(list(encoder.tp_encoders[14:]))
        self.norm = encoder.tp_norm

    def forward(self, prefix, lengths):
        mask = (torch.arange(prefix.shape[1], device=prefix.device)[None] < lengths[:, None])[
            :, None
        ]
        for layer in self.layers:
            prefix = layer(prefix, mask)
        return self.norm(prefix)


def pool_valid_frames(encoded, lengths):
    """Exactly the existing mean/std/three uneven thirds, excluding prompts."""
    vectors = []
    for index, length in enumerate(lengths.detach().cpu().tolist()):
        if not 4 < length <= encoded.shape[1]:
            raise ValueError("TAIL_VALID_LENGTH_INVALID")
        frames = encoded[index, 4:length]
        sections = torch.tensor_split(frames, 3)
        vectors.append(
            torch.cat(
                [frames.mean(0), frames.std(0, unbiased=False)]
                + [part.mean(0) if len(part) else frames.mean(0) for part in sections]
            )
        )
    return torch.stack(vectors)


def state_digest(module):
    result = hashlib.sha256()
    for name, value in sorted(module.state_dict().items()):
        result.update(name.encode())
        tensor = value.detach().cpu().contiguous()
        result.update(str(tensor.dtype).encode())
        result.update(str(tuple(tensor.shape)).encode())
        result.update(tensor.numpy().tobytes())
    return result.hexdigest()


def _padded_frontend(source, samples):
    features = [source.frontend(s) for s in samples]
    lengths = torch.tensor([len(f) + 4 for f in features], device=source.device)
    x = torch.zeros(len(features), int(lengths.max()), 560, device=source.device)
    prompt = source.embed(torch.tensor(PROMPTS, device=source.device))
    for i, feature in enumerate(features):
        x[i, :4] = prompt
        x[i, 4 : len(feature) + 4] = feature.to(source.device)
    return x, lengths


def preflight(source, prefix, tail, samples):
    with torch.inference_mode():
        x, lengths = _padded_frontend(source, samples)
        cached = prefix(x, lengths)
        split = tail(cached, lengths)
        whole = source.encoder(x, lengths)
        differences = [
            float((split[i, :n] - whole[i, :n]).abs().max()) for i, n in enumerate(lengths.tolist())
        ]
        pooled = pool_valid_frames(split, lengths).cpu().numpy()
        pool_differences = [
            float(np.max(np.abs(pooled[i] - pool_frames(whole[i, 4:n].cpu().numpy()))))
            for i, n in enumerate(lengths.tolist())
        ]
        single_differences = []
        for i, sample in enumerate(samples):
            one_x, one_n = _padded_frontend(source, [sample])
            one = tail(prefix(one_x, one_n), one_n)[0, : one_n[0]]
            single_differences.append(float((one - whole[i, : lengths[i]]).abs().max()))
    if max(differences + pool_differences + single_differences) > 5e-3:
        raise ValueError("TAIL_PREFIX_PADDING_OR_POOL_PARITY_FAILED")
    return {
        "splitEncoderMaximumDifference": max(differences),
        "poolMaximumDifference": max(pool_differences),
        "paddingMaximumDifference": max(single_differences),
        "realAudioExamples": len(samples),
        "qualityEvidence": False,
    }


def cache_prefix(manifest, model, output, *, device):
    config = configuration()
    rows = [r for r in read_rows(manifest) if r["split"] in {"train", "calibration"}]
    eligible = [
        r
        for r in rows
        if not r.get("numericalQualityFlags")
        and not r.get("labelPolicyFlags")
        and not r.get("placeholder")
    ]
    if not eligible:
        raise ValueError("TAIL_CACHE_NO_ELIGIBLE_ROWS")
    output.mkdir(parents=True, exist_ok=True)
    identity = {
        "architecture": ARCHITECTURE,
        "manifestSha256": fingerprint(manifest),
        "sourceWeightsSha256": FILES["model.pt"],
        "sourceRevision": REVISION,
        "configurationSha256": fingerprint(CONFIG),
        "device": device,
        "code": {
            name: fingerprint(Path(__file__).with_name(name))
            for name in (
                "pretrained_tail_finetune.py",
                "pretrained_sensevoice.py",
                "audio.py",
                "pretrained_features.py",
            )
        },
        "testUsed": False,
    }
    identity_path = output / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("TAIL_CACHE_IDENTITY_CHANGED")
    write(identity_path, identity)
    identity_sha = fingerprint(identity_path)
    source = SenseVoiceFeatures(model, device=device)
    prefix, tail = FrozenPrefix(source.encoder).eval(), TrainableTail(source.encoder).eval()
    first = [trim_silence(decode_wav(Path(r["file"]).read_bytes())) for r in eligible[:3]]
    parity = preflight(source, prefix, tail, first)
    started = time.perf_counter()
    for start in range(0, len(eligible), config["cacheBatchSize"]):
        batch = eligible[start : start + config["cacheBatchSize"]]
        pending = []
        for row in batch:
            path = output / (row["sha256"] + ".npz")
            if path.exists():
                with read_cached(path, identity_sha):
                    pass
            else:
                pending.append(row)
        if pending:
            samples = [trim_silence(decode_wav(Path(r["file"]).read_bytes())) for r in pending]
            with torch.inference_mode():
                x, lengths = _padded_frontend(source, samples)
                encoded = prefix(x, lengths)
                original = pool_valid_frames(tail(encoded, lengths), lengths).cpu().numpy()
                for i, row in enumerate(pending):
                    n = int(lengths[i])
                    save_cached(
                        output / (row["sha256"] + ".npz"),
                        {
                            "prefix": encoded[i, :n].cpu().numpy(),
                            "length": np.asarray(n, dtype=np.int64),
                            "pitch": pitch_vector(samples[i]),
                            "originalPooled": original[i],
                        },
                        identity_sha,
                    )
        print(
            json.dumps(
                {"prefixCached": min(start + len(batch), len(eligible)), "total": len(eligible)}
            ),
            flush=True,
        )
    metadata = {
        **identity,
        "identitySha256": identity_sha,
        "rows": len(rows),
        "eligibleRows": len(eligible),
        "prefixStateSha256": state_digest(prefix),
        "initialTailStateSha256": state_digest(tail),
        "parity": parity,
        "elapsedSeconds": time.perf_counter() - started,
    }
    write(output / "cache.json", metadata)
    return metadata


def _cache_items(rows, cache, vocab, identity_sha):
    items = []
    annotations = supervision(rows)
    for index, row in enumerate(rows):
        labels = [
            vocab[k].index(str(row[k])) if str(row[k]) in vocab[k] else -1 for k in COMPONENTS
        ]
        path = cache / (row["sha256"] + ".npz")
        if (
            row.get("numericalQualityFlags")
            or row.get("labelPolicyFlags")
            or row.get("placeholder")
        ):
            continue
        with read_cached(path, identity_sha) as record:
            prefix = record["prefix"].copy()
            length = int(record["length"])
            pitch = record["pitch"].copy()
        if (
            prefix.shape != (length, 512)
            or length <= 4
            or pitch.shape != (68,)
            or not np.isfinite(prefix).all()
            or not np.isfinite(pitch).all()
        ):
            raise ValueError("TAIL_CACHE_ARRAY_INVALID")
        items.append(
            {
                "index": index,
                "prefix": torch.from_numpy(prefix),
                "pitch": pitch,
                "labels": labels,
                "annotations": annotations[index].tolist(),
            }
        )
    return items


def _forward(tail, head, batch, normal, device):
    lengths = torch.tensor([len(r["prefix"]) for r in batch], device=device)
    padded = torch.zeros(len(batch), int(lengths.max()), 512, device=device)
    for i, row in enumerate(batch):
        padded[i, : lengths[i]] = row["prefix"].to(device)
    acoustic = pool_valid_frames(tail(padded, lengths), lengths)
    pitch = torch.from_numpy(np.stack([r["pitch"] for r in batch])).to(device)
    acoustic = (acoustic - normal["mean"]) / normal["scale"]
    pitch = (pitch - normal["pitch_mean"]) / normal["pitch_scale"]
    return head.separate(acoustic, pitch)


def _calibration(tail, head, items, rows, vocab, normal, device, size):
    tail.eval()
    head.eval()
    identities, validities = [[] for _ in range(3)], [[] for _ in range(3)]
    with torch.inference_mode():
        for start in range(0, len(items), size):
            identity, validity = _forward(tail, head, items[start : start + size], normal, device)
            for i in range(3):
                identities[i].append(identity[i].cpu())
                validities[i].append(validity[i].cpu())
    identities = [torch.cat(a) for a in identities]
    validities = [torch.cat(a) for a in validities]
    labels = torch.tensor([r["labels"] for r in items])
    annotations = torch.tensor([r["annotations"] for r in items])
    losses = factorized_loss(identities, validities, labels, annotations)
    probabilities = [
        np.full((len(rows), len(vocab[k])), 1 / len(vocab[k]), dtype=np.float32) for k in COMPONENTS
    ]
    for i, (identity, validity) in enumerate(zip(identities, validities, strict=True)):
        combined = (identity.log_softmax(-1) + torch.nn.functional.logsigmoid(validity)).softmax(-1)
        probabilities[i][[r["index"] for r in items]] = combined.numpy()
    return [float(x) for x in losses], probabilities


def train(manifest, model, cache, initializer, output, *, device):
    if output.exists():
        raise ValueError("TAIL_TRAIN_OUTPUT_EXISTS")
    config = configuration()
    metadata = json.loads((cache / "cache.json").read_text())
    initial = json.loads((initializer / "model.json").read_text())
    if (
        metadata["manifestSha256"] != fingerprint(manifest)
        or initial["manifestSha256"] != fingerprint(manifest)
        or initial["variant"] != "factorized-identity-validity"
        or initial.get("acousticProbe")
        or initial.get("acousticDerivative")
        or initial.get("pitchOverride")
        or initial["dimensions"] != 2560
        or initial["headSha256"] != fingerprint(initializer / "heads.pt")
        or initial["normalizationSha256"] != fingerprint(initializer / "normalization.npz")
        or metadata["identitySha256"] != fingerprint(cache / "identity.json")
        or metadata["configurationSha256"] != fingerprint(CONFIG)
    ):
        raise ValueError("TAIL_TRAIN_INPUT_IDENTITY_MISMATCH")
    torch.manual_seed(config["seed"])
    torch.set_num_threads(2)
    rng = np.random.default_rng(config["seed"])
    rows = read_rows(manifest)
    train_rows = [r for r in rows if r["split"] == "train"]
    cal_rows = [r for r in rows if r["split"] == "calibration"]
    vocab = initial["vocabulary"]
    train_items = _cache_items(train_rows, cache, vocab, metadata["identitySha256"])
    cal_items = _cache_items(cal_rows, cache, vocab, metadata["identitySha256"])
    if not train_items or not cal_items:
        raise ValueError("TAIL_TRAIN_CALIBRATION_REQUIRED")
    source = SenseVoiceFeatures(model, device="cpu")
    frozen_sha = state_digest(FrozenPrefix(source.encoder))
    tail = TrainableTail(source.encoder).to(device)
    if (
        frozen_sha != metadata["prefixStateSha256"]
        or state_digest(tail) != metadata["initialTailStateSha256"]
    ):
        raise ValueError("TAIL_SOURCE_STATE_MISMATCH")
    del source
    gc.collect()
    head = FactorizedHeads(2560, [len(vocab[k]) for k in COMPONENTS]).to(device)
    head.load_state_dict(
        torch.load(initializer / "heads.pt", map_location=device, weights_only=True)
    )
    initial_tail = {k: v.detach().cpu().clone() for k, v in tail.state_dict().items()}
    initial_head_sha = state_digest(head)
    with np.load(initializer / "normalization.npz", allow_pickle=False) as data:
        normal_arrays = {k: data[k].copy() for k in data.files}
    normal = {k: torch.from_numpy(v).to(device) for k, v in normal_arrays.items()}
    optimizer = torch.optim.AdamW(
        [
            {"params": head.parameters(), "lr": config["headLearningRate"]},
            {"params": tail.parameters(), "lr": config["tailLearningRate"]},
        ],
        weight_decay=config["weightDecay"],
    )
    output.mkdir(parents=True)
    initial_losses, _ = _calibration(
        tail, head, cal_items, cal_rows, vocab, normal, device, config["batchSize"]
    )
    best, selected = initial_losses[0], 0
    checkpoint = {"tail." + k: v.detach().cpu().clone() for k, v in tail.state_dict().items()}
    checkpoint.update({"head." + k: v.detach().cpu().clone() for k, v in head.state_dict().items()})
    write(output / "initial-calibration.json", {"losses": initial_losses, "epoch": 0})
    history = []
    started = time.perf_counter()
    for epoch in range(config["warmupEpochs"] + config["fineTuneEpochs"]):
        tail.requires_grad_(epoch >= config["warmupEpochs"])
        tail.train()
        head.train()
        order = rng.permutation(len(train_items))
        losses = []
        first_tail_gradient = None
        for start in range(0, len(order), config["batchSize"]):
            batch = [train_items[i] for i in order[start : start + config["batchSize"]]]
            identity, validity = _forward(tail, head, batch, normal, device)
            labels = torch.tensor([r["labels"] for r in batch], device=device)
            annotations = torch.tensor([r["annotations"] for r in batch], device=device)
            loss = factorized_loss(identity, validity, labels, annotations)[0]
            optimizer.zero_grad()
            loss.backward()
            if first_tail_gradient is None:
                first_tail_gradient = sum(
                    float(parameter.grad.detach().abs().sum())
                    for parameter in tail.parameters()
                    if parameter.grad is not None
                )
            nn.utils.clip_grad_norm_(
                [*head.parameters(), *tail.parameters()],
                config["gradientClip"],
                error_if_nonfinite=True,
            )
            optimizer.step()
            losses.append(float(loss.detach()))
        cal_losses, probabilities = _calibration(
            tail, head, cal_items, cal_rows, vocab, normal, device, config["batchSize"]
        )
        history.append(
            {
                "epoch": epoch + 1,
                "tailTrainable": epoch >= config["warmupEpochs"],
                "firstBatchTailGradientAbsoluteSum": first_tail_gradient,
                "trainLoss": float(np.mean(losses)),
                "calibrationLoss": cal_losses[0],
                "calibrationIdentityLoss": cal_losses[1],
                "calibrationValidityLoss": cal_losses[2],
            }
        )
        if cal_losses[0] < best:
            best, selected = cal_losses[0], epoch + 1
            checkpoint = {
                "tail." + k: v.detach().cpu().clone() for k, v in tail.state_dict().items()
            }
            checkpoint.update(
                {"head." + k: v.detach().cpu().clone() for k, v in head.state_dict().items()}
            )
        write(output / "training.json", history)
        print(json.dumps(history[-1]), flush=True)
    last_tail_sha = state_digest(tail)
    last_changes = {
        k: float((v.detach().cpu() - initial_tail[k]).abs().max())
        for k, v in tail.state_dict().items()
    }
    tail.load_state_dict({k[5:]: v for k, v in checkpoint.items() if k.startswith("tail.")})
    head.load_state_dict({k[5:]: v for k, v in checkpoint.items() if k.startswith("head.")})
    cal_losses, probabilities = _calibration(
        tail, head, cal_items, cal_rows, vocab, normal, device, config["batchSize"]
    )
    labels = np.asarray(
        [
            [vocab[k].index(str(r[k])) if str(r[k]) in vocab[k] else -1 for k in COMPONENTS]
            for r in cal_rows
        ]
    )
    calibration = calibrate(list(zip(*probabilities, strict=True)), labels, rows=cal_rows)
    save_file(checkpoint, output / "tail-head.safetensors")
    np.savez(output / "normalization.npz", **normal_arrays)
    changes = {
        k: float((v.detach().cpu() - initial_tail[k]).abs().max())
        for k, v in tail.state_dict().items()
    }
    result = {
        "schemaVersion": 1,
        "architecture": ARCHITECTURE,
        "model": "sensevoice",
        "configuration": config,
        "configurationSha256": fingerprint(CONFIG),
        "manifestSha256": fingerprint(manifest),
        "cacheMetadataSha256": fingerprint(cache / "cache.json"),
        "initializerMetadataSha256": fingerprint(initializer / "model.json"),
        "initializerHeadSha256": initial["headSha256"],
        "initializerSelectedEpoch": initial["selectedEpoch"],
        "sourceWeightsSha256": FILES["model.pt"],
        "sourceRevision": REVISION,
        "frozenPrefixStateSha256": frozen_sha,
        "frozenPrefixUsedOnlyAsCachedConstant": True,
        "initialHeadStateSha256": initial_head_sha,
        "selectedHeadStateSha256": state_digest(head),
        "initialTailStateSha256": metadata["initialTailStateSha256"],
        "selectedTailStateSha256": state_digest(tail),
        "tailTensorMaximumChanges": changes,
        "lastEpochTailStateSha256": last_tail_sha,
        "lastEpochTailTensorMaximumChanges": last_changes,
        "initialCalibrationLoss": initial_losses[0],
        "vocabulary": vocab,
        "coveredTargets": initial["coveredTargets"],
        "selectedEpoch": selected,
        "calibrationLoss": cal_losses[0],
        "trainingSeconds": time.perf_counter() - started,
        "trainRows": len(train_items),
        "calibrationRows": len(cal_rows),
        "calibrationLossRows": len(cal_items),
        "testUsed": False,
        "experimental": True,
        "checkpointSha256": fingerprint(output / "tail-head.safetensors"),
        "normalizationSha256": fingerprint(output / "normalization.npz"),
        "codeSha256": fingerprint(Path(__file__)),
        "factorizedCodeSha256": fingerprint(Path(__file__).with_name("pretrained_factorized.py")),
        "qualityEvidence": "Cached prefix training/calibration only; full CPU evaluation pending.",
    }
    write(output / "calibration.json", calibration)
    write(output / "model.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("cache")
    for key in ("manifest", "model", "output"):
        prepare.add_argument("--" + key, type=Path, required=True)
    prepare.add_argument("--device", choices=("cpu", "mps"), default="mps")
    fit = sub.add_parser("train")
    for key in ("manifest", "model", "cache", "initializer", "output"):
        fit.add_argument("--" + key, type=Path, required=True)
    fit.add_argument("--device", choices=("cpu", "mps"), default="mps")
    args = vars(parser.parse_args())
    action = args.pop("action")
    print(json.dumps((cache_prefix if action == "cache" else train)(**args)))


if __name__ == "__main__":
    main()
