"""Actual phonetic CTC training on SenseVoice's first50 acoustic encoder layers.

The original70-layer source stays intact. These three randomly initialized
phonetic heads are new outputs, not original SenseVoice CTC or Hanzi decoding.
The H vocabulary supplies phonetic symbols only, never its acoustic weights.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import random
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file, save_file
from torch import nn

from pinyin_matcher.audio import decode_wav, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_finetune import (
    _batches,
    _class_weights,
    _labels,
    _write,
    signed_ctc_events,
)
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_prepare import REGISTRY
from pinyin_matcher.pretrained_sensevoice import (
    FILES,
    REVISION,
    SOURCE_REVISION,
    SenseVoiceFeatures,
    _check_files,
    _cmvn,
    _Layer,
)

ARCHITECTURE = "sensevoice-50-ctc-v1"
HEADS = ("initial", "final", "tone")
COMPONENTS = ("onset", "rime", "tone")
PROMPTS = [3, 1, 2, 15]
CONFIG = ROOT / "content/pronunciation-pretrained-sensevoice-finetune.json"
VOCAB_FILES = [*(f"v2_1_{head}_vocabulary.json" for head in HEADS), "v2_1_target_schema.json"]


def configuration() -> dict:
    config = json.loads(CONFIG.read_text())
    if (
        config["warmupEpochs"] != 2
        or config["fineTuneEpochs"] != 10
        or config["batchSize"] != 16
        or config["retainedEncoderLayers"] != 50
        or config["frozenEncoderLayers"] != 44
        or config["trainableEncoderLayers"] != 6
        or config["prompts"] != PROMPTS
        or config["dither"] != 0
        or config["gradientCheckpointing"] is not False
    ):
        raise ValueError("SENSEVOICE_PHONETIC_PROTOCOL_CHANGED")
    return config


class _AcousticEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoders0 = nn.ModuleList([_Layer(560)])
        self.encoders = nn.ModuleList([_Layer() for _ in range(49)])
        self.after_norm = nn.LayerNorm(512)

    def forward(self, x, lengths):
        positions = torch.arange(1, x.shape[1] + 1, device=x.device, dtype=x.dtype)
        scales = torch.exp(
            torch.arange(280, device=x.device, dtype=x.dtype) * (-math.log(10000) / 279)
        )
        phase = positions[:, None] * scales[None]
        x = x * math.sqrt(512) + torch.cat((phase.sin(), phase.cos()), dim=-1)[None]
        mask = (torch.arange(x.shape[1], device=x.device)[None] < lengths[:, None])[:, None]
        for layer in [*self.encoders0, *self.encoders]:
            x = layer(x, mask)
        return self.after_norm(x)


class _PhoneticSense(nn.Module):
    def __init__(self, embedding_rows: int):
        super().__init__()
        self.encoder = _AcousticEncoder()
        self.embed = nn.Embedding(embedding_rows, 560)
        self.register_buffer("cmvn", torch.empty(2, 560))
        self.initial_head = nn.Linear(512, 24)
        self.final_head = nn.Linear(512, 44)
        self.tone_head = nn.Linear(512, 7)

    def forward(self, features, lengths):
        prompt = self.embed(torch.tensor(PROMPTS, device=features.device))
        padded = torch.cat((prompt[None].expand(len(features), -1, -1), features), dim=1)
        encoded = self.encoder(padded, lengths + 4)[:, 4:]
        return (
            encoded,
            self.initial_head(encoded),
            self.final_head(encoded),
            self.tone_head(encoded),
        )


def _source_model(directory: Path) -> _PhoneticSense:
    _check_files(directory)
    state = torch.load(directory / "model.pt", map_location="cpu", weights_only=True, mmap=True)
    embedding_rows = len(state["embed.weight"])
    with torch.device("meta"):
        model = _PhoneticSense(embedding_rows)
    weights = {
        key: value
        for key, value in state.items()
        if key.startswith(("encoder.encoders0.", "encoder.encoders.", "encoder.after_norm."))
        or key == "embed.weight"
    }
    weights["cmvn"] = _cmvn(directory / "am.mvn")
    for head, width in zip(HEADS, (24, 44, 7), strict=True):
        for name, value in nn.Linear(512, width).state_dict().items():
            weights[f"{head}_head.{name}"] = value
    model.load_state_dict(weights, strict=True, assign=True)
    return model.eval()


def select_trainable(model: _PhoneticSense, *, tail: bool) -> list[str]:
    model.requires_grad_(False)
    for head in (model.initial_head, model.final_head, model.tone_head):
        head.requires_grad_(True)
    if tail:
        for layer in model.encoder.encoders[-6:]:
            layer.requires_grad_(True)
        model.encoder.after_norm.requires_grad_(True)
    return [name for name, parameter in model.named_parameters() if parameter.requires_grad]


def _frontend(model: _PhoneticSense, samples: np.ndarray) -> torch.Tensor:
    # The reviewed official adapter supplies exactly dither0/LFR7-stride6/CMVN.
    holder = type("FixedCmvnFrontend", (), {})()
    holder.cmvn = model.cmvn.detach().cpu()
    return SenseVoiceFeatures.frontend(holder, samples)


def _forward(model: _PhoneticSense, items: list[dict], device: str):
    lengths = torch.tensor([len(item["features"]) for item in items], dtype=torch.long)
    features = torch.zeros(len(items), int(lengths.max()), 560, device=device)
    for index, item in enumerate(items):
        features[index, : len(item["features"])] = item["features"].to(device)
    outputs = model(features, lengths.to(device))
    annotations = torch.tensor([item["annotations"] for item in items], dtype=torch.long)
    return list(outputs[1:]), lengths, annotations


def prepare_rows(rows: list[dict], model: _PhoneticSense, vocabularies: dict) -> tuple[list, dict]:
    result, counts = [], Counter()
    aliases = native_rime_aliases("hanziflow")
    for row in rows:
        counts["allRowsRetainedForEvaluation"] += 1
        if (
            row.get("labelPolicyFlags")
            or row.get("numericalQualityFlags")
            or row.get("placeholder")
        ):
            counts["predeclaredUnassessable"] += 1
            continue
        try:
            targets, annotations = _labels(row, vocabularies, aliases)
            samples = trim_silence(decode_wav(Path(row["file"]).read_bytes()))
            features = _frontend(model, samples)
        except ValueError:
            counts["unsupportedOrUnavailable"] += 1
            continue
        if not len(features) or not torch.isfinite(features).all():
            raise ValueError("SENSEVOICE_TRAIN_FRONTEND_INVALID")
        result.append(
            {
                "id": row["id"],
                "samples": samples,
                "features": features,
                "targets": targets,
                "annotations": annotations,
                "trusted": row.get("expertLabel") == "unanimous-correct"
                and annotations == [1, 1, 1],
            }
        )
        counts["eligibleNaturalWords"] += 1
        counts["trustedAllCorrectWords"] += result[-1]["trusted"]
        counts["minimumCtcFrames"] = min(
            counts.get("minimumCtcFrames", len(features)), len(features)
        )
        for index, component in enumerate(COMPONENTS):
            counts[component + ":" + str(annotations[index])] += 1
    return result, dict(counts)


def epoch_items(natural: list[dict], model: _PhoneticSense, rng: random.Random) -> tuple[list, int]:
    config = configuration()
    trusted = [item for item in natural if item["trusted"]]
    if not trusted:
        raise ValueError("SENSEVOICE_NO_TRUSTED_COMPOSITION_ROOTS")
    count = round(len(natural) * config["compositionExtraFraction"])
    pause = np.zeros(round(config["compositionPauseSeconds"] * 16000), dtype=np.float32)
    result = list(natural)
    for _ in range(count):
        first, second = rng.choice(trusted), rng.choice(trusted)
        samples = np.r_[first["samples"], pause, second["samples"]]
        targets = [a + b for a, b in zip(first["targets"], second["targets"], strict=True)]
        features = _frontend(model, samples)
        minimum = max(
            len(tokens) + sum(a == b for a, b in zip(tokens, tokens[1:], strict=False))
            for tokens in targets
        )
        if len(features) < minimum:
            raise ValueError("SENSEVOICE_COMPOSED_CTC_PATH_IMPOSSIBLE")
        result.append(
            {
                "id": "composition:" + first["id"] + ":" + second["id"],
                "samples": samples,
                "features": features,
                "targets": targets,
                "annotations": [1, 1, 1],
                "trusted": True,
            }
        )
    return result, count


def calibration(model: _PhoneticSense, items: list[dict], device: str, size: int) -> dict:
    sums, counts = np.zeros((3, 2)), np.zeros((3, 2), dtype=np.int64)
    model.eval()
    with torch.inference_mode():
        for batch in _batches(items, size):
            outputs, lengths, annotations = _forward(model, batch, device)
            losses, _ = signed_ctc_events(
                outputs, lengths, [item["targets"] for item in batch], annotations
            )
            for component in range(3):
                for label in (0, 1):
                    chosen = annotations[:, component] == label
                    sums[component, label] += float(losses[chosen, component].sum())
                    counts[component, label] += int(chosen.sum())
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    return {
        "balancedSignedCtcLoss": float(means[counts > 0].mean()),
        "componentClassMeanLoss": means.tolist(),
        "componentClassCounts": counts.tolist(),
    }


def preflight(model: _PhoneticSense, original: Path, natural: list[dict], device: str) -> dict:
    """Actual original50-layer parity plus real-input MPS gradient validation."""
    sample = natural[0]["samples"]
    captured = []
    source = SenseVoiceFeatures(original, device="cpu")
    hook = source.encoder.after_norm.register_forward_hook(
        lambda _, __, value: captured.append(value.detach().cpu())
    )
    source.extract(sample)
    hook.remove()
    batch = [{**natural[0], "features": _frontend(model, sample)}]
    features = batch[0]["features"][None]
    with torch.inference_mode():
        actual = model(features, torch.tensor([features.shape[1]]))[0]
    parity = float(torch.max(torch.abs(actual - captured[0][:, 4:])))
    del source
    captured.clear()
    gc.collect()
    if parity > 1e-5:
        raise ValueError("SENSEVOICE_SOURCE_MID_ENCODER_PARITY_FAILED")
    model.to(device)
    gradient_results = []
    for tail in (False, True):
        names = select_trainable(model, tail=tail)
        model.zero_grad(set_to_none=True)
        # A repeated same-phone composition requires a real blank CTC state.
        composed = {
            **natural[0],
            "samples": np.r_[sample, np.zeros(2880, dtype=np.float32), sample],
            "targets": [tokens + tokens for tokens in natural[0]["targets"]],
            "annotations": [1, 1, 1],
        }
        composed["features"] = _frontend(model, composed["samples"])
        items = [natural[0], composed]
        outputs, lengths, annotations = _forward(model, items, device)
        losses, _ = signed_ctc_events(
            outputs, lengths, [item["targets"] for item in items], annotations
        )
        losses.sum().backward()
        missing = [
            name
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
            and (parameter.grad is None or not torch.isfinite(parameter.grad).all())
        ]
        if missing:
            raise ValueError("SENSEVOICE_TRAIN_GRADIENT_INVALID:" + ",".join(missing))
        gradient_results.append(
            {
                "phase": "tail-six" if tail else "heads-only",
                "trainableTensors": len(names),
                "allGradientsPresentAndFinite": True,
                "ctcFrameCounts": lengths.tolist(),
                "repeatedTargetLength": 2,
            }
        )
    model.zero_grad(set_to_none=True)
    return {
        "sourceAfterNormMaxAbs": parity,
        "gradientChecks": gradient_results,
        "finalTestRead": False,
    }


def train(
    original: Path, vocabulary_directory: Path, manifest: Path, output: Path, *, device="mps"
) -> dict:
    from pinyin_matcher.pretrained_experiment import read_rows

    config = configuration()
    if device not in {"cpu", "mps"} or (device == "mps" and not torch.backends.mps.is_available()):
        raise ValueError("SENSEVOICE_OFFLINE_DEVICE_UNAVAILABLE")
    torch.manual_seed(config["seed"])
    torch.set_num_threads(2)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    source_registry = json.loads(REGISTRY.read_text())["models"]
    vocabulary_source = source_registry["hanziflow"]
    expected_vocabulary = {
        item["path"]: item["sha256"]
        for item in vocabulary_source["files"]
        if item["path"] in VOCAB_FILES
    }
    for filename, digest in expected_vocabulary.items():
        if fingerprint(vocabulary_directory / filename) != digest:
            raise ValueError("SENSEVOICE_PHONETIC_VOCABULARY_DIGEST_MISMATCH")
    document = json.loads(manifest.read_text())
    if (
        document.get("version") != config["requiredAlignmentVersion"]
        or document.get("frozenTestIncluded") is not False
        or document.get("alignmentMapping", {}).get("aliases") != native_rime_aliases("hanziflow")
    ):
        raise ValueError("SENSEVOICE_REQUIRES_NONFINAL_MODEL_SPECIFIC_ALIGNMENT")
    output.mkdir(parents=True, exist_ok=True)
    model = _source_model(original)
    parameters = sum(parameter.numel() for parameter in model.parameters())
    if parameters > config["parameterLimit"] or parameters * 4 > config["weightBytesLimit"]:
        raise ValueError("SENSEVOICE_DERIVATIVE_PARAMETER_BUDGET_EXCEEDED")
    vocabularies = {
        head: json.loads((vocabulary_directory / f"v2_1_{head}_vocabulary.json").read_text())
        for head in HEADS
    }
    if [len(vocabularies[head]) for head in HEADS] != [24, 44, 7]:
        raise ValueError("SENSEVOICE_PHONETIC_VOCABULARY_SHAPE_MISMATCH")
    rows = read_rows(manifest)
    prepared = {
        split: prepare_rows([row for row in rows if row["split"] == split], model, vocabularies)
        for split in ("train", "calibration")
    }
    natural, counts = prepared["train"]
    cal, cal_counts = prepared["calibration"]
    if not natural or not cal:
        raise ValueError("SENSEVOICE_TRAIN_CALIBRATION_REQUIRED")
    proof = preflight(model, original, natural, device)
    proof.update(
        {
            "parameters": parameters,
            "configSha256": fingerprint(CONFIG),
            "manifestSha256": fingerprint(manifest),
        }
    )
    _write(output / "preflight.json", proof)
    print(json.dumps({"preflight": proof, "train": counts, "calibration": cal_counts}), flush=True)
    all_trainable = select_trainable(model, tail=True)
    initial_parameters = {
        name: parameter.detach().cpu().clone()
        for name, parameter in model.named_parameters()
        if name in all_trainable
    }
    initial = calibration(model, cal, device, config["batchSize"])
    history = [{"epoch": 0, "phase": "random-head-initial", **initial}]
    best_score, best_epoch, best_state = initial["balancedSignedCtcLoss"], 0, initial_parameters
    weights = _class_weights(natural)
    started = time.perf_counter()
    optimizer = None
    for epoch in range(1, config["warmupEpochs"] + config["fineTuneEpochs"] + 1):
        tail = epoch > config["warmupEpochs"]
        if epoch in (1, config["warmupEpochs"] + 1):
            select_trainable(model, tail=tail)
            head_parameters = [
                parameter
                for name, parameter in model.named_parameters()
                if parameter.requires_grad and "_head." in name
            ]
            groups = [
                {
                    "params": head_parameters,
                    "lr": config["headLearningRate"] if tail else config["warmupHeadLearningRate"],
                }
            ]
            if tail:
                groups.append(
                    {
                        "params": [
                            parameter
                            for name, parameter in model.named_parameters()
                            if parameter.requires_grad and "_head." not in name
                        ],
                        "lr": config["encoderLearningRate"],
                    }
                )
            optimizer = torch.optim.AdamW(groups, weight_decay=config["weightDecay"], foreach=False)
        rng = random.Random(config["seed"] + epoch)
        items, compositions = epoch_items(natural, model, rng)
        batches = _batches(items, config["batchSize"], rng)
        sums = 0.0
        model.train()
        for index, batch in enumerate(batches):
            optimizer.zero_grad(set_to_none=True)
            outputs, lengths, annotations = _forward(model, batch, device)
            values, _ = signed_ctc_events(
                outputs, lengths, [item["targets"] for item in batch], annotations
            )
            known = annotations >= 0
            class_weights = (
                torch.stack(
                    [
                        weights[component, annotations[:, component].clamp(min=0)]
                        for component in range(3)
                    ],
                    dim=-1,
                )
                * known
            )
            loss = (values * class_weights).sum() / known.sum().clamp(min=1)
            if known.any():
                loss.backward()
                missing = [
                    name
                    for name, parameter in model.named_parameters()
                    if parameter.requires_grad and parameter.grad is None
                ]
                if missing:
                    raise ValueError("SENSEVOICE_TRAIN_GRADIENT_MISSING:" + ",".join(missing))
                torch.nn.utils.clip_grad_norm_(
                    [parameter for parameter in model.parameters() if parameter.requires_grad],
                    config["gradientClip"],
                    error_if_nonfinite=True,
                )
                optimizer.step()
            sums += float(loss.detach())
            if index % 100 == 0:
                print(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "phase": "tail-six" if tail else "heads-only",
                            "step": index,
                            "steps": len(batches),
                            "loss": float(loss.detach()),
                            "seconds": time.perf_counter() - started,
                        }
                    ),
                    flush=True,
                )
        assessment = calibration(model, cal, device, config["batchSize"])
        record = {
            "epoch": epoch,
            "phase": "tail-six" if tail else "heads-only",
            "trainingMeanBatchLoss": sums / len(batches),
            "naturalExamples": len(natural),
            "trustedTwoWordCompositions": compositions,
            **assessment,
            "elapsedSeconds": time.perf_counter() - started,
        }
        history.append(record)
        print(json.dumps(record), flush=True)
        if assessment["balancedSignedCtcLoss"] < best_score:
            best_score, best_epoch = assessment["balancedSignedCtcLoss"], epoch
            best_state = {
                name: parameter.detach().cpu().clone()
                for name, parameter in model.named_parameters()
                if name in all_trainable
            }
            torch.save(best_state, output / "trainable-best.pt")
        _write(
            output / "training-progress.json",
            {"history": history, "selectedEpoch": best_epoch, "finalTestRead": False},
        )
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if name in best_state:
                parameter.copy_(best_state[name].to(device))
    model.eval().to("cpu")
    state = {name: value.detach().contiguous() for name, value in model.state_dict().items()}
    reference = _source_model(original).state_dict()
    frozen_equal = all(
        torch.equal(value, reference[name])
        for name, value in state.items()
        if name not in all_trainable
    )
    if not frozen_equal:
        raise ValueError("SENSEVOICE_FROZEN_WEIGHTS_CHANGED")
    save_file(state, str(output / "tuned.safetensors"))
    if (output / "tuned.safetensors").stat().st_size > config["weightBytesLimit"]:
        raise ValueError("SENSEVOICE_DERIVATIVE_WEIGHT_BUDGET_EXCEEDED")
    required = ["am.mvn", "config.yaml", "README.md", "MODEL_LICENSE"]
    for filename in required:
        shutil.copy2(original / filename, output / filename)
    for filename in VOCAB_FILES:
        shutil.copy2(vocabulary_directory / filename, output / filename)
    license_name = "SOURCE-MIT.txt"
    shutil.copy2(ROOT / "resources/licenses/SenseVoice-MIT.txt", output / license_name)
    metadata = {
        "schemaVersion": 1,
        "architecture": ARCHITECTURE,
        "sourceRepository": source_registry["sensevoice"]["repository"],
        "sourceRevision": REVISION,
        "sourceCodeRevision": SOURCE_REVISION,
        "parentWeightSha256": FILES["model.pt"],
        "architectureConfig": {
            "embeddingRows": model.embed.num_embeddings,
            "dimensions": 512,
            "retainedEncoderLayers": 50,
            "droppedTaskEncoderLayers": 20,
        },
        "parameterCount": parameters,
        "phoneticHeadSource": (
            "New random three-head CTC, not original SenseVoice outputs or Hanzi decoding"
        ),
        "phoneticVocabularySource": {
            "repository": vocabulary_source["repository"],
            "revision": vocabulary_source["revision"],
            "files": expected_vocabulary,
        },
        "nativeRimeAliases": native_rime_aliases("hanziflow"),
        "manifestSha256": fingerprint(manifest),
        "fineTuneConfigSha256": fingerprint(CONFIG),
        "fineTuneCodeSha256": fingerprint(Path(__file__)),
        "sourceAdapterCodeSha256": fingerprint(
            Path(__file__).with_name("pretrained_sensevoice.py")
        ),
        "signedCtcCodeSha256": fingerprint(Path(__file__).with_name("pretrained_finetune.py")),
        "audioFrontendCodeSha256": fingerprint(Path(__file__).with_name("audio.py")),
        "configuration": {**config, "device": device},
        "dataCounts": {"train": counts, "calibration": cal_counts},
        "preflight": proof,
        "history": history,
        "selectedEpoch": best_epoch,
        "selectedPhase": "tail-six" if best_epoch > config["warmupEpochs"] else "heads-only",
        "trainableParameterNames": all_trainable,
        "allFrozenTensorsUnchanged": frozen_equal,
        "changedEncoderTensors": sum(
            not torch.equal(state[name], initial_parameters[name])
            for name in all_trainable
            if "_head." not in name
        ),
        "changedPhoneticHeadTensors": sum(
            not torch.equal(state[name], initial_parameters[name])
            for name in all_trainable
            if "_head." in name
        ),
        "expertLabelsUnchanged": True,
        "replacementPhonesInvented": False,
        "distillation": False,
        "finalTestRead": False,
        "qualityGateStatus": (
            "CTC loss is model selection only; full CPU acceptance/rejection/abstention "
            "gates remain."
        ),
        "files": {
            filename: {
                "sha256": fingerprint(output / filename),
                "bytes": (output / filename).stat().st_size,
            }
            for filename in ["tuned.safetensors", *required, *VOCAB_FILES, license_name]
        },
    }
    _write(output / "tuned.json", metadata)
    return metadata


class TunedSenseVoiceEvidence:
    """Verified CPU2 standalone50-layer derivative with new phonetic heads."""

    dimensions = 512
    dimension = 512
    name = "sensevoice"

    def __init__(self, directory: Path, *, device="cpu", threads=2, check=True):
        directory = Path(directory)
        if device not in {"cpu", "mps"} or (device == "cpu" and threads != 2):
            raise ValueError("SENSEVOICE_TUNED_CPU_REQUIRES_TWO_THREADS")
        metadata = json.loads((directory / "tuned.json").read_text())
        if (
            metadata.get("architecture") != ARCHITECTURE
            or metadata["sourceRevision"] != REVISION
            or metadata["parentWeightSha256"] != FILES["model.pt"]
        ):
            raise ValueError("SENSEVOICE_TUNED_PARENT_IDENTITY_MISMATCH")
        if metadata.get("nativeRimeAliases") != native_rime_aliases("hanziflow"):
            raise ValueError("SENSEVOICE_TUNED_PHONETIC_SCHEMA_MISMATCH")
        if check:
            required = {"tuned.safetensors", "am.mvn", "config.yaml", "MODEL_LICENSE", *VOCAB_FILES}
            if not required.issubset(metadata.get("files", {})):
                raise ValueError("SENSEVOICE_TUNED_REQUIRED_FILES_MISSING")
            registry = json.loads(REGISTRY.read_text())["models"]
            pinned = {item["path"]: item["sha256"] for item in registry["sensevoice"]["files"]}
            pinned.update(
                {
                    item["path"]: item["sha256"]
                    for item in registry["hanziflow"]["files"]
                    if item["path"] in VOCAB_FILES
                }
            )
            for filename, expected in metadata["files"].items():
                path = (directory / filename).resolve()
                if (
                    not path.is_relative_to(directory.resolve())
                    or fingerprint(path) != expected["sha256"]
                ):
                    raise ValueError("SENSEVOICE_TUNED_FILE_DIGEST_MISMATCH:" + filename)
                if filename in pinned and expected["sha256"] != pinned[filename]:
                    raise ValueError("SENSEVOICE_TUNED_FIXED_SOURCE_CHANGED:" + filename)
        torch.set_num_threads(threads)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        self.directory, self.device, self.metadata = directory, device, metadata
        self.vocabularies = {
            head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text())
            for head in HEADS
        }
        with torch.device("meta"):
            self.model = _PhoneticSense(metadata["architectureConfig"]["embeddingRows"])
        self.model.load_state_dict(
            load_file(str(directory / "tuned.safetensors")), strict=True, assign=True
        )
        self.model.eval().to(device)
        if not torch.equal(self.model.cmvn.cpu(), _cmvn(directory / "am.mvn")):
            raise ValueError("SENSEVOICE_TUNED_CMVN_CHANGED")

    @torch.inference_mode()
    def evidence_batch(self, samples: list[np.ndarray]) -> list[dict]:
        features = [_frontend(self.model, sample) for sample in samples]
        lengths = torch.tensor(
            [len(item) for item in features], dtype=torch.long, device=self.device
        )
        padded = torch.zeros(len(features), int(lengths.max()), 560, device=self.device)
        for index, item in enumerate(features):
            padded[index, : len(item)] = item.to(self.device)
        outputs = self.model(padded, lengths)
        return [
            {
                "frames": outputs[0][index, :length].cpu().numpy(),
                "native": {
                    head: value[index, :length].cpu().numpy()
                    for head, value in zip(HEADS, outputs[1:], strict=True)
                },
            }
            for index, length in enumerate(lengths.tolist())
        ]

    def evidence(self, samples: np.ndarray) -> dict:
        return self.evidence_batch([samples])[0]

    def extract(self, samples: np.ndarray) -> np.ndarray:
        return self.evidence(samples)["frames"]

    def extract_batch(self, samples: list[np.ndarray]) -> list[np.ndarray]:
        return [item["frames"] for item in self.evidence_batch(samples)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument(
        "--vocabularies", type=Path, default=ROOT / "models/pinyin-pretrained/hanziflow"
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    args = parser.parse_args()
    result = train(args.model, args.vocabularies, args.manifest, args.output, device=args.device)
    print(
        json.dumps(
            {
                "selectedEpoch": result["selectedEpoch"],
                "parameterCount": result["parameterCount"],
                "allFrozenTensorsUnchanged": result["allFrozenTensorsUnchanged"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
