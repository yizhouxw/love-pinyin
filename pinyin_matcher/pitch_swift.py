"""Bounded local SwiftF0 0.3.0 ONNX pitch, separate from syllable recognition.

The upstream model and the small silence-gate adaptation use the MIT license:
Copyright (c) 2025-2026 Lars Nieradzik, https://github.com/lars76/swift-f0.
Installation copies the matching LICENSE beside the explicitly supplied model.
No SwiftF0 package, network, Torch, ASR or TTS is loaded by this runtime adapter.
"""

from pathlib import Path

import numpy as np
import onnxruntime as ort

from pinyin_matcher.audio import (
    MAX_SECONDS,
    SAMPLE_RATE,
    AudioRejected,
    quality_check,
    trim_silence,
)
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pitch_v2 import PitchTrack

PITCH_FEATURE_VERSION = "relative-swift-f0-0.3.0-contour32-v1"
COMPONENT_PITCH_FEATURE_VERSION = "relative-swift-f0-0.3.0-components32-v2"
SUPPORTED_FEATURE_VERSIONS = frozenset({PITCH_FEATURE_VERSION, COMPONENT_PITCH_FEATURE_VERSION})
MODEL_SHA256 = "6385e8c2ebc3872e82c9ff5946228de44cd3be77a750ea53698b7dbfe94b0a22"
HOP_LENGTH = 256


def component_support(pitch: PitchTrack) -> tuple[np.ndarray, dict]:
    """Remove only brief, weak and disconnected voiced islands; never use F0 labels."""
    good = np.flatnonzero(pitch.voiced)
    if not len(good):
        return good, {"voicedComponents": 0, "removedVoicedFrames": 0}
    # Six genuinely unvoiced hops separate components. Short creaky gaps stay connected.
    components = np.split(good, np.flatnonzero(np.diff(good) > 6) + 1)
    energy = [float(np.sum(pitch.rms[index] ** 2)) for index in components]
    principal = int(np.argmax(energy))
    reference_rms = max(float(np.median(pitch.rms[components[principal]])), 1e-9)
    retained, removed = [], []
    for index, frames in enumerate(components):
        discard = (
            index != principal
            and len(frames) <= 6
            and float(np.median(pitch.confidence[frames])) < 0.8
            and float(np.median(pitch.rms[frames])) < reference_rms * 0.15
        )
        (removed if discard else retained).append(frames)
    return np.concatenate(retained), {
        "voicedComponents": len(components),
        "retainedVoicedComponents": len(retained),
        "removedVoicedFrames": sum(len(index) for index in removed),
        "rawVoicedFrames": len(good),
    }


