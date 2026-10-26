"""Fixed equal-probability readout ensemble sharing a single acoustic encoder."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import (
    arrays,
    calibrate,
    covered_targets,
    read_rows,
    write,
)
from pinyin_matcher.pretrained_heads import ComponentHeads


class ReadoutEnsemble(nn.Module):
    def __init__(self, members):
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, acoustic, pitch):
        outputs = [member(acoustic, pitch) for member in self.members]
        return tuple(
            torch.stack([output[i].softmax(-1) for output in outputs])
            .mean(0)
            .clamp_min(1e-12)
            .log()
            for i in range(3)
        )


def build(manifest, cache, members, output):
    if output.exists() or not 2 <= len(members) <= 4 or len(set(members)) != len(members):
        raise ValueError("ENSEMBLE_OUTPUT_OR_MEMBERS_INVALID")
    torch.set_num_threads(2)
    metadata = [json.loads((p / "model.json").read_text()) for p in members]
    first = metadata[0]
    keys = (
        "manifestSha256",
        "vocabulary",
        "dimensions",
        "acousticDerivative",
        "configuration",
        "cacheMetadataSha256",
    )
    if any(any(m[k] != first[k] for k in keys) for m in metadata):
        raise ValueError("ENSEMBLE_SOURCE_INCOMPATIBLE")
    if first["manifestSha256"] != fingerprint(manifest) or first[
        "cacheMetadataSha256"
    ] != fingerprint(cache / "cache.json"):
        raise ValueError("ENSEMBLE_SOURCE_DIGEST_MISMATCH")
    networks, norm = [], None
    for directory, m in zip(members, metadata, strict=True):
        if (
            m.get("representation", "pool5-v1") != "pool5-v1"
            or m.get("pitchOverride")
            or m["variant"]
            not in {"linear", "multihead", "independent", "mixup", "tone-specialist"}
        ):
            raise ValueError("ENSEMBLE_REPRESENTATION_UNSUPPORTED")
        if (
            fingerprint(directory / "heads.pt") != m["headSha256"]
            or fingerprint(directory / "normalization.npz") != m["normalizationSha256"]
        ):
            raise ValueError("ENSEMBLE_MEMBER_DIGEST_MISMATCH")
        with np.load(directory / "normalization.npz", allow_pickle=False) as data:
            current = {k: data[k].copy() for k in data.files}
        if norm is not None and (
            set(norm) != set(current) or any(not np.array_equal(norm[k], current[k]) for k in norm)
        ):
            raise ValueError("ENSEMBLE_NORMALIZATION_MISMATCH")
        norm = current
        network = ComponentHeads(
            m["dimensions"],
            [len(m["vocabulary"][k]) for k in ("onset", "rime", "tone")],
            variant="multihead" if m["variant"] == "mixup" else m["variant"],
            hidden=m["configuration"]["hiddenSize"],
            dropout=m["configuration"]["dropout"],
        )
        network.load_state_dict(
            torch.load(directory / "heads.pt", map_location="cpu", weights_only=True)
        )
        networks.append(network.eval())
    model = ReadoutEnsemble(networks).eval()
    all_rows = read_rows(manifest)
    rows = [r for r in all_rows if r["split"] == "calibration"]
    train_rows = [
        r
        for r in all_rows
        if r["split"] == "train"
        and not r.get("numericalQualityFlags")
        and not r.get("labelPolicyFlags")
        and not r.get("placeholder")
    ]
    targets = covered_targets(first["vocabulary"], train_rows)
    acoustic, pitch, labels = arrays(rows, cache, first["vocabulary"])
    acoustic = (acoustic - norm["mean"]) / norm["scale"]
    pitch = (pitch - norm["pitch_mean"]) / norm["pitch_scale"]
    with torch.inference_mode():
        probabilities = [
            v.softmax(-1).numpy()
            for v in model(torch.from_numpy(acoustic), torch.from_numpy(pitch))
        ]
    calibration = calibrate(list(zip(*probabilities, strict=True)), labels, rows=rows)
    output.mkdir(parents=True)
    torch.save(model.state_dict(), output / "heads.pt")
    torch.onnx.export(
        model,
        (torch.zeros(1, first["dimensions"]), torch.zeros(1, 68)),
        str(output / "heads.onnx"),
        input_names=["acoustic", "pitch"],
        output_names=["initial", "final", "tone"],
        dynamic_axes={k: {0: "batch"} for k in ("acoustic", "pitch", "initial", "final", "tone")},
        opset_version=17,
        dynamo=False,
    )
    np.savez(output / "normalization.npz", **norm)
    result = {
        **first,
        "variant": "equal-probability-ensemble",
        "coveredTargets": targets,
        "selectedEpoch": None,
        "selectedComponentEpochs": None,
        "checkpointSelection": "fixed-members-no-additional-gradient",
        "regularizationConfigSha256": None,
        "members": [{"path": str(p), "sha256": fingerprint(p / "model.json")} for p in members],
        "thresholds": calibration["selected"]["threshold"],
        "trainingSeconds": 0,
        "headSha256": fingerprint(output / "heads.pt"),
        "headOnnxSha256": fingerprint(output / "heads.onnx"),
        "normalizationSha256": fingerprint(output / "normalization.npz"),
        "headCodeSha256": fingerprint(Path(__file__)),
        "testUsed": False,
        "experimental": True,
        "toneAssessed": False,
    }
    write(output / "model.json", result)
    write(output / "calibration.json", calibration)
    return calibration["selected"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("manifest", "cache", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--member", type=Path, action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.cache, args.member, args.output)))


if __name__ == "__main__":
    main()
