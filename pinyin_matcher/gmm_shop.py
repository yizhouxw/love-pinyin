"""MATCH-18: research-only GMM/HMM target likelihood experiment."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.fft import dct
from scipy.special import logsumexp
from threadpoolctl import threadpool_limits

from pinyin_matcher.audio import AudioRejected, decode_wav, features
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog, targets_by_id
from pinyin_matcher.pretrained_runtime import signal_guard

SEED = 3182026
COMPONENTS = ("onset", "rime", "tone")
THRESHOLDS = (-4.0, -3.0, -2.0, -1.0, 0.0, 0.5, 1.0, 2.0, 3.0)
REJECT = -8.0


def acoustic(payload):
    samples = decode_wav(payload)
    array, info = features(samples)
    if info["voicedFrames"] < 5:
        raise AudioRejected("TONE_INSUFFICIENT_VOICING")
    cep = dct(array[:, :64], type=2, norm="ortho", axis=1)[:, 1:14] / 4
    # Tone is relative within the utterance; no absolute speaker pitch identity.
    points = np.linspace(0, len(array) - 1, 7)
    tone = np.concatenate(
        [np.interp(points, np.arange(len(array)), array[:, k]) for k in (65, 66, 67)]
    )
    return cep.astype(np.float32), tone.astype(np.float32), samples


def read_data(manifest):
    from pinyin_matcher.pretrained_experiment import read_rows

    rows = read_rows(manifest, verify_splits=("train", "calibration"))
    native = [
        r
        for r in rows
        if r.get("source", "").startswith("aishell3")
        and r["split"] == "train"
        and not r.get("labelPolicyFlags")
        and not r.get("numericalQualityFlags")
        and not r.get("placeholder")
    ]
    cal = [
        r
        for r in rows
        if r.get("source") == "ompal-v1"
        and r["split"] == "calibration"
        and r.get("expertLabel") in {"unanimous-correct", "unanimous-error"}
    ]
    return native, cal


def fit_gmm(arrays):
    from sklearn.mixture import GaussianMixture

    values = np.concatenate(arrays)
    if len(values) > 6000:
        values = values[np.random.default_rng(SEED).choice(len(values), 6000, replace=False)]
    if len(values) < 20:
        raise ValueError("INSUFFICIENT_PHONE_FRAMES")
    model = GaussianMixture(
        n_components=4, covariance_type="diag", reg_covar=0.05, max_iter=30, random_state=SEED
    )
    model.fit(values)
    return {
        "weights": model.weights_.tolist(),
        "means": model.means_.tolist(),
        "variances": model.covariances_.tolist(),
    }


def log_emission(x, parameters):
    means = np.asarray(parameters["means"])
    variances = np.asarray(parameters["variances"])
    weights = np.asarray(parameters["weights"])
    x = np.atleast_2d(x)
    logp = -0.5 * (
        np.log(2 * np.pi * variances).sum(axis=1)[None, :]
        + ((x[:, None, :] - means) ** 2 / variances).sum(axis=2)
    )
    return logsumexp(logp + np.log(weights), axis=1)


def hmm_path(x, onset, rime):
    """Two-state left-to-right Viterbi; fixed equal self/advance transitions."""
    a, b = log_emission(x, onset), log_emission(x, rime)
    # Every state consumes at least two frames. Transitions have equal costs,
    # so they cancel across paths of equal length.
    candidates = np.cumsum(a)[:-2] + np.cumsum(b[::-1])[::-1][1:-1]
    if len(candidates) < 2:
        raise ValueError("AUDIO_TOO_SHORT_FOR_HMM")
    candidates[0] = -np.inf
    boundary = int(np.argmax(candidates)) + 1
    return boundary, float(candidates[boundary - 1] / len(x))


def target_scores(x, tone, targets, model):
    # Cache all phone likelihoods once. A left-to-right target path chooses
    # its boundary; each state is then compared against all competing phones.
    onset = {k: log_emission(x, v) for k, v in model["onset"].items()}
    rime = {k: log_emission(x, v) for k, v in model["rime"].items()}
    tones = {k: float(log_emission(tone, v)[0]) for k, v in model["tone"].items()}
    scored = []
    for target in targets:
        a, r, t = target["onset"], target["rime"], str(target["tone"])
        # Without a zero-onset acoustic model, do not claim it was assessed.
        if not a or a not in onset or r not in rime or t not in tones or len(x) < 5:
            scored.append(None)
            continue
        paths = np.cumsum(onset[a])[:-2] + np.cumsum(rime[r][::-1])[::-1][1:-1]
        paths[0] = -np.inf
        boundary = int(np.argmax(paths)) + 1
        onset_target = float(onset[a][:boundary].mean())
        onset_other = max(
            float(value[:boundary].mean()) for key, value in onset.items() if key != a
        )
        rime_target = float(rime[r][boundary:].mean())
        rime_other = max(float(value[boundary:].mean()) for key, value in rime.items() if key != r)
        tone_other = max(value for key, value in tones.items() if key != t)
        scored.append(
            min(onset_target - onset_other, rime_target - rime_other, (tones[t] - tone_other) / 21)
        )
    return scored


def train(manifest, output):
    if output.exists():
        raise ValueError("OUTPUT_EXISTS")
    native, cal = read_data(manifest)
    target_map = targets_by_id(load_catalog())
    ids = json.loads((ROOT / "content/pronunciation-targets.json").read_text())["pilotIds"]
    targets = [target_map[k] for k in ids]
    train_data, skipped = [], Counter()
    for row in native:
        try:
            x, pitch, _ = acoustic(Path(row["file"]).read_bytes())
            if len(x) < 5:
                raise ValueError("SHORT")
            train_data.append((row, x, pitch))
        except (AudioRejected, ValueError) as error:
            skipped[str(error)] += 1
    print(json.dumps({"usable": len(train_data), "skipped": dict(skipped)}), flush=True)
    models = None
    for iteration in range(2):
        a, b, t = defaultdict(list), defaultdict(list), defaultdict(list)
        for row, x, pitch in train_data:
            onset, rime = row["onset"], row["rime"]
            boundary = max(2, min(len(x) - 2, int(len(x) * 0.35)))
            if iteration and onset and onset in models["onset"] and rime in models["rime"]:
                boundary, _ = hmm_path(x, models["onset"][onset], models["rime"][rime])
            if onset:
                a[onset].append(x[:boundary])
            b[rime].append(x[boundary:] if onset else x)
            t[str(row["tone"])].append(pitch[None, :])
        models = {
            "onset": {k: fit_gmm(v) for k, v in sorted(a.items())},
            "rime": {k: fit_gmm(v) for k, v in sorted(b.items())},
            "tone": {k: fit_gmm(v) for k, v in sorted(t.items())},
        }
        print(json.dumps({"iteration": iteration + 1, "phoneModels": len(a) + len(b)}), flush=True)
    ids = [t["id"] for t in targets]
    diagnosis, skipped_cal = [], Counter()
    for row in cal:
        target_id = "pm-" + row["syllable"]
        if target_id not in ids:
            continue
        try:
            x, pitch, samples = acoustic(Path(row["file"]).read_bytes())
            guard = signal_guard(samples)
            scores = [None] * len(targets) if guard else target_scores(x, pitch, targets, models)
        except (AudioRejected, ValueError) as error:
            guard, scores = str(error), [None] * len(targets)
        skipped_cal[guard or "none"] += 1
        diagnosis.append((row, ids.index(target_id), scores))
    candidates = []
    for threshold in THRESHOLDS:
        counts = evaluate(diagnosis, targets, threshold)
        n, near = counts["correctRoots"], counts["nearRoots"]
        violation = (
            max(0, counts["nearFalseAccept"] / max(near, 1) / 0.05 - 1)
            + max(0, counts["correctRetry"] / max(n, 1) / 0.1 - 1)
            + max(0, counts["correctUncertain"] / max(n, 1) / 0.2 - 1)
        )
        candidates.append((violation, -counts["correctMatched"], threshold, counts))
    _, _, threshold, counts = min(candidates, key=lambda v: v[:3])
    output.mkdir(parents=True)
    model = {
        "schemaVersion": 1,
        "experimental": True,
        "seed": SEED,
        "trainingIterations": 2,
        "models": models,
        "targets": targets,
        "threshold": threshold,
        "rejectThreshold": REJECT,
        "manifestSha256": fingerprint(manifest),
        "catalogSha256": fingerprint(ROOT / "content/pronunciation-targets.json"),
        "trainingCodeSha256": fingerprint(Path(__file__)),
        "trainingRoots": len(native),
        "usableRoots": len(train_data),
        "skippedRoots": dict(skipped),
        "calibration": counts,
        "calibrationGuards": dict(skipped_cal),
        "finalTestUsed": False,
    }
    (output / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    return {
        "modelSha256": fingerprint(output / "model.json"),
        "threshold": threshold,
        "calibration": counts,
        "guards": dict(skipped_cal),
    }


def evaluate(rows, targets, threshold):
    result = Counter()
    for row, index, scores in rows:
        value = scores[index]
        status = (
            "Uncertain"
            if value is None
            else "Matched"
            if value >= threshold
            else "Retry"
            if value <= REJECT
            else "Uncertain"
        )
        if row["expertLabel"] == "unanimous-correct":
            result["correctRoots"] += 1
            result["correct" + status] += 1
            rivals = [
                j
                for j, other in enumerate(targets)
                if j != index
                and sum(str(targets[index][k]) != str(other[k]) for k in COMPONENTS) == 1
            ]
            if rivals:
                result["nearRoots"] += 1
                result["nearFalseAccept"] += int(
                    any(scores[j] is not None and scores[j] >= threshold for j in rivals)
                )
            else:
                result["noNearRoots"] += 1
        else:
            result["expertErrorRoots"] += 1
            result["expertError" + status] += 1
    return {
        k: result[k]
        for k in (
            "correctRoots",
            "correctMatched",
            "correctRetry",
            "correctUncertain",
            "nearRoots",
            "nearFalseAccept",
            "noNearRoots",
            "expertErrorRoots",
            "expertErrorMatched",
            "expertErrorRetry",
            "expertErrorUncertain",
        )
    }


def match(package, target, payload):
    model = json.loads((package / "model.json").read_text())
    if model["catalogSha256"] != fingerprint(ROOT / "content/pronunciation-targets.json"):
        return {"status": "unavailable", "reason": "CATALOG_CHANGED", "experimental": True}
    ids = [item["id"] for item in model["targets"]]
    if target not in ids:
        return {"status": "unavailable", "reason": "TARGET_NOT_TRAINED", "experimental": True}
    try:
        x, tone, samples = acoustic(payload)
        guard = signal_guard(samples)
        if guard:
            return {"status": "uncertain", "reason": guard, "experimental": True}
        score = target_scores(x, tone, model["targets"], model["models"])[ids.index(target)]
        status = (
            "uncertain"
            if score is None
            else "matched"
            if score >= model["threshold"]
            else "retry"
            if score <= model["rejectThreshold"]
            else "uncertain"
        )
        return {
            "status": status,
            "reason": "MISSING_NEIGHBORS" if score is None else None,
            "experimental": True,
            "toneAssessed": False,
        }
    except (AudioRejected, ValueError):
        return {"status": "uncertain", "reason": "AUDIO_UNASSESSABLE", "experimental": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--manifest", required=True, type=Path)
    fit.add_argument("--output", required=True, type=Path)
    infer = sub.add_parser("match")
    infer.add_argument("--package", required=True, type=Path)
    infer.add_argument("--target", required=True)
    infer.add_argument("--wav", required=True, type=Path)
    args = parser.parse_args()
    with threadpool_limits(limits=2):
        result = (
            train(args.manifest, args.output)
            if args.action == "train"
            else match(args.package, args.target, args.wav.read_bytes())
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
