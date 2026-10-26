"""Fixed SenseVoice intermediate-layer probes; train/calibration only."""

import argparse
import json
import math
import time
from pathlib import Path

import torch
from torch.nn import functional as F

from pinyin_matcher.audio import decode_wav, trim_silence
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import (
    cache_identity,
    read_cached,
    read_rows,
    save_cached,
    write,
)
from pinyin_matcher.pretrained_features import configuration, pitch_vector, pool_frames
from pinyin_matcher.pretrained_sensevoice import SenseVoiceFeatures

LAYERS = (20, 35, 50)


def intermediate_frames(model, waves):
    features = [model.frontend(wave) for wave in waves]
    lengths = torch.tensor([len(f) + 4 for f in features], device=model.device)
    padded = torch.zeros(len(features), int(lengths.max()), 560, device=model.device)
    with torch.inference_mode():
        prompt = model.embed(torch.tensor([3, 1, 2, 15], device=model.device))
        for index, feature in enumerate(features):
            padded[index, :4] = prompt
            padded[index, 4 : len(feature) + 4] = feature.to(model.device)
        positions = torch.arange(1, padded.shape[1] + 1, device=model.device, dtype=padded.dtype)
        scales = torch.exp(
            torch.arange(280, device=model.device, dtype=padded.dtype) * (-math.log(10000) / 279)
        )
        phase = positions[:, None] * scales[None]
        x = padded * math.sqrt(512) + torch.cat((phase.sin(), phase.cos()), dim=-1)[None]
        mask = (torch.arange(x.shape[1], device=model.device)[None] < lengths[:, None])[:, None]
        result = {}
        for depth, layer in enumerate([*model.encoder.encoders0, *model.encoder.encoders], 1):
            x = layer(x, mask)
            if depth in LAYERS:
                normalized = model.encoder.after_norm(x) if depth == 50 else F.layer_norm(x, (512,))
                result[depth] = [
                    normalized[i, 4 : len(f) + 4].cpu().numpy() for i, f in enumerate(features)
                ]
        return result


def prepare(manifest, model_path, output, device="mps", batch_size=16):
    rows = read_rows(manifest)
    selected = [r for r in rows if r["split"] in {"train", "calibration"}]
    identity = cache_identity("sensevoice", model_path)
    identity["intermediateProbe"] = {
        "depths": list(LAYERS),
        "normalization": "parameter-free-layernorm-20-35;pretrained-after_norm-50",
        "codeSha256": fingerprint(Path(__file__)),
    }
    identity_shas = {}
    for depth in LAYERS:
        directory = output / str(depth)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "identity.json"
        value = {**identity, "selectedDepth": depth}
        if path.exists() and json.loads(path.read_text()) != value:
            raise ValueError("PROBE_CACHE_IDENTITY_CHANGED")
        write(path, value)
        identity_shas[depth] = fingerprint(path)
    model = SenseVoiceFeatures(model_path, device=device)
    started = time.perf_counter()
    for start in range(0, len(selected), batch_size):
        pending, waves = [], []
        for row in selected[start : start + batch_size]:
            if (
                row.get("numericalQualityFlags")
                or row.get("labelPolicyFlags")
                or row.get("placeholder")
            ):
                continue
            complete = True
            for depth in LAYERS:
                path = output / str(depth) / (row["sha256"] + ".npz")
                if path.exists():
                    with read_cached(path, identity_shas[depth]):
                        pass
                else:
                    complete = False
            if complete:
                continue
            pending.append(row)
            waves.append(trim_silence(decode_wav(Path(row["file"]).read_bytes())))
        if waves:
            encoded = intermediate_frames(model, waves)
            for index, (row, wave) in enumerate(zip(pending, waves, strict=True)):
                pitch = pitch_vector(wave)
                for depth in LAYERS:
                    frames = encoded[depth][index]
                    save_cached(
                        output / str(depth) / (row["sha256"] + ".npz"),
                        {"pooled": pool_frames(frames), "pitch": pitch, "frames": frames},
                        identity_shas[depth],
                    )
        if start % (batch_size * 10) == 0:
            print(
                json.dumps(
                    {
                        "rows": start + len(pending),
                        "total": len(selected),
                        "seconds": time.perf_counter() - started,
                    }
                ),
                flush=True,
            )
    for depth in LAYERS:
        write(
            output / str(depth) / "cache.json",
            {
                "model": "sensevoice",
                "selectedDepth": depth,
                "cacheIdentitySha256": identity_shas[depth],
                "manifestSha256": fingerprint(manifest),
                "configuration": configuration(),
                "rows": len(selected),
                "testIncluded": False,
                "device": device,
                "elapsedSeconds": time.perf_counter() - started,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("manifest", "model", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    args = parser.parse_args()
    prepare(args.manifest, args.model, args.output, args.device)


if __name__ == "__main__":
    main()