def install_from_fixed_tool_package(destination: Path) -> dict:
    """Explicit offline setup only; never called by the matcher constructor."""
    import importlib.metadata
    import importlib.util
    import json
    import shutil

    if importlib.metadata.version("swift-f0") != "0.3.0":
        raise ValueError("FIXED_SWIFT_TOOL_VERSION_REQUIRED")
    source = Path(importlib.util.find_spec("swift_f0").origin).parent
    if fingerprint(source / "model.onnx") != MODEL_SHA256:
        raise ValueError("PITCH_TRACKER_MODEL_DIGEST_MISMATCH")
    license_file = source.parent / "swift_f0-0.3.0.dist-info/licenses/LICENSE"
    if not license_file.is_file():
        raise ValueError("UPSTREAM_SWIFT_LICENSE_REQUIRED")
    destination.mkdir(parents=True, exist_ok=True)
    model_file = destination / "model.onnx"
    if model_file.exists() and fingerprint(model_file) != MODEL_SHA256:
        raise ValueError("REFUSE_TO_OVERWRITE_DIFFERENT_PITCH_MODEL")
    shutil.copyfile(source / "model.onnx", model_file)
    shutil.copyfile(license_file, destination / "LICENSE")
    record = {
        "package": "swift-f0",
        "version": "0.3.0",
        "license": "MIT",
        "source": "https://github.com/lars76/swift-f0",
        "wheelSha256": "d7240c7c94b1d3e8f0e0cd2701b79be89a0f23a19cd5f944895a6518ecad72f3",
        "modelFile": model_file.name,
        "modelSha256": MODEL_SHA256,
        "bytes": model_file.stat().st_size,
        "providers": ["CPUExecutionProvider"],
        "runtimeDownload": False,
        "installation": "Explicit offline-tool copy; runtime requires this local file",
    }
    (destination / "installation.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


class SwiftPitch:
    """Explicit CPU tracker; a model/digest mismatch fails instead of falling back."""

    def __init__(
        self,
        model: Path,
        expected_sha256: str = MODEL_SHA256,
        *,
        feature_version: str = PITCH_FEATURE_VERSION,
    ):
        if feature_version not in SUPPORTED_FEATURE_VERSIONS:
            raise ValueError("PITCH_FEATURE_VERSION_UNSUPPORTED")
        self.feature_version = feature_version
        if (
            expected_sha256 != MODEL_SHA256
            or not model.is_file()
            or model.stat().st_size > 256 * 1024
            or fingerprint(model) != expected_sha256
        ):
            raise ValueError("PITCH_TRACKER_MODEL_DIGEST_MISMATCH")
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError("CPU_PITCH_TRACKER_REQUIRED")

    def track(self, samples: np.ndarray, *, check: bool = True, run_options=None) -> PitchTrack:
        samples = np.asarray(samples, dtype=np.float32)
        if (
            samples.ndim != 1
            or not 2400 <= len(samples) <= SAMPLE_RATE * MAX_SECONDS
            or not np.isfinite(samples).all()
        ):
            raise AudioRejected("AUDIO_INVALID")
        if check:
            quality_check(samples)
        samples = trim_silence(samples)
        samples = samples / max(float(np.sqrt(np.mean(samples * samples))), 0.01) * 0.1
        f0, confidence = self.session.run(
            ["pitch", "confidence"],
            {
                "audio": samples[None],
                "fmin": np.asarray(46.875, dtype=np.float32),
                "fmax": np.asarray(1000, dtype=np.float32),
            },
            run_options=run_options,
        )
        f0, confidence = f0[0], confidence[0]
        expected_frames = max(1, len(samples) // HOP_LENGTH)
        if (
            f0.shape != (expected_frames,)
            or confidence.shape != f0.shape
            or not np.isfinite(f0).all()
            or not np.isfinite(confidence).all()
            or np.any((confidence < 0) | (confidence > 1))
        ):
            raise ValueError("PITCH_TRACKER_OUTPUT_INVALID")
        hops = samples[: expected_frames * HOP_LENGTH].reshape(expected_frames, HOP_LENGTH)
        confidence = confidence.copy()
        confidence[np.abs(hops).max(axis=1) < 0.001] = 0
        rms = np.sqrt(np.mean(hops * hops, axis=1))
        voiced = (confidence >= 0.5) & (f0 >= 46.875) & (f0 <= 1000)
        return PitchTrack(
            np.where(voiced, f0, 0).astype(np.float32),
            confidence.astype(np.float32),
            voiced,
            rms,
            np.arange(expected_frames, dtype=np.float32) * HOP_LENGTH / SAMPLE_RATE,
        )

    def contour(
        self, samples: np.ndarray, *, check: bool = True, run_options=None
    ) -> tuple[np.ndarray, dict]:
        pitch = self.track(samples, check=check, run_options=run_options)
        if self.feature_version == COMPONENT_PITCH_FEATURE_VERSION:
            good, components = component_support(pitch)
        else:
            good, components = np.flatnonzero(pitch.voiced), {}
        if len(good) < 6:
            raise AudioRejected("NO_RELIABLE_VOICED_SPEECH")
        positions = np.linspace(good[0], good[-1], 32)
        log_f0 = np.log2(pitch.f0[good])
        # Preserve the changing low-pitch tail and creaky intervals. A wider
        # median filter can erase the short third-tone trough we need to retain.
        relative = np.interp(positions, good, log_f0) - np.median(log_f0)
        relative = np.clip(relative, -2, 2)
        confidence = np.interp(positions, np.arange(len(pitch.f0)), pitch.confidence)
        mask = pitch.voiced.astype(np.float32)
        if components:
            mask[:] = 0
            mask[good] = 1
        voiced = np.interp(positions, np.arange(len(pitch.f0)), mask)
        array = np.stack([relative, np.gradient(relative), confidence, voiced], axis=1).astype(
            np.float32
        )
        summary = pitch.summary()
        if components:
            summary.update(
                components,
                voicedFrames=len(good),
                medianF0=float(np.median(pitch.f0[good])),
                pitchRangeOctaves=float(np.ptp(log_f0)),
                medianPeriodicity=float(np.median(pitch.confidence[good])),
            )
        return array, summary


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Explicit offline SwiftF0 tracker installation")
    parser.add_argument("--install-from-tool-package", type=Path, required=True)
    print(
        json.dumps(install_from_fixed_tool_package(parser.parse_args().install_from_tool_package))
    )
