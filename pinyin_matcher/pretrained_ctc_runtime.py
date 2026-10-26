"""Direct native CTC event matching and calibration, without a learned readout.

All source classes contribute to complete blank/single-label/multiple-label
events. No probability is normalized over an expected target or catalog subset.
SenseVoice requires this project's separately trained phonetic-head derivative;
the original SenseVoice model has no native phonetic/tone matching output.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pinyin_matcher.audio import AudioRejected, decode_wav, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_features import configuration
from pinyin_matcher.pretrained_native import native_probabilities, native_rime_aliases
from pinyin_matcher.pretrained_runtime import PretrainedMatcher, component_decision, signal_guard

COMPONENTS = ("onset", "rime", "tone")
HEADS = ("initial", "final", "tone")


def load_encoder(name: str, directory: Path):
    """Explicit two-thread CPU source selection; never download or fall back."""
    tuned_path = directory / "tuned.json"
    if tuned_path.is_file():
        tuned = json.loads(tuned_path.read_text())
        if name == "sensevoice" and tuned.get("architecture") == "sensevoice-50-ctc-int8-v1":
            from pinyin_matcher.pretrained_sensevoice_export import OnnxSenseVoiceEvidence

            return OnnxSenseVoiceEvidence(directory, threads=2)
        if name == "sensevoice" and tuned.get("architecture") == "sensevoice-50-ctc-v1":
            from pinyin_matcher.pretrained_sensevoice_finetune import TunedSenseVoiceEvidence

            return TunedSenseVoiceEvidence(directory, device="cpu", threads=2)
        if name == "hanziflow" and not tuned.get("architecture"):
            from pinyin_matcher.pretrained_finetune import TunedHanziFlowEvidence

            return TunedHanziFlowEvidence(directory, device="cpu", threads=2)
        raise ValueError("NATIVE_CTC_DERIVATIVE_ARCHITECTURE_UNSUPPORTED")
    if name != "hanziflow":
        raise ValueError("ORIGINAL_SENSEVOICE_HAS_NO_PHONETIC_HEAD")
    from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

    return Wav2VecEvidence(name, directory, device="cpu", threads=2)


def source_vocabularies(directory: Path):
    return {
        head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text()) for head in HEADS
    }


def verify_source(name: str, directory: Path):
    tuned_path = directory / "tuned.json"
    if not tuned_path.is_file():
        from pinyin_matcher.pretrained_prepare import verify

        verify(name, directory)
        return
    tuned = json.loads(tuned_path.read_text())
    for relative, record in tuned["files"].items():
        source = (directory / relative).resolve()
        if (
            not source.is_relative_to(directory.resolve())
            or fingerprint(source) != record["sha256"]
        ):
            raise ValueError("NATIVE_CTC_SOURCE_FILE_CHANGED")


def _readout(native: dict, vocabulary: dict, native_vocabulary: dict, cfg: dict):
    # Both H and the NEW Sense50 heads use H's declared vocabulary semantics.
    # This does not relabel the original SenseVoice model as phonetic.
    return native_probabilities(
        "hanziflow", native, vocabulary, native_vocab=native_vocabulary, config=cfg
    )


def _evidence(probabilities, details):
    return {
        **{
            key: {"probabilities": value.tolist()}
            for key, value in zip(COMPONENTS, probabilities, strict=True)
        },
        "forceUncertain": bool(details.get("forceUncertain") or details.get("unavailable")),
        "nativeCTC": details,
    }


def native_decision(probabilities, details, expected, thresholds):
    if details.get("forceUncertain") or details.get("unavailable"):
        return "uncertain"
    return component_decision(probabilities, expected, thresholds)


class NativeCTCMatcher(PretrainedMatcher):
    """Local CPU-only matcher with the same cancellation/status CLI contract."""

    def __init__(self, package):
        self.directory = Path(package).resolve()
        self.lock = threading.Lock()
        self.metadata, self.targets = {}, {}
        self.encoder = self.session = None
        self.problem = "MODEL_UNAVAILABLE"
        try:
            metadata_path = self.directory / "model.json"
            if metadata_path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("MODEL_METADATA_TOO_LARGE")
            metadata = json.loads(metadata_path.read_text())
            if (
                metadata["schemaVersion"] != 1
                or metadata["headKind"] != "native-ctc"
                or metadata["model"] not in {"hanziflow", "sensevoice"}
                or metadata["encoderBackend"] not in {"torch", "sensevoice-ctc-int8"}
                or metadata["configuration"] != configuration()
                or metadata["nativeRimeAliases"] != native_rime_aliases("hanziflow")
            ):
                raise ValueError("NATIVE_CTC_PACKAGE_INVALID")
            resources = metadata.get("packageFiles")
            if not isinstance(resources, dict) or not resources:
                raise ValueError("NATIVE_CTC_PACKAGE_FILES_REQUIRED")
            for relative, record in resources.items():
                path = (self.directory / relative).resolve()
                if not path.is_relative_to(self.directory) or fingerprint(path) != record["sha256"]:
                    raise ValueError("BUNDLE_RESOURCE_DIGEST_MISMATCH")
            thresholds = metadata["thresholds"]
            if set(thresholds) != {"probability", "margin"} or any(
                type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
                for value in thresholds.values()
            ):
                raise ValueError("MODEL_THRESHOLDS_INVALID")
            vocabulary = metadata["vocabulary"]
            if set(vocabulary) != set(COMPONENTS) or any(
                not isinstance(values, list)
                or not values
                or len(set(values)) != len(values)
                or any(not isinstance(value, str) for value in values)
                for values in vocabulary.values()
            ):
                raise ValueError("MODEL_VOCABULARY_INVALID")
            targets = metadata["coveredTargets"]
            self.targets = {target["id"]: target for target in targets}
            if (
                not targets
                or len(self.targets) != len(targets)
                or any(
                    str(target[key]) not in vocabulary[key]
                    for target in targets
                    for key in COMPONENTS
                )
            ):
                raise ValueError("MODEL_TARGETS_INVALID")
            self.native_vocabulary = source_vocabularies(self.directory / "encoder")
            if self.native_vocabulary != metadata["nativeVocabularies"]:
                raise ValueError("NATIVE_CTC_VOCABULARY_DIGEST_MISMATCH")
            tuned_path = self.directory / "encoder/tuned.json"
            quantized = (
                tuned_path.is_file()
                and json.loads(tuned_path.read_text()).get("architecture")
                == "sensevoice-50-ctc-int8-v1"
            )
            if quantized != (metadata["encoderBackend"] == "sensevoice-ctc-int8"):
                raise ValueError("NATIVE_CTC_BACKEND_METADATA_MISMATCH")
            self.encoder = load_encoder(metadata["model"], self.directory / "encoder")
            self.metadata, self.session, self.problem = metadata, self.encoder, ""
        except Exception as error:
            self.encoder = self.session = None
            self.problem = str(error) if isinstance(error, ValueError) else "MODEL_UNAVAILABLE"

    def match(self, target_id, wav_bytes, *, cancel=None, timeout=2.0, evidence=False):
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
            acoustic = self.encoder.evidence(trim_silence(samples))
            native = {"native_" + key: value for key, value in acoustic["native"].items()}
            probabilities, details = _readout(
                native,
                self.metadata["vocabulary"],
                self.native_vocabulary,
                self.metadata["configuration"],
            )
            reason = interrupted()
            if reason:
                return self._result("uncertain", reason)
            target = self.targets[target_id]
            expected = [
                self.metadata["vocabulary"][key].index(str(target[key])) for key in COMPONENTS
            ]
            status = native_decision(probabilities, details, expected, self.metadata["thresholds"])
            extra = {"elapsedMilliseconds": (time.perf_counter() - started) * 1000}
            if evidence:
                extra["internalEvidence"] = _evidence(probabilities, details)
            return self._result(
                status,
                "NATIVE_CTC_EVIDENCE_INSUFFICIENT" if status == "uncertain" else None,
                **extra,
            )
        except Exception as error:
            return self._result(
                "unavailable", str(error) if isinstance(error, ValueError) else "INFERENCE_FAILED"
            )
        finally:
            self.lock.release()


def calibrate(name: str, manifest: Path, cache: Path, model: Path, output: Path):
    """Calibrate all15 predeclared thresholds with real-WAV guards, never test."""
    from pinyin_matcher.pretrained_evaluate import compare_targets
    from pinyin_matcher.pretrained_experiment import (
        cache_identity,
        covered_targets,
        read_cached,
        read_rows,
        write,
    )
    from pinyin_matcher.pretrained_metrics import metrics

    if output.exists():
        raise ValueError("CTC_CALIBRATION_DESTINATION_ALREADY_EXISTS")
    document = json.loads(manifest.read_text())
    if document.get("frozenTestIncluded") or any(
        row["split"] == "test" for row in document["items"]
    ):
        raise ValueError("CTC_CALIBRATION_CANNOT_OPEN_FROZEN_TEST")
    identity = json.loads((cache / "identity.json").read_text())
    if identity != cache_identity(name, model):
        raise ValueError("CTC_CACHE_IDENTITY_MISMATCH")
    verify_source(name, model)
    cache_metadata = json.loads((cache / "cache.json").read_text())
    if cache_metadata["manifestSha256"] != fingerprint(manifest) or cache_metadata["testIncluded"]:
        raise ValueError("CTC_CALIBRATION_CACHE_MANIFEST_MISMATCH")
    if (
        name == "sensevoice"
        and not identity.get("derivative", {}).get("architecture") == "sensevoice-50-ctc-v1"
    ):
        raise ValueError("ORIGINAL_SENSEVOICE_HAS_NO_PHONETIC_HEAD")
    rows = read_rows(manifest, verify_splits=("calibration",))
    training = [
        r
        for r in rows
        if r["split"] == "train"
        and not r.get("labelPolicyFlags")
        and not r.get("numericalQualityFlags")
        and not r.get("placeholder")
    ]
    calibration = [r for r in rows if r["split"] == "calibration"]
    if not training or not calibration:
        raise ValueError("CTC_TRAIN_CALIBRATION_INVENTORY_REQUIRED")
    cfg = configuration()
    thresholds = [
        {"probability": p, "margin": m}
        for p in cfg["acceptProbabilities"]
        for m in cfg["acceptMargins"]
    ]
    if len(thresholds) != 15:
        raise ValueError("CTC_FIXED15_THRESHOLD_GRID_REQUIRED")
    vocabulary = {key: sorted({str(row[key]) for row in training}) for key in COMPONENTS}
    targets = covered_targets(vocabulary, training)
    native_vocabulary = source_vocabularies(model)
    metadata = {
        "schemaVersion": 1,
        "model": name,
        "variant": "native-ctc",
        "headKind": "native-ctc",
        "encoderBackend": "torch",
        "configuration": cfg,
        "vocabulary": vocabulary,
        "nativeVocabularies": native_vocabulary,
        "coveredTargets": targets,
        "nativeRimeAliases": native_rime_aliases("hanziflow"),
        "phoneticHeadOrigin": "project-trained-SenseVoice50-CTC"
        if name == "sensevoice"
        else "HanziFlow-native-CTC-with-declared-derivative",
        "manifestSha256": fingerprint(manifest),
        "cacheIdentitySha256": fingerprint(cache / "identity.json"),
        "cacheMetadataSha256": fingerprint(cache / "cache.json"),
        "acousticDerivative": identity.get("derivative"),
        "acousticSource": identity["model"],
        "testUsed": False,
        "experimental": True,
        "toneAssessed": False,
        "trainingMethod": (
            "No downstream readout training; complete native CTC events and calibrated thresholds"
        ),
        "implementationSha256": fingerprint(Path(__file__)),
    }
    prepared = []
    for row in calibration:
        reason = None
        probabilities = [np.zeros(len(vocabulary[key])) for key in COMPONENTS]
        details = {"forceUncertain": True, "unavailable": True}
        if (
            row.get("labelPolicyFlags")
            or row.get("numericalQualityFlags")
            or row.get("placeholder")
        ):
            reason = "PREDECLARED_UNASSESSABLE"
        else:
            try:
                samples = decode_wav(Path(row["file"]).read_bytes())
                reason = signal_guard(samples)
            except AudioRejected as error:
                reason = str(error)
            if not reason:
                with read_cached(
                    cache / (row["sha256"] + ".npz"), metadata["cacheIdentitySha256"]
                ) as cached:
                    if "error" in cached:
                        reason = "ACOUSTIC_CACHE_ERROR"
                    else:
                        probabilities, details = _readout(
                            dict(cached), vocabulary, native_vocabulary, cfg
                        )
        prepared.append((row, probabilities, details, reason))
    matcher = SimpleNamespace(
        targets={target["id"]: target for target in targets}, metadata=metadata
    )

    def records_for(threshold):
        matcher.metadata["thresholds"] = threshold
        result = []
        for row, probabilities, details, reason in prepared:
            target = next(
                (
                    target
                    for target in targets
                    if all(str(target[key]) == str(row[key]) for key in COMPONENTS)
                ),
                None,
            )
            expected = [
                vocabulary[key].index(str(row[key])) if str(row[key]) in vocabulary[key] else -1
                for key in COMPONENTS
            ]
            status = (
                "unavailable"
                if target is None
                else native_decision(probabilities, details, expected, threshold)
            )
            result.extend(
                compare_targets(
                    row,
                    matcher,
                    {
                        "status": status,
                        "reason": reason,
                        "internalEvidence": _evidence(probabilities, details),
                    },
                )
            )
        return result

    candidates = []
    for index, threshold in enumerate(thresholds):
        measured = metrics(records_for(threshold))
        violations = [
            check["rate"] / check["limit"] if check["rate"] is not None else math.inf
            for check in measured["gates"]["checks"]
        ]
        rank = (
            max(violations),
            sum(violations),
            -measured["positive"]["accepted"]["count"],
            threshold["probability"],
            threshold["margin"],
        )
        candidates.append({"thresholds": threshold, "metrics": measured, "selectionRank": rank})
        print(
            json.dumps({"calibratedThreshold": index + 1, "total": 15, "model": name}), flush=True
        )
    selected = min(candidates, key=lambda candidate: tuple(candidate["selectionRank"]))
    metadata["thresholds"] = selected["thresholds"]
    metadata["calibrationRows"] = len(calibration)
    metadata["calibrationSpeakers"] = len({row["speakerId"] for row in calibration})
    output.mkdir(parents=True)
    write(output / "model.json", metadata)
    write(
        output / "calibration.json",
        {"selected": selected, "candidates": candidates, "testUsed": False},
    )
    write(output / "calibration-records.json", records_for(selected["thresholds"]))
    return {"model": name, "thresholds": selected["thresholds"], "metrics": selected["metrics"]}


def bundle(calibration: Path, model: Path, output: Path, *, quantized_model: Path | None = None):
    """Copy verified local source/derivative weights and license notices only."""
    if output.exists():
        raise ValueError("BUNDLE_DESTINATION_ALREADY_EXISTS")
    metadata = json.loads((calibration / "model.json").read_text())
    name = metadata["model"]
    if metadata["headKind"] != "native-ctc" or metadata["testUsed"] is not False:
        raise ValueError("NATIVE_CTC_CALIBRATION_METADATA_INVALID")
    from pinyin_matcher.pretrained_experiment import cache_identity

    identity = cache_identity(name, model)
    if identity.get("derivative") != metadata["acousticDerivative"]:
        raise ValueError("NATIVE_CTC_SOURCE_DERIVATIVE_CHANGED")
    if metadata["acousticDerivative"]:
        tuned = json.loads((model / "tuned.json").read_text())
        resources = {filename: record["sha256"] for filename, record in tuned["files"].items()}
        resources["tuned.json"] = metadata["acousticDerivative"]["metadataSha256"]
    else:
        resources = {record["path"]: record["sha256"] for record in identity["model"]["files"]}
    source_model = model
    if quantized_model is not None:
        if name != "sensevoice" or not metadata["acousticDerivative"]:
            raise ValueError("NATIVE_CTC_QUANTIZED_BACKEND_REQUIRES_SENSEVOICE_DERIVATIVE")
        quantized = json.loads((quantized_model / "tuned.json").read_text())
        parent = quantized_model / "parent-tuned.json"
        if (
            quantized.get("architecture") != "sensevoice-50-ctc-int8-v1"
            or fingerprint(parent) != metadata["acousticDerivative"]["metadataSha256"]
            or quantized.get("parentTunedMetadataSha256") != fingerprint(parent)
            or quantized.get("parentTunedWeightSha256")
            != tuned["files"]["tuned.safetensors"]["sha256"]
            or quantized["sourceRevision"] != identity["model"]["revision"]
            or quantized["parentWeightSha256"] != tuned["parentWeightSha256"]
            or "encoder.int8.onnx" not in quantized["files"]
            or "parent-tuned.json" not in quantized["files"]
        ):
            raise ValueError("NATIVE_CTC_QUANTIZED_PARENT_IDENTITY_MISMATCH")
        resources = {filename: record["sha256"] for filename, record in quantized["files"].items()}
        resources["tuned.json"] = fingerprint(quantized_model / "tuned.json")
        metadata["encoderBackend"] = "sensevoice-ctc-int8"
        metadata["acousticDerivative"] = {
            "metadataSha256": resources["tuned.json"],
            "weightSha256": resources["encoder.int8.onnx"],
            "parentWeightSha256": quantized["parentWeightSha256"],
            "sourceRevision": quantized["sourceRevision"],
            "architecture": quantized["architecture"],
            "parentFineTuneMetadataSha256": fingerprint(parent),
        }
        metadata["quantization"] = {
            "parentCalibrationSha256": fingerprint(calibration / "model.json"),
            "thresholdsChanged": False,
            "calibrationReusedForThresholdSelection": False,
            "method": "Exported ONNX CPU graph with dynamic INT8 quantization",
            "sourceMetadata": quantized,
        }
        source_model = quantized_model
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-ctc-bundle-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for filename, expected in resources.items():
            source = (source_model / filename).resolve()
            if not source.is_relative_to(source_model.resolve()) or fingerprint(source) != expected:
                raise ValueError("NATIVE_CTC_SOURCE_FILE_CHANGED")
            destination = stage / "encoder" / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        for license_file in (
            (ROOT / "resources/licenses").glob("SenseVoice-*.txt") if name == "sensevoice" else []
        ):
            destination = stage / "licenses" / license_file.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(license_file, destination)
        (stage / "MODEL_LICENSE_NOTICE.json").write_text(
            json.dumps(
                {
                    "sourceRepository": identity["model"]["repository"],
                    "sourceRevision": identity["model"]["revision"],
                    "declaredLicense": identity["model"]["license"],
                    "licenseEvidence": identity["model"]["licenseEvidence"],
                    "scope": (
                        "Local research CPU bundle; source model cards and license texts preserved"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        metadata["packageFiles"] = {
            str(path.relative_to(stage)): {
                "sha256": fingerprint(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        metadata["packageBytes"] = sum(
            record["bytes"] for record in metadata["packageFiles"].values()
        )
        (stage / "model.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        stage.rename(output)
    return {"directory": str(output.resolve()), "modelSha256": fingerprint(output / "model.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--name", required=True, choices=["hanziflow", "sensevoice"])
    calibration.add_argument("--manifest", required=True, type=Path)
    calibration.add_argument("--cache", required=True, type=Path)
    calibration.add_argument("--model", required=True, type=Path)
    calibration.add_argument("--output", required=True, type=Path)
    packing = sub.add_parser("bundle")
    packing.add_argument("--calibration", required=True, type=Path)
    packing.add_argument("--model", required=True, type=Path)
    packing.add_argument("--output", required=True, type=Path)
    packing.add_argument("--quantized-model", type=Path)
    inference = sub.add_parser("match")
    inference.add_argument("--model", required=True, type=Path)
    inference.add_argument("--target", required=True)
    inference.add_argument("--wav", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "calibrate":
        result = calibrate(args.name, args.manifest, args.cache, args.model, args.output)
    elif args.action == "bundle":
        result = bundle(
            args.calibration, args.model, args.output, quantized_model=args.quantized_model
        )
    else:
        result = NativeCTCMatcher(args.model).match(
            args.target, args.wav.read_bytes(), evidence=True
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
