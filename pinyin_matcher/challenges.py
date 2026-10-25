"""Frozen-model held-out environmental, additional-speech and tone challenges."""

import argparse
import json
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import decode_wav, encode_wav
from pinyin_matcher.catalog import ROOT, targets_by_id
from pinyin_matcher.data import augment, dataset_digest, read_manifest
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.inference import PinyinMatcher


def evaluate(model: Path, manifest: Path, output: Path, substitutions: Path | None = None):
    matcher = PinyinMatcher(model)
    if matcher.session is None:
        raise ValueError(matcher.problem)
    rows = [row for row in read_manifest(manifest) if row["split"] == "test"]
    if not rows:
        raise ValueError("TEST_SAMPLES_REQUIRED")
    results = []

    def record(case, key, payload, sample_id, *, expected_match):
        result = matcher.match(key, payload, include_evidence=True)
        results.append(
            {
                "case": case,
                "sampleId": sample_id,
                "targetId": key,
                "expectedMatch": expected_match,
                **result,
            }
        )

    for index, row in enumerate(rows):
        samples = decode_wav((manifest.parent / row["file"]).read_bytes())
        for snr in [20, 10, 0]:
            changed = augment(samples, row["seed"] + 10_000_000 + snr, snr=snr)
            record(
                f"environment-{snr}dB",
                row["targetId"],
                encode_wav(changed),
                row["id"],
                expected_match=True,
            )
        other = rows[(index + 17) % len(rows)]
        if other["targetId"] == row["targetId"]:
            other = next(
                candidate for candidate in rows if candidate["targetId"] != row["targetId"]
            )
        extra = decode_wav((manifest.parent / other["file"]).read_bytes())
        combined = np.concatenate([samples, np.zeros(2400, dtype=np.float32), extra])
        record(
            "extra-syllable", row["targetId"], encode_wav(combined), row["id"], expected_match=False
        )
    for index in range(20):
        noise = np.random.default_rng(100_000 + index).normal(0, 0.1, 16000).astype(np.float32)
        record(
            "non-speech-noise",
            rows[index % len(rows)]["targetId"],
            encode_wav(noise),
            str(index),
            expected_match=False,
        )
    record(
        "silence", rows[0]["targetId"], encode_wav(np.zeros(16000)), "silence", expected_match=False
    )
    if substitutions:
        targets = targets_by_id()
        definitions = json.loads((ROOT / "content/pronunciation-challenges.json").read_text())[
            "definitions"
        ]
        against = {entry["pinyin"]: entry["against"] for entry in definitions}
        for row in read_manifest(substitutions):
            if row["split"] != "test":
                raise ValueError("SUBSTITUTION_CHALLENGES_MUST_BE_HELD_OUT")
            if row["targetId"] in matcher.metadata["coveredTargetIds"]:
                record(
                    "new-voice-positive",
                    row["targetId"],
                    (substitutions.parent / row["file"]).read_bytes(),
                    row["id"],
                    expected_match=True,
                )
                continue
            key = against[targets[row["targetId"]]["pinyin"]]
            record(
                "untrained-tone-or-umlaut",
                key,
                (substitutions.parent / row["file"]).read_bytes(),
                row["id"],
                expected_match=False,
            )

    def metrics(group):
        return {
            "samples": len(group),
            **{
                status: sum(r["status"] == status for r in group)
                for status in ["matched", "retry", "uncertain", "unavailable"]
            },
        }

    report = {
        "cohort": "synthetic-held-out-intended-labels",
        "modelSha256": matcher.metadata["sha256"],
        "datasetSha256": dataset_digest(manifest),
        "thresholdsFrozenBeforeTest": True,
        "substitutionDatasetSha256": dataset_digest(substitutions) if substitutions else None,
        "byCase": {
            case: metrics([r for r in results if r["case"] == case])
            for case in sorted({r["case"] for r in results})
        },
        "results": results,
        "realChildAccuracyEstablished": False,
    }
    atomic_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--substitutions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(evaluate(args.model, args.manifest, args.output, args.substitutions)["byCase"])
    )
