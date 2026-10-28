"""Two-thread full four-second timing and fresh-process startup measurements."""

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_info, threadpool_limits

from pinyin_matcher.audio import decode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.traditional_shop import match


def benchmark(package, wav, target, output):
    if output.exists():
        raise ValueError("TRADITIONAL_BENCHMARK_OUTPUT_EXISTS")
    payload = wav.read_bytes()
    if len(decode_wav(payload)) != 64000:
        raise ValueError("TRADITIONAL_BENCHMARK_FOUR_SECONDS_REQUIRED")
    models = json.loads((package / "model.json").read_text())["models"]
    results = {}
    for method in models:
        for _ in range(3):
            if match(package, method, target, payload).get("reason") is not None:
                raise ValueError("TRADITIONAL_BENCHMARK_DID_NOT_RUN_MODEL")
        times = []
        for _ in range(30):
            started = time.perf_counter()
            response = match(package, method, target, payload)
            times.append((time.perf_counter() - started) * 1000)
            if response.get("reason") is not None:
                raise ValueError("TRADITIONAL_BENCHMARK_DID_NOT_RUN_MODEL")
        cold = []
        for _ in range(5):
            command = [
                sys.executable,
                "-m",
                "pinyin_matcher.traditional_shop",
                "match",
                "--package",
                str(package),
                "--method",
                method,
                "--target",
                target,
                "--wav",
                str(wav),
            ]
            started = time.perf_counter()
            process = subprocess.run(command, check=True, capture_output=True, text=True)
            cold.append((time.perf_counter() - started) * 1000)
            if json.loads(process.stdout)["reason"] is not None:
                raise ValueError("TRADITIONAL_COLD_DID_NOT_RUN_MODEL")
        p95 = float(np.percentile(times, 95))
        results[method] = {
            "warmP95Milliseconds": p95,
            "realTimeFactor": p95 / 4000,
            "warmTimingsMilliseconds": times,
            "coldWallP95Milliseconds": float(np.percentile(cold, 95)),
            "coldWallMilliseconds": cold,
            "passesLatencyAndRtf": p95 <= 400,
        }
    result = {
        "schemaVersion": 1,
        "threads": 2,
        "threadPools": threadpool_info(),
        "audioSha256": fingerprint(wav),
        "modelSha256": fingerprint(package / "model.json"),
        "packageBytes": sum(x.stat().st_size for x in package.iterdir() if x.is_file()),
        "peakRssMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024),
        "scope": "Each warm call reloads the local package, decodes WAV, "
        "runs features, comparisons and target decision; cold adds fresh process/imports. "
        "Shared machine; OS cache not flushed.",
        "methods": results,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    with threadpool_limits(limits=2):
        print(json.dumps(benchmark(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == "__main__":
    main()
