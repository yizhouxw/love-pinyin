"""Reproducible calibration-only pressure cases from expert-annotated real speech.

No model-based selection, frozen test audio, TTS labels or threshold changes.
Repeated queries share an actual-payload SHA unit and cannot inflate evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from pinyin_matcher.audio import AudioRejected, decode_wav, encode_wav, quality_check
from pinyin_matcher.catalog import ROOT, fingerprint

PROTOCOL = ROOT / "content/pronunciation-pretrained-stress.json"
STATUSES = {"matched", "retry", "uncertain", "unavailable"}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def load_protocol(path: Path = PROTOCOL) -> dict:
    data = json.loads(path.read_text())
    if data["phase"] != "calibration-diagnostic" or data["establishesFinalAcceptance"] is not False:
        raise ValueError("CALIBRATION_STRESS_IS_NOT_FINAL_ACCEPTANCE")
    expected = {
        "cleanExplicitRejection": 0.1,
        "cleanAbstentionIncludingUnavailable": 0.2,
        "multiSyllableFalseAcceptance": 0.05,
        "unassessableInputMatched": 0,
        "unassessableInputExplicitRetry": 0,
    }
    if data["limits"] != expected or data["sourceSplit"] != "calibration":
        raise ValueError("STRESS_PROTOCOL_LIMIT_OR_SPLIT_CHANGED")
    return data


def _key(row: dict) -> tuple[str, str, str]:
    return tuple(str(row[k]) for k in ("onset", "rime", "tone"))


def common_targets(packages: list[Path], manifest_sha: str) -> tuple[dict, list[dict]]:
    records, mappings = [], []
    for package in packages:
        path = package / "model.json"
        metadata = json.loads(path.read_text())
        if metadata.get("manifestSha256") != manifest_sha:
            raise ValueError("STRESS_PACKAGE_WAS_NOT_BUILT_FROM_THIS_SOURCE_MANIFEST")
        targets = {_key(t): t["id"] for t in metadata["coveredTargets"]}
        mappings.append(targets)
        records.append(
            {
                "package": str(package.resolve()),
                "model": metadata["model"],
                "metadataSha256": fingerprint(path),
            }
        )
    if len(mappings) < 3:
        raise ValueError("STRESS_COMPARISON_REQUIRES_AT_LEAST_THREE_PACKAGES")
    keys = set.intersection(*(set(m) for m in mappings))
    # Every model must expose the same canonical target ID for each source.
    return {k: mappings[0][k] for k in keys if len({m[k] for m in mappings}) == 1}, records


def select_sources(
    rows: list[dict], protocol: dict, targets: dict, base: Path
) -> tuple[list, dict]:
    """Inspect calibration metadata/audio only; other splits are never opened."""
    by_speaker = defaultdict(list)
    all_calibration_speakers = {r["speakerId"] for r in rows if r["split"] == "calibration"}
    reasons = Counter()
    for row in rows:
        if row["split"] != "calibration":
            continue
        if row.get("expertLabel") != "unanimous-correct":
            reasons["EXPERT_NOT_UNANIMOUS_CORRECT"] += 1
            continue
        ratings = row.get("expertRatings", {})
        if any(
            not isinstance(ratings.get(key), list)
            or len(ratings[key]) != 3
            or any(str(v) != "1" for v in ratings[key])
            for key in ("onset", "rime", "tone")
        ):
            reasons["RAW_EXPERT_VOTES_NOT_THREE_UNANIMOUS_CORRECT"] += 1
            continue
        if not row.get("expertAnnotationResolved", False):
            reasons["EXPERT_ANNOTATION_UNRESOLVED"] += 1
            continue
        if row.get("labelPolicyFlags") or row.get("numericalQualityFlags"):
            reasons["PREDECLARED_POLICY_OR_NUMERICAL_FLAG"] += 1
            continue
        if not row.get("alignment", {}).get("available", False) or row.get("alignment", {}).get(
            "flags"
        ):
            reasons["BOUNDARY_UNAVAILABLE"] += 1
            continue
        if _key(row) not in targets:
            reasons["OUTSIDE_COMMON_COVERAGE"] += 1
            continue
        path = Path(row["file"])
        if not path.is_absolute():
            path = base / path
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError("STRESS_SOURCE_SHA256_MISMATCH")
        try:
            samples = decode_wav(payload)
            quality_check(samples)
        except AudioRejected:
            reasons["SOURCE_NUMERIC_AUDIO_UNASSESSABLE"] += 1
            continue
        duration = len(samples) / 16000
        minimum = protocol["sourceRequirements"]["minimumSeconds"]
        maximum = protocol["sourceRequirements"]["maximumSeconds"]
        if not minimum <= duration <= maximum:
            reasons["OUTSIDE_PREDECLARED_CONTROL_DURATION"] += 1
            continue
        by_speaker[row["speakerId"]].append(
            {**row, "absoluteFile": str(path.resolve()), "targetId": targets[_key(row)]}
        )
    seed = protocol["selection"]["seed"]
    count = protocol["selection"]["anchorsPerSpeaker"]
    selected = []
    for speaker in sorted(all_calibration_speakers):
        candidates = by_speaker[speaker]
        ordered = sorted(
            candidates,
            key=lambda r: hashlib.sha256(f"{seed}:{speaker}:{r['id']}".encode()).hexdigest(),
        )
        if len(ordered) < count:
            raise ValueError("STRESS_CALIBRATION_SPEAKER_HAS_TOO_FEW_ELIGIBLE_SOURCES")
        for anchor in ordered[:count]:
            partner = next(
                (
                    r
                    for r in ordered
                    if r["parentSha256"] != anchor["parentSha256"] and _key(r) != _key(anchor)
                ),
                None,
            )
            if partner is None:
                raise ValueError("STRESS_DISTINCT_UTTERANCE_PARTNER_REQUIRED")
            selected.append((anchor, partner))
    if not selected:
        raise ValueError("STRESS_NO_ELIGIBLE_CALIBRATION_SOURCES")
    return selected, {
        "allCalibrationSpeakers": len(all_calibration_speakers),
        "eligibleSpeakers": sum(bool(rows) for rows in by_speaker.values()),
        "eligibleWords": sum(map(len, by_speaker.values())),
        "anchors": len(selected),
        "eligibilityExclusionCounts": dict(reasons),
    }


def noise_payload(samples: np.ndarray, snr_db: float, seed: int) -> tuple[bytes, dict]:
    rng = np.random.Generator(np.random.PCG64(seed))
    noise = rng.standard_normal(len(samples)).astype(np.float32)
    speech_rms = float(np.sqrt(np.mean(samples * samples)))
    noise *= speech_rms / (10 ** (snr_db / 20) * float(np.sqrt(np.mean(noise * noise))))
    mixed = samples + noise
    gain = min(1, 0.8 / max(float(np.abs(mixed).max()), 1e-9))
    measured = 20 * math.log10(speech_rms / float(np.sqrt(np.mean(noise * noise))))
    return encode_wav(mixed * gain), {
        "noiseSeed": seed,
        "snrDb": snr_db,
        "prePcmMeasuredSnrDb": measured,
        "jointGain": gain,
        "rng": "NumPy Generator PCG64",
    }


def wrong_rate_payload(samples: np.ndarray, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        handle.writeframes((samples * 32767).astype("<i2").tobytes())
    return out.getvalue()


def source_lineage(source: dict, pipeline_snapshot: Path | None) -> dict:
    """Bind actual preparation code while checking corrected phonetic semantics."""
    from pinyin_matcher.pretrained_native import native_rime_aliases

    mapping = source.get("alignmentMapping", {})
    aliases = native_rime_aliases("hanziflow")
    alias_sha = hashlib.sha256(
        json.dumps(aliases, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    registry = json.loads((ROOT / "content/pronunciation-pretrained-models.json").read_text())
    schema_sha = next(
        f["sha256"]
        for f in registry["models"]["hanziflow"]["files"]
        if f["path"] == "v2_1_target_schema.json"
    )
    if (
        source.get("version") != "ompal-three-head-midpoint-v2-model-specific-apical"
        or mapping.get("model") != "hanziflow"
        or mapping.get("aliases") != aliases
        or mapping.get("aliasesSha256") != alias_sha
        or mapping.get("upstreamTargetSchemaSha256") != schema_sha
        or source.get("alignerSha256")
        != fingerprint(Path(__file__).with_name("pretrained_align.py"))
    ):
        raise ValueError("STRESS_SOURCE_BOUNDARIES_DO_NOT_MATCH_CURRENT_IMPLEMENTATION")
    current_sha = fingerprint(Path(__file__).with_name("pretrained_ompal_clips.py"))
    old_sha = source.get("pipelineSha256")
    snapshot_sha = fingerprint(pipeline_snapshot) if pipeline_snapshot is not None else None
    if old_sha != current_sha and snapshot_sha != old_sha:
        raise ValueError("STRESS_ORIGINAL_PIPELINE_SNAPSHOT_REQUIRED")
    return {
        "pipelineSha256AtPreparation": old_sha,
        "currentPipelineSha256": current_sha,
        "pipelineChangedSincePreparation": old_sha != current_sha,
        "pipelineSnapshot": str(pipeline_snapshot.resolve()) if pipeline_snapshot else None,
        "pipelineSnapshotSha256": snapshot_sha,
        "alignmentMapping": mapping,
        "currentAliasConfigurationSha256": fingerprint(
            ROOT / "content/pronunciation-pretrained-experiment.json"
        ),
        "semanticAliasesMatchCurrentConfiguration": True,
        "alignerSha256": source["alignerSha256"],
        "provenanceNote": (
            "Original calibration preparation code is preserved by exact SHA. "
            "Subsequent source changes add frozen-test verification and output lineage; "
            "the original manifest and model training hashes are unchanged."
        ),
    }


def prepare(
    manifest: Path,
    packages: list[Path],
    output: Path,
    *,
    expected_source_sha: str,
    protocol_path: Path = PROTOCOL,
    source_pipeline_snapshot: Path | None = None,
) -> dict:
    protocol = load_protocol(protocol_path)
    if (output / "manifest.json").exists():
        raise ValueError("STRESS_PREPARATION_OUTPUT_ALREADY_EXISTS")
    if fingerprint(manifest) != expected_source_sha:
        raise ValueError("STRESS_EXPECTED_SOURCE_MANIFEST_SHA_MISMATCH")
    source = json.loads(manifest.read_text())
    if source.get("frozenTestIncluded"):
        raise ValueError("STRESS_MUST_NOT_OPEN_FROZEN_TEST_COHORT")
    lineage = source_lineage(source, source_pipeline_snapshot)
    targets, package_records = common_targets(packages, expected_source_sha)
    selected, selection_info = select_sources(source["items"], protocol, targets, manifest.parent)
    cases, source_records = [], {}
    rules = protocol["cases"]

    def add(anchor, kind, suffix, payload, parents, parameters, target_ids=None):
        digest = hashlib.sha256(payload).hexdigest()
        file = output / "payloads" / (digest + ".bin")
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.exists() and fingerprint(file) != digest:
            raise ValueError("STRESS_PAYLOAD_CACHE_CORRUPTED")
        if not file.exists():
            file.write_bytes(payload)
        case_id = f"{anchor['id']}-{kind}-{suffix}"
        cases.append(
            {
                "id": case_id,
                "kind": kind,
                "unitId": digest,
                "file": str(file.resolve()),
                "sha256": digest,
                "split": "calibration",
                "speakerId": anchor["speakerId"],
                "sourceWordIds": [p["id"] for p in parents],
                "parentSha256": [p["sha256"] for p in parents],
                "parentUtteranceSha256": [p["parentSha256"] for p in parents],
                "source": "OMPAL-expert-unanimous-real-speech-derived-stress",
                "targetIds": sorted(set(target_ids or [anchor["targetId"]])),
                "expectedBehavior": protocol["outcomes"][kind],
                "parameters": parameters,
            }
        )

    for anchor, partner in selected:
        for row in (anchor, partner):
            source_records[row["id"]] = {
                key: row.get(key)
                for key in (
                    "id",
                    "speakerId",
                    "sourceUtteranceId",
                    "sha256",
                    "parentSha256",
                    "expectedPinyin",
                    "expertRatings",
                    "expertLabel",
                    "alignment",
                    "labelPolicyFlags",
                )
            }
        samples = decode_wav(Path(anchor["absoluteFile"]).read_bytes())
        other = decode_wav(Path(partner["absoluteFile"]).read_bytes())
        add(
            anchor,
            "clean-control",
            "original",
            Path(anchor["absoluteFile"]).read_bytes(),
            [anchor],
            {"transform": "none"},
        )
        for gap in rules["twoSyllablePauseSeconds"]:
            payload = encode_wav(
                np.concatenate([samples, np.zeros(round(gap * 16000), dtype=np.float32), other])
            )
            add(
                anchor,
                "two-syllable",
                str(gap),
                payload,
                [anchor, partner],
                {
                    "pauseSeconds": gap,
                    "knownSyllableCount": 2,
                    "limitation": (
                        "Two expert-correct word clips concatenated; "
                        "not newly recorded connected speech."
                    ),
                },
                [anchor["targetId"], partner["targetId"]],
            )
        add(
            anchor,
            "omission-silence",
            "blank",
            encode_wav(np.zeros(round(rules["omissionSilenceSeconds"] * 16000), dtype=np.float32)),
            [anchor],
            {"seconds": rules["omissionSilenceSeconds"], "pronunciationErrorLabel": None},
        )
        for snr in rules["noiseSnrDb"]:
            seed = int(
                hashlib.sha256(
                    f"{protocol['selection']['seed']}:{anchor['id']}:{snr}".encode()
                ).hexdigest()[:16],
                16,
            )
            payload, parameters = noise_payload(samples, snr, seed)
            add(anchor, "noise", str(snr), payload, [anchor], parameters)
        for seconds in rules["overlongSeconds"]:
            add(
                anchor,
                "overlong",
                str(seconds),
                encode_wav(np.resize(samples, round(seconds * 16000))),
                [anchor],
                {
                    "seconds": seconds,
                    "transform": "repeat-for-duration-contract-only",
                    "pronunciationErrorLabel": None,
                },
            )
        add(
            anchor,
            "too-short",
            "duration",
            encode_wav(samples[: round(rules["tooShortSeconds"] * 16000)]),
            [anchor],
            {"seconds": rules["tooShortSeconds"]},
        )
        add(
            anchor,
            "wrong-sample-rate",
            str(rules["wrongSampleRate"]),
            wrong_rate_payload(samples, rules["wrongSampleRate"]),
            [anchor],
            {"headerSampleRate": rules["wrongSampleRate"], "pronunciationErrorLabel": None},
        )
        add(
            anchor,
            "truncated-wav",
            "shortened",
            encode_wav(samples)[: -rules["truncatedWavRemoveBytes"]],
            [anchor],
            {"removedBytes": rules["truncatedWavRemoveBytes"]},
        )
        add(
            anchor,
            "non-wav",
            "invalid",
            rules["nonWavPayloadUtf8"].encode(),
            [anchor],
            {"encoding": "invalid-audio-UTF8"},
        )
    result = {
        "schemaVersion": 1,
        "phase": "calibration-diagnostic",
        "establishesFinalAcceptance": False,
        "protocol": protocol,
        "protocolSha256": fingerprint(protocol_path),
        "preparerCodeSha256": fingerprint(Path(__file__)),
        "sourceManifest": str(manifest.resolve()),
        "sourceManifestSha256": expected_source_sha,
        "pipelineSha256": source["pipelineSha256"],
        "alignerSha256": source["alignerSha256"],
        "sourceCodeLineage": lineage,
        "packagesAtPreparation": package_records,
        "selection": selection_info,
        "sources": list(source_records.values()),
        "cases": cases,
        "caseCounts": dict(Counter(c["kind"] for c in cases)),
        "actualPayloadUnits": len({c["sha256"] for c in cases}),
        "duplicatePayloadCases": len(cases) - len({c["sha256"] for c in cases}),
        "independentUtteranceRoots": len({r["parentSha256"] for r in source_records.values()}),
    }
    write_json(output / "manifest.json", result)
    return result


def wilson(count: int, denominator: int) -> dict:
    if not denominator:
        return {"count": count, "denominator": 0, "rate": None, "wilson95": None}
    z = 1.959963984540054
    p = count / denominator
    center = (p + z * z / (2 * denominator)) / (1 + z * z / denominator)
    half = (
        z
        * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator**2))
        / (1 + z * z / denominator)
    )
    return {
        "count": count,
        "denominator": denominator,
        "rate": p,
        "wilson95": [center - half, center + half],
    }


def build_report(data: dict, predictions: list[dict], *, model_available: bool) -> dict:
    allowed = {(case["id"], target) for case in data["cases"] for target in case["targetIds"]}
    by_key = {}
    for row in predictions:
        key = (row["caseId"], row["targetId"])
        if key not in allowed:
            raise ValueError("STRESS_UNPLANNED_RESULT")
        if key in by_key:
            raise ValueError("STRESS_DUPLICATE_RESULT")
        by_key[key] = row
    complete, missing = [], 0
    for case in data["cases"]:
        for target in case["targetIds"]:
            row = by_key.get((case["id"], target))
            if row is None:
                missing += 1
                row = {
                    "caseId": case["id"],
                    "targetId": target,
                    "status": "unavailable",
                    "reason": "STRESS_RESULT_MISSING",
                }
            if row["status"] not in STATUSES:
                raise ValueError("STRESS_UNKNOWN_STATUS")
            complete.append(
                {
                    **row,
                    "kind": case["kind"],
                    "unitId": case["sha256"],
                    "expectedBehavior": case["expectedBehavior"],
                }
            )
    by_kind = {}
    for kind in sorted({c["kind"] for c in data["cases"]}):
        rows = [r for r in complete if r["kind"] == kind]
        units = defaultdict(list)
        for row in rows:
            units[row["unitId"]].append(row)
        by_kind[kind] = {
            "queries": len(rows),
            "actualPayloadUnits": len(units),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "matchedUnits": wilson(
                sum(any(r["status"] == "matched" for r in group) for group in units.values()),
                len(units),
            ),
            "explicitRetryUnits": wilson(
                sum(any(r["status"] == "retry" for r in group) for group in units.values()),
                len(units),
            ),
            "abstentionUnits": wilson(
                sum(
                    all(r["status"] in {"uncertain", "unavailable"} for r in group)
                    for group in units.values()
                ),
                len(units),
            ),
            "reasons": dict(Counter(r.get("reason") for r in rows if r.get("reason"))),
        }
    combined_units = defaultdict(list)
    for row in complete:
        combined_units[row["unitId"]].append(row)
    if any(len({r["expectedBehavior"] for r in group}) != 1 for group in combined_units.values()):
        raise ValueError("STRESS_PAYLOAD_HAS_CONFLICTING_EXPECTED_BEHAVIOR")
    overall_by_behavior = {}
    for behavior in {c["expectedBehavior"] for c in data["cases"]}:
        groups = [g for g in combined_units.values() if g[0]["expectedBehavior"] == behavior]
        overall_by_behavior[behavior] = {
            "actualPayloadUnits": len(groups),
            "matchedUnits": wilson(
                sum(any(r["status"] == "matched" for r in g) for g in groups), len(groups)
            ),
            "explicitRetryUnits": wilson(
                sum(any(r["status"] == "retry" for r in g) for g in groups), len(groups)
            ),
            "abstentionUnits": wilson(
                sum(all(r["status"] in {"uncertain", "unavailable"} for r in g) for g in groups),
                len(groups),
            ),
        }
    limits = data["protocol"]["limits"]
    checks = {"modelAvailable": model_available, "completeResults": missing == 0}
    for kind, report in by_kind.items():
        behavior = data["protocol"]["outcomes"][kind]
        if behavior == "accept":
            checks[kind + ":explicitRejection"] = (
                report["explicitRetryUnits"]["rate"] <= limits["cleanExplicitRejection"]
            )
            checks[kind + ":abstention"] = (
                report["abstentionUnits"]["rate"] <= limits["cleanAbstentionIncludingUnavailable"]
            )
        elif behavior == "do-not-match":
            checks[kind + ":falseAcceptance"] = (
                report["matchedUnits"]["rate"] <= limits["multiSyllableFalseAcceptance"]
            )
        else:
            checks[kind + ":matched"] = (
                report["matchedUnits"]["rate"] <= limits["unassessableInputMatched"]
            )
            checks[kind + ":explicitRetry"] = (
                report["explicitRetryUnits"]["rate"] <= limits["unassessableInputExplicitRetry"]
            )
    return {
        "schemaVersion": 1,
        "phase": "calibration-diagnostic",
        "establishesFinalAcceptance": False,
        "plannedCases": len(data["cases"]),
        "plannedQueries": len(complete),
        "actualPayloadUnits": len({r["unitId"] for r in complete}),
        "missingResults": missing,
        "overallByExpectedBehavior": overall_by_behavior,
        "byKind": by_kind,
        "checks": checks,
        "stressChecksPassed": all(checks.values()),
        "predictions": complete,
        "limits": limits,
        "limitations": [
            "Derived siblings share sources and speakers; Wilson intervals are descriptive only.",
            "This calibration stress report cannot establish frozen-test or child accuracy.",
            "Silence/noise/invalid inputs have no child-pronunciation error label.",
        ],
    }


def evaluate(manifest: Path, package: Path, output: Path) -> dict:
    from pinyin_matcher.pretrained_runtime import load_matcher

    if output.exists():
        raise ValueError("STRESS_EVALUATION_OUTPUT_ALREADY_EXISTS")
    data = json.loads(manifest.read_text())
    current_protocol = load_protocol()  # No relaxed inline copy can replace the fixed protocol.
    if data["protocol"] != current_protocol:
        raise ValueError("STRESS_INLINE_PROTOCOL_MISMATCH")
    if any(c["expectedBehavior"] != current_protocol["outcomes"][c["kind"]] for c in data["cases"]):
        raise ValueError("STRESS_CASE_OUTCOME_MISMATCH")
    if fingerprint(Path(data["sourceManifest"])) != data["sourceManifestSha256"]:
        raise ValueError("STRESS_SOURCE_CHANGED_SINCE_PREPARATION")
    lineage = data["sourceCodeLineage"]
    if (
        lineage["pipelineSnapshot"]
        and fingerprint(Path(lineage["pipelineSnapshot"])) != lineage["pipelineSnapshotSha256"]
    ):
        raise ValueError("STRESS_ORIGINAL_PIPELINE_SNAPSHOT_CHANGED")
    if data["phase"] != "calibration-diagnostic" or any(
        c["split"] != "calibration" for c in data["cases"]
    ):
        raise ValueError("STRESS_EVALUATION_IS_CALIBRATION_ONLY")
    if data["protocolSha256"] != fingerprint(PROTOCOL):
        raise ValueError("STRESS_PROTOCOL_DIGEST_MISMATCH")
    metadata_path = package / "model.json"
    metadata_sha = fingerprint(metadata_path)
    if metadata_sha not in {p["metadataSha256"] for p in data["packagesAtPreparation"]}:
        raise ValueError("STRESS_PACKAGE_CHANGED_SINCE_PREPARATION")
    matcher = load_matcher(package)
    available = matcher.info()["status"] == "available"
    records = []
    started = time.perf_counter()
    for index, case in enumerate(data["cases"], 1):
        path = Path(case["file"])
        if fingerprint(path) != case["sha256"]:
            raise ValueError("STRESS_PAYLOAD_DIGEST_MISMATCH")
        payload = path.read_bytes()
        for target in case["targetIds"]:
            begin = time.perf_counter()
            result = matcher.match(target, payload)
            records.append(
                {
                    "caseId": case["id"],
                    "targetId": target,
                    "status": result["status"],
                    "reason": result.get("reason"),
                    "elapsedMilliseconds": (time.perf_counter() - begin) * 1000,
                }
            )
        if index % 50 == 0:
            print(
                json.dumps({"stressCasesEvaluated": index, "totalCases": len(data["cases"])}),
                flush=True,
            )
    report = build_report(data, records, model_available=available)
    report.update(
        {
            "manifestSha256": fingerprint(manifest),
            "protocolSha256": data["protocolSha256"],
            "package": str(package.resolve()),
            "metadataSha256": metadata_sha,
            "sourceManifestSha256": data["sourceManifestSha256"],
            "modelInfo": matcher.info(),
            "elapsedSeconds": time.perf_counter() - started,
            "device": "cpu",
            "threads": 2,
            "runtimeCodeSha256": fingerprint(Path(__file__).with_name("pretrained_runtime.py")),
        }
    )
    if fingerprint(metadata_path) != metadata_sha:
        report["stressChecksPassed"] = False
        report["checks"]["packageStableDuringEvaluation"] = False
    write_json(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--manifest", type=Path, required=True)
    prep.add_argument("--expected-source-sha256", required=True)
    prep.add_argument("--package", type=Path, action="append", required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--source-pipeline-snapshot", type=Path)
    run = sub.add_parser("evaluate")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--package", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = (
        prepare(
            args.manifest,
            args.package,
            args.output,
            expected_source_sha=args.expected_source_sha256,
            source_pipeline_snapshot=args.source_pipeline_snapshot,
        )
        if args.action == "prepare"
        else evaluate(args.manifest, args.package, args.output)
    )
    print(
        json.dumps(
            {
                "cases": len(data.get("cases", [])),
                "queries": data.get("plannedQueries"),
                "stressChecksPassed": data.get("stressChecksPassed", False),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
