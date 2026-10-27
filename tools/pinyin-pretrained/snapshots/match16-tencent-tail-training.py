"""Train the last Chinese Wav2Vec2 layer and component heads on trusted roots.

This offline experiment reads only train and calibration audio. It exports a
local checkpoint; it never decodes Chinese text or evaluates final-test audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file
from torch import nn

from pinyin_matcher.audio import decode_wav, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import read_cached, read_rows, supervision, write
from pinyin_matcher.pretrained_factorized import FactorizedHeads, factorized_loss
from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

SEED = 3182026
COMPONENTS = ("onset", "rime", "tone")
CONFIG = ROOT / "content/pronunciation-pretrained-chinese-tail.json"


def select_rows(rows, limit=1200):
    groups = {}
    for row, labels in zip(rows, supervision(rows), strict=True):
        if row["split"] != "train" or not (labels == 1).any():
            continue
        if row.get("labelPolicyFlags") or row.get("numericalQualityFlags"):
            continue
        score = hashlib.sha256(f"{SEED}:{row['id']}".encode()).hexdigest()
        groups.setdefault(row["speakerId"], []).append((score, row))
    lists = {k: [r for _, r in sorted(v, key=lambda x: x[0])] for k, v in groups.items()}
    selected = []
    for position in range(max(map(len, lists.values()), default=0)):
        for speaker in sorted(lists):
            if position < len(lists[speaker]):
                selected.append(lists[speaker][position])
                if len(selected) == limit:
                    return selected
    return selected


def masked_frames(model, samples, device):
    normalized = [(s - s.mean()) / np.sqrt(s.var() + 1e-7) for s in samples]
    lengths = torch.tensor([len(s) for s in normalized], device=device)
    waveform = torch.zeros(len(samples), int(lengths.max()), device=device)
    for index, sample in enumerate(normalized):
        waveform[index, : len(sample)] = torch.from_numpy(sample).to(device)
    hidden = waveform[:, None, :]
    for layer in model.feature_extractor.conv_layers:
        conv = layer.conv
        if conv.padding != (0,) or conv.dilation != (1,):
            raise ValueError("CHINESE_TAIL_UNSUPPORTED_CONVOLUTION")
        hidden = conv(hidden)
        lengths = (lengths - conv.kernel_size[0]) // conv.stride[0] + 1
        mask = torch.arange(hidden.shape[-1], device=device)[None, :] < lengths[:, None]
        if hasattr(layer, "layer_norm"):
            norm = layer.layer_norm
            if not isinstance(norm, nn.GroupNorm) or norm.num_groups != hidden.shape[1]:
                raise ValueError("CHINESE_TAIL_UNSUPPORTED_NORMALIZATION")
            valid = mask[:, None, :]
            mean = (hidden * valid).sum(-1, keepdim=True) / lengths[:, None, None]
            variance = ((hidden - mean).square() * valid).sum(-1, keepdim=True) / lengths[
                :, None, None
            ]
            hidden = (hidden - mean) * torch.rsqrt(variance + norm.eps)
            hidden = hidden * norm.weight[None, :, None] + norm.bias[None, :, None]
        hidden = layer.activation(hidden) * mask[:, None, :]
    hidden, _ = model.feature_projection(hidden.transpose(1, 2))
    result = model.encoder(hidden, attention_mask=mask).last_hidden_state
    if model.adapter is not None:
        raise ValueError("CHINESE_TAIL_ADAPTER_UNSUPPORTED")
    return result, lengths


def differentiable_pool(frames, lengths):
    vectors = []
    for frame, length in zip(frames, lengths.tolist(), strict=True):
        frame = frame[:length]
        sizes = [length // 3 + int(i < length % 3) for i in range(3)]
        if min(sizes) < 1:
            raise ValueError("CHINESE_TAIL_TOO_FEW_FRAMES")
        parts = torch.split(frame, sizes)
        vectors.append(
            torch.cat([frame.mean(0), frame.std(0, unbiased=False), *[p.mean(0) for p in parts]])
        )
    return torch.stack(vectors)


def tensor_digest(value):
    return hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def train(manifest, cache, initializer, model_dir, output, device):
    if output.exists():
        raise ValueError("CHINESE_TAIL_OUTPUT_EXISTS")
    protocol = json.loads(CONFIG.read_text())
    if protocol != {
        "schemaVersion": 1,
        "experimentId": "tencent-chinese-last-layer-v1",
        "seed": SEED,
        "trainRoots": 1200,
        "selection": "speaker-balanced-sha256-before-model-evaluation",
        "epochs": 4,
        "batchSize": 8,
        "tailLearningRate": 0.00001,
        "headLearningRate": 0.0001,
        "weightDecay": 0.01,
        "trainedTransformerLayers": 1,
        "checkpointSelection": "full-calibration-known-components-factorized-loss",
        "finalTestUsed": False,
    }:
        raise ValueError("CHINESE_TAIL_PROTOCOL_CHANGED")
    metadata = json.loads((initializer / "model.json").read_text())
    cache_meta = json.loads((cache / "cache.json").read_text())
    if (
        metadata["model"] != "tencent-zh-base"
        or metadata["manifestSha256"] != fingerprint(manifest)
        or cache_meta["manifestSha256"] != fingerprint(manifest)
        or metadata["cacheMetadataSha256"] != fingerprint(cache / "cache.json")
    ):
        raise ValueError("CHINESE_TAIL_INPUT_MISMATCH")
    rows = read_rows(manifest)
    selected = select_rows(rows)
    if len(selected) != 1200:
        raise ValueError("CHINESE_TAIL_TRAIN_SAMPLE_INSUFFICIENT")
    cal_rows = [r for r in rows if r["split"] == "calibration"]
    active_cal = [
        r
        for r, a in zip(cal_rows, supervision(cal_rows), strict=True)
        if not r.get("labelPolicyFlags") and not r.get("numericalQualityFlags") and (a >= 0).any()
    ]
    vocab = metadata["vocabulary"]
    identity = fingerprint(cache / "identity.json")

    def materialize(items):
        samples, pitches, labels = [], [], []
        for row in items:
            samples.append(trim_silence(decode_wav(Path(row["file"]).read_bytes())))
            with read_cached(cache / (row["sha256"] + ".npz"), identity) as item:
                pitches.append(item["pitch"].copy())
            labels.append(
                [vocab[k].index(str(row[k])) if str(row[k]) in vocab[k] else -1 for k in COMPONENTS]
            )
        return samples, np.stack(pitches), np.asarray(labels, dtype=np.int64), supervision(items)

    train_samples, train_pitch, train_labels, train_ann = materialize(selected)
    cal_samples, cal_pitch, cal_labels, cal_ann = materialize(active_cal)
    norm = np.load(initializer / "normalization.npz")
    mean, scale, pm, ps = [
        torch.from_numpy(norm[k].copy()).to(device)
        for k in ("mean", "scale", "pitch_mean", "pitch_scale")
    ]
    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    model = Wav2VecEvidence("tencent-zh-base", model_dir, device=device).model
    model.eval()
    for param in model.parameters():
        param.requires_grad_(False)
    tail = model.encoder.layers[-1]
    tail.requires_grad_(True)
    original_digests = {key: tensor_digest(value) for key, value in model.state_dict().items()}
    head = FactorizedHeads(
        metadata["dimensions"],
        [len(vocab[k]) for k in COMPONENTS],
        hidden=metadata["configuration"]["hiddenSize"],
        dropout=metadata["configuration"]["dropout"],
    ).to(device)
    head.load_state_dict(
        torch.load(initializer / "heads.pt", map_location=device, weights_only=True)
    )
    optimizer = torch.optim.AdamW(
        [{"params": tail.parameters(), "lr": 0.00001}, {"params": head.parameters(), "lr": 0.0001}],
        weight_decay=0.01,
    )
    rng = np.random.default_rng(SEED)
    best, history, best_encoder, best_head = float("inf"), [], None, None
    started = time.perf_counter()

    def forward(samples, pitch):
        frames, lengths = masked_frames(model, samples, device)
        pooled = (differentiable_pool(frames, lengths) - mean) / scale
        pitch = (torch.from_numpy(pitch).to(device) - pm) / ps
        return head.separate(pooled, pitch)

    for epoch in range(4):
        model.eval()
        tail.train()
        head.train()
        losses = []
        order = rng.permutation(len(selected))
        for start in range(0, len(order), 8):
            indices = order[start : start + 8]
            identity_logits, validity_logits = forward(
                [train_samples[i] for i in indices], train_pitch[indices]
            )
            loss, _, _ = factorized_loss(
                identity_logits,
                validity_logits,
                torch.from_numpy(train_labels[indices]).to(device),
                torch.from_numpy(train_ann[indices]).to(device),
            )
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(list(tail.parameters()) + list(head.parameters()), 5)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        model.eval()
        head.eval()
        cal_identity, cal_validity = [], []
        with torch.inference_mode():
            for start in range(0, len(active_cal), 8):
                ids, valid = forward(cal_samples[start : start + 8], cal_pitch[start : start + 8])
                cal_identity.append([x.cpu() for x in ids])
                cal_validity.append([x.cpu() for x in valid])
            merged_id = [torch.cat([x[i] for x in cal_identity]) for i in range(3)]
            merged_val = [torch.cat([x[i] for x in cal_validity]) for i in range(3)]
            score = float(
                factorized_loss(
                    merged_id, merged_val, torch.from_numpy(cal_labels), torch.from_numpy(cal_ann)
                )[0]
            )
        history.append(
            {"epoch": epoch + 1, "trainingLoss": float(np.mean(losses)), "calibrationLoss": score}
        )
        print(json.dumps(history[-1]), flush=True)
        if score < best:
            best, best_epoch = score, epoch + 1
            best_encoder = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_head = {k: v.detach().cpu().clone() for k, v in head.state_dict().items()}
    changed = [k for k, v in best_encoder.items() if tensor_digest(v) != original_digests[k]]
    if not changed or any(not k.startswith("encoder.layers.11.") for k in changed):
        raise ValueError("CHINESE_TAIL_FROZEN_PARAMETER_CHANGED_OR_TAIL_UNCHANGED")
    output.mkdir(parents=True)
    save_file(best_encoder, str(output / "model.safetensors"))
    torch.save(best_head, output / "heads.pt")
    report = {
        "schemaVersion": 1,
        "sourceModel": "tencent-zh-base",
        "seed": SEED,
        "trainingRoots": len(selected),
        "trainingSpeakers": len({r["speakerId"] for r in selected}),
        "calibrationRoots": len(cal_rows),
        "calibrationActiveForLoss": len(active_cal),
        "selectedEpoch": best_epoch,
        "epochs": 4,
        "batchSize": 8,
        "trainIdsSha256": hashlib.sha256("\n".join(r["id"] for r in selected).encode()).hexdigest(),
        "manifestSha256": fingerprint(manifest),
        "cacheSha256": fingerprint(cache / "cache.json"),
        "initializerSha256": fingerprint(initializer / "model.json"),
        "configurationSha256": fingerprint(CONFIG),
        "codeSha256": fingerprint(Path(__file__)),
        "modelSha256": fingerprint(output / "model.safetensors"),
        "headSha256": fingerprint(output / "heads.pt"),
        "changedParameterNames": changed,
        "history": history,
        "elapsedSeconds": time.perf_counter() - started,
        "finalTestUsed": False,
    }
    write(output / "training.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cache", "initializer", "model-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    print(json.dumps(train(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
