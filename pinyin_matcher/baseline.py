"""Deterministic log-Mel/relative-pitch DTW comparator, not a pronunciation score."""

import argparse
from pathlib import Path

import numpy as np
from scipy.spatial.distance import cdist

from pinyin_matcher.catalog import targets_by_id
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.train import prepare


def resize(sequence: np.ndarray, frames=40) -> np.ndarray:
    positions = np.linspace(0, len(sequence) - 1, frames)
    return np.stack(
        [
            np.interp(positions, np.arange(len(sequence)), sequence[:, i])
            for i in range(sequence.shape[1])
        ],
        axis=1,
    )


def dtw(first: np.ndarray, second: np.ndarray, band=10) -> float:
    cost = cdist(first, second, metric="sqeuclidean") / first.shape[1]
    previous = np.full(len(second) + 1, np.inf)
    previous[0] = 0
    for i in range(len(first)):
        current = np.full(len(second) + 1, np.inf)
        for j in range(max(0, i - band), min(len(second), i + band + 1)):
            current[j + 1] = cost[i, j] + min(previous[j], previous[j + 1], current[j])
        previous = current
    return float(previous[-1] / (len(first) + len(second)))


def evaluate(manifest: Path, output: Path, cache: Path | None = None):
    rows, arrays = prepare(manifest, cache or output / "feature-cache")
    covered = sorted({r["targetId"] for r in rows if r["split"] == "train"})
    prototypes = {}
    for key in covered:
        values = [
            resize(arrays[r["id"]][0])
            for r in rows
            if r["split"] == "train" and r["targetId"] == key
        ]
        mean = np.mean(values, axis=0)
        # A real training exemplar, never an averaged waveform or test sample.
        prototypes[key] = values[int(np.argmin([np.mean((x - mean) ** 2) for x in values]))]
    targets = targets_by_id()
    results = []
    for row in rows:
        if row["split"] != "test":
            continue
        value = resize(arrays[row["id"]][0])
        candidate = min(covered, key=lambda key: dtw(value, prototypes[key]))
        actual, predicted = targets[row["targetId"]], targets[candidate]
        results.append(
            {
                "id": row["id"],
                "targetId": row["targetId"],
                "candidateId": candidate,
                "correct": candidate == row["targetId"],
                "contentCorrect": actual["phones"] == predicted["phones"],
                "toneCorrect": actual["tone"] == predicted["tone"],
            }
        )
    report = {
        "cohort": "synthetic-intended-labels",
        "split": "test",
        "method": "training-exemplar-banded-DTW",
        "samples": len(results),
        "top1Accuracy": sum(r["correct"] for r in results) / len(results),
        "contentAccuracy": sum(r["contentCorrect"] for r in results) / len(results),
        "toneAccuracy": sum(r["toneCorrect"] for r in results) / len(results),
        "results": results,
    }
    atomic_json(output / "baseline-test.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    report = evaluate(args.manifest, args.output, args.cache_dir)
    print({key: value for key, value in report.items() if key != "results"})
