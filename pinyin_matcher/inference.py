"""CPU-only local matcher. No torch, TTS, ASR, network, or audio persistence."""

import json
import math
import threading
import time
from pathlib import Path

import numpy as np
from scipy.special import log_softmax

from pinyin_matcher.audio import FEATURE_VERSION, AudioRejected, decode_wav, features
from pinyin_matcher.catalog import CATALOG, fingerprint, load_catalog, targets_by_id
from pinyin_matcher.contour import PITCH_FEATURE_VERSION, contour


def ctc_log_probability(logits: np.ndarray, sequence: list[int]) -> float:
    """CTC forward sum, including blanks/repetitions; never forces a best path."""
    if not sequence:
        return float(logits[:, 0].sum())
    if len(sequence) > len(logits):
        return -math.inf
    labels = [0]
    for token in sequence:
        labels.extend([token, 0])
    previous = np.full(len(labels), -np.inf)
    previous[0] = logits[0, 0]
    previous[1] = logits[0, labels[1]]
    for frame in logits[1:]:
        current = previous.copy()
        current[1:] = np.logaddexp(current[1:], previous[:-1])
        for index in range(2, len(labels)):
            if labels[index] and labels[index] != labels[index - 2]:
                current[index] = np.logaddexp(current[index], previous[index - 2])
        previous = current + frame[labels]
    return float(np.logaddexp(previous[-1], previous[-2]))


