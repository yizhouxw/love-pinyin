"""Explicit local TD-PSOLA derivation; recordings remain private with their original licence.

Only voiced periods are rearranged. Consonants, silence and duration are retained.
No model, TTS, network, or runtime audio processing is involved.
"""

import bisect
import hashlib
import math
import struct
import wave
from pathlib import Path

from scripts.prepare_pinyin_source import atomic_json, check_recording
from server import daily_pronunciation, source_audio


def pitch_period(frame: list[float], rate: int) -> float | None:
    """YIN difference / cumulative mean; refuse aperiodic and silent frames."""
    if sum(v * v for v in frame) / len(frame) < 0.000001:
        return None
    width = len(frame) // 2
    total = 0.0
    scores = [1.0]
    for lag in range(1, rate // 80):
        difference = sum((frame[n] - frame[n + lag]) ** 2 for n in range(width))
        total += difference
        scores.append(difference * lag / total if total else 1.0)
    low, high = rate // 500, len(scores) - 2
    for lag in range(low, high):
        if scores[lag] < 0.3:
            while lag < high and scores[lag + 1] < scores[lag]:
                lag += 1
            a, b, c = scores[lag - 1 : lag + 2]
            offset = (a - c) / (2 * (a - 2 * b + c)) if a - 2 * b + c else 0
            return lag + offset
    return None


def level_tone(
    samples: list[float], rate: int, target: float, *, steady_nucleus: bool = False
) -> tuple[list[float], dict]:
    """Pitch-synchronous overlap-add with a constant synthesis period."""
    hop, half = rate // 200, rate // 50
    frames = []
    for center in range(half, len(samples) - half, hop):
        period = pitch_period(samples[center - half : center + half], rate)
        frames.append((center, period))
    # A brief unreliable frame inside a vowel must not split one voiced segment.
    # Bridge at most 15 ms between measured periods; never bridge into consonants.
    measured = frames.copy()
    for n, (center, period) in enumerate(measured):
        if period is not None:
            continue
        before = next(
            (j for j in range(n - 1, max(-1, n - 4), -1) if measured[j][1] is not None), None
        )
        after = next(
            (j for j in range(n + 1, min(len(frames), n + 4)) if measured[j][1] is not None), None
        )
        if before is not None and after is not None and after - before <= 4:
            left, right = measured[before][1], measured[after][1]
            frames[n] = (center, left + (right - left) * (n - before) / (after - before))
    runs: list[list[tuple[int, float]]] = []
    current: list[tuple[int, float]] = []
    for center, period in frames:
        if period is None:
            if current:
                runs.append(current)
                current = []
        else:
            current.append((center, period))
    if current:
        runs.append(current)
    output = samples.copy()
    processed = 0
    for run in runs:
        if len(run) * hop < rate * 0.06:
            continue
        start, end = run[0][0], run[-1][0]
        # Follow positive waveform peaks using the measured local fundamental.
        marks = [max(range(start, start + round(run[0][1])), key=samples.__getitem__)]
        while marks[-1] < end:
            frame_index = min(len(run) - 1, max(0, round((marks[-1] - start) / hop)))
            period = run[frame_index][1]
            predicted = marks[-1] + period
            radius = period * 0.22
            left = max(marks[-1] + 1, round(predicted - radius))
            right = min(len(samples), round(predicted + radius) + 1)
            marks.append(max(range(left, right), key=samples.__getitem__))
        mixed = [0.0] * len(samples)
        weights = [0.0] * len(samples)
        cursor = float(marks[0])
        while cursor <= marks[-1]:
            at = bisect.bisect_left(marks, cursor)
            nearest = min(
                range(max(0, at - 1), min(len(marks), at + 1)), key=lambda n: abs(marks[n] - cursor)
            )
            if steady_nucleus:
                # ce4 has a very short breathy vowel. Reuse its central grain to
                # avoid unrelated noise phases on consecutive synthesis pulses.
                nearest = len(marks) // 2
            origin = marks[nearest]
            neighbors = [
                marks[n + 1] - marks[n]
                for n in range(max(0, nearest - 1), min(len(marks) - 1, nearest + 1))
            ]
            radius = round(sum(neighbors) / len(neighbors))
            destination = round(cursor)
            for offset in range(-radius, radius + 1):
                src, dst = origin + offset, destination + offset
                if 0 <= src < len(samples) and 0 <= dst < len(samples):
                    weight = 0.5 + 0.5 * math.cos(math.pi * offset / radius)
                    mixed[dst] += samples[src] * weight
                    weights[dst] += weight
            cursor += rate / target
        fade = rate // 100
        for n in range(start, end):
            if weights[n] > 0.01:
                blend = min(1.0, (n - start) / fade, (end - n) / fade)
                output[n] = blend * mixed[n] / weights[n] + (1 - blend) * samples[n]
        processed += end - start
    if processed < rate * 0.08:
        raise ValueError("Not enough periodic speech to derive a first tone")
    return output, {"voicedSeconds": round(processed / rate, 4), "targetHz": target}


def prepare(assets: list[dict], workspace: Path) -> dict:
    sources = {a["id"]: a for a in assets}
    result = {}
    for asset_id, recipe in daily_pronunciation.policy()["derivedFirstTones"].items():
        source = sources[recipe["sourceId"]]
        if source["sha256"] != recipe["sourceSha256"] or recipe["method"] != "td-psola-v1":
            raise ValueError("First-tone source or method mismatch")
        source_path = source_audio.SOURCE_DIR / "clips" / f"{source['sha256']}.mp3"
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("First-tone source corrupt")
        decoded = workspace / "first-tone-source.wav"
        check_recording(source_path, decoded)
        with wave.open(str(decoded)) as audio:
            rate = audio.getframerate()
            samples = [
                v[0] / 32768 for v in struct.iter_unpack("<h", audio.readframes(audio.getnframes()))
            ]
        if rate != recipe["sampleRate"]:
            raise ValueError("First-tone sample rate mismatch")
        leveled, metrics = level_tone(
            samples, rate, recipe["targetHz"], steady_nucleus=recipe.get("steadyNucleus", False)
        )
        candidate = workspace / "first-tone.wav"
        with wave.open(str(candidate), "wb") as audio:
            audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            audio.writeframes(
                b"".join(struct.pack("<h", round(max(-1, min(0.9999, v)) * 32768)) for v in leveled)
            )
        raw = candidate.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        destination = source_audio.SOURCE_DIR / "clips" / f"{digest}.wav"
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(raw)
        temporary.replace(destination)
        result[asset_id] = {
            "sha256": digest,
            "bytes": len(raw),
            "sourceId": source["id"],
            "sourceSha256": source["sha256"],
            "recipeSha256": daily_pronunciation.signature(recipe),
            "method": recipe["method"],
            "seconds": len(samples) / rate,
            **metrics,
        }
    atomic_json(source_audio.SOURCE_DIR / "daily-first-tones.json", result)
    return result
