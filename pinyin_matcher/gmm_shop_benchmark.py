"""Measure full CPU research matcher, including decoding and fresh-process startup."""

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from pinyin_matcher.audio import decode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.gmm_shop import match


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    payload = args.wav.read_bytes()
    if len(decode_wav(payload)) != 64000:
        raise ValueError("FOUR_SECOND_WAV_REQUIRED")
    with threadpool_limits(limits=2):
        for _ in range(3):
            if match(args.package, args.target, payload).get("reason") is not None:
                raise ValueError("INFERENCE_NOT_EXERCISED")
        warm = []
        for _ in range(30):
            started = time.perf_counter()
            answer = match(args.package, args.target, payload)
            warm.append((time.perf_counter() - started) * 1000)
            if answer.get("reason") is not None:
                raise ValueError("INFERENCE_NOT_EXERCISED")
        cold = []
        for _ in range(5):
            cmd = [
                sys.executable,
                "-m",
                "pinyin_matcher.gmm_shop",
                "match",
                "--package",
                str(args.package),
                "--target",
                args.target,
                "--wav",
                str(args.wav),
            ]
            started = time.perf_counter()
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            cold.append((time.perf_counter() - started) * 1000)
            if json.loads(result.stdout).get("reason") is not None:
                raise ValueError("COLD_INFERENCE_NOT_EXERCISED")
    p95 = float(np.percentile(warm, 95))
    output = {
        "threads": 2,
        "modelSha256": fingerprint(args.package / "model.json"),
        "audioSha256": fingerprint(args.wav),
        "packageBytes": sum(p.stat().st_size for p in args.package.iterdir() if p.is_file()),
        "peakRssMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576,
        "warmP95Milliseconds": p95,
        "warmTimesMilliseconds": warm,
        "realTimeFactor": p95 / 4000,
        "coldP95Milliseconds": float(np.percentile(cold, 95)),
        "coldTimesMilliseconds": cold,
        "scope": (
            "includes model reload, WAV decode, guard, feature extraction and target comparison; "
            "fresh process cold includes imports; OS cache not flushed"
        ),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
