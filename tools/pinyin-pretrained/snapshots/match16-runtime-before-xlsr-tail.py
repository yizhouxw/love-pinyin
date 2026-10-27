"""Local two-thread CPU inference for exported pretrained component matchers.

Only acoustic encoder frames, dedicated component heads and pitch evidence are
used. No text decoder, network, target-conditioned alignment or audio writing.
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
from pathlib import Path

import numpy as np
from scipy.special import softmax

from pinyin_matcher.audio import AudioRejected, decode_wav, quality_check
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_features import configuration, represent

COMPONENTS = ("onset", "rime", "tone")


def signal_guard(samples: np.ndarray) -> str | None:
    """Conservative numerical guards, never pronunciation or accuracy scores."""
    if len(samples) > configuration()["features"]["maximumSpeechSeconds"] * 16000:
        return "AUDIO_OVER_FOUR_SECONDS"
    try:
        quality_check(samples)
    except AudioRejected as error:
        return str(error)
    padded = np.pad(samples, (0, max(0, 400 - len(samples))))
    windows = np.lib.stride_tricks.sliding_window_view(padded, 400)[::160]
    energy = np.mean(windows * windows, axis=1)
    # Spectrally flat broadband input lacks the vowel evidence needed for a
    # complete Mandarin syllable. Fricatives alone are intentionally insufficient.
    relevant = energy > max(float(energy.max()) * 0.1, 1e-7)
    power = np.abs(np.fft.rfft(windows * np.hanning(400), 512)) ** 2 + 1e-12
    flatness = np.exp(np.log(power).mean(axis=1)) / power.mean(axis=1)
    if relevant.any() and float(np.median(flatness[relevant])) > 0.35:
        return "NONSPEECH_BROADBAND_INPUT"
    threshold = max(float(energy.max()) * 0.015, 1e-6)
    active = np.flatnonzero(energy > threshold)
    if not len(active):
        return "NO_SPEECH_ENERGY"
    # The single-syllable contract cannot assess two separated utterances.
    groups = np.split(active, np.flatnonzero(np.diff(active) > 18) + 1)
    substantial = [g for g in groups if len(g) >= 6]
    if len(substantial) > 1:
        return "MULTIPLE_SEPARATED_SPEECH_REGIONS"
    return None


def component_decision(probabilities, expected, thresholds) -> str:
    if len(probabilities) != 3:
        raise ValueError("HEAD_OUTPUT_COUNT_INVALID")
    best, scores, margins = [], [], []
    for values in probabilities:
        values = np.asarray(values)
        if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
            raise ValueError("HEAD_OUTPUT_INVALID")
        choice = int(values.argmax())
        ordered = np.sort(values)
        best.append(choice)
        scores.append(float(values[choice]))
        margins.append(float(ordered[-1] - ordered[-2]) if len(ordered) > 1 else 1.0)
    if min(scores) < thresholds["probability"] or min(margins) < thresholds["margin"]:
        return "uncertain"
    return "matched" if best == list(expected) else "retry"


class PretrainedMatcher:
    """Instantiate once; `match(target_id, wav_bytes)` never stores the recording."""

    def __init__(self, package: Path | str):
        self.directory = Path(package)
        self.lock = threading.Lock()
        self.metadata = {}
        self.encoder = None
        self.session = None
        self.problem = "MODEL_UNAVAILABLE"
        self.targets = {}
        try:
            path = self.directory / "model.json"
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("MODEL_METADATA_TOO_LARGE")
            metadata = json.loads(path.read_text())
            for relative, record in metadata.get("packageFiles", {}).items():
                resource = (self.directory / relative).resolve()
                if (
                    not resource.is_relative_to(self.directory.resolve())
                    or fingerprint(resource) != record["sha256"]
                ):
                    raise ValueError("BUNDLE_RESOURCE_DIGEST_MISMATCH")
            if metadata["schemaVersion"] != 1 or metadata["model"] not in {
                "hanziflow",
                "charsiu",
                "sensevoice",
                "tencent-zh-base",
                "tencent-zh-tail-v1",
                "tencent-zh-raw",
                "chinese-xlsr-asr",
            }:
                raise ValueError("MODEL_METADATA_INVALID")
            if metadata["configuration"] != configuration():
                raise ValueError("FEATURE_CONFIGURATION_MISMATCH")
            representation = metadata.get("representation", "pool5-v1")
            if representation not in {"pool5-v1", "temporal16-v1"}:
                raise ValueError("UNKNOWN_REPRESENTATION")
            if representation == "temporal16-v1" and metadata.get(
                "representationCodeSha256"
            ) != fingerprint(Path(__file__).with_name("pretrained_temporal.py")):
                raise ValueError("TEMPORAL_REPRESENTATION_CODE_MISMATCH")
            thresholds = metadata["thresholds"]
            if set(thresholds) != {"probability", "margin"} or any(
                type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
                for value in thresholds.values()
            ):
                raise ValueError("MODEL_THRESHOLDS_INVALID")
            vocabulary = metadata["vocabulary"]
            if set(vocabulary) != set(COMPONENTS):
                raise ValueError("MODEL_VOCABULARY_INVALID")
            for values in vocabulary.values():
                if (
                    not isinstance(values, list)
                    or not values
                    or len(values) != len(set(values))
                    or not all(isinstance(x, str) for x in values)
                ):
                    raise ValueError("MODEL_VOCABULARY_INVALID")
            targets = metadata["coveredTargets"]
            self.targets = {target["id"]: target for target in targets}
            if not self.targets or len(self.targets) != len(targets):
                raise ValueError("MODEL_TARGETS_INVALID")
            for target in targets:
                if any(str(target[key]) not in vocabulary[key] for key in COMPONENTS):
                    raise ValueError("TARGET_OUTSIDE_COMPONENT_VOCABULARY")
            head_file, normalization_file = (
                self.directory / "heads.onnx",
                self.directory / "normalization.npz",
            )
            if (
                fingerprint(head_file) != metadata["headOnnxSha256"]
                or fingerprint(normalization_file) != metadata["normalizationSha256"]
            ):
                raise ValueError("MODEL_DIGEST_MISMATCH")
            with np.load(normalization_file, allow_pickle=False) as data:
                self.normalization = {
                    key: data[key].copy() for key in ("mean", "scale", "pitch_mean", "pitch_scale")
                }
            for key, value in self.normalization.items():
                expected = (
                    metadata["dimensions"]
                    if key in {"mean", "scale"}
                    else configuration()["features"]["pitchFrames"] * 2 + 4
                )
                if (
                    value.shape != (expected,)
                    or not np.isfinite(value).all()
                    or ("scale" in key and np.any(value <= 0))
                ):
                    raise ValueError("NORMALIZATION_INVALID")
            import onnxruntime as ort

            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.session = ort.InferenceSession(
                str(head_file), options, providers=["CPUExecutionProvider"]
            )
            if self.session.get_providers() != ["CPUExecutionProvider"]:
                raise ValueError("CPU_PROVIDER_REQUIRED")
            backend = metadata.get("encoderBackend", "int8")
            if backend == "torch":
                if metadata.get("acousticDerivative"):
                    if (
                        fingerprint(self.directory / "encoder/tuned.json")
                        != metadata["acousticDerivative"]["metadataSha256"]
                    ):
                        raise ValueError("DERIVATIVE_METADATA_DIGEST_MISMATCH")
                    if metadata["model"] == "sensevoice":
                        from pinyin_matcher.pretrained_sensevoice_finetune import (
                            TunedSenseVoiceEvidence,
                        )

                        self.encoder = TunedSenseVoiceEvidence(
                            self.directory / "encoder", device="cpu", threads=2
                        )
                    elif metadata["model"] == "hanziflow":
                        from pinyin_matcher.pretrained_finetune import TunedHanziFlowEvidence

                        self.encoder = TunedHanziFlowEvidence(
                            self.directory / "encoder", device="cpu", threads=2
                        )
                    else:
                        raise ValueError("DERIVATIVE_ARCHITECTURE_UNSUPPORTED")
                elif metadata["model"] == "sensevoice":
                    from pinyin_matcher.pretrained_sensevoice import SenseVoiceFeatures

                    self.encoder = SenseVoiceFeatures(self.directory / "encoder", device="cpu")
                else:
                    from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

                    self.encoder = Wav2VecEvidence(
                        metadata["model"], self.directory / "encoder", device="cpu"
                    )
            elif backend != "int8":
                raise ValueError("CPU_BACKEND_INVALID")
            elif metadata["model"] == "sensevoice":
                from pinyin_matcher.pretrained_sensevoice import SenseVoiceFeatures

                self.encoder = SenseVoiceFeatures(
                    self.directory / "encoder", device="cpu", quantized=True
                )
            else:
                from pinyin_matcher.pretrained_export import OnnxWav2VecEvidence

                self.encoder = OnnxWav2VecEvidence(
                    metadata["model"], self.directory / "encoder", quantized=True
                )
            self.metadata = metadata
            self.pitch_override = None
            if metadata.get("pitchOverride"):
                from pinyin_matcher.pretrained_pitch import SwiftPitchVector

                source = metadata["pitchOverride"]["sourceIdentity"]
                if fingerprint(self.directory / "pitch/model.onnx") != source["modelSha256"]:
                    raise ValueError("PITCH_SOURCE_DIGEST_MISMATCH")
                self.pitch_override = SwiftPitchVector(self.directory / "pitch/model.onnx")
            self.problem = ""
        except Exception as error:
            self.encoder = None
            self.session = None
            self.problem = str(error) if isinstance(error, ValueError) else "MODEL_UNAVAILABLE"

    def _result(self, status: str, reason: str | None = None, **extra) -> dict:
        return {
            "status": status,
            "reason": reason,
            "experimental": True,
            "toneAssessed": False,
            "mode": "pretrained-acoustic-component-match",
            "model": self.metadata.get("model"),
            "variant": self.metadata.get("variant"),
            **extra,
        }

    def info(self) -> dict:
        return self._result(
            "available" if self.session is not None else "unavailable",
            self.problem or None,
            coveredTargetIds=sorted(self.targets),
            threads=2,
            device="cpu",
        )

    def match(
        self,
        target_id: str,
        wav_bytes: bytes,
        *,
        cancel=None,
        timeout: float = 2.0,
        evidence: bool = False,
    ) -> dict:
        if self.session is None or self.encoder is None:
            return self._result("unavailable", self.problem)
        if target_id not in self.targets:
            return self._result("unavailable", "TARGET_NOT_TRAINED")
        if not self.lock.acquire(blocking=False):
            return self._result("uncertain", "MODEL_BUSY")
        started = time.perf_counter()
        deadline = started + min(max(timeout, 0.001), 2.0)

        def interrupted():
            if cancel is not None and cancel.is_set():
                return "CANCELLED"
            return "MATCH_TIMEOUT" if time.perf_counter() >= deadline else None

        try:
            reason = interrupted()
            if reason:
                return self._result("uncertain", reason)
            try:
                samples = decode_wav(wav_bytes)
            except AudioRejected as error:
                return self._result("uncertain", str(error))
            reason = signal_guard(samples)
            if reason:
                return self._result("uncertain", reason)
            representation = represent(self.encoder, samples)
            reason = interrupted()
            if reason:
                return self._result("uncertain", reason)
            if getattr(self, "pitch_override", None) is not None:
                vector, pitch_info = self.pitch_override.vector(samples)
                if not pitch_info["available"]:
                    return self._result("uncertain", "PITCH_EVIDENCE_UNAVAILABLE")
                representation["pitch"] = vector
            reason = interrupted()
            if reason:
                return self._result("uncertain", reason)
            normal = self.normalization
            if self.metadata.get("representation") == "temporal16-v1":
                from pinyin_matcher.pretrained_temporal import temporal_vector

                representation["pooled"] = temporal_vector(representation["frames"])
            acoustic = (representation["pooled"] - normal["mean"]) / normal["scale"]
            pitch = (representation["pitch"] - normal["pitch_mean"]) / normal["pitch_scale"]
            outputs = self.session.run(
                None,
                {
                    "acoustic": acoustic[None].astype(np.float32),
                    "pitch": pitch[None].astype(np.float32),
                },
            )
            if len(outputs) != 3 or any(
                value.shape != (1, len(self.metadata["vocabulary"][key]))
                for key, value in zip(COMPONENTS, outputs, strict=True)
            ):
                raise ValueError("HEAD_OUTPUT_SHAPE_INVALID")
            probabilities = [softmax(value[0]) for value in outputs]
            target = self.targets[target_id]
            expected = [
                self.metadata["vocabulary"][key].index(str(target[key])) for key in COMPONENTS
            ]
            status = component_decision(probabilities, expected, self.metadata["thresholds"])
            reason = interrupted()
            if reason:
                return self._result("uncertain", reason)
            extra = {"elapsedMilliseconds": (time.perf_counter() - started) * 1000}
            if evidence:
                extra["internalEvidence"] = {
                    key: {
                        "best": self.metadata["vocabulary"][key][int(p.argmax())],
                        "probabilities": p.tolist(),
                    }
                    for key, p in zip(COMPONENTS, probabilities, strict=True)
                }
            return self._result(
                status,
                "COMPONENT_EVIDENCE_INSUFFICIENT" if status == "uncertain" else None,
                **extra,
            )
        except Exception as error:
            return self._result(
                "unavailable", str(error) if isinstance(error, ValueError) else "INFERENCE_FAILED"
            )
        finally:
            self.lock.release()


def load_matcher(package):
    """Select only a locally declared matcher implementation, with no downloads."""
    try:
        metadata = json.loads((Path(package) / "model.json").read_text())
    except (OSError, ValueError):
        return PretrainedMatcher(package)
    if metadata.get("headKind") == "native-comparison":
        from pinyin_matcher.pretrained_comparison_runtime import ComparisonMatcher

        return ComparisonMatcher(package)
    if metadata.get("headKind") == "native-ctc":
        from pinyin_matcher.pretrained_ctc_runtime import NativeCTCMatcher

        return NativeCTCMatcher(package)
    return PretrainedMatcher(package)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["info", "match"])
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--target")
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--evidence", action="store_true")
    args = parser.parse_args()
    matcher = load_matcher(args.model)
    if args.action == "match":
        if not args.target or args.wav is None:
            parser.error("match requires --target and --wav")
        result = matcher.match(args.target, args.wav.read_bytes(), evidence=args.evidence)
    else:
        result = matcher.info()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
