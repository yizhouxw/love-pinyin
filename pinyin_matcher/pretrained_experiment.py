"""Reproducible frozen-encoder probes and dedicated component-head optimization.

No test waveform is read by cache/train unless a frozen-test run is explicitly
requested. Native phone outputs are saved as separate diagnostics; Hanzi text
decoding is never performed by any stage of this experiment.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch import nn

from pinyin_matcher.audio import AudioRejected, decode_wav
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog
from pinyin_matcher.pretrained_features import configuration, encoder, represent_batch
from pinyin_matcher.pretrained_heads import ComponentHeads


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def cache_identity(name, model_path=None):
    from pinyin_matcher.pretrained_prepare import REGISTRY

    sources = [
        "pretrained_features.py",
        "audio.py",
        "pretrained_sensevoice.py" if name == "sensevoice" else "pretrained_wav2vec.py",
    ]
    identity = {
        "schemaVersion": 2,
        "model": json.loads(REGISTRY.read_text())["models"][name],
        "code": {n: fingerprint(Path(__file__).with_name(n)) for n in sources},
        "features": configuration()["features"],
    }
    if model_path is not None and (Path(model_path) / "tuned.json").is_file():
        if name not in {"hanziflow", "sensevoice"}:
            raise ValueError("DERIVATIVE_MODEL_UNSUPPORTED")
        derivative = Path(model_path) / "tuned.json"
        metadata = json.loads(derivative.read_text())
        weight = Path(model_path) / "tuned.safetensors"
        if fingerprint(weight) != metadata["files"]["tuned.safetensors"]["sha256"]:
            raise ValueError("DERIVATIVE_WEIGHT_DIGEST_MISMATCH")
        identity["derivative"] = {
            "metadataSha256": fingerprint(derivative),
            "weightSha256": fingerprint(weight),
            "parentWeightSha256": metadata["parentWeightSha256"],
            "sourceRevision": metadata["sourceRevision"],
        }
        adapter = "pretrained_finetune.py"
        if name == "sensevoice":
            architecture = metadata.get("architecture")
            if architecture not in {"sensevoice-50-ctc-v1", "sensevoice-70-native-sequence-v1"}:
                raise ValueError("DERIVATIVE_ARCHITECTURE_UNSUPPORTED")
            identity["derivative"]["architecture"] = architecture
            adapter = (
                "pretrained_native_sequence.py"
                if architecture == "sensevoice-70-native-sequence-v1"
                else "pretrained_sensevoice_finetune.py"
            )
        identity["code"][adapter] = fingerprint(Path(__file__).with_name(adapter))
    return identity


def read_cached(path, identity):
    sidecar = json.loads(path.with_suffix(".json").read_text())
    if sidecar["identity"] != identity or sidecar["sha256"] != fingerprint(path):
        raise ValueError("FEATURE_CACHE_DIGEST_OR_IDENTITY_MISMATCH")
    return np.load(path, allow_pickle=False)


def save_cached(path, value, identity):
    with path.with_suffix(".part").open("wb") as handle:
        np.savez_compressed(handle, **value)
    path.with_suffix(".part").replace(path)
    write(path.with_suffix(".json"), {"identity": identity, "sha256": fingerprint(path)})


def read_rows(manifest: Path, *, verify_splits=("train", "calibration")) -> list[dict]:
    from pinyin_matcher.pretrained_freeze import assert_source_splits

    data = json.loads(manifest.read_text())
    rows = data["items"]
    assert_source_splits(rows)
    tables = {
        field: {}
        for field in ("speakerId", "voiceFamilyId", "referenceSourceId", "sha256", "parentSha256")
    }
    ids = set()
    for row in rows:
        if row["id"] in ids or row["split"] not in {"train", "calibration", "test", "diagnostic"}:
            raise ValueError("DATA_ROW_INVALID")
        ids.add(row["id"])
        for field, table in tables.items():
            if field == "sha256" and row.get("placeholder") is True:
                continue
            if row.get(field) and table.setdefault(row[field], row["split"]) != row["split"]:
                raise ValueError("SPEAKER_OR_AUDIO_LEAKAGE: " + field)
        path = Path(row["file"])
        if not path.is_absolute():
            path = manifest.parent / path
        row["file"] = str(path.resolve())
        if row["split"] in verify_splits and fingerprint(path) != row["sha256"]:
            raise ValueError("DATA_AUDIO_DIGEST_MISMATCH")
        for component in ("onset", "rime", "tone"):
            if component not in row:
                raise ValueError("PHONETIC_LABEL_REQUIRED")
    return rows


def cache_features(
    name: str,
    model_path: Path,
    manifest: Path,
    output: Path,
    *,
    device: str,
    test=False,
    frozen_plan: Path | None = None,
    batch_size=8,
):
    if test:
        from pinyin_matcher.pretrained_freeze import verify_test_manifest

        verify_test_manifest(manifest, frozen_plan)
    rows = read_rows(
        manifest,
        verify_splits=("train", "calibration", "test", "diagnostic")
        if test
        else ("train", "calibration"),
    )
    selected = [r for r in rows if test or r["split"] not in {"test", "diagnostic"}]
    output.mkdir(parents=True, exist_ok=True)
    identity = cache_identity(name, model_path)
    identity_path = output / "identity.json"
    if identity_path.exists():
        if json.loads(identity_path.read_text()) != identity:
            raise ValueError("FEATURE_CACHE_IDENTITY_CHANGED_USE_NEW_DIRECTORY")
    elif any(output.glob("*.npz")):
        raise ValueError("UNBOUND_LEGACY_CACHE_USE_NEW_DIRECTORY")
    else:
        write(identity_path, identity)
    identity_sha = fingerprint(identity_path)
    if identity.get("derivative"):
        if name == "sensevoice":
            if identity["derivative"].get("architecture") == "sensevoice-70-native-sequence-v1":
                from pinyin_matcher.pretrained_native_sequence import NativeSequenceEvidence

                model = NativeSequenceEvidence(model_path, device=device)
            else:
                from pinyin_matcher.pretrained_sensevoice_finetune import TunedSenseVoiceEvidence

                model = TunedSenseVoiceEvidence(model_path, device=device)
        else:
            from pinyin_matcher.pretrained_finetune import TunedHanziFlowEvidence

            model = TunedHanziFlowEvidence(model_path, device=device)
    else:
        model = encoder(name, model_path, device=device)
    started = time.perf_counter()
    for start in range(0, len(selected), batch_size):
        missing, samples = [], []
        for row in selected[start : start + batch_size]:
            path = output / (row["sha256"] + ".npz")
            if (
                row.get("labelPolicyFlags")
                or row.get("numericalQualityFlags")
                or row.get("placeholder")
            ):
                continue
            if path.exists():
                with read_cached(path, identity_sha):
                    pass
                continue
            try:
                sample = decode_wav(Path(row["file"]).read_bytes())
            except AudioRejected as error:
                dimensions = (
                    512 if name == "sensevoice" else 768 if name.startswith("tencent-zh-") else 1024
                )
                invalid = {
                    "pooled": np.zeros(dimensions * 5, dtype=np.float32),
                    "pitch": np.zeros(68, dtype=np.float32),
                    "error": np.asarray(str(error)),
                }
                save_cached(path, invalid, identity_sha)
            else:
                missing.append(path)
                samples.append(sample)
        if samples:
            for path, evidence in zip(missing, represent_batch(model, samples), strict=True):
                save_cached(path, evidence, identity_sha)
        if start % 80 == 0:
            print(
                json.dumps(
                    {
                        "model": name,
                        "cached": min(start + batch_size, len(selected)),
                        "total": len(selected),
                        "elapsed": time.perf_counter() - started,
                    }
                ),
                flush=True,
            )
    metadata = {
        "model": name,
        "cacheIdentitySha256": identity_sha,
        "modelDirectory": str(model_path.resolve()),
        "device": device,
        "manifestSha256": fingerprint(manifest),
        "configuration": configuration(),
        "featureCodeSha256": fingerprint(Path(__file__).with_name("pretrained_features.py")),
        "rows": len(selected),
        "testIncluded": test,
        "frozenPlanSha256": fingerprint(frozen_plan) if test else None,
        "predeclaredUnassessableRows": sum(
            bool(
                r.get("labelPolicyFlags") or r.get("numericalQualityFlags") or r.get("placeholder")
            )
            for r in selected
        ),
        "elapsedSeconds": time.perf_counter() - started,
    }
    write(output / ("cache-with-test.json" if test else "cache.json"), metadata)
    return metadata


def arrays(rows, cache, vocab, *, temporal=False):
    pooled, pitch, labels = [], [], []
    identity = fingerprint(cache / "identity.json")
    repository = json.loads((cache / "identity.json").read_text())["model"]["repository"]
    dimensions = (
        2560
        if "SenseVoice" in repository
        else 3840
        if repository == "TencentGameMate/chinese-wav2vec2-base"
        else 5120
    )
    if temporal:
        from pinyin_matcher.pretrained_temporal import TEMPORAL_BINS, temporal_vector

        dimensions = dimensions // 5 * TEMPORAL_BINS
    for row in rows:
        if (
            row.get("labelPolicyFlags")
            or row.get("numericalQualityFlags")
            or row.get("placeholder")
        ):
            pooled.append(np.zeros(dimensions, dtype=np.float32))
            pitch.append(np.zeros(68, dtype=np.float32))
        else:
            with read_cached(cache / (row["sha256"] + ".npz"), identity) as item:
                pooled.append(temporal_vector(item["frames"]) if temporal else item["pooled"])
                pitch.append(item["pitch"])
        labels.append(
            [
                vocab[k].index(str(row[k])) if str(row[k]) in vocab[k] else -1
                for k in ("onset", "rime", "tone")
            ]
        )
    return np.stack(pooled), np.stack(pitch), np.asarray(labels, dtype=np.int64)


def covered_targets(vocab, rows=()):
    targets = {t["id"]: t for t in load_catalog()["targets"] if t["form"] == "whole-syllable"}
    labels = json.loads((ROOT / "content/pronunciation-mandi-labels.json").read_text())["labels"]
    for label in labels.values():
        target_id = "pm-" + label["syllable"]
        targets[target_id] = {
            "id": target_id,
            "pinyin": label["syllable"],
            "form": "whole-syllable",
            **label,
        }
    for row in rows:
        target_id = "pm-" + row["syllable"].replace("ü", "v")
        targets.setdefault(
            target_id,
            {
                "id": target_id,
                "pinyin": row["syllable"],
                "form": "whole-syllable",
                **{k: row[k] for k in ("onset", "rime", "tone")},
            },
        )
    # A known syllable base must be challenged in all four tones, even when
    # a particular lexical tone was absent from this corpus's sentences.
    # This composes tones only; it never invents arbitrary onset/rime pairs.
    for target in list(targets.values()):
        identifier = target["id"]
        if not identifier.startswith("pm-") or identifier[-1:] not in "012345":
            continue
        base = identifier[3:-1]
        if not base:
            continue
        for tone in (1, 2, 3, 4):
            if str(tone) not in vocab["tone"]:
                continue
            identifier = f"pm-{base}{tone}"
            targets.setdefault(
                identifier,
                {
                    "id": identifier,
                    "pinyin": base.replace("v", "ü") + str(tone),
                    "syllable": base + str(tone),
                    "form": "whole-syllable",
                    "onset": target["onset"],
                    "rime": target["rime"],
                    "tone": tone,
                    "composedToneVariant": True,
                },
            )
    return [
        t for t in targets.values() if all(str(t[k]) in vocab[k] for k in ("onset", "rime", "tone"))
    ]


def supervision(rows):
    values = {"unanimous-correct": 1, "unanimous-error": 0}
    return np.asarray(
        [
            [
                -1
                if row.get("labelPolicyFlags") or row.get("numericalQualityFlags")
                else values.get(row.get("componentExpertLabels", {}).get(k), -1)
                if row.get("componentExpertLabels")
                else 1
                for k in ("onset", "rime", "tone")
            ]
            for row in rows
        ],
        dtype=np.int64,
    )


def component_loss(outputs, labels, annotations):
    """Expert errors suppress the expected phone, without inventing a replacement."""
    losses = []
    for index, output in enumerate(outputs):
        valid = (annotations[:, index] >= 0) & (labels[:, index] >= 0)
        if not valid.any():
            continue
        chosen = labels[valid, index]
        expert = annotations[valid, index]
        log_probability = output[valid].log_softmax(-1).gather(1, chosen[:, None])[:, 0]
        terms = []
        if (expert == 1).any():
            terms.append(-log_probability[expert == 1].mean())
        if (expert == 0).any():
            terms.append(
                -torch.log1p(-log_probability[expert == 0].exp().clamp(max=1 - 1e-6)).mean()
            )
        # Rare human errors receive their own mean rather than vanishing among
        # thousands of correct component labels. No replacement phone is given.
        losses.append(sum(terms) / len(terms))
    return sum(losses) if losses else sum(o.sum() * 0 for o in outputs)


def calibrated_rows(probabilities, labels, rows, thresholds):
    positive, negative, explicit, abstain, false_accept, correct = 0, 0, 0, 0, 0, 0
    by_error = {}
    counterfactual_n, counterfactual_errors = 0, 0
    for ps, truth, row in zip(probabilities, labels, rows, strict=True):
        kind = row.get("expertLabel", "unanimous-correct")
        if kind not in {"unanimous-correct", "unanimous-error"} or row.get("labelPolicyFlags"):
            continue
        invalid = (
            bool(row.get("numericalQualityFlags"))
            or row.get("runtimePitchUnavailable", False)
            or (truth < 0).any()
        )
        status = "uncertain" if invalid else classify(ps, truth, thresholds)
        if kind == "unanimous-correct":
            positive += 1
            correct += status == "matched"
            explicit += status == "retry"
            abstain += status == "uncertain"
            # Counterfactual component neighbours share this independent audio
            # root; the most confidently wrong tuple is a conservative failure.
            negative += 1
            counterfactual_n += 1
            best = [int(p.argmax()) for p in ps]
            counterfactual_wrong = (
                not invalid and list(truth) != best and classify(ps, best, thresholds) == "matched"
            )
            false_accept += counterfactual_wrong
            counterfactual_errors += counterfactual_wrong
        else:
            negative += 1
            false_accept += status == "matched"
            for key, value in row["componentExpertLabels"].items():
                if value == "unanimous-error":
                    group = by_error.setdefault(key, {"n": 0, "falseAccept": 0})
                    group["n"] += 1
                    group["falseAccept"] += status == "matched"
    if not positive or not negative:
        raise ValueError("CALIBRATION_REQUIRES_ASSESSABLE_POSITIVES_AND_NEGATIVES")
    stratum_rates = [g["falseAccept"] / g["n"] for g in by_error.values() if g["n"]]
    if counterfactual_n:
        stratum_rates.append(counterfactual_errors / counterfactual_n)
    return {
        "positive": {"matched": correct, "retry": explicit, "uncertain": abstain},
        "n": positive,
        "negativeUnits": negative,
        "falseAcceptance": max([false_accept / negative, *stratum_rates]),
        "pooledFalseAcceptance": false_accept / negative,
        "counterfactualFalseAcceptance": {"n": counterfactual_n, "count": counterfactual_errors},
        "explicitRejection": explicit / positive,
        "abstention": abstain / positive,
        "expertErrors": by_error,
        "unassessableRowsRetained": len(rows)
        - positive
        - sum(
            r.get("expertLabel") == "unanimous-error" and not r.get("labelPolicyFlags")
            for r in rows
        ),
    }


def classify(probabilities, expected, threshold):
    """Four results retain uncertainty in all accuracy denominators."""
    best = [int(p.argmax()) for p in probabilities]
    scores = [float(p[b]) for p, b in zip(probabilities, best, strict=True)]
    margins = [float(np.sort(p)[-1] - np.sort(p)[-2]) if len(p) > 1 else 1.0 for p in probabilities]
    confident = min(scores) >= threshold["probability"] and min(margins) >= threshold["margin"]
    if not confident:
        return "uncertain"
    return "matched" if best == list(expected) else "retry"


def validation(probabilities, labels, threshold, invalid=None):
    positive = Counter()
    negative_units = 0
    invalid = invalid if invalid is not None else [False] * len(labels)
    for ps, truth, unusable in zip(probabilities, labels, invalid, strict=True):
        if unusable:
            positive["uncertain"] += 1
            continue
        positive[classify(ps, truth, threshold)] += 1
        # Most difficult errors include every tone, initial and final substitution,
        # not an average over easy target pairings. Any false match fails this root.
        best = [int(p.argmax()) for p in ps]
        wrong = any(a != b for a, b in zip(best, truth, strict=True))
        negative_units += int(wrong and classify(ps, best, threshold) == "matched")
    n = len(labels)
    return {
        "positive": dict(positive),
        "n": n,
        "falseAcceptance": negative_units / n,
        "explicitRejection": positive["retry"] / n,
        "abstention": positive["uncertain"] / n,
    }


def calibrate(probabilities, labels, invalid=None, rows=None):
    config = configuration()
    candidates = []
    for probability in config["acceptProbabilities"]:
        for margin in config["acceptMargins"]:
            threshold = {"probability": probability, "margin": margin}
            metric = (
                calibrated_rows(probabilities, labels, rows, threshold)
                if rows is not None
                else validation(probabilities, labels, threshold, invalid)
            )
            violation = sum(
                max(0, metric[key] / limit - 1)
                for key, limit in (
                    ("falseAcceptance", 0.05),
                    ("explicitRejection", 0.1),
                    ("abstention", 0.2),
                )
            )
            candidates.append({"threshold": threshold, "metrics": metric, "violation": violation})
    selected = min(
        candidates,
        key=lambda c: (c["violation"], c["metrics"]["abstention"], c["metrics"]["falseAcceptance"]),
    )
    return {"selected": selected, "candidates": candidates, "testUsed": False}


def train(
    manifest: Path, cache: Path, output: Path, *, name, variant, device="cpu", pitch_cache=None
):
    cache_metadata = json.loads((cache / "cache.json").read_text())
    if cache_metadata["manifestSha256"] != fingerprint(manifest):
        raise ValueError("TRAINING_CACHE_MANIFEST_MISMATCH")
    if cache_metadata["model"] != name:
        raise ValueError("TRAINING_CACHE_MODEL_MISMATCH")
    acoustic_identity = json.loads((cache / "identity.json").read_text())
    rows = read_rows(manifest)
    train_all = [r for r in rows if r["split"] == "train"]
    train_rows = [
        r for r in train_all if not r.get("numericalQualityFlags") and not r.get("labelPolicyFlags")
    ]
    calibration_rows = [r for r in rows if r["split"] == "calibration"]
    if not train_rows or not calibration_rows:
        raise ValueError("TRAIN_AND_CALIBRATION_REQUIRED")
    config = configuration()
    vocab = {key: sorted({str(r[key]) for r in train_rows}) for key in ("onset", "rime", "tone")}
    x, pitch, labels = arrays(train_rows, cache, vocab, temporal=variant == "temporal")
    cx, cp, cl = arrays(calibration_rows, cache, vocab, temporal=variant == "temporal")
    pitch_override = None
    pitch_available = calibration_pitch_available = None
    if pitch_cache is not None:
        from pinyin_matcher.pretrained_pitch import PitchCache

        override = PitchCache(pitch_cache)
        if override.metadata["baseManifestSha256"] != fingerprint(manifest):
            raise ValueError("PITCH_CACHE_MANIFEST_MISMATCH")

        def pitch_arrays(selected):
            values, available = [], []
            for row in selected:
                if row.get("numericalQualityFlags") or row.get("labelPolicyFlags"):
                    vector, info = np.zeros(68, dtype=np.float32), {"available": False}
                else:
                    vector, info = override.read(row)
                values.append(vector)
                available.append(info["available"])
            return np.stack(values), np.asarray(available, dtype=bool)

        pitch, pitch_available = pitch_arrays(train_rows)
        cp, calibration_pitch_available = pitch_arrays(calibration_rows)
        calibration_rows = [
            {**row, "runtimePitchUnavailable": not available}
            for row, available in zip(calibration_rows, calibration_pitch_available, strict=True)
        ]
        pitch_override = {
            "featureVersion": override.metadata["featureVersion"],
            "cacheManifestSha256": fingerprint(Path(pitch_cache)),
            "sourceIdentity": override.metadata["identity"],
            "trainPitchUnavailable": int((~pitch_available).sum()),
            "calibrationPitchUnavailable": int((~calibration_pitch_available).sum()),
        }
    annotations, cal_annotations = supervision(train_rows), supervision(calibration_rows)
    if pitch_available is not None:
        annotations[~pitch_available, 2] = -1
        cal_annotations[~calibration_pitch_available, 2] = -1
    mean, scale = x.mean(0), np.maximum(x.std(0), 0.1)
    pitch_mean, pitch_scale = pitch.mean(0), np.maximum(pitch.std(0), 0.1)
    x, cx = (x - mean) / scale, (cx - mean) / scale
    pitch, cp = (pitch - pitch_mean) / pitch_scale, (cp - pitch_mean) / pitch_scale
    torch.manual_seed(config["seed"])
    rng = np.random.default_rng(config["seed"])
    torch.set_num_threads(2)
    head = ComponentHeads(
        x.shape[1],
        [len(vocab[k]) for k in vocab],
        variant="multihead" if variant == "mixup" else variant,
        hidden=config["hiddenSize"],
        dropout=config["dropout"],
    ).to(device)
    optimizer = torch.optim.AdamW(
        head.parameters(), lr=config["learningRate"], weight_decay=config["weightDecay"]
    )
    x, pitch, labels = [torch.from_numpy(a).to(device) for a in (x, pitch, labels)]
    ctx, cpt, clt = [torch.from_numpy(a).to(device) for a in (cx, cp, cl)]
    annotations = torch.from_numpy(annotations).to(device)
    cal_annotations = torch.from_numpy(cal_annotations).to(device)
    best, history, checkpoint = float("inf"), [], None
    component_best = [float("inf")] * 3
    component_epochs = [0] * 3
    started = time.perf_counter()
    for epoch in range(config["maximumEpochs"]):
        head.train()
        permutation = rng.permutation(len(x))
        losses = []
        for start in range(0, len(x), config["batchSize"]):
            indices = torch.tensor(permutation[start : start + config["batchSize"]], device=device)
            result = head(x[indices], pitch[indices])
            loss = component_loss(result, labels[indices], annotations[indices])
            if variant == "mixup":
                from pinyin_matcher.pretrained_mixup import mixup_loss

                loss = loss + mixup_loss(
                    head, x[indices], pitch[indices], labels[indices], annotations[indices], rng
                )
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(head.parameters(), 5)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        head.eval()
        with torch.inference_mode():
            logits = head(ctx, cpt)
            calibration_loss = component_loss(logits, clt, cal_annotations).item()
            correct = [
                (o.argmax(-1) == clt[:, i]).float().mean().item() for i, o in enumerate(logits)
            ]
        history.append(
            {
                "epoch": epoch + 1,
                "loss": float(np.mean(losses)),
                "calibrationLoss": calibration_loss,
                "componentTargetAgreementDiagnostic": correct,
            }
        )
        if variant in {"independent", "temporal"}:
            if checkpoint is None:
                checkpoint = {}
            for component, prefix in enumerate(("initial.", "final.", "tone.")):
                mask = torch.full_like(cal_annotations, -1)
                mask[:, component] = cal_annotations[:, component]
                score = component_loss(logits, clt, mask).item()
                if score < component_best[component]:
                    component_best[component] = score
                    component_epochs[component] = epoch + 1
                    checkpoint.update(
                        {
                            key: value.detach().cpu().clone()
                            for key, value in head.state_dict().items()
                            if key.startswith(prefix)
                        }
                    )
            selected_epoch = None
        elif calibration_loss < best:
            best = calibration_loss
            checkpoint = {
                key: value.detach().cpu().clone() for key, value in head.state_dict().items()
            }
            selected_epoch = epoch + 1
        if (epoch + 1) % 20 == 0:
            print(json.dumps({"model": name, "variant": variant, **history[-1]}), flush=True)
    head.load_state_dict(checkpoint)
    head.eval()
    with torch.inference_mode():
        outputs = [o.softmax(-1).cpu().numpy() for o in head(ctx, cpt)]
    probabilities = list(zip(*outputs, strict=True))
    calibration = calibrate(
        probabilities,
        cl,
        [
            bool(r.get("numericalQualityFlags")) or r.get("runtimePitchUnavailable", False)
            for r in calibration_rows
        ],
        rows=calibration_rows if any(r.get("expertLabel") for r in calibration_rows) else None,
    )
    output.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, output / "heads.pt")
    cpu_head = head.to("cpu")
    with torch.inference_mode():
        torch.onnx.export(
            cpu_head,
            (torch.zeros(1, len(mean)), torch.zeros(1, len(pitch_mean))),
            str(output / "heads.onnx"),
            input_names=["acoustic", "pitch"],
            output_names=["initial", "final", "tone"],
            dynamic_axes={
                key: {0: "batch"} for key in ("acoustic", "pitch", "initial", "final", "tone")
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
        "variant": variant,
        "acousticProbe": {
            **acoustic_identity["intermediateProbe"],
            "selectedDepth": acoustic_identity["selectedDepth"],
        }
        if "intermediateProbe" in acoustic_identity
        else None,
        "regularizationConfigSha256": fingerprint(
            ROOT / "content/pronunciation-pretrained-mixup.json"
        )
        if variant == "mixup"
        else None,
        "representation": "temporal16-v1" if variant == "temporal" else "pool5-v1",
        "representationCodeSha256": fingerprint(Path(__file__).with_name("pretrained_temporal.py"))
        if variant == "temporal"
        else None,
        "vocabulary": vocab,
        "dimensions": len(mean),
        "configuration": config,
        "selectedEpoch": selected_epoch,
        "selectedComponentEpochs": component_epochs
        if variant in {"independent", "temporal"}
        else None,
        "checkpointSelection": "independent-component-loss"
        if variant in {"independent", "temporal"}
        else "joint-loss",
        "trainRows": len(train_rows),
        "calibrationRows": len(calibration_rows),
        "trainingNumericalExclusions": sum(bool(r.get("numericalQualityFlags")) for r in train_all),
        "trainingPolicyExclusions": sum(bool(r.get("labelPolicyFlags")) for r in train_all),
        "trainingTotalExclusions": len(train_all) - len(train_rows),
        "trainSpeakers": len({r["speakerId"] for r in train_rows}),
        "calibrationSpeakers": len({r["speakerId"] for r in calibration_rows}),
        "manifestSha256": fingerprint(manifest),
        "cacheMetadataSha256": fingerprint(cache / "cache.json"),
        "acousticDerivative": acoustic_identity.get("derivative"),
        "pitchOverride": pitch_override,
        "headSha256": fingerprint(output / "heads.pt"),
        "headCodeSha256": fingerprint(Path(__file__).with_name("pretrained_heads.py")),
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
    sub = parser.add_subparsers(dest="action", required=True)
    cache = sub.add_parser("cache")
    cache.add_argument(
        "--name",
        required=True,
        choices=[
            "hanziflow",
            "charsiu",
            "sensevoice",
            "tencent-zh-base",
            "tencent-zh-tail-v1",
            "tencent-zh-raw",
            "chinese-xlsr-asr",
            "chinese-xlsr-tail-v1",
        ],
    )
    cache.add_argument("--model", type=Path, required=True)
    cache.add_argument("--manifest", type=Path, required=True)
    cache.add_argument("--output", type=Path, required=True)
    cache.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    cache.add_argument("--include-frozen-test", action="store_true")
    cache.add_argument("--frozen-plan", type=Path)
    cache.add_argument("--batch-size", type=int, default=8)
    fit = sub.add_parser("train")
    fit.add_argument("--manifest", type=Path, required=True)
    fit.add_argument("--cache", type=Path, required=True)
    fit.add_argument("--output", type=Path, required=True)
    fit.add_argument("--name", required=True)
    fit.add_argument(
        "--variant",
        choices=["linear", "multihead", "tone-specialist", "independent", "temporal", "mixup"],
        required=True,
    )
    fit.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    fit.add_argument("--pitch-cache", type=Path)
    args = parser.parse_args()
    if args.action == "cache":
        result = cache_features(
            args.name,
            args.model,
            args.manifest,
            args.output,
            device=args.device,
            test=args.include_frozen_test,
            frozen_plan=args.frozen_plan,
            batch_size=args.batch_size,
        )
    else:
        result = train(
            args.manifest,
            args.cache,
            args.output,
            name=args.name,
            variant=args.variant,
            device=args.device,
            pitch_cache=args.pitch_cache,
        )
    summary = {
        k: v
        for k, v in result.items()
        if k
        not in {
            "coveredTargets",
            "trainingTargetSyllables",
            "vocabulary",
            "coveredComponents",
            "configuration",
        }
    }
    if "coveredTargets" in result:
        summary["coveredTargetCount"] = len(result["coveredTargets"])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
