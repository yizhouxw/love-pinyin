"""Generate the iOS course MP3s from original lesson scripts with local Qwen."""

import hashlib
import io
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from scripts.build_open_voice import CONFIG, create_engine
from server.content import load_curriculum
from server.learning_audio import text_digest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "content/ios-lesson-narration.json"
OUTPUT = ROOT / "resources/audio/ios-lessons"


def load_locked_voice():
    config = json.loads(CONFIG.read_text())
    model = (ROOT / "models/qwen3-tts" / config["directory"]).resolve()
    for name, digest in config["files"].items():
        path = (model / name).resolve(strict=True)
        with path.open("rb") as handle:
            if (
                model not in path.parents
                or hashlib.file_digest(handle, "sha256").hexdigest() != digest
            ):
                raise ValueError(f"TTS model digest mismatch: {name}")

    return config, create_engine(model, config)


def main() -> None:
    config, synthesize = load_locked_voice()
    scripts = json.loads(SCRIPTS.read_text())["lessons"]
    if set(scripts) != {lesson["id"] for lesson in load_curriculum()["lessons"]}:
        raise ValueError("Expected one original script for each current lesson")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = {}
    for lesson_id, sections in scripts.items():
        speech = []
        for section in sections:
            samples, rate = synthesize(section)
            if rate != 24000 or len(samples) < rate or not np.isfinite(samples).all():
                raise ValueError(f"Invalid speech for {lesson_id}")
            speech.extend((samples, np.zeros(rate // 2)))
        pcm = (np.clip(np.concatenate(speech), -1, 1) * 32767).astype("<i2")
        wav = io.BytesIO()
        with wave.open(wav, "wb") as handle:
            handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            handle.writeframes(pcm.tobytes())
        mp3 = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "wav",
                "-i",
                "pipe:0",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "64k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav.getvalue(),
            capture_output=True,
            check=True,
        ).stdout
        filename = f"{lesson_id}.mp3"
        (OUTPUT / filename).write_bytes(mp3)
        rows[lesson_id] = {
            "file": filename,
            "sha256": hashlib.sha256(mp3).hexdigest(),
            "textSha256": text_digest("\n".join(sections)),
            "seconds": round(len(pcm) / rate, 3),
        }
        print(f"{lesson_id}: {rows[lesson_id]['seconds']} seconds", flush=True)
    manifest = {
        "version": 1,
        "sourceType": "local-open-tts",
        "model": config["model"],
        "modelRevision": config["revision"],
        "speaker": config["speaker"],
        "license": config["license"],
        "lessons": rows,
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
