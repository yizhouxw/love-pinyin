"""Export and calibrate the head jointly optimized with the Chinese encoder tail."""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import torch

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import arrays, calibrate, read_rows, write
from pinyin_matcher.pretrained_factorized import FactorizedHeads
from pinyin_matcher.pretrained_prepare import verify


def prepare(manifest, cache, initializer, checkpoint, encoder, output):
    if output.exists():
        raise ValueError("CHINESE_JOINT_HEAD_OUTPUT_EXISTS")
    base = json.loads((initializer / "model.json").read_text())
    training = json.loads((checkpoint / "training.json").read_text())
    cache_meta = json.loads((cache / "cache.json").read_text())
    source = verify("chinese-xlsr-tail-v1", encoder)
    if (
        base["model"] != "chinese-xlsr-asr"
        or base["testUsed"] is not False
        or training["finalTestUsed"] is not False
        or training["manifestSha256"] != fingerprint(manifest)
        or training["initializerSha256"] != fingerprint(initializer / "model.json")
        or training["headSha256"] != fingerprint(checkpoint / "heads.pt")
        or source["trainingReportSha256"] != fingerprint(checkpoint / "training.json")
        or cache_meta["model"] != "chinese-xlsr-tail-v1"
        or cache_meta["manifestSha256"] != fingerprint(manifest)
    ):
        raise ValueError("CHINESE_JOINT_HEAD_INPUT_MISMATCH")
    rows = [r for r in read_rows(manifest) if r["split"] == "calibration"]
    vocab = base["vocabulary"]
    x, pitch, labels = arrays(rows, cache, vocab)
    with np.load(initializer / "normalization.npz", allow_pickle=False) as norm:
        x = (x - norm["mean"]) / norm["scale"]
        pitch = (pitch - norm["pitch_mean"]) / norm["pitch_scale"]
    model = FactorizedHeads(
        base["dimensions"],
        [len(vocab[k]) for k in ("onset", "rime", "tone")],
        hidden=base["configuration"]["hiddenSize"],
        dropout=base["configuration"]["dropout"],
    )
    torch.set_num_threads(2)
    model.load_state_dict(
        torch.load(checkpoint / "heads.pt", map_location="cpu", weights_only=True)
    )
    model.eval()
    with torch.inference_mode():
        outputs = [
            x.softmax(-1).numpy() for x in model(torch.from_numpy(x), torch.from_numpy(pitch))
        ]
    calibration = calibrate(list(zip(*outputs, strict=True)), labels, rows=rows)
    output.mkdir(parents=True)
    shutil.copy2(initializer / "normalization.npz", output / "normalization.npz")
    shutil.copy2(checkpoint / "heads.pt", output / "heads.pt")
    with torch.inference_mode():
        torch.onnx.export(
            model,
            (torch.zeros(1, base["dimensions"]), torch.zeros(1, 68)),
            str(output / "heads.onnx"),
            input_names=["acoustic", "pitch"],
            output_names=["initial", "final", "tone"],
            dynamic_axes={
                k: {0: "batch"} for k in ("acoustic", "pitch", "initial", "final", "tone")
            },
            opset_version=17,
            dynamo=False,
        )
    metadata = dict(base)
    metadata.update(
        model="chinese-xlsr-tail-v1",
        variant="factorized-joint-tail",
        selectedEpoch=training["selectedEpoch"],
        checkpointSelection="joint-tail-calibration-loss",
        manifestSha256=fingerprint(manifest),
        cacheMetadataSha256=fingerprint(cache / "cache.json"),
        headSha256=fingerprint(output / "heads.pt"),
        headOnnxSha256=fingerprint(output / "heads.onnx"),
        headCodeSha256=fingerprint(Path(__file__)),
        normalizationSha256=fingerprint(output / "normalization.npz"),
        thresholds=calibration["selected"]["threshold"],
        jointTrainingReportSha256=fingerprint(checkpoint / "training.json"),
        trainingSeconds=training["elapsedSeconds"],
    )
    write(output / "model.json", metadata)
    write(output / "calibration.json", calibration)
    return {
        "model": metadata["model"],
        "variant": metadata["variant"],
        "thresholds": metadata["thresholds"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cache", "initializer", "checkpoint", "encoder", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    print(json.dumps(prepare(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
