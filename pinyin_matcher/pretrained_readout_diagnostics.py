"""Inspect component errors on calibration only, without opening final audio."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import onnxruntime as ort

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import arrays, read_rows, supervision, write


def diagnose(manifest, cache, heads, output):
    if output.exists():
        raise ValueError("DIAGNOSTIC_OUTPUT_EXISTS")
    metadata = json.loads((heads / "model.json").read_text())
    if metadata["manifestSha256"] != fingerprint(manifest):
        raise ValueError("HEAD_MANIFEST_MISMATCH")
    if metadata["headOnnxSha256"] != fingerprint(heads / "heads.onnx"):
        raise ValueError("HEAD_DIGEST_MISMATCH")
    if metadata["normalizationSha256"] != fingerprint(heads / "normalization.npz"):
        raise ValueError("NORMALIZATION_DIGEST_MISMATCH")
    if metadata["cacheMetadataSha256"] != fingerprint(cache / "cache.json"):
        raise ValueError("CACHE_DIGEST_MISMATCH")
    if metadata.get("pitchOverride"):
        raise ValueError("EXTERNAL_PITCH_NOT_SUPPORTED_BY_THIS_DIAGNOSTIC")
    rows = [r for r in read_rows(manifest) if r["split"] == "calibration"]
    vocab = metadata["vocabulary"]
    acoustic, pitch, labels = arrays(
        rows, cache, vocab, temporal=metadata.get("representation") == "temporal16-v1"
    )
    with np.load(heads / "normalization.npz", allow_pickle=False) as norm:
        acoustic = (acoustic - norm["mean"]) / norm["scale"]
        pitch = (pitch - norm["pitch_mean"]) / norm["pitch_scale"]
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(heads / "heads.onnx"), options, providers=["CPUExecutionProvider"]
    )
    outputs = session.run(None, {"acoustic": acoustic, "pitch": pitch})
    best = np.stack([o.argmax(-1) for o in outputs], axis=1)
    annotations = supervision(rows)
    components = {}
    for i, key in enumerate(("onset", "rime", "tone")):
        valid = (annotations[:, i] == 1) & (labels[:, i] >= 0)
        confusions = Counter(
            (vocab[key][truth], vocab[key][pred])
            for truth, pred in zip(labels[valid, i], best[valid, i], strict=True)
            if truth != pred
        )
        components[key] = {
            "expertCorrectAssessable": int(valid.sum()),
            "argmaxCorrect": int((best[valid, i] == labels[valid, i]).sum()),
            "confusions": [
                {"expected": a, "predicted": b, "n": n} for (a, b), n in confusions.most_common(20)
            ],
        }
    positive = np.asarray(
        [
            r.get("expertLabel") == "unanimous-correct" and not r.get("labelPolicyFlags")
            for r in rows
        ]
    )
    usable = np.asarray(
        [not r.get("numericalQualityFlags") and not r.get("placeholder") for r in rows]
    ) & (labels >= 0).all(1)
    duration_groups = {}
    for index, row in enumerate(rows):
        if not positive[index]:
            continue
        duration = row.get("bounds", {}).get("originalDurationSeconds")
        band = (
            "unknown"
            if duration is None
            else "under-200ms"
            if duration < 0.2
            else "200-400ms"
            if duration < 0.4
            else "over-400ms"
        )
        group = duration_groups.setdefault(band, {"positiveRoots": 0, "argmaxAllCorrect": 0})
        group["positiveRoots"] += 1
        group["argmaxAllCorrect"] += int(usable[index] and (best[index] == labels[index]).all())
    report = {
        "schemaVersion": 1,
        "split": "calibration",
        "finalTestRead": False,
        "kind": "cached-readout-diagnostic-not-full-cpu-evaluation",
        "manifestSha256": fingerprint(manifest),
        "headMetadataSha256": fingerprint(heads / "model.json"),
        "codeSha256": fingerprint(Path(__file__)),
        "components": components,
        "durationGroups": duration_groups,
        "positiveRoots": int(positive.sum()),
        "positiveUnusable": int((positive & ~usable).sum()),
        "positiveAllThreeArgmaxCorrect": int((positive & usable & (best == labels).all(1)).sum()),
        "positiveErrorComponentCounts": dict(
            Counter(str(int(n)) for n in (best != labels)[positive & usable].sum(1))
        ),
    }
    write(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("manifest", "cache", "heads", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(diagnose(args.manifest, args.cache, args.heads, args.output), ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
