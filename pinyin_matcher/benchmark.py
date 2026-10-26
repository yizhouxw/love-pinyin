"""CPU latency and actual held-out reference-audio checks, independent of training."""

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.generate import atomic_json
from pinyin_matcher.inference import PinyinMatcher


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def benchmark(model: Path, output: Path, repeats: int = 3):
    before = peak_rss_bytes()
    started = time.perf_counter()
    matcher = PinyinMatcher(model, threads=2)
    cold = (time.perf_counter() - started) * 1000
    if matcher.session is None:
        raise ValueError(matcher.problem)
    target_map = matcher.targets
    assets = json.loads((ROOT / "content/daily-reading.json").read_text())["assets"]
    assets = {item["id"]: item for item in assets}
    results, latencies, rtfs, recordings = [], [], [], []
    for key in matcher.metadata["coveredTargetIds"]:
        target = target_map[key]
        asset = assets.get(target["standardAudioId"])
        if asset is None:
            continue
        source = ROOT / "private/pinyinsound/clips" / (asset["sha256"] + ".mp3")
        if fingerprint(source) != asset["sha256"]:
            raise ValueError("REFERENCE_AUDIO_DIGEST_MISMATCH")
        process = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source),
                "-f",
                "wav",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-acodec",
                "pcm_s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        # ffmpeg pipe WAV may use a streaming length. Re-encode bounded PCM locally.
        import io
        import wave

        with wave.open(io.BytesIO(process.stdout)) as decoded:
            samples = (
                np.frombuffer(decoded.readframes(128000), dtype="<i2").astype(np.float32) / 32768
            )
        payload = encode_wav(samples)
        recordings.append((key, samples))
        for repeat in range(repeats):
            begin = time.perf_counter()
            result = matcher.match(key, payload, include_evidence=True)
            elapsed = time.perf_counter() - begin
            if repeat:
                latencies.append(elapsed * 1000)
                rtfs.append(elapsed / (len(samples) / 16000))
        results.append({"targetId": key, "referenceId": target["standardAudioId"], **result})
    # Repeating actual voice to four seconds is a duration/extra-speech stress
    # check, not another positive pronunciation sample or a child recording.
    long_latencies, long_rtfs, extra_speech = [], [], []
    for key, samples in recordings:
        repeated = np.tile(np.concatenate([samples, np.zeros(2400, dtype=np.float32)]), 16)
        four_seconds = encode_wav(repeated[:64000])
        for _ in range(repeats):
            begin = time.perf_counter()
            result = matcher.match(key, four_seconds)
            elapsed = time.perf_counter() - begin
            long_latencies.append(elapsed * 1000)
            long_rtfs.append(elapsed / 4)
        extra_speech.append({"targetId": key, **result})
    if not latencies:
        raise ValueError("NO_HELD_OUT_REFERENCE_AUDIO")
    peak = peak_rss_bytes()
    report = {
        "cohort": "PinYinSound-reference-diagnostic-not-independent-speaker-not-child",
        "qualityGateEvaluation": False,
        "independentSpeakerValidation": False,
        "cpuProviders": matcher.session.get_providers(),
        "threads": 2,
        "coldLoadMilliseconds": cold,
        "p95Milliseconds": float(np.percentile(latencies, 95)),
        "p95RealTimeFactor": float(np.percentile(rtfs, 95)),
        "peakProcessRSSBytes": peak,
        "peakRSSIncreaseBytes": max(0, peak - before),
        "fourSecondRepeatedSpeechP95Milliseconds": float(np.percentile(long_latencies, 95)),
        "fourSecondRepeatedSpeechP95RealTimeFactor": float(np.percentile(long_rtfs, 95)),
        "extraSpeechFalsePass": sum(r["status"] == "matched" for r in extra_speech),
        "extraSpeechSamples": len(extra_speech),
        "modelBytes": (model / matcher.metadata["file"]).stat().st_size
        + (
            (model / matcher.metadata["pitchTone"]["file"]).stat().st_size
            if matcher.metadata.get("pitchTone")
            else 0
        )
        + (
            (model / matcher.metadata["pitchTone"]["tracker"]["file"]).stat().st_size
            if matcher.metadata.get("pitchTone", {}).get("tracker")
            else 0
        ),
        "samples": len(results),
        "matched": sum(r["status"] == "matched" for r in results),
        "retry": sum(r["status"] == "retry" for r in results),
        "uncertain": sum(r["status"] == "uncertain" for r in results),
        "results": results,
        "extraSpeechResults": extra_speech,
        "realChildAccuracyEstablished": False,
    }
    atomic_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.model, args.output)
    print(
        json.dumps(
            {k: v for k, v in report.items() if not k.endswith("Results") and k != "results"},
            ensure_ascii=False,
        )
    )
