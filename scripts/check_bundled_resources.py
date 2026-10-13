"""Validate bundled non-private audio before one-command startup."""

import struct
import wave

from server import learning_audio


def check():
    available = learning_audio.available_assets()
    missing = [key for key, ready in available.items() if not ready]
    if missing:
        raise ValueError(f"Bundled audio missing/corrupt: {missing}")
    files = {}
    for asset in learning_audio.read_manifest().values():
        if asset.get("purpose") == "chinese-instruction":
            files[asset["file"]] = asset
    for asset in files.values():
        expected = learning_audio.expected_assets()[asset["id"]]
        path, _, _ = learning_audio.registered_file(asset, expected)
        with wave.open(str(path)) as pcm:
            if pcm.getnchannels() != 1 or pcm.getsampwidth() != 2 or pcm.getnframes() < 100:
                raise ValueError(f"Invalid bundled PCM: {asset['id']}")
            samples = struct.iter_unpack("<h", pcm.readframes(pcm.getnframes()))
            if max(abs(value[0]) for value in samples) < 328:
                raise ValueError(f"Silent bundled narration: {asset['id']}")
    return {"ready": len(available), "directory": str(learning_audio.LEARNING_AUDIO_DIR)}


if __name__ == "__main__":
    print(check())