class PinyinMatcher:
    """Instantiate once; match(target_id, pcm_wav) is the future adapter boundary."""

    def __init__(self, model_directory: Path | str, *, threads: int = 2):
        self.directory = Path(model_directory)
        self.lock = threading.Lock()
        self.session = None
        self.pitch_session = None
        self.pitch_tracker = None
        self.problem = "MODEL_UNAVAILABLE"
        self.catalog = load_catalog()
        self.targets = targets_by_id(self.catalog)
        self.metadata = {}
        try:
            metadata_file = self.directory / "model.json"
            if metadata_file.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("MODEL_METADATA_INVALID")
            metadata = json.loads(metadata_file.read_text())
            catalog_path = CATALOG
            if metadata.get("catalogFile"):
                catalog_path = (self.directory / metadata["catalogFile"]).resolve()
                if (
                    not catalog_path.is_relative_to(self.directory.resolve())
                    or catalog_path.stat().st_size > 4 * 1024 * 1024
                ):
                    raise ValueError("MODEL_CATALOG_PATH_INVALID")
                self.catalog = load_catalog(catalog_path)
                self.targets = targets_by_id(self.catalog)
            if metadata["featureVersion"] != FEATURE_VERSION or metadata[
                "catalogSha256"
            ] != fingerprint(catalog_path):
                raise ValueError("MODEL_CATALOG_MISMATCH")
            if metadata.get("status") not in {"experimental", "validated"}:
                raise ValueError("MODEL_NOT_TRAINED")
            file = (self.directory / metadata["file"]).resolve()
            if (
                not file.is_relative_to(self.directory.resolve())
                or file.stat().st_size > 32 * 1024 * 1024
                or fingerprint(file) != metadata["sha256"]
            ):
                raise ValueError("MODEL_DIGEST_MISMATCH")
            if not 2 <= len(set(metadata["coveredTargetIds"])) == len(
                metadata["coveredTargetIds"]
            ) <= 1000 or any(key not in self.targets for key in metadata["coveredTargetIds"]):
                raise ValueError("MODEL_TARGETS_INVALID")
            if metadata.get("decisionVersion", 1) not in (1, 2, 3):
                raise ValueError("MODEL_DECISION_VERSION_UNSUPPORTED")
            if metadata.get("acousticInput") not in {None, "mel-only"}:
                raise ValueError("MODEL_ACOUSTIC_INPUT_UNSUPPORTED")
            for field in ("onsets", "rimes"):
                values = metadata[field]
                if (
                    not isinstance(values, list)
                    or not values
                    or len(values) != len(set(values))
                    or not all(isinstance(value, str) for value in values)
                    or any(
                        self.targets[key][field[:-1]] not in values
                        for key in metadata["coveredTargetIds"]
                    )
                ):
                    raise ValueError("MODEL_PHONETIC_HEADS_INVALID")
            version = metadata.get("decisionVersion", 1)
            required_thresholds = (
                {"minimumContentMargin", "maximumFreeCtcAdvantage", "minimumToneProbability"}
                if version == 3
                else {"minimumScore", "minimumMargin", "minimumCtc"}
            )
            optional_thresholds = {"minimumComponentProbability", "maximumFreeCtcAdvantage"}
            if version == 3:
                optional_thresholds = set()
            if not required_thresholds <= set(metadata["thresholds"]) or (
                set(metadata["thresholds"]) - required_thresholds - optional_thresholds
            ):
                raise ValueError("MODEL_THRESHOLDS_INVALID")
            if any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in metadata["thresholds"].values()
            ):
                raise ValueError("MODEL_THRESHOLDS_INVALID")
            thresholds = metadata["thresholds"]
            if version == 3:
                from pinyin_matcher.decision_v3 import _thresholds

                _thresholds(thresholds)
            elif (
                thresholds["minimumScore"] > 0
                or thresholds["minimumCtc"] > 0
                or thresholds["minimumMargin"] < 0
                or not 0 <= thresholds.get("minimumComponentProbability", 0.5) <= 1
                or thresholds.get("maximumFreeCtcAdvantage", 0.05) < 0
            ):
                raise ValueError("MODEL_THRESHOLDS_INVALID")
            import onnxruntime as ort

            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = max(1, min(threads, 4))
            options.inter_op_num_threads = 1
            options.log_severity_level = 3
            self.session = ort.InferenceSession(
                str(file), sess_options=options, providers=["CPUExecutionProvider"]
            )
            if metadata.get("pitchTone"):
                pitch = metadata["pitchTone"]
                pitch_file = (self.directory / pitch["file"]).resolve()
                from pinyin_matcher.pitch_swift import SUPPORTED_FEATURE_VERSIONS

                if (
                    pitch["featureVersion"]
                    not in {PITCH_FEATURE_VERSION, *SUPPORTED_FEATURE_VERSIONS}
                    or not pitch_file.is_relative_to(self.directory.resolve())
                    or pitch_file.stat().st_size > 2 * 1024 * 1024
                    or fingerprint(pitch_file) != pitch["sha256"]
                ):
                    raise ValueError("PITCH_MODEL_DIGEST_MISMATCH")
                self.pitch_session = ort.InferenceSession(
                    str(pitch_file), sess_options=options, providers=["CPUExecutionProvider"]
                )
                inputs, outputs = self.pitch_session.get_inputs(), self.pitch_session.get_outputs()
                swift = pitch["featureVersion"] in SUPPORTED_FEATURE_VERSIONS
                expected_channels = 4 if swift else 2
                if (
                    len(inputs) != 1
                    or inputs[0].name != "contour"
                    or inputs[0].type != "tensor(float)"
                    or inputs[0].shape[1:] != [32, expected_channels]
                    or len(outputs) != 1
                    or outputs[0].name != "tone"
                    or outputs[0].shape[1:] != [6]
                ):
                    raise ValueError("PITCH_MODEL_INTERFACE_MISMATCH")
                if swift:
                    from pinyin_matcher.pitch_swift import SwiftPitch

                    if version != 3:
                        raise ValueError("RAW_PITCH_REQUIRES_DECISION_V3")
                    tracker = pitch["tracker"]
                    tracker_path = (self.directory / tracker["file"]).resolve()
                    if not tracker_path.is_relative_to(self.directory.resolve()):
                        raise ValueError("PITCH_TRACKER_PATH_INVALID")
                    self.pitch_tracker = SwiftPitch(
                        tracker_path, tracker["sha256"], feature_version=pitch["featureVersion"]
                    )
            if version == 3 and self.pitch_tracker is None:
                raise ValueError("INDEPENDENT_RAW_PITCH_REQUIRED")
            self.metadata = metadata
            self.problem = ""
        # ONNX Runtime exposes several native exception types, all load failures
        # must remain unavailable rather than preventing an importing app starting.
        except Exception as error:
            self.session = None
            self.pitch_session = None
            self.pitch_tracker = None
            self.problem = str(error) if isinstance(error, ValueError) else "MODEL_UNAVAILABLE"

    def _result(self, status: str, reason: str | None = None, **extra) -> dict:
        return {
            "status": status,
            "reason": reason,
            "mode": "target-acoustic-match",
            "toneAssessed": bool(self.metadata.get("toneValidated", False)),
            "qualityPassed": bool(self.metadata.get("qualityPassed", False)),
            "modelVersion": self.metadata.get("version"),
            "experimental": self.metadata.get("status") != "validated",
            **extra,
        }

    def _scores(self, array: np.ndarray, *, run_options=None, deadline=None, cancel=None) -> dict:
        acoustic_array = array.copy() if self.metadata.get("acousticInput") == "mel-only" else array
        if self.metadata.get("acousticInput") == "mel-only":
            acoustic_array[:, 64:] = 0
        phones, onset, rime, tone = self.session.run(
            None,
            {"acoustic": acoustic_array[None], "lengths": np.array([len(array)], dtype=np.int64)},
            run_options=run_options,
        )
        if self.pitch_session is not None:
            tone = self.pitch_session.run(
                None, {"contour": contour(array)[None]}, run_options=run_options
            )[0]
        if any(not np.isfinite(value).all() for value in (phones, onset, rime, tone)):
            raise ValueError("NONFINITE_MODEL_OUTPUT")
        if (
            phones.shape != (1, len(array), len(self.catalog["tokens"]))
            or onset.shape != (1, len(self.metadata["onsets"]))
            or rime.shape != (1, len(self.metadata["rimes"]))
            or tone.shape != (1, 6)
        ):
            raise ValueError("MODEL_OUTPUT_SHAPE_INVALID")
        phone_log = log_softmax(phones[0], axis=-1)
        onset_log, rime_log, tone_log = (log_softmax(x[0]) for x in (onset, rime, tone))
        tokens = self.catalog["tokens"]
        path = np.argmax(phone_log, axis=-1).tolist()
        decoded = [
            token for i, token in enumerate(path) if token and (i == 0 or token != path[i - 1])
        ]
        free_score = (
            ctc_log_probability(phone_log, decoded) / len(array) if len(decoded) <= 16 else 0
        )
        head_indices = (
            int(np.argmax(onset_log)),
            int(np.argmax(rime_log)),
            int(np.argmax(tone_log)),
        )
        scores = {}
        for key in self.metadata["coveredTargetIds"]:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("MATCH_CANCELLED")
            if deadline is not None and time.perf_counter() >= deadline:
                raise TimeoutError("MATCHER_TIMEOUT")
            target = self.targets[key]
            sequence = [tokens.index(token) for token in target["phones"]]
            # Per-frame normalization keeps CTC evidence comparable across lengths.
            acoustic = ctc_log_probability(phone_log, sequence) / len(array)
            category = float(
                onset_log[self.metadata["onsets"].index(target["onset"])]
                + rime_log[self.metadata["rimes"].index(target["rime"])]
            )
            tonal = float(tone_log[target["tone"]]) if self.metadata.get("toneEnabled") else 0
            scores[key] = {
                "score": category + tonal + acoustic,
                "content": category + acoustic,
                "toneProbability": float(np.exp(tone_log[target["tone"]])),
                "onsetProbability": float(
                    np.exp(onset_log[self.metadata["onsets"].index(target["onset"])])
                ),
                "rimeProbability": float(
                    np.exp(rime_log[self.metadata["rimes"].index(target["rime"])])
                ),
                "componentAgreement": (
                    head_indices[0] == self.metadata["onsets"].index(target["onset"])
                    and head_indices[1] == self.metadata["rimes"].index(target["rime"])
                    and (not self.metadata.get("toneEnabled") or head_indices[2] == target["tone"])
                ),
                "freeCtcAdvantage": float(free_score - acoustic),
                "ctc": acoustic,
            }
        return scores

    def _branch_evidence(
        self, array: np.ndarray, samples: np.ndarray, target_id: str, *, run_options=None
    ):
        """Independent phonetic heads and raw-waveform pitch; no truth labels."""
        acoustic = array.copy()
        if self.metadata.get("acousticInput") == "mel-only":
            acoustic[:, 64:] = 0
        phones, onset, rime, _ = self.session.run(
            None,
            {"acoustic": acoustic[None], "lengths": np.asarray([len(array)], dtype=np.int64)},
            run_options=run_options,
        )
        if (
            phones.shape != (1, len(array), len(self.catalog["tokens"]))
            or onset.shape != (1, len(self.metadata["onsets"]))
            or rime.shape != (1, len(self.metadata["rimes"]))
            or any(not np.isfinite(x).all() for x in (phones, onset, rime))
        ):
            raise ValueError("MODEL_OUTPUT_SHAPE_INVALID")
        onset_log, rime_log = log_softmax(onset[0]), log_softmax(rime[0])
        oi, ri = int(np.argmax(onset_log)), int(np.argmax(rime_log))
        pair = (self.metadata["onsets"][oi], self.metadata["rimes"][ri])
        candidates = {
            tuple(row["phones"])
            for row in self.targets.values()
            if (row["onset"], row["rime"]) == pair
        }
        predicted = list(next(iter(candidates))) if len(candidates) == 1 else []
        margins = [
            float(np.sort(values)[-1] - np.sort(values)[-2]) for values in (onset_log, rime_log)
        ]
        evidence = {
            "targetPhones": self.targets[target_id]["phones"],
            "targetTone": self.targets[target_id]["tone"],
            "predictedPhones": predicted,
            "contentMargin": min(margins),
            "freeCtcAdvantage": 0.0,
            "predictedTone": None,
            "toneProbability": 0.0,
            "pitchReliable": False,
        }
        if predicted:
            phone_log = log_softmax(phones[0], axis=-1)
            path = np.argmax(phone_log, axis=-1).tolist()
            decoded = [v for i, v in enumerate(path) if v and (i == 0 or v != path[i - 1])]
            sequence = [self.catalog["tokens"].index(token) for token in predicted]
            constrained = ctc_log_probability(phone_log, sequence) / len(array)
            free = ctc_log_probability(phone_log, decoded) / len(array) if len(decoded) <= 16 else 0
            evidence["freeCtcAdvantage"] = float(free - constrained)
        try:
            pitch, quality = self.pitch_tracker.contour(samples, run_options=run_options)
            tone = self.pitch_session.run(None, {"contour": pitch[None]}, run_options=run_options)[
                0
            ]
            if tone.shape != (1, 6) or not np.isfinite(tone).all():
                raise ValueError("PITCH_MODEL_OUTPUT_INVALID")
            probabilities = np.exp(log_softmax(tone[0]))
            index = int(np.argmax(probabilities))
            evidence.update(
                predictedTone=index,
                toneProbability=float(probabilities[index]),
                pitchReliable=index in {1, 2, 3, 4},
                pitchQuality=quality,
            )
        except AudioRejected:
            # No confident voiced evidence is never a request to try again.
            evidence["predictedPhones"] = []
        evidence["candidateId"] = next(
            (
                key
                for key in sorted(self.targets)
                if self.targets[key]["form"] == "whole-syllable"
                and self.targets[key]["phones"] == evidence["predictedPhones"]
                and self.targets[key]["tone"] == evidence["predictedTone"]
            ),
            None,
        )
        return evidence

    def capabilities(self) -> dict:
        return {
            "available": self.session is not None,
            "reason": self.problem or None,
            "mode": "target-acoustic-match",
            "modelVersion": self.metadata.get("version"),
            "coveredTargetIds": self.metadata.get("coveredTargetIds", []),
            "forms": sorted(
                {self.targets[key]["form"] for key in self.metadata.get("coveredTargetIds", [])}
            ),
            "toneAssessed": bool(self.metadata.get("toneValidated", False)),
            "qualityPassed": bool(self.metadata.get("qualityPassed", False)),
            "experimental": self.metadata.get("status") != "validated",
            "providers": self.session.get_providers() if self.session else [],
            "toneEvidence": "relative-pitch-only" if self.pitch_session else "shared-acoustic-head",
        }

    def match(
        self,
        target_id: str,
        wav: bytes,
        *,
        include_evidence: bool = False,
        cancel: threading.Event | None = None,
    ) -> dict:
        if target_id not in self.targets:
            return self._result("unavailable", "TARGET_NOT_FOUND")
        if not self.session:
            return self._result("unavailable", self.problem)
        if target_id not in self.metadata["coveredTargetIds"]:
            return self._result("unavailable", "TARGET_NOT_TRAINED")
        if cancel is not None and cancel.is_set():
            return self._result("unavailable", "MATCH_CANCELLED")
        if not self.lock.acquire(blocking=False):
            return self._result("unavailable", "MATCHER_BUSY")
        started = time.perf_counter()
        timer = None
        try:
            samples = decode_wav(wav)
            array, quality = features(samples)
            if self.metadata.get("decisionVersion", 1) != 3 and quality["voicedFrames"] < 8:
                return self._result("uncertain", "NO_RELIABLE_VOICED_SPEECH")
            import onnxruntime as ort

            options = ort.RunOptions()
            timer = threading.Timer(2, lambda: setattr(options, "terminate", True))
            timer.daemon = True
            timer.start()
            if self.metadata.get("decisionVersion", 1) == 3:
                from pinyin_matcher.decision_v3 import decide

                evidence = self._branch_evidence(array, samples, target_id, run_options=options)
                decision = decide(evidence, self.metadata["thresholds"])
                if time.perf_counter() - started > 2:
                    return self._result("unavailable", "MATCHER_TIMEOUT")
                if cancel is not None and cancel.is_set():
                    return self._result("unavailable", "MATCH_CANCELLED")
                return self._result(
                    **decision,
                    durationMilliseconds=round((time.perf_counter() - started) * 1000, 2),
                    **(
                        {
                            "branchEvidence": evidence,
                            "candidateId": evidence.get("candidateId"),
                            "quality": quality,
                        }
                        if include_evidence
                        else {}
                    ),
                )
            values = self._scores(array, run_options=options, deadline=started + 2, cancel=cancel)
            ordered = sorted(values, key=lambda key: values[key]["score"], reverse=True)
            best, runner = ordered[:2]
            margin = values[best]["score"] - values[runner]["score"]
            thresholds = self.metadata["thresholds"]
            if (
                values[best]["score"] < thresholds["minimumScore"]
                or margin < thresholds["minimumMargin"]
                or values[best]["ctc"] < thresholds["minimumCtc"]
            ):
                status, reason = "uncertain", "INSUFFICIENT_EVIDENCE"
            elif self.metadata.get("decisionVersion", 1) >= 2 and (
                not values[best]["componentAgreement"]
                or min(
                    values[best]["onsetProbability"],
                    values[best]["rimeProbability"],
                    values[best]["toneProbability"] if self.metadata.get("toneEnabled") else 1,
                )
                < thresholds.get("minimumComponentProbability", 0.5)
                or values[best]["freeCtcAdvantage"]
                > thresholds.get("maximumFreeCtcAdvantage", 0.05)
            ):
                status, reason = "uncertain", "OUTSIDE_SUPPORTED_PHONETIC_EVIDENCE"
            elif best == target_id:
                status, reason = "matched", None
            else:
                status, reason = "retry", "OTHER_TARGET_DETECTED"
            if time.perf_counter() - started > 2:
                return self._result("unavailable", "MATCHER_TIMEOUT")
            if cancel is not None and cancel.is_set():
                return self._result("unavailable", "MATCH_CANCELLED")
            evidence = (
                {
                    "candidateId": best,
                    "margin": margin,
                    "targetEvidence": values[target_id],
                    "quality": quality,
                }
                if include_evidence
                else {}
            )
            return self._result(
                status,
                reason,
                durationMilliseconds=round((time.perf_counter() - started) * 1000, 2),
                **evidence,
            )
        except AudioRejected as error:
            return self._result("uncertain", str(error))
        except InterruptedError:
            return self._result("unavailable", "MATCH_CANCELLED")
        except TimeoutError:
            return self._result("unavailable", "MATCHER_TIMEOUT")
        except Exception:
            if time.perf_counter() - started >= 2:
                return self._result("unavailable", "MATCHER_TIMEOUT")
            return self._result("unavailable", "INFERENCE_FAILED")
        finally:
            if timer is not None:
                timer.cancel()
            self.lock.release()
