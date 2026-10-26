"""Local CPU target validity using native all-class acoustic evidence."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import AudioRejected, decode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_comparison import ComparisonHead, classify
from pinyin_matcher.pretrained_features import represent
from pinyin_matcher.pretrained_runtime import PretrainedMatcher, signal_guard


class ComparisonMatcher(PretrainedMatcher):
    """Same CLI contract as the frozen-encoder heads; no character decoder."""

    supports_target_comparison_batch = True

    def __init__(self, package):
        self.directory = Path(package)
        self.lock = threading.Lock()
        self.metadata, self.targets = {}, {}
        self.encoder = self.session = None
        self.problem = "MODEL_UNAVAILABLE"
        try:
            path = self.directory / "model.json"
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("MODEL_METADATA_TOO_LARGE")
            metadata = json.loads(path.read_text())
            if (
                metadata["schemaVersion"] != 1
                or metadata["model"] != "hanziflow"
                or metadata["encoderBackend"] != "torch"
                or metadata["headKind"] != "native-comparison"
            ):
                raise ValueError("COMPARISON_PACKAGE_INVALID")
            if not metadata.get("packageFiles"):
                raise ValueError("COMPARISON_PACKAGE_FILES_REQUIRED")
            for relative, record in metadata["packageFiles"].items():
                resource = (self.directory / relative).resolve()
                if (
                    not resource.is_relative_to(self.directory.resolve())
                    or fingerprint(resource) != record["sha256"]
                ):
                    raise ValueError("BUNDLE_RESOURCE_DIGEST_MISMATCH")
            self.head = ComparisonHead(self.directory)
            if self.head.metadata["thresholds"] != metadata["thresholds"]:
                raise ValueError("COMPARISON_THRESHOLD_MISMATCH")
            targets = metadata["coveredTargets"]
            self.targets = {target["id"]: target for target in targets}
            if not targets or len(self.targets) != len(targets):
                raise ValueError("COMPARISON_TARGETS_INVALID")
            derivative = metadata.get("acousticDerivative")
            if derivative:
                from pinyin_matcher.pretrained_finetune import TunedHanziFlowEvidence

                if (
                    fingerprint(self.directory / "encoder/tuned.json")
                    != derivative["metadataSha256"]
                ):
                    raise ValueError("DERIVATIVE_METADATA_DIGEST_MISMATCH")
                self.encoder = TunedHanziFlowEvidence(self.directory / "encoder", threads=2)
            else:
                from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

                self.encoder = Wav2VecEvidence("hanziflow", self.directory / "encoder", threads=2)
            self.metadata, self.session = metadata, self.head.session
            self.problem = ""
        except Exception as error:
            self.encoder = self.session = None
            self.problem = str(error) if isinstance(error, ValueError) else "MODEL_UNAVAILABLE"

    def match(
        self,
        target_id,
        wav_bytes,
        *,
        cancel=None,
        timeout=2.0,
        evidence=False,
        comparison_target_ids=None,
    ):
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
            native = {k: representation["native_" + k] for k in ("initial", "final", "tone")}
            requested = [target_id]
            if evidence and comparison_target_ids is not None:
                requested = list(dict.fromkeys([target_id, *comparison_target_ids]))
                if len(requested) > 1024 or any(key not in self.targets for key in requested):
                    raise ValueError("COMPARISON_REQUEST_TARGETS_INVALID")
            targets = [self.targets[key] for key in requested]
            probabilities = self.head.probabilities_for_targets(
                native, targets, pitch=representation["pitch"]
            )
            if (
                probabilities.shape != (len(targets), 3)
                or not np.isfinite(probabilities).all()
                or np.any((probabilities < 0) | (probabilities > 1))
            ):
                raise ValueError("COMPARISON_OUTPUT_INVALID")
            decisions = {
                target["id"]: classify(p, self.metadata["thresholds"])
                for target, p in zip(targets, probabilities, strict=True)
            }
            reason = interrupted()
            if reason:
                return self._result("uncertain", reason)
            status = decisions[target_id]
            extra = {"elapsedMilliseconds": (time.perf_counter() - started) * 1000}
            if evidence:
                extra["internalEvidence"] = {"targetDecisions": decisions}
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
