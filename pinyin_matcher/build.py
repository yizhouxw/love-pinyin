"""Full offline build. Test is opened only after both branches and calibration freeze."""

import argparse
from pathlib import Path

from pinyin_matcher.pitch import attach
from pinyin_matcher.pitch import train as train_pitch
from pinyin_matcher.pitch_standard import prepare as prepare_anchors
from pinyin_matcher.train import calibrate, evaluate, prepare, train


def build(manifest: Path, output: Path, cache: Path, device="auto", epochs=None):
    train(
        manifest, output, device=device, epochs=epochs, cache_directory=cache, evaluate_test=False
    )
    anchors = output / "tone-anchors"
    prepare_anchors(anchors)
    pitch = output / "pitch-training"
    train_pitch(manifest, cache, pitch, anchors / "manifest.json")
    attach(output, pitch)
    rows, arrays = prepare(manifest, cache)
    calibrate(manifest, output, rows, arrays)
    return evaluate(manifest, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    parser.add_argument("--epochs", type=int)
    args = parser.parse_args()
    build(args.manifest, args.output, args.cache_dir, args.device, args.epochs)
