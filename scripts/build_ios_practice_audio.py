"""Generate audio for original iOS practice, reusing only exact approved TTS inputs."""

import hashlib
import json
import wave

import numpy as np

from scripts.build_ios_lesson_audio import load_locked_voice
from server import learning_audio, source_audio
from server.materials import GENERATED, original_packs, reusable_voice


def main() -> None:
    _, _, scripts = original_packs({row["id"] for row in source_audio.catalog()["assets"]})
    reuse = reusable_voice()
    GENERATED.mkdir(parents=True, exist_ok=True)
    synthesize = load_locked_voice()[1]
    manifest = {}
    for asset_id, text in scripts.items():
        text_sha = learning_audio.text_digest(text)
        if text_sha in reuse:
            continue
        path = GENERATED / f"{asset_id}.wav"
        if not path.is_file():
            samples, rate = synthesize(text)
            if rate != 24000 or len(samples) < rate // 6 or not np.isfinite(samples).all():
                raise ValueError(f"Invalid speech for {asset_id}")
            with wave.open(str(path), "wb") as handle:
                handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        manifest[asset_id] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "textSha256": text_sha,
        }
        print(f"{len(manifest)}: {asset_id}", flush=True)
    (GENERATED / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
