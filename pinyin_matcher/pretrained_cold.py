"""Measure fresh-process, complete local CLI startup and inference."""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import wave
from pathlib import Path


def benchmark(package: Path, wav: Path, target: str, output: Path, *, repeats=5):
    if not 3 <= repeats <= 30:
        raise ValueError("COLD_BENCHMARK_REQUIRES_3_TO_30_PROCESSES")
    if output.exists():
        raise ValueError("COLD_BENCHMARK_OUTPUT_EXISTS")
    with wave.open(str(wav), "rb") as source:
        if (
            source.getframerate() != 16000
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getnframes() != 64000
        ):
            raise ValueError("COLD_BENCHMARK_REQUIRES_FOUR_SECOND_PCM16_MONO_16KHZ")
    command = [
        sys.executable,
        "-m",
        "pinyin_matcher.pretrained_runtime",
        "match",
        "--model",
        str(package.resolve()),
        "--wav",
        str(wav.resolve()),
        "--target",
        target,
        "--evidence",
    ]
    environment = {
        **os.environ,
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    runs = []
    for index in range(repeats):
        started = time.perf_counter()
        result = subprocess.run(
            command, env=environment, text=True, capture_output=True, timeout=120, check=True
        )
        milliseconds = (time.perf_counter() - started) * 1000
        prediction = json.loads(result.stdout)
        if (
            "internalEvidence" not in prediction
            or "elapsedMilliseconds" not in prediction
            or prediction["status"] == "unavailable"
        ):
            raise ValueError("COLD_BENCHMARK_DID_NOT_EXECUTE_COMPLETE_MODEL")
        runs.append(
            {
                "freshProcess": index + 1,
                "wallMilliseconds": milliseconds,
                "inferenceMilliseconds": prediction["elapsedMilliseconds"],
                "status": prediction["status"],
            }
        )
        print(json.dumps(runs[-1]), flush=True)
    ordered = sorted(r["wallMilliseconds"] for r in runs)
    position = (len(ordered) - 1) * 0.95
    lower = math.floor(position)
    upper = math.ceil(position)
    report = {
        "schemaVersion": 1,
        "threads": 2,
        "device": "cpu",
        "repeats": repeats,
        "freshProcessWallP95Milliseconds": ordered[lower]
        + (ordered[upper] - ordered[lower]) * (position - lower),
        "runs": runs,
        "modelSha256": hashlib.sha256((package / "model.json").read_bytes()).hexdigest(),
        "payloadSha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
        "command": command,
        "includes": (
            "Python process, imports, CLI parsing, local package integrity checks, model load, "
            "WAV decode, features, encoder, heads, comparison, evidence JSON and process exit."
        ),
        "operatingSystemFileCacheFlushed": False,
        "qualityEvidence": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    print(
        json.dumps(benchmark(args.model, args.wav, args.target, args.output, repeats=args.repeats)),
        flush=True,
    )


if __name__ == "__main__":
    main()
