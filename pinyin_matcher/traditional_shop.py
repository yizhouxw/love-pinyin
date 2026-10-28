"""CPU-only target-conditioned traditional pronunciation matcher research pilot.

TTS descriptions are weak intended labels. This tool does not load speech
recognition models or use text decoding, and never claims child validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.fft import dct
from scipy.special import expit
from threadpoolctl import threadpool_limits

from pinyin_matcher.audio import AudioRejected, decode_wav, features
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog, targets_by_id
from pinyin_matcher.data import read_manifest
from pinyin_matcher.pretrained_runtime import signal_guard

CONFIG = ROOT / "content/pronunciation-traditional-shop.json"
CATALOG = ROOT / "content/pronunciation-targets.json"
COMPONENTS = ("onset", "rime", "tone")


def config():
    p = json.loads(CONFIG.read_text())
    if (
        p["id"] != "traditional-shop-pilot-v1"
        or p["featureFrames"] != 20
        or p["templatesPerTarget"] != 6
        or p["templatesPerGenerator"] != 3
        or p["standardTemplatePolicy"] != "replace-last-cosy-when-available"
        or p["cpuThreads"] != 2
        or p["finalTestUsed"] is not False
    ):
        raise ValueError("TRADITIONAL_PROTOCOL_CHANGED")
    return p


def encode(array):
    """Retain cepstral spectral shape and relative pitch at fixed temporal positions."""
    if array.ndim != 2 or array.shape[1] != 68 or not len(array):
        raise ValueError("TRADITIONAL_FEATURE_INVALID")
    cep = dct(array[:, :64], type=2, axis=1, norm="ortho")[:, 1:14] / 4.0
    values = np.concatenate((cep, array[:, 65:68]), axis=1)
    x = np.linspace(0, len(values) - 1, config()["featureFrames"])
    return np.stack(
        [np.interp(x, np.arange(len(values)), values[:, i]) for i in range(16)], axis=1
    ).astype(np.float32)


def dtw_batch(query, refs, *, band=5):
    """Batched, bounded DTW; returns independent spectral and relative-tone distances."""
    if refs.ndim != 3 or query.shape != refs.shape[1:]:
        raise ValueError("TRADITIONAL_TEMPLATE_SHAPE_INVALID")
    count, frames, _ = refs.shape
    delta = refs[:, :, None, :] - query[None, None, :, :]
    spectral = np.mean(delta[..., :13] ** 2, axis=-1)
    tone = np.mean(delta[..., 13:] ** 2, axis=-1)
    costs = spectral + 0.7 * tone
    previous = np.full((count, frames + 1), np.inf, dtype=np.float32)
    previous[:, 0] = 0
    for i in range(frames):
        current = np.full_like(previous, np.inf)
        for j in range(max(0, i - band), min(frames, i + band + 1)):
            current[:, j + 1] = costs[:, i, j] + np.minimum(
                np.minimum(previous[:, j], previous[:, j + 1]), current[:, j]
            )
        previous = current
    return previous[:, -1] / (frames * 2)


def distances(query, refs, groups, family=None):
    values = dtw_batch(query, refs, band=config()["dtwBand"])
    if family is not None:
        values = np.where(np.asarray(groups) == family, np.inf, values)
    return values


def comparison(query, bank, group_ids, eligible, family=None):
    count, per_target, frames, width = bank.shape
    refs = bank.reshape(count * per_target, frames, width)
    values = distances(query, refs, group_ids, family).reshape(count, per_target)
    results = []
    for index in range(count):
        selected = np.sort(values[index][np.isfinite(values[index])])[
            : config()["nearestTemplates"]
        ]
        if len(selected) < 2:
            raise ValueError("TRADITIONAL_INSUFFICIENT_CROSS_FAMILY_TEMPLATES")
        best = float(np.mean(selected))
        others = [float(np.min(values[j])) for j in eligible[index] if np.isfinite(values[j]).any()]
        competitor = (
            min(others)
            if others
            else min(float(np.min(values[j])) for j in range(count) if j != index)
        )
        best_idx = np.argsort(values[index])[: min(len(selected), config()["nearestTemplates"])]
        chosen = bank[index, best_idx]
        difference = chosen - query[None]
        first = float(np.mean(difference[:, :7, :13] ** 2))
        last = float(np.mean(difference[:, 7:, :13] ** 2))
        pitch = float(np.mean(difference[:, :, 13:] ** 2))
        results.append(
            [
                best,
                float(selected[0]),
                float(selected[-1]),
                competitor,
                competitor - best,
                first,
                last,
                pitch,
            ]
        )
    return np.asarray(results, dtype=np.float32)


def nearest(targets):
    return [
        [
            j
            for j, b in enumerate(targets)
            if j != i and sum(str(a[k]) != str(b[k]) for k in COMPONENTS) == 1
        ]
        for i, a in enumerate(targets)
    ]


def source_features(row, manifest, cache):
    # The source audio digest is validated by read_manifest; derive features
    # from its bytes, not from an unhashed historical experiment cache.
    samples = decode_wav((manifest.parent / row["file"]).read_bytes())
    return encode(features(samples)[0])


def choose_templates(train, manifest, cache, targets):
    import soundfile as sf
    from scipy.signal import resample_poly

    assets = {
        a["id"]: a for a in json.loads((ROOT / "content/daily-reading.json").read_text())["assets"]
    }
    by_target = {}
    for row in train:
        by_target.setdefault((row["targetId"], row["generator"]), []).append(row)
    bank, provenance = [], []
    for target in targets:
        chosen, families = [], set()
        for generator in ("qwen", "cosy"):
            entries = sorted(
                by_target.get((target["id"], generator), []),
                key=lambda r: hashlib.sha256(f"{config()['seed']}:{r['id']}".encode()).hexdigest(),
            )
            for row in entries:
                if row["voiceFamilyId"] in families:
                    continue
                chosen.append(row)
                families.add(row["voiceFamilyId"])
                if (
                    sum(r["generator"] == generator for r in chosen)
                    == config()["templatesPerGenerator"]
                ):
                    break
        if len(chosen) != config()["templatesPerTarget"]:
            raise ValueError("TRADITIONAL_TEMPLATE_COVERAGE_INSUFFICIENT")
        vectors = [source_features(row, manifest, cache) for row in chosen]
        records = [
            {
                "targetId": row["targetId"],
                "generator": row["generator"],
                "voiceFamilyId": row["voiceFamilyId"],
                "referenceRootId": row["referenceRootId"],
                "sha256": row["sha256"],
            }
            for row in chosen
        ]
        standard = assets.get(target.get("standardAudioId"))
        if standard:
            path = ROOT / "private/pinyinsound/clips" / (standard["sha256"] + ".mp3")
            if path.is_file():
                if fingerprint(path) != standard["sha256"]:
                    raise ValueError("TRADITIONAL_STANDARD_DIGEST_MISMATCH")
                audio, rate = sf.read(path, dtype="float32")
                if audio.ndim == 2:
                    audio = audio.mean(axis=1)
                if rate != 16000:
                    from math import gcd

                    div = gcd(rate, 16000)
                    audio = resample_poly(audio, 16000 // div, rate // div).astype(np.float32)
                try:
                    vectors[-1] = encode(features(audio)[0])
                except AudioRejected:
                    pass
                else:
                    records[-1] = {
                        "targetId": target["id"],
                        "generator": "pinyinsound",
                        "voiceFamilyId": "pinyinsound-standard",
                        "referenceRootId": "pinyinsound-standard",
                        "sha256": standard["sha256"],
                    }
        bank.append(vectors)
        provenance.extend(records)
    return np.asarray(bank, dtype=np.float32), provenance


def score_model(name, x, model):
    x = np.asarray(x, dtype=np.float64)
    if name == "dtw":
        return np.exp(-x[:, 0])
    if name == "dtw-contrast":
        return expit(8.0 * x[:, 4])
    if name == "svm":
        return expit(((x - model["mean"]) / model["scale"]) @ model["coef"] + model["intercept"])
    score = np.full(len(x), model["initial"], dtype=np.float64)
    for tree in model["trees"]:
        nodes = np.zeros(len(x), dtype=np.int64)
        while True:
            feature = np.asarray(tree["feature"])[nodes]
            active = feature >= 0
            if not active.any():
                break
            positions = np.flatnonzero(active)
            current = nodes[positions]
            goes_left = x[positions, feature[active]] <= np.asarray(tree["threshold"])[current]
            nodes[positions] = np.where(
                goes_left, np.asarray(tree["left"])[current], np.asarray(tree["right"])[current]
            )
        score += model["rate"] * np.asarray(tree["value"])[nodes]
    return expit(score)


def serial_models(x, y):
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.svm import LinearSVC

    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-6)
    svm = LinearSVC(C=config()["svmC"], random_state=config()["seed"], max_iter=20000, dual="auto")
    svm.fit((x - mean) / scale, y)
    boost = GradientBoostingClassifier(
        n_estimators=config()["boostingTrees"],
        max_depth=config()["boostingDepth"],
        learning_rate=config()["boostingLearningRate"],
        random_state=config()["seed"],
    )
    boost.fit(x, y)
    trees = []
    for estimator in boost.estimators_[:, 0]:
        t = estimator.tree_
        trees.append(
            {
                "feature": t.feature.tolist(),
                "threshold": t.threshold.tolist(),
                "left": t.children_left.tolist(),
                "right": t.children_right.tolist(),
                "value": t.value[:, 0, 0].tolist(),
            }
        )
    prior = float(boost.init_.class_prior_[1])
    models = {
        "dtw": {},
        "dtw-contrast": {},
        "svm": {
            "mean": mean.tolist(),
            "scale": scale.tolist(),
            "coef": svm.coef_[0].tolist(),
            "intercept": float(svm.intercept_[0]),
        },
        "boost": {
            "initial": float(np.log(prior / (1 - prior))),
            "rate": boost.learning_rate,
            "trees": trees,
        },
    }
    for name, expected in (
        ("svm", expit(svm.decision_function((x - mean) / scale))),
        ("boost", boost.predict_proba(x)[:, 1]),
    ):
        if not np.allclose(score_model(name, x, models[name]), expected, rtol=1e-6, atol=1e-6):
            raise ValueError("TRADITIONAL_EXPORT_NUMERICAL_MISMATCH")
    return models


def metrics(scores, true_indices, rivals, threshold):
    matched = retry = uncertain = bad = 0
    for probs, true, negative in zip(scores, true_indices, rivals, strict=True):
        value = probs[true]
        matched += int(value >= threshold)
        retry += int(value <= config()["rejectThreshold"])
        uncertain += int(config()["rejectThreshold"] < value < threshold)
        bad += int(any(probs[i] >= threshold for i in negative))
    n = len(true_indices)
    return {
        "roots": n,
        "correctAccepted": matched,
        "correctExplicitReject": retry,
        "correctAbstention": uncertain,
        "nearNeighborFalseAccept": bad,
        "nearNeighborRoots": sum(bool(x) for x in rivals),
    }


def train(manifest: Path, cache: Path, output: Path):
    if output.exists():
        raise ValueError("TRADITIONAL_OUTPUT_EXISTS")
    settings = config()
    rows = read_manifest(manifest)
    ready = json.loads((cache / "ready.json").read_text())
    if (
        ready["datasetSha256"] != fingerprint(manifest)
        or ready["featureVersion"] != "logmel64-pitch4-v1"
    ):
        raise ValueError("TRADITIONAL_CACHE_IDENTITY_MISMATCH")
    train_rows = [r for r in rows if r["split"] == "train"]
    cal_rows = [r for r in rows if r["split"] == "calibration"]
    target_map = targets_by_id(load_catalog())
    targets = [target_map[k] for k in sorted({r["targetId"] for r in train_rows})]
    if len(targets) != 32 or any(t["form"] != "whole-syllable" for t in targets):
        raise ValueError("TRADITIONAL_PILOT_TARGETS_CHANGED")
    index = {t["id"]: i for i, t in enumerate(targets)}
    rivals = nearest(targets)
    bank, provenance = choose_templates(train_rows, manifest, cache, targets)
    families = [r["voiceFamilyId"] for r in provenance]
    x, y = [], []
    for row_number, row in enumerate(train_rows):
        i = index[row["targetId"]]
        comparison_rows = comparison(
            source_features(row, manifest, cache), bank, families, rivals, row["voiceFamilyId"]
        )
        x.append(comparison_rows[i])
        y.append(1)
        choices = sorted(
            rivals[i],
            key=lambda j: hashlib.sha256(
                f"{settings['seed']}:{row['id']}:{targets[j]['id']}".encode()
            ).hexdigest(),
        )[: settings["negativeTargetsPerTrainRoot"]]
        for j in choices:
            x.append(comparison_rows[j])
            y.append(0)
        if (row_number + 1) % 500 == 0:
            print(
                json.dumps({"trainingRootsPrepared": row_number + 1, "total": len(train_rows)}),
                flush=True,
            )
    x, y = np.asarray(x), np.asarray(y)
    models = serial_models(x, y)
    cal_x, cal_truth, cal_neg = [], [], []
    for row in cal_rows:
        i = index[row["targetId"]]
        cal_x.append(comparison(source_features(row, manifest, cache), bank, families, rivals))
        cal_truth.append(i)
        cal_neg.append(rivals[i])
    thresholds, summaries = {}, {}
    for name, model in models.items():
        scores = np.stack([score_model(name, row, model) for row in cal_x])
        candidates = []
        for threshold in settings["acceptThresholds"]:
            m = metrics(scores, cal_truth, cal_neg, threshold)
            n = m["roots"]
            neg = m["nearNeighborRoots"]
            violations = (
                max(0, m["nearNeighborFalseAccept"] / neg / 0.05 - 1)
                + max(0, m["correctExplicitReject"] / n / 0.1 - 1)
                + max(0, m["correctAbstention"] / n / 0.2 - 1)
            )
            candidates.append((violations, -m["correctAccepted"], threshold, m))
        _, _, threshold, result = min(candidates, key=lambda a: (a[0], a[1], a[2]))
        thresholds[name], summaries[name] = threshold, result
    output.mkdir(parents=True)
    np.savez_compressed(output / "templates.npz", bank=bank)
    metadata = {
        "schemaVersion": 1,
        "experimental": True,
        "labelProvenance": "tts-intended-unverified",
        "models": models,
        "thresholds": thresholds,
        "targets": targets,
        "templateProvenance": provenance,
        "manifestSha256": fingerprint(manifest),
        "configurationSha256": fingerprint(CONFIG),
        "catalogSha256": fingerprint(CATALOG),
        "templatesSha256": fingerprint(output / "templates.npz"),
        "trainingCodeSha256": fingerprint(Path(__file__)),
        "trainRoots": len(train_rows),
        "trainComparisonPairs": len(y),
        "trainingNegatives": int((y == 0).sum()),
        "calibrationRoots": len(cal_rows),
        "calibration": summaries,
        "testUsed": False,
        "runtimeThreads": 2,
    }
    (output / "model.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return {"trainRoots": len(train_rows), "pairs": len(y), "calibration": summaries}


def load(package):
    data = json.loads((package / "model.json").read_text())
    if (
        data["configurationSha256"] != fingerprint(CONFIG)
        or data["catalogSha256"] != fingerprint(CATALOG)
        or data["templatesSha256"] != fingerprint(package / "templates.npz")
    ):
        raise ValueError("TRADITIONAL_PACKAGE_INTEGRITY_MISMATCH")
    with np.load(package / "templates.npz", allow_pickle=False) as arrays:
        bank = arrays["bank"].copy()
    return data, bank


def match(package, method, target_id, payload):
    data, bank = load(package)
    if method not in data["models"]:
        return {"status": "unavailable", "reason": "METHOD_UNKNOWN", "experimental": True}
    targets = data["targets"]
    ids = [t["id"] for t in targets]
    if target_id not in ids:
        return {"status": "unavailable", "reason": "TARGET_NOT_TRAINED", "experimental": True}
    try:
        sample = decode_wav(payload)
        reason = signal_guard(sample)
        if reason:
            return {"status": "uncertain", "reason": reason, "experimental": True}
        vector = encode(features(sample)[0])
        entries = comparison(
            vector, bank, [r["voiceFamilyId"] for r in data["templateProvenance"]], nearest(targets)
        )
        value = float(
            score_model(
                method,
                entries[ids.index(target_id) : ids.index(target_id) + 1],
                data["models"][method],
            )[0]
        )
        status = (
            "matched"
            if value >= data["thresholds"][method]
            else "retry"
            if value <= config()["rejectThreshold"]
            else "uncertain"
        )
        return {"status": status, "reason": None, "experimental": True, "toneAssessed": False}
    except (AudioRejected, ValueError):
        return {"status": "uncertain", "reason": "AUDIO_UNASSESSABLE", "experimental": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--manifest", required=True, type=Path)
    fit.add_argument("--cache", required=True, type=Path)
    fit.add_argument("--output", required=True, type=Path)
    infer = sub.add_parser("match")
    infer.add_argument("--package", required=True, type=Path)
    infer.add_argument("--method", choices=("dtw", "dtw-contrast", "svm", "boost"), required=True)
    infer.add_argument("--target", required=True)
    infer.add_argument("--wav", required=True, type=Path)
    args = parser.parse_args()
    with threadpool_limits(limits=2):
        result = (
            train(args.manifest, args.cache, args.output)
            if args.action == "train"
            else match(args.package, args.method, args.target, args.wav.read_bytes())
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
