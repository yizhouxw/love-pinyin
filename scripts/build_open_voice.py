"""Offline, reproducible generation of redistributable Chinese narration (not pinyin)."""

import argparse
import hashlib
import json
import os
import shutil
import wave
from pathlib import Path

import numpy as np

from server import learning_audio

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "content" / "voice-build.json"


def generate(
    output: Path, model_dir: Path, limit: int | None = None, shard: int = 0, shards: int = 1
) -> dict:
    import sherpa_onnx

    if shards < 1 or not 0 <= shard < shards:
        raise ValueError("Invalid generation shard")

    config = json.loads(CONFIG.read_text())
    model = model_dir / config["directory"]
    for name, digest in config["files"].items():
        path = (model / name).resolve(strict=True)
        if (
            model.resolve() not in path.parents
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError(f"TTS model digest mismatch: {name}")
    tts = sherpa_onnx.OfflineTts(
        sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(model / config["modelFile"]),
                    voices=str(model / "voices.bin"),
                    tokens=str(model / "tokens.txt"),
                    data_dir=str(model / "espeak-ng-data"),
                    lexicon=",".join(str(model / name) for name in config["lexicons"]),
                ),
                num_threads=config["threads"],
                provider="cpu",
            ),
            rule_fsts=",".join(str(model / name) for name in config["ruleFiles"]),
        )
    )
    scripts = learning_audio.narration_scripts()
    expected = learning_audio.expected_assets()
    output.mkdir(parents=True, exist_ok=True)
    (output / "narration").mkdir(exist_ok=True)
    assets = []
    seen = {}
    generated = 0
    for asset_id, text in scripts.items():
        key = learning_audio.text_digest(
            json.dumps({"config": config, "text": text}, sort_keys=True, ensure_ascii=False)
        )
        if int(key, 16) % shards != shard:
            continue
        relative = f"narration/{key}.wav"
        path = output / relative
        if text not in seen:
            if not path.exists():
                audio = tts.generate(text, sid=config["speaker"], speed=config["speed"])
                samples = np.asarray(audio.samples)
                if (
                    len(samples) < 100
                    or not np.isfinite(samples).all()
                    or np.max(np.abs(samples)) < 0.01
                ):
                    raise ValueError(f"Empty/invalid synthesized speech: {asset_id}")
                temporary = path.with_suffix(".tmp")
                with wave.open(str(temporary), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(audio.sample_rate)
                    handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
                os.replace(temporary, path)
                generated += 1
                print(f"Generated {generated}: {asset_id}", flush=True)
            with wave.open(str(path)) as handle:
                seconds = handle.getnframes() / handle.getframerate()
                sample_rate = handle.getframerate()
            seen[text] = {
                **expected[asset_id],
                "sourceType": "local-open-tts",
                "file": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "durationSeconds": round(seconds, 3),
                "voice": config["model"],
                "sampleRate": sample_rate,
                "speed": config["speed"],
                "engineVersion": config["engineVersion"],
                "modelSha256": config["archiveSha256"],
                "distribution": "redistributable-model-generated",
                "license": config["license"],
            }
        assets.append({**seen[text], "id": asset_id})
        if limit is not None and len(seen) >= limit:
            return {"generated": generated, "sample": str(path)}
    if shards > 1:
        return {"generated": generated, "shard": shard, "shards": shards}
    # Copy only the requested, non-child course recordings; never copy private trees.
    (output / "lessons").mkdir(exist_ok=True)
    for lesson_id, item in learning_audio.lesson_recordings().items():
        source = ROOT / "resources" / "audio" / "lessons" / item["file"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        relative = f"lessons/{item['file']}"
        if source.resolve() != (output / relative).resolve():
            shutil.copyfile(source, output / relative)
        assets.append(
            {
                "id": f"lesson-{lesson_id}",
                **expected[f"lesson-{lesson_id}"],
                "file": relative,
                "sha256": digest,
                "distribution": "user-provided-non-mit",
            }
        )
    temporary = output / "manifest.tmp"
    temporary.write_text(
        json.dumps({"version": 1, "assets": assets}, ensure_ascii=False, indent=2) + "\n"
    )
    os.replace(temporary, output / "manifest.json")
    return {
        "generated": generated,
        "narrationIds": len(scripts),
        "uniqueNarration": len(seen),
        "assets": len(assets),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models" / "kokoro")
    parser.add_argument("--output", type=Path, default=ROOT / "resources" / "audio")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    print(
        json.dumps(
            generate(args.output, args.model_dir, args.limit, args.shard, args.shards),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
