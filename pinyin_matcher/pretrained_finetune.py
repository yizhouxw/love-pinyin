"""Actual last-two-layer HanziFlow phonetic CTC fine-tuning, offline only.

Expert correctness is unchanged. Positive components supervise their full CTC
event; negative components suppress that expected event without guessing the
replacement phone. Trusted two-word compositions retain genuine multiple labels.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file, save_file
from torch.nn import functional as functional

from pinyin_matcher.audio import decode_wav, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_prepare import REGISTRY
from pinyin_matcher.pretrained_wav2vec import HanziFlow, Wav2VecEvidence

VERSION = "hanziflow-last-two-expert-signed-ctc-v1"
HEADS = ("initial", "final", "tone")
COMPONENTS = ("onset", "rime", "tone")
SEED = 3182026
FINETUNE_CONFIG = ROOT / "content/pronunciation-pretrained-finetune.json"


def fine_tune_configuration() -> dict:
    config = json.loads(FINETUNE_CONFIG.read_text())
    if (
        config["seed"] != SEED
        or config["maximumEpochs"] != 10
        or config["batchSize"] != 16
        or config["trainableTransformerLayers"] != 2
        or config["specAugment"] is not False
        or config["layerDrop"] != 0
        or config["gradientCheckpointing"] is not False
        or config["cpuCtcDoublePrecision"] is not True
    ):
        raise ValueError("FINETUNE_PROTOCOL_CHANGED")
    return config


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def signed_ctc_events(
    logits: list[torch.Tensor],
    lengths: torch.Tensor,
    targets: list[list[list[int]]],
    annotations: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """CPU double CTC with gradients copied back to the acoustic device.

    No probability is conditioned on the expected label or closed target subset.
    MPS lacks some CTC kernels; differentiable device copies keep encoder/heads
    on MPS and run only the small dynamic program on CPU.
    """
    losses, nlls = [], []
    for head, output in enumerate(logits):
        sequences = [word[head] for word in targets]
        flat = torch.tensor(
            [token for sequence in sequences for token in sequence], dtype=torch.long
        )
        target_lengths = torch.tensor([len(sequence) for sequence in sequences], dtype=torch.long)
        log_probs = (
            output.to(device="cpu")
            .to(dtype=torch.float64)
            .log_softmax(-1)
            .transpose(0, 1)
            .contiguous()
        )
        nll = functional.ctc_loss(
            log_probs,
            flat,
            lengths.cpu(),
            target_lengths,
            blank=0,
            reduction="none",
            zero_infinity=False,
        )
        if not torch.isfinite(nll).all():
            raise ValueError("FINETUNE_CTC_EVENT_NONFINITE")
        # Stable -log(1-exp(-nll)); numerical floor retains the gradient direction.
        stable = nll + (nll.clamp(min=1e-12) - nll).detach()
        negative = -torch.log(-torch.expm1(-stable))
        signed = torch.where(annotations[:, head] == 1, nll, negative)
        losses.append(torch.where(annotations[:, head] >= 0, signed, torch.zeros_like(signed)))
        nlls.append(nll)
    return torch.stack(losses, dim=-1), torch.stack(nlls, dim=-1)


def freeze_for_finetuning(model: HanziFlow) -> list[str]:
    # Upstream config enables reentrant checkpointing. Its frozen first-layer
    # inputs have no gradient, which otherwise disconnects the trainable tail.
    if hasattr(model.encoder, "gradient_checkpointing_disable"):
        model.encoder.gradient_checkpointing_disable()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    layers = model.encoder.encoder.layers
    if len(layers) != 24:
        raise ValueError("FINETUNE_EXPECTED_24_ENCODER_LAYERS")
    for layer in layers[-2:]:
        layer.requires_grad_(True)
    for head in (model.initial_head, model.final_head, model.tone_head):
        head.requires_grad_(True)
    model.encoder.config.apply_spec_augment = False
    model.encoder.config.layerdrop = 0.0
    return [name for name, parameter in model.named_parameters() if parameter.requires_grad]


def _training_mode(model: HanziFlow):
    model.eval()
    for layer in model.encoder.encoder.layers[-2:]:
        layer.train()
    for head in (model.initial_head, model.final_head, model.tone_head):
        head.train()


def _labels(row: dict, vocabularies: dict, aliases: dict) -> tuple[list[list[int]], list[int]]:
    tokens = (row["onset"] or "ZERO", aliases.get(row["rime"], row["rime"]), "T" + str(row["tone"]))
    if any(
        token not in vocabularies[head] or token in {"<blank>", "<unk>"}
        for head, token in zip(HEADS, tokens, strict=True)
    ):
        raise ValueError("FINETUNE_EXPECTED_COMPONENT_UNSUPPORTED")
    targets = [[vocabularies[head][token]] for head, token in zip(HEADS, tokens, strict=True)]
    known = {"unanimous-correct": 1, "unanimous-error": 0}
    annotations = [
        known.get(row.get("componentExpertLabels", {}).get(key), -1) for key in COMPONENTS
    ]
    return targets, annotations


def prepare_rows(rows: list[dict], vocabularies: dict, aliases: dict) -> tuple[list[dict], dict]:
    result = []
    counts = Counter()
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
        except ValueError:
            counts["unsupportedOrUnavailable"] += 1
            continue
        result.append(
            {
                "id": row["id"],
                "samples": samples,
                "targets": targets,
                "annotations": annotations,
                "trusted": row.get("expertLabel") == "unanimous-correct"
                and annotations == [1, 1, 1],
            }
        )
        counts["eligibleNaturalWords"] += 1
        counts["trustedAllCorrectWords"] += result[-1]["trusted"]
        counts["noKnownExpertComponent"] += not any(value >= 0 for value in annotations)
        for index, component in enumerate(COMPONENTS):
            counts[component + ":" + str(annotations[index])] += 1
    return result, dict(counts)


def epoch_items(natural: list[dict], rng: random.Random) -> tuple[list[dict], int]:
    trusted = [item for item in natural if item["trusted"]]
    if not trusted:
        raise ValueError("FINETUNE_REQUIRES_TRUSTED_COMPOSITION_SOURCES")
    config = fine_tune_configuration()
    count = round(len(natural) * config["compositionExtraFraction"])
    gap = np.zeros(round(config["compositionPauseSeconds"] * 16000), dtype=np.float32)
    result = list(natural)
    for _ in range(count):
        first, second = rng.choice(trusted), rng.choice(trusted)
        result.append(
            {
                "id": "composition:" + first["id"] + ":" + second["id"],
                "samples": np.r_[first["samples"], gap, second["samples"]],
                "targets": [
                    a + b for a, b in zip(first["targets"], second["targets"], strict=True)
                ],
                "annotations": [1, 1, 1],
                "trusted": True,
            }
        )
    return result, count


def _batches(items: list[dict], size: int, rng: random.Random | None = None) -> list[list[dict]]:
    # Randomized length buckets retain every natural root while avoiding padding
    # a150ms word to the longest composed utterance in every MPS batch.
    ordered = sorted(items, key=lambda item: len(item["samples"]))
    batches = [ordered[start : start + size] for start in range(0, len(ordered), size)]
    if rng is not None:
        rng.shuffle(batches)
    return batches


def _forward(
    model: HanziFlow, items: list[dict], device: str
) -> tuple[list[torch.Tensor], torch.Tensor, torch.Tensor]:
    lengths = [len(item["samples"]) for item in items]
    waveform = torch.zeros(len(items), max(lengths), device=device)
    mask = torch.zeros(len(items), max(lengths), dtype=torch.long, device=device)
    for index, item in enumerate(items):
        samples = item["samples"]
        normalized = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
        waveform[index, : len(samples)] = torch.from_numpy(normalized).to(device)
        mask[index, : len(samples)] = 1
    frames = model.encoder(waveform, attention_mask=mask).last_hidden_state
    outputs = [head(frames) for head in (model.initial_head, model.final_head, model.tone_head)]
    counts = model.encoder._get_feat_extract_output_lengths(torch.tensor(lengths)).long()
    annotations = torch.tensor([item["annotations"] for item in items], dtype=torch.long)
    return outputs, counts, annotations


def _class_weights(items: list[dict]) -> torch.Tensor:
    labels = np.asarray([item["annotations"] for item in items])
    weights = np.ones((3, 2), dtype=np.float64)
    for component in range(3):
        counts = np.asarray([(labels[:, component] == value).sum() for value in (0, 1)])
        for value in (0, 1):
            if counts[value]:
                weights[component, value] = counts.sum() / (2 * counts[value])
    return torch.from_numpy(weights)


def _calibration(model: HanziFlow, items: list[dict], device: str, size: int) -> dict:
    model.eval()
    sums = np.zeros((3, 2), dtype=np.float64)
    counts = np.zeros((3, 2), dtype=np.int64)
    with torch.inference_mode():
        for batch in _batches(items, size):
            outputs, lengths, annotations = _forward(model, batch, device)
            losses, _ = signed_ctc_events(
                outputs, lengths, [item["targets"] for item in batch], annotations
            )
            for component in range(3):
                for label in (0, 1):
                    selected = annotations[:, component] == label
                    sums[component, label] += float(losses[selected, component].sum())
                    counts[component, label] += int(selected.sum())
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    return {
        "balancedSignedCtcLoss": float(means[counts > 0].mean()),
        "componentClassMeanLoss": means.tolist(),
        "componentClassCounts": counts.tolist(),
    }


def train(
    model_path: Path, manifest: Path, output: Path, *, device="mps", epochs=10, batch_size=16
) -> dict:
    from pinyin_matcher.pretrained_experiment import read_rows

    config = fine_tune_configuration()
    if (
        device not in {"cpu", "mps"}
        or not 1 <= epochs <= config["maximumEpochs"]
        or batch_size != config["batchSize"]
    ):
        raise ValueError("FINETUNE_REQUIRES_CPU_OR_MPS_MAX10_EPOCHS_BATCH16")
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("FINETUNE_MPS_UNAVAILABLE")
    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    document = json.loads(manifest.read_text())
    mapping = document.get("alignmentMapping", {})
    source = json.loads(REGISTRY.read_text())["models"]["hanziflow"]
    schema_sha = next(
        item["sha256"] for item in source["files"] if item["path"] == "v2_1_target_schema.json"
    )
    aliases = native_rime_aliases("hanziflow")
    if (
        document.get("version") != config["requiredAlignmentVersion"]
        or document.get("frozenTestIncluded") is not False
        or mapping.get("aliases") != aliases
        or mapping.get("upstreamTargetSchemaSha256") != schema_sha
        or document.get("alignerSha256")
        != fingerprint(Path(__file__).with_name("pretrained_align.py"))
    ):
        raise ValueError("FINETUNE_REQUIRES_REBUILT_MODEL_SPECIFIC_ALIGNMENT")
    output.mkdir(parents=True, exist_ok=True)
    adapter = Wav2VecEvidence("hanziflow", model_path, device=device)
    model = adapter.model
    trainable = freeze_for_finetuning(model)
    rows = read_rows(manifest)
    prepared = {
        split: prepare_rows(
            [row for row in rows if row["split"] == split], adapter.vocabularies, aliases
        )
        for split in ("train", "calibration")
    }
    natural, counts = prepared["train"]
    calibration, calibration_counts = prepared["calibration"]
    if not natural or not calibration:
        raise ValueError("FINETUNE_TRAIN_CALIBRATION_REQUIRED")
    encoder_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if parameter.requires_grad and name.startswith("encoder.")
    ]
    head_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if parameter.requires_grad and not name.startswith("encoder.")
    ]
    optimizer = torch.optim.AdamW(
        [
            {"params": encoder_parameters, "lr": config["encoderLearningRate"]},
            {"params": head_parameters, "lr": config["headLearningRate"]},
        ],
        weight_decay=config["weightDecay"],
        foreach=False,
    )
    class_weights = _class_weights(natural)
    initial = _calibration(model, calibration, device, batch_size)
    history = [{"epoch": 0, **initial}]
    best_score, best_epoch, best_state = initial["balancedSignedCtcLoss"], 0, None
    started = time.perf_counter()
    print(
        json.dumps(
            {
                "train": counts,
                "calibration": calibration_counts,
                "initial": initial,
                "trainableParameters": sum(
                    parameter.numel() for parameter in model.parameters() if parameter.requires_grad
                ),
            }
        ),
        flush=True,
    )
    for epoch in range(1, epochs + 1):
        rng = random.Random(SEED + epoch)
        items, compositions = epoch_items(natural, rng)
        _training_mode(model)
        losses, steps = 0.0, 0
        batches = _batches(items, batch_size, rng)
        for index, batch in enumerate(batches):
            optimizer.zero_grad(set_to_none=True)
            outputs, lengths, annotations = _forward(model, batch, device)
            values, _ = signed_ctc_events(
                outputs, lengths, [item["targets"] for item in batch], annotations
            )
            known = annotations >= 0
            weights = (
                torch.stack(
                    [
                        class_weights[component, annotations[:, component].clamp(min=0)]
                        for component in range(3)
                    ],
                    dim=-1,
                )
                * known
            )
            loss = (values * weights).sum() / known.sum().clamp(min=1)
            if known.any():
                loss.backward()
                missing = [
                    name
                    for name, parameter in model.named_parameters()
                    if parameter.requires_grad and parameter.grad is None
                ]
                if missing:
                    raise ValueError("FINETUNE_TRAINABLE_GRADIENT_MISSING:" + ",".join(missing))
                torch.nn.utils.clip_grad_norm_(
                    [parameter for parameter in model.parameters() if parameter.requires_grad],
                    config["gradientClip"],
                )
                optimizer.step()
            losses += float(loss.detach())
            steps += 1
            if index % 100 == 0:
                print(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "step": index,
                            "steps": len(batches),
                            "loss": float(loss.detach()),
                            "seconds": time.perf_counter() - started,
                        }
                    ),
                    flush=True,
                )
        assessment = _calibration(model, calibration, device, batch_size)
        record = {
            "epoch": epoch,
            "trainingMeanBatchLoss": losses / steps,
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
                if parameter.requires_grad
            }
            torch.save(best_state, output / "trainable-best.pt")
        _write(
            output / "training-progress.json",
            {"history": history, "selectedEpoch": best_epoch, "finalTestRead": False},
        )
    if best_state is not None:
        with torch.no_grad():
            for name, parameter in model.named_parameters():
                if name in best_state:
                    parameter.copy_(best_state[name].to(device))
    model.eval().to("cpu")
    state = {name: value.detach().contiguous() for name, value in model.state_dict().items()}
    save_file(state, str(output / "tuned.safetensors"))
    original = load_file(str(model_path / "model.safetensors"))
    frozen_equal = all(
        torch.equal(value, original[name]) for name, value in state.items() if name not in trainable
    )
    changed = sum(not torch.equal(state[name], original[name]) for name in trainable)
    if not frozen_equal:
        raise ValueError("FINETUNE_FROZEN_WEIGHTS_CHANGED")
    required = [
        "config.json",
        "preprocessor_config.json",
        "README.md",
        "v2_1_target_schema.json",
        *(f"v2_1_{head}_vocabulary.json" for head in HEADS),
    ]
    for name in required:
        shutil.copy2(model_path / name, output / name)
    metadata = {
        "schemaVersion": 1,
        "version": VERSION,
        "sourceRepository": source["repository"],
        "sourceRevision": source["revision"],
        "parentWeightSha256": next(
            item["sha256"] for item in source["files"] if item["path"] == "model.safetensors"
        ),
        "manifestSha256": fingerprint(manifest),
        "fineTuneCodeSha256": fingerprint(Path(__file__)),
        "fineTuneConfigSha256": fingerprint(FINETUNE_CONFIG),
        "adapterCodeSha256": fingerprint(Path(__file__).with_name("pretrained_wav2vec.py")),
        "audioFrontendCodeSha256": fingerprint(Path(__file__).with_name("audio.py")),
        "configuration": {
            **config,
            "epochs": epochs,
            "device": device,
        },
        "nativeRimeAliases": aliases,
        "alignmentMapping": mapping,
        "selectedEpoch": best_epoch,
        "trainableParameterNames": trainable,
        "allFrozenTensorsUnchanged": frozen_equal,
        "changedTrainableTensors": changed,
        "dataCounts": {"train": counts, "calibration": calibration_counts},
        "history": history,
        "expertLabelsUnchanged": True,
        "replacementPhonesInvented": False,
        "augmentationCountsAreNotNewAudioRoots": True,
        "finalTestRead": False,
        "qualityGateStatus": (
            "Signed CTC loss is model selection only; full acceptance/rejection/abstention "
            "gates remain to be evaluated."
        ),
        "files": {
            name: {"sha256": fingerprint(output / name), "bytes": (output / name).stat().st_size}
            for name in ["tuned.safetensors", *required]
        },
    }
    _write(output / "tuned.json", metadata)
    return metadata


class TunedHanziFlowEvidence(Wav2VecEvidence):
    """CPU inference from verified derivative weights, without original weights."""

    def __init__(self, directory: Path, *, device="cpu", threads=2, check=True):
        directory = Path(directory)
        if device not in {"cpu", "mps"} or (device == "cpu" and threads != 2):
            raise ValueError("TUNED_CPU_REQUIRES_TWO_THREADS")
        metadata = json.loads((directory / "tuned.json").read_text())
        source = json.loads(REGISTRY.read_text())["models"]["hanziflow"]
        original = {item["path"]: item for item in source["files"]}
        if (
            metadata["sourceRevision"] != source["revision"]
            or metadata["parentWeightSha256"] != original["model.safetensors"]["sha256"]
        ):
            raise ValueError("TUNED_PARENT_IDENTITY_MISMATCH")
        if check:
            required = {
                "tuned.safetensors",
                "config.json",
                "preprocessor_config.json",
                "README.md",
                "v2_1_target_schema.json",
                *(f"v2_1_{head}_vocabulary.json" for head in HEADS),
            }
            if not required.issubset(metadata.get("files", {})):
                raise ValueError("TUNED_REQUIRED_FILES_MISSING")
            if metadata.get("nativeRimeAliases") != native_rime_aliases("hanziflow"):
                raise ValueError("TUNED_NATIVE_SCHEMA_MISMATCH")
            for name, expected in metadata["files"].items():
                path = (directory / name).resolve()
                if (
                    not path.is_relative_to(directory.resolve())
                    or fingerprint(path) != expected["sha256"]
                ):
                    raise ValueError("TUNED_FILE_DIGEST_MISMATCH:" + name)
                if name in original and expected["sha256"] != original[name]["sha256"]:
                    raise ValueError("TUNED_FIXED_CONFIG_CHANGED:" + name)
        torch.set_num_threads(threads)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        self.name, self.device, self.directory = "hanziflow", device, directory
        self.dimensions = 1024
        self.vocabularies = {
            head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text())
            for head in HEADS
        }
        with torch.device("meta"):
            self.model = HanziFlow(json.loads((directory / "config.json").read_text()))
        self.model.load_state_dict(
            load_file(str(directory / "tuned.safetensors")), strict=True, assign=True
        )
        self.model.eval().to(device)
        self.metadata = metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--model", type=Path, required=True)
    fit.add_argument("--manifest", type=Path, required=True)
    fit.add_argument("--output", type=Path, required=True)
    fit.add_argument("--device", choices=["cpu", "mps"], default="mps")
    fit.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()
    result = train(args.model, args.manifest, args.output, device=args.device, epochs=args.epochs)
    print(
        json.dumps(
            {
                "selectedEpoch": result["selectedEpoch"],
                "allFrozenTensorsUnchanged": result["allFrozenTensorsUnchanged"],
                "changedTrainableTensors": result["changedTrainableTensors"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
