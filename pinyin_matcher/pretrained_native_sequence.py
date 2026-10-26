"""Whole-utterance native pinyin CTC, with original SenseVoice's last six TP layers.

Only explicit offline preparation resamples supplied licensed speech. Inference
never downloads or derives labels from characters or from an expected target.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import re
import shutil
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file, save_file
from scipy.signal import resample_poly
from torch import nn
from torch.nn import functional as F

from pinyin_matcher.audio import decode_wav, encode_wav, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_aishell3 import parse_content, verify_pinyin
from pinyin_matcher.pretrained_experiment import (
    calibrate,
    covered_targets,
    read_cached,
    read_rows,
    save_cached,
    write,
)
from pinyin_matcher.pretrained_finetune import _labels, signed_ctc_events
from pinyin_matcher.pretrained_native import native_probabilities, native_rime_aliases
from pinyin_matcher.pretrained_ompal_policy import _components
from pinyin_matcher.pretrained_prepare import REGISTRY
from pinyin_matcher.pretrained_runtime import signal_guard
from pinyin_matcher.pretrained_sensevoice import FILES, REVISION, SenseVoiceFeatures
from pinyin_matcher.pretrained_tail_finetune import (
    FrozenPrefix,
    TrainableTail,
    _padded_frontend,
    preflight,
    state_digest,
)

ARCHITECTURE = "sensevoice-70-native-sequence-v1"
CONFIG = ROOT / "content/pronunciation-pretrained-native-sequence.json"
DATA_CONFIG = ROOT / "content/pronunciation-aishell3-data.json"
HEADS = ("initial", "final", "tone")
COMPONENTS = ("onset", "rime", "tone")
VOCAB_FILES = [*(f"v2_1_{head}_vocabulary.json" for head in HEADS), "v2_1_target_schema.json"]


def configuration():
    value = json.loads(CONFIG.read_text())
    if (
        value["seed"] != 3182026
        or value["warmupEpochs"] != 2
        or value["fineTuneEpochs"] != 10
        or value["batchSize"] != 32
        or value["tailLearningRate"] != 1e-5
        or value["headLearningRate"] != 1e-3
        or value["frozenEncoderLayers"] != 64
        or value["trainableTaskEncoderLayers"] != 6
        or value["prompts"] != [3, 1, 2, 15]
        or value["dither"] != 0
        or value["finalTestUsed"]
    ):
        raise ValueError("NATIVE_SEQUENCE_PROTOCOL_CHANGED")
    return value


def vocabularies(directory):
    pinned = {
        r["path"]: r["sha256"]
        for r in json.loads(REGISTRY.read_text())["models"]["hanziflow"]["files"]
    }
    if any(fingerprint(directory / name) != pinned[name] for name in VOCAB_FILES):
        raise ValueError("NATIVE_FIXED_VOCABULARY_CHANGED")
    result = {
        head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text()) for head in HEADS
    }
    if any(
        len(result[head]) != count
        or result[head].get("<blank>") != 0
        or set(result[head].values()) != set(range(count))
        for head, count in zip(HEADS, (24, 44, 7), strict=True)
    ):
        raise ValueError("NATIVE_VOCABULARY_SCHEMA_INVALID")
    return result


def provided_sequences(pinyin, vocab):
    """Parse already provided pinyin; unsupported sounds are never dropped."""
    sequences = [[], [], []]
    unsupported = []
    aliases = native_rime_aliases("hanziflow")
    for index, syllable in enumerate(pinyin):
        parsed = _components(syllable)
        tokens = (
            parsed["onset"] or "ZERO",
            aliases.get(parsed["rime"], parsed["rime"]),
            "T" + str(parsed["tone"]),
        )
        for component, (head, token) in enumerate(zip(HEADS, tokens, strict=True)):
            if token not in vocab[head] or token in {"<blank>", "<unk>"}:
                unsupported.append(
                    {"index": index, "pinyin": syllable, "component": head, "token": token}
                )
            else:
                sequences[component].append(vocab[head][token])
    if not pinyin or unsupported:
        return None, unsupported or [{"reason": "EMPTY_PINYIN_SEQUENCE"}]
    return sequences, []


def minimum_ctc_frames(tokens):
    return len(tokens) + sum(a == b for a, b in zip(tokens, tokens[1:], strict=False))


def _read_pcm(path, *, rate=None):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (1, 2, "NONE"):
            raise ValueError("NATIVE_MONO_PCM16_REQUIRED")
        source_rate, frames = audio.getframerate(), audio.getnframes()
        if not 8000 <= source_rate <= 192000 or not 400 <= frames <= source_rate * 120:
            raise ValueError("NATIVE_AUDIO_DURATION_OR_RATE_INVALID")
        if rate is not None and source_rate != rate:
            raise ValueError("NATIVE_DERIVED_RATE_MISMATCH")
        raw = audio.readframes(frames)
        if len(raw) != frames * 2:
            raise ValueError("NATIVE_AUDIO_TRUNCATED")
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768, source_rate


def derive_audio(row, output):
    """Exactly one source-to-16k conversion; existing derived audio is verified."""
    source = Path(row["file"])
    if fingerprint(source) != row["sha256"]:
        raise ValueError("NATIVE_SOURCE_AUDIO_CHANGED")
    path = output / (row["id"] + ".wav")
    sidecar = path.with_suffix(".json")
    if path.exists() or sidecar.exists():
        metadata = json.loads(sidecar.read_text())
        if metadata["sourceSha256"] != row["sha256"] or fingerprint(path) != metadata["sha256"]:
            raise ValueError("NATIVE_DERIVED_AUDIO_CHANGED")
        return trim_silence(_read_pcm(path, rate=16000)[0]), metadata
    samples, rate = _read_pcm(source)
    divisor = math.gcd(rate, 16000)
    if rate != 16000:
        samples = resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_wav(samples))
    metadata = {
        "sourceSha256": row["sha256"],
        "sha256": fingerprint(path),
        "sourceRate": rate,
        "sampleRate": 16000,
        "up": 16000 // divisor,
        "down": rate // divisor,
        "method": "scipy-resample-poly-once-then-PCM16",
        "file": str(path.resolve()),
        "samples": len(samples),
    }
    write(sidecar, metadata)
    return trim_silence(_read_pcm(path, rate=16000)[0]), metadata


def _native_manifest(manifest):
    data, pinned = json.loads(manifest.read_text()), json.loads(DATA_CONFIG.read_text())
    if (
        not data["complete"]
        or not data["trainingOnly"]
        or data["finalTestRead"]
        or data["configSha256"] != fingerprint(DATA_CONFIG)
        or data["verifiedFiles"] != len(pinned["files"])
        or len(data["files"]) != len(pinned["files"])
    ):
        raise ValueError("NATIVE_COMPLETE_PINNED_TRAINING_DATA_REQUIRED")
    actual = {r["id"]: r for r in data["files"]}
    if set(actual) != {r["id"] for r in pinned["files"]}:
        raise ValueError("NATIVE_SOURCE_INVENTORY_MISMATCH")
    for record in pinned["metadataFiles"]:
        path = manifest.parent / "metadata" / record["localName"]
        if fingerprint(path) != record["sha256"]:
            raise ValueError("NATIVE_SOURCE_METADATA_CHANGED")
    provided = parse_content((manifest.parent / "metadata/train-content.txt").read_text())
    prosody = {}
    for line in (manifest.parent / "metadata/train-labels.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) != 3 or not re.fullmatch(r"SSB\d+", fields[0]):
            raise ValueError("NATIVE_PROSODY_LABEL_FORMAT_INVALID")
        name = fields[0] + ".wav"
        if name in prosody:
            raise ValueError("NATIVE_PROSODY_LABEL_DUPLICATED")
        prosody[name] = [p for p in fields[1].split() if p not in {"%", "$"}]
    for expected in pinned["files"]:
        row = actual[expected["id"]]
        if (
            row["status"] == "failed"
            or row["split"] != "train"
            or any(
                row[key] != expected[key]
                for key in ("sha256", "speakerId", "path", "pinyinSourceLineSha256")
            )
        ):
            raise ValueError("NATIVE_SOURCE_OR_LABEL_MISMATCH")
        verify_pinyin(row, provided)
        if row["pinyin"] != prosody.get(Path(row["path"]).name):
            raise ValueError("NATIVE_PROVIDED_PINYIN_SOURCES_DISAGREE")
        if fingerprint(Path(row["file"])) != row["sha256"]:
            raise ValueError("NATIVE_COMPLETE_AUDIO_INVENTORY_CHANGED")
    return data["files"]


def cache_native(manifest, model, vocabulary, output, *, device):
    config = configuration()
    rows = _native_manifest(manifest)
    vocab = vocabularies(vocabulary)
    identity = {
        "architecture": ARCHITECTURE,
        "manifestSha256": fingerprint(manifest),
        "sourceWeightsSha256": FILES["model.pt"],
        "configurationSha256": fingerprint(CONFIG),
        "codeSha256": fingerprint(Path(__file__)),
        "prefixCodeSha256": fingerprint(Path(__file__).with_name("pretrained_tail_finetune.py")),
        "audioCodeSha256": fingerprint(Path(__file__).with_name("audio.py")),
        "dependencyLockSha256": fingerprint(ROOT / "tools/pinyin-pretrained/uv.lock"),
        "pinyinRulesSha256": fingerprint(ROOT / "content/pronunciation-rules.json"),
        "nativeAliasConfigurationSha256": fingerprint(
            ROOT / "content/pronunciation-pretrained-experiment.json"
        ),
        "nativeVocabularySha256": {name: fingerprint(vocabulary / name) for name in VOCAB_FILES},
        "device": device,
        "testUsed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    identity_path = output / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("NATIVE_PREFIX_CACHE_IDENTITY_CHANGED")
    write(identity_path, identity)
    identity_sha = fingerprint(identity_path)
    prepared, excluded = [], []
    for row in rows:
        targets, unsupported = provided_sequences(row["pinyin"], vocab)
        if unsupported:
            excluded.append(
                {"id": row["id"], "reason": "UNSUPPORTED_PROVIDED_PINYIN", "tokens": unsupported}
            )
            continue
        samples, derived = derive_audio(row, output / "audio")
        prepared.append({"row": row, "targets": targets, "samples": samples, "derived": derived})
    if not prepared:
        raise ValueError("NATIVE_NO_SUPPORTED_SEQUENCE")
    source = SenseVoiceFeatures(model, device=device)
    prefix, tail = FrozenPrefix(source.encoder).eval(), TrainableTail(source.encoder).eval()
    parity = preflight(source, prefix, tail, [r["samples"] for r in prepared[:3]])
    items = []
    started = time.perf_counter()
    # Full utterances are grouped by length; no fragment or word-boundary inference.
    prepared.sort(key=lambda r: (len(r["samples"]), r["row"]["id"]))
    for start in range(0, len(prepared), config["cacheBatchSize"]):
        batch = prepared[start : start + config["cacheBatchSize"]]
        with torch.inference_mode():
            x, lengths = _padded_frontend(source, [r["samples"] for r in batch])
            frames = prefix(x, lengths)
            for i, row in enumerate(batch):
                length = int(lengths[i])
                if any(length - 4 < minimum_ctc_frames(t) for t in row["targets"]):
                    excluded.append({"id": row["row"]["id"], "reason": "CTC_PATH_TOO_SHORT"})
                    continue
                path = output / (row["row"]["id"] + ".npz")
                if path.exists():
                    with read_cached(path, identity_sha):
                        pass
                else:
                    save_cached(
                        path,
                        {
                            "prefix": frames[i, :length].cpu().numpy(),
                            "length": np.asarray(length, dtype=np.int64),
                        },
                        identity_sha,
                    )
                items.append(
                    {
                        "id": row["row"]["id"],
                        "speakerId": row["row"]["speakerId"],
                        "file": str(path.resolve()),
                        "sha256": fingerprint(path),
                        "targets": row["targets"],
                        "length": length,
                        "providedPinyin": row["row"]["pinyin"],
                        "audio": row["derived"],
                    }
                )
        print(
            json.dumps(
                {
                    "cachedNativeUtterances": min(start + len(batch), len(prepared)),
                    "supportedPlanned": len(prepared),
                }
            ),
            flush=True,
        )
    result = {
        **identity,
        "identitySha256": identity_sha,
        "plannedUtterances": len(rows),
        "cachedUtterances": len(items),
        "excludedUtterances": len(excluded),
        "providedSyllables": sum(len(row["pinyin"]) for row in rows),
        "trainingSyllables": sum(len(row["providedPinyin"]) for row in items),
        "prefixStateSha256": state_digest(prefix),
        "initialTailStateSha256": state_digest(tail),
        "parity": parity,
        "elapsedSeconds": time.perf_counter() - started,
        "excluded": excluded,
        "items": items,
    }
    write(output / "cache.json", result)
    return {k: v for k, v in result.items() if k not in {"items", "excluded"}}


class NativeSequenceHeads(nn.Module):
    def __init__(self):
        super().__init__()
        self.initial_head = nn.Linear(512, 24)
        self.final_head = nn.Linear(512, 44)
        self.tone_head = nn.Linear(512, 7)

    def forward(self, encoded):
        return self.initial_head(encoded), self.final_head(encoded), self.tone_head(encoded)


def _forward(tail, heads, items, device):
    lengths = torch.tensor([len(r["prefix"]) for r in items], device=device)
    x = torch.zeros(len(items), int(lengths.max()), 512, device=device)
    for i, item in enumerate(items):
        x[i, : lengths[i]] = item["prefix"].to(device)
    encoded = tail(x, lengths)[:, 4:]
    return heads(encoded), lengths - 4


def validate_cached_labels(metadata, source_rows, native_vocab, cache):
    """Reconstruct labels from verified source metadata, never trust cache targets."""
    source = {r["id"]: r for r in source_rows}
    items, exclusions = metadata["items"], metadata["excluded"]
    selected_ids = [r["id"] for r in items]
    excluded_ids = [r["id"] for r in exclusions]
    if (
        len(set(selected_ids)) != len(selected_ids)
        or len(set(excluded_ids)) != len(excluded_ids)
        or set(selected_ids) & set(excluded_ids)
        or set(selected_ids) | set(excluded_ids) != set(source)
        or metadata["cachedUtterances"] != len(items)
        or metadata["excludedUtterances"] != len(exclusions)
        or metadata["plannedUtterances"] != len(source)
    ):
        raise ValueError("NATIVE_CACHED_SOURCE_PARTITION_INVALID")
    for item in items:
        row = source[item["id"]]
        expected, errors = provided_sequences(row["pinyin"], native_vocab)
        if (
            errors
            or item["targets"] != expected
            or item["providedPinyin"] != row["pinyin"]
            or item["speakerId"] != row["speakerId"]
        ):
            raise ValueError("NATIVE_CACHED_LABEL_OR_SPEAKER_CHANGED")
    for item in exclusions:
        row = source[item["id"]]
        targets, errors = provided_sequences(row["pinyin"], native_vocab)
        if item["reason"] == "UNSUPPORTED_PROVIDED_PINYIN":
            if not errors or item.get("tokens") != errors:
                raise ValueError("NATIVE_UNSUPPORTED_EXCLUSION_NOT_JUSTIFIED")
        elif item["reason"] == "CTC_PATH_TOO_SHORT" and not errors:
            path = cache / "audio" / (row["id"] + ".wav")
            audio = json.loads(path.with_suffix(".json").read_text())
            if audio["sourceSha256"] != row["sha256"] or audio["sha256"] != fingerprint(path):
                raise ValueError("NATIVE_SHORT_SEQUENCE_AUDIO_CHANGED")
            samples = trim_silence(_read_pcm(path, rate=16000)[0])
            frames = math.ceil(((len(samples) - 400) // 160 + 1) / 6)
            if not any(frames < minimum_ctc_frames(t) for t in targets):
                raise ValueError("NATIVE_SHORT_SEQUENCE_EXCLUSION_NOT_JUSTIFIED")
        else:
            raise ValueError("NATIVE_UNKNOWN_TRAINING_EXCLUSION")


def sequence_ctc_loss(outputs, lengths, targets):
    """Differentiable CPU float64 CTC; target-length scaling affects training only."""
    losses = []
    for component, logits in enumerate(outputs):
        sequences = [t[component] for t in targets]
        target_lengths = torch.tensor([len(t) for t in sequences], dtype=torch.long)
        if any(
            int(length) < minimum_ctc_frames(t)
            for length, t in zip(lengths.cpu(), sequences, strict=True)
        ):
            raise ValueError("NATIVE_CTC_PATH_IMPOSSIBLE")
        flat = torch.tensor([token for t in sequences for token in t], dtype=torch.long)
        logp = (
            logits.to(device="cpu")
            .to(dtype=torch.float64)
            .log_softmax(-1)
            .transpose(0, 1)
            .contiguous()
        )
        nll = F.ctc_loss(
            logp,
            flat,
            lengths.cpu(),
            target_lengths,
            blank=0,
            reduction="none",
            zero_infinity=False,
        )
        if not torch.isfinite(nll).all():
            raise ValueError("NATIVE_CTC_LOSS_NONFINITE")
        losses.append((nll / target_lengths).mean())
    return sum(losses)


def _calibration_items(manifest, cache, vocab):
    rows = [
        r
        for r in read_rows(manifest, verify_splits=("calibration",))
        if r["split"] == "calibration"
    ]
    metadata = json.loads((cache / "cache.json").read_text())
    if metadata["manifestSha256"] != fingerprint(manifest):
        raise ValueError("NATIVE_CALIBRATION_MANIFEST_MISMATCH")
    identity_sha = fingerprint(cache / "identity.json")
    items, exclusions = [], []
    aliases = native_rime_aliases("hanziflow")
    for index, row in enumerate(rows):
        if (
            row.get("numericalQualityFlags")
            or row.get("labelPolicyFlags")
            or row.get("placeholder")
        ):
            exclusions.append({"id": row["id"], "reason": "PREDECLARED_UNASSESSABLE"})
            continue
        try:
            targets, annotations = _labels(row, vocab, aliases)
        except ValueError as error:
            exclusions.append({"id": row["id"], "reason": str(error)})
            continue
        with read_cached(cache / (row["sha256"] + ".npz"), identity_sha) as entry:
            prefix = torch.from_numpy(entry["prefix"].copy())
        samples = decode_wav(Path(row["file"]).read_bytes())
        items.append(
            {
                "index": index,
                "prefix": prefix,
                "targets": targets,
                "annotations": annotations,
                "guard": signal_guard(samples),
            }
        )
    return rows, items, exclusions, metadata


def calibration(tail, heads, items, rows, generic_vocab, native_vocab, device, batch_size):
    tail.eval()
    heads.eval()
    sums, counts = np.zeros((3, 2)), np.zeros((3, 2), dtype=np.int64)
    probabilities = [
        np.zeros((len(rows), len(generic_vocab[k])), dtype=np.float64) for k in COMPONENTS
    ]
    forced = Counter()
    with torch.inference_mode():
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            outputs, lengths = _forward(tail, heads, batch, device)
            annotations = torch.tensor([r["annotations"] for r in batch])
            losses, _ = signed_ctc_events(
                list(outputs), lengths, [r["targets"] for r in batch], annotations
            )
            for component in range(3):
                for label in (0, 1):
                    chosen = annotations[:, component] == label
                    sums[component, label] += float(losses[chosen, component].sum())
                    counts[component, label] += int(chosen.sum())
            cpu = [x.cpu().numpy() for x in outputs]
            for i, item in enumerate(batch):
                native = {
                    "native_" + head: values[i, : int(lengths[i])]
                    for head, values in zip(HEADS, cpu, strict=True)
                }
                values, details = native_probabilities(
                    "hanziflow", native, generic_vocab, native_vocab=native_vocab
                )
                reason = item["guard"] or (
                    "NATIVE_EVENT_UNASSESSABLE" if details["forceUncertain"] else None
                )
                if reason:
                    forced[reason] += 1
                    continue
                for component in range(3):
                    probabilities[component][item["index"]] = values[component]
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    return {
        "balancedSignedCtcLoss": float(means[counts > 0].mean()),
        "componentClassMeanLoss": means.tolist(),
        "componentClassCounts": counts.tolist(),
        "forcedAbstentions": dict(forced),
    }, probabilities


def train(
    native_cache,
    source_manifest,
    calibration_manifest,
    calibration_cache,
    model,
    vocabulary,
    output,
    *,
    device,
):
    if output.exists():
        raise ValueError("NATIVE_SEQUENCE_OUTPUT_EXISTS")
    config = configuration()
    metadata = json.loads((native_cache / "cache.json").read_text())
    native_vocab = vocabularies(vocabulary)
    source_rows = _native_manifest(source_manifest)
    if metadata["manifestSha256"] != fingerprint(source_manifest):
        raise ValueError("NATIVE_TRAIN_SOURCE_MANIFEST_CHANGED")
    validate_cached_labels(metadata, source_rows, native_vocab, native_cache)
    if (
        metadata["configurationSha256"] != fingerprint(CONFIG)
        or metadata["identitySha256"] != fingerprint(native_cache / "identity.json")
        or metadata["cachedUtterances"] + metadata["excludedUtterances"]
        != metadata["plannedUtterances"]
        or any(
            metadata["nativeVocabularySha256"][name] != fingerprint(vocabulary / name)
            for name in VOCAB_FILES
        )
    ):
        raise ValueError("NATIVE_TRAIN_CACHE_IDENTITY_MISMATCH")
    items = []
    for row in metadata["items"]:
        path = Path(row["file"])
        if fingerprint(path) != row["sha256"]:
            raise ValueError("NATIVE_TRAIN_CACHE_CORRUPT")
        with read_cached(path, metadata["identitySha256"]) as data:
            items.append(
                {"prefix": torch.from_numpy(data["prefix"].copy()), "targets": row["targets"]}
            )
    if not items:
        raise ValueError("NATIVE_TRAINING_EMPTY")
    cal_rows, cal_items, cal_excluded, cal_metadata = _calibration_items(
        calibration_manifest, calibration_cache, native_vocab
    )
    train_rows = [
        r
        for r in read_rows(calibration_manifest)
        if r["split"] == "train"
        and not r.get("numericalQualityFlags")
        and not r.get("labelPolicyFlags")
    ]
    generic_vocab = {k: sorted({str(r[k]) for r in train_rows}) for k in COMPONENTS}
    torch.manual_seed(config["seed"])
    source = SenseVoiceFeatures(model, device="cpu")
    frozen = state_digest(FrozenPrefix(source.encoder))
    if frozen != metadata["prefixStateSha256"] or frozen != cal_metadata["prefixStateSha256"]:
        raise ValueError("NATIVE_PREFIX_SOURCE_MISMATCH")
    tail = TrainableTail(source.encoder).to(device)
    del source
    gc.collect()
    heads = NativeSequenceHeads().to(device)
    initial_tail = {k: v.detach().cpu().clone() for k, v in tail.state_dict().items()}
    initial_heads = {k: v.detach().cpu().clone() for k, v in heads.state_dict().items()}
    optimizer = torch.optim.AdamW(
        [
            {"params": heads.parameters(), "lr": config["headLearningRate"]},
            {"params": tail.parameters(), "lr": config["tailLearningRate"]},
        ],
        weight_decay=config["weightDecay"],
    )
    output.mkdir(parents=True)
    initial, _ = calibration(
        tail, heads, cal_items, cal_rows, generic_vocab, native_vocab, device, config["batchSize"]
    )
    history, best, epoch_selected = [], initial["balancedSignedCtcLoss"], 0
    checkpoint = {"tail." + k: v.clone() for k, v in initial_tail.items()}
    checkpoint.update({"heads." + k: v.clone() for k, v in initial_heads.items()})
    started = time.perf_counter()
    order = sorted(range(len(items)), key=lambda i: len(items[i]["prefix"]))
    for epoch in range(config["warmupEpochs"] + config["fineTuneEpochs"]):
        tune = epoch >= config["warmupEpochs"]
        tail.requires_grad_(tune)
        tail.train()
        heads.train()
        rng = np.random.default_rng(config["seed"] + epoch)
        batches = [
            order[i : i + config["batchSize"]] for i in range(0, len(order), config["batchSize"])
        ]
        rng.shuffle(batches)
        losses, first_grad = [], None
        for indices in batches:
            batch = [items[i] for i in indices]
            outputs, lengths = _forward(tail, heads, batch, device)
            loss = sequence_ctc_loss(outputs, lengths, [r["targets"] for r in batch])
            optimizer.zero_grad()
            loss.backward()
            if first_grad is None:
                first_grad = sum(
                    float(p.grad.abs().sum()) for p in tail.parameters() if p.grad is not None
                )
            nn.utils.clip_grad_norm_(
                [*tail.parameters(), *heads.parameters()],
                config["gradientClip"],
                error_if_nonfinite=True,
            )
            optimizer.step()
            losses.append(float(loss.detach()))
        result, _ = calibration(
            tail,
            heads,
            cal_items,
            cal_rows,
            generic_vocab,
            native_vocab,
            device,
            config["batchSize"],
        )
        history.append(
            {
                "epoch": epoch + 1,
                "tailTrainable": tune,
                "trainLoss": float(np.mean(losses)),
                "firstBatchTailGradientAbsoluteSum": first_grad,
                **result,
            }
        )
        if result["balancedSignedCtcLoss"] < best:
            best, epoch_selected = result["balancedSignedCtcLoss"], epoch + 1
            checkpoint = {
                "tail." + k: v.detach().cpu().clone() for k, v in tail.state_dict().items()
            }
            checkpoint.update(
                {"heads." + k: v.detach().cpu().clone() for k, v in heads.state_dict().items()}
            )
        write(output / "training.json", history)
        print(json.dumps(history[-1]), flush=True)
    last_tail_changes = {
        k: float((v.detach().cpu() - initial_tail[k]).abs().max())
        for k, v in tail.state_dict().items()
    }
    tail.load_state_dict({k[5:]: v for k, v in checkpoint.items() if k.startswith("tail.")})
    heads.load_state_dict({k[6:]: v for k, v in checkpoint.items() if k.startswith("heads.")})
    result, probabilities = calibration(
        tail, heads, cal_items, cal_rows, generic_vocab, native_vocab, device, config["batchSize"]
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
    resources = ["am.mvn", "config.yaml", "MODEL_LICENSE", "README.md"]
    for name in resources:
        shutil.copy2(model / name, output / name)
    for name in VOCAB_FILES:
        shutil.copy2(vocabulary / name, output / name)
    shutil.copy2(ROOT / "resources/licenses/SenseVoice-MIT.txt", output / "SOURCE-MIT.txt")
    files = {
        name: {"sha256": fingerprint(output / name), "bytes": (output / name).stat().st_size}
        for name in ["tuned.safetensors", *resources, *VOCAB_FILES, "SOURCE-MIT.txt"]
    }
    metadata = {
        "schemaVersion": 1,
        "architecture": ARCHITECTURE,
        "model": "sensevoice",
        "sourceDirectory": str(model.resolve()),
        "sourceRevision": REVISION,
        "sourceWeightsSha256": FILES["model.pt"],
        "parentWeightSha256": FILES["model.pt"],
        "configuration": config,
        "configurationSha256": fingerprint(CONFIG),
        "nativeRimeAliases": native_rime_aliases("hanziflow"),
        "files": files,
        "nativeCacheMetadataSha256": fingerprint(native_cache / "cache.json"),
        "nativeSourceManifestSha256": fingerprint(source_manifest),
        "manifestSha256": fingerprint(calibration_manifest),
        "calibrationPrefixSha256": fingerprint(calibration_cache / "cache.json"),
        "vocabulary": generic_vocab,
        "coveredTargets": covered_targets(generic_vocab, train_rows),
        "trainingUtterances": len(items),
        "trainingSpeakers": len(
            {r["speakerId"] for r in json.loads((native_cache / "cache.json").read_text())["items"]}
        ),
        "calibrationRows": len(cal_rows),
        "calibrationLossRows": len(cal_items),
        "calibrationExclusions": cal_excluded,
        "initialCalibration": initial,
        "selectedEpoch": epoch_selected,
        "selectedCalibration": result,
        "trainingSeconds": time.perf_counter() - started,
        "frozenPrefixStateSha256": frozen,
        "frozenPrefixUsedOnlyAsCachedConstant": True,
        "lastEpochTailTensorMaximumChanges": last_tail_changes,
        "selectedTailTensorMaximumChanges": {
            k: float((v.detach().cpu() - initial_tail[k]).abs().max())
            for k, v in tail.state_dict().items()
        },
        "selectedHeadTensorMaximumChanges": {
            k: float((v.detach().cpu() - initial_heads[k]).abs().max())
            for k, v in heads.state_dict().items()
        },
        "implementationSha256": fingerprint(Path(__file__)),
        "testUsed": False,
        "labelLimitation": (
            "Provided realized pinyin is corpus annotation, "
            "not independently re-audited phonetic truth or child validation."
        ),
        "qualityEvidence": "Cached prefix calibration; full CPU export evaluation pending.",
    }
    write(output / "calibration.json", summary)
    write(output / "tuned.json", metadata)
    return {
        k: metadata[k]
        for k in ("architecture", "selectedEpoch", "trainingSeconds", "trainingUtterances")
    }


class NativeSequenceEvidence:
    """Explicit local source + trained delta; deploy the independent INT8 export."""

    dimensions = 512
    name = "sensevoice"

    def __init__(self, directory, *, source=None, device="cpu", threads=2):
        if threads != 2 or device not in {"cpu", "mps"}:
            raise ValueError("NATIVE_SEQUENCE_DEVICE_OR_THREADS_INVALID")
        self.directory = Path(directory)
        self.metadata = json.loads((self.directory / "tuned.json").read_text())
        if (
            self.metadata["architecture"] != ARCHITECTURE
            or self.metadata["sourceWeightsSha256"] != FILES["model.pt"]
            or self.metadata["parentWeightSha256"] != FILES["model.pt"]
            or self.metadata["sourceRevision"] != REVISION
            or self.metadata["configuration"] != configuration()
            or self.metadata["configurationSha256"] != fingerprint(CONFIG)
            or self.metadata["nativeRimeAliases"] != native_rime_aliases("hanziflow")
        ):
            raise ValueError("NATIVE_SEQUENCE_ARCHITECTURE_OR_PARENT_MISMATCH")
        required = {
            "tuned.safetensors",
            "am.mvn",
            "config.yaml",
            "MODEL_LICENSE",
            "README.md",
            "SOURCE-MIT.txt",
            *VOCAB_FILES,
        }
        if not required.issubset(self.metadata["files"]):
            raise ValueError("NATIVE_SEQUENCE_REQUIRED_RESOURCES_MISSING")
        for relative, record in self.metadata["files"].items():
            path = (self.directory / relative).resolve()
            if (
                not path.is_relative_to(self.directory.resolve())
                or fingerprint(path) != record["sha256"]
            ):
                raise ValueError("NATIVE_SEQUENCE_RESOURCE_CHANGED")
        self.native_vocab = vocabularies(self.directory)
        self.source = SenseVoiceFeatures(source or self.metadata["sourceDirectory"], device=device)
        self.encoder, self.embed, self.cmvn = (
            self.source.encoder,
            self.source.embed,
            self.source.cmvn,
        )
        delta = load_file(self.directory / "tuned.safetensors", device="cpu")
        tail = TrainableTail(self.encoder)
        self.heads = NativeSequenceHeads().to(device).eval()
        expected = {"tail." + k for k in tail.state_dict()} | {
            "heads." + k for k in self.heads.state_dict()
        }
        if set(delta) != expected:
            raise ValueError("NATIVE_SEQUENCE_CHECKPOINT_KEYS_INVALID")
        tail.load_state_dict({k[5:]: v for k, v in delta.items() if k.startswith("tail.")})
        self.heads.load_state_dict({k[6:]: v for k, v in delta.items() if k.startswith("heads.")})
        self.device = self.source.device

    def frontend(self, samples):
        return self.source.frontend(samples)

    def evidence_batch(self, samples):
        with torch.inference_mode():
            x, lengths = _padded_frontend(self.source, samples)
            encoded = self.encoder(x, lengths)[:, 4:]
            outputs = self.heads(encoded)
            return [
                {
                    "frames": encoded[i, : n - 4].cpu().numpy(),
                    "native": {
                        head: value[i, : n - 4].cpu().numpy()
                        for head, value in zip(HEADS, outputs, strict=True)
                    },
                }
                for i, n in enumerate(lengths.tolist())
            ]

    def evidence(self, samples):
        return self.evidence_batch([samples])[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("cache")
    for key in ("manifest", "model", "vocabulary", "output"):
        prepare.add_argument("--" + key, type=Path, required=True)
    prepare.add_argument("--device", choices=("cpu", "mps"), default="mps")
    fit = sub.add_parser("train")
    for key in (
        "native-cache",
        "source-manifest",
        "calibration-manifest",
        "calibration-cache",
        "model",
        "vocabulary",
        "output",
    ):
        fit.add_argument("--" + key, type=Path, required=True)
    fit.add_argument("--device", choices=("cpu", "mps"), default="mps")
    args = vars(parser.parse_args())
    action = args.pop("action")
    print(json.dumps((cache_native if action == "cache" else train)(**args)))


if __name__ == "__main__":
    main()
