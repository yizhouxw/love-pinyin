"""Reproduce the exact common four-second benchmark bytes without inference."""

import argparse
import hashlib
import importlib.util
import io
import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "content/pronunciation-pretrained-cpu-pressure.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source: Path, archived_audio: Path | None, output: Path, *, config_path=CONFIG):
    config = json.loads(config_path.read_text())
    if output.exists() or output.with_suffix(".wav.json").exists():
        raise ValueError("PRESSURE_OUTPUT_ALREADY_EXISTS")
    if digest(source) != config["sourceSha256"]:
        raise ValueError("PRESSURE_SOURCE_CHANGED")
    if config.get("mode") == "pcm-frame-window":
        with wave.open(str(source), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
                raise ValueError("PRESSURE_SOURCE_PCM_FORMAT_CHANGED")
            start, end = config["sourcePcmFrameRange"]
            if end - start != 64000 or start < 0 or end > audio.getnframes():
                raise ValueError("PRESSURE_PCM_WINDOW_INVALID")
            audio.setpos(start)
            pcm = audio.readframes(end - start)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setparams((1, 2, 16000, 64000, "NONE", "not compressed"))
            audio.writeframes(pcm)
        payload = buffer.getvalue()
    else:
        if archived_audio is None or digest(archived_audio) != config["archivedAudioCodeSha256"]:
            raise ValueError("PRESSURE_ARCHIVED_AUDIO_CODE_CHANGED")
        spec = importlib.util.spec_from_file_location("preserved_pressure_audio", archived_audio)
        if spec is None or spec.loader is None:
            raise ValueError("PRESSURE_ARCHIVED_AUDIO_UNAVAILABLE")
        audio = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audio)
        payload = audio.encode_wav(
            np.resize(audio.decode_wav(source.read_bytes()), config["samples"])
        )
    if hashlib.sha256(payload).hexdigest() != config["payloadSha256"]:
        raise ValueError("PRESSURE_PAYLOAD_DIFFERS_FROM_BASELINE")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as target:
        target.write(payload)
    report = {
        **config,
        "output": str(output.resolve()),
        "bytes": len(payload),
        "configurationSha256": digest(config_path),
        "preparationCodeSha256": digest(Path(__file__)),
        "numpyVersion": np.__version__,
        "modelExecuted": False,
        "timingPerformed": False,
        "qualityEvidence": False,
    }
    output.with_suffix(".wav.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archived-audio-code", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(args.source, args.archived_audio_code, args.output, config_path=args.config)
        )
    )


if __name__ == "__main__":
    main()
