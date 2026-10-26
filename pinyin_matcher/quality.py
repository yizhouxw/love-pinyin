"""Frozen, source-stratified pronunciation quality gates; never calibrates models.

An evaluation manifest declares sources and individual positive/negative cases before
execution. Multiple negative target pairs for one audio unit count as one trial with
an ``any matched`` failure, so easy negatives cannot dilute a hard false acceptance.
"""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint

STATUSES = ("matched", "retry", "uncertain", "unavailable")
PROTOCOL_FILE = ROOT / "content/pronunciation-quality-protocol-v2.json"
PROTOCOL = json.loads(PROTOCOL_FILE.read_text())
PROTOCOL_VERSION = PROTOCOL["protocolVersion"]
PROTOCOL_SHA256 = fingerprint(PROTOCOL_FILE)
LIMITS = dict(PROTOCOL["qualityLimits"])
NEGATIVE_CASES = {
    "cross-language-acoustic-mismatch": (
        "A documented phoneme, tone or syllable-count mismatch; "
        "a language/dialect label alone is insufficient."
    ),
    "near-phoneme": "A different onset/rime or unsupported phoneme, independent of language name.",
    "tone": "The same syllable with a different acoustic lexical tone.",
    "extra-syllable": "Additional spoken syllables beyond the requested single syllable.",
    "non-speech": "Silence/noise without the requested speech.",
}


def assert_protocol(expected_sha256: str | None = None):
    if (
        PROTOCOL_VERSION != 2
        or fingerprint(PROTOCOL_FILE) != PROTOCOL_SHA256
        or expected_sha256 is not None
        and expected_sha256 != PROTOCOL_SHA256
    ):
        raise ValueError("QUALITY_PROTOCOL_CHANGED_OR_UNSUPPORTED")


def validate_case_semantics(case: dict):
    """Language is provenance; it never determines a negative label."""
    if case.get("case") in NEGATIVE_CASES and case.get("expectedMatch") is not False:
        raise ValueError("NEGATIVE_CASE_REQUIRES_EXPLICIT_ACOUSTIC_MISMATCH")
    if case.get("case") == "cross-language-acoustic-mismatch" and (
        case.get("mismatchBasis") not in {"phoneme", "tone", "syllable-count"}
        or not isinstance(case.get("mismatchDescription"), str)
        or not case["mismatchDescription"].strip()
    ):
        raise ValueError("LANGUAGE_LABEL_IS_NOT_ACOUSTIC_MISMATCH")


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def _evaluation_code() -> dict[str, str]:
    directory = Path(__file__).parent
    return {
        name: fingerprint(directory / name)
        for name in (
            "quality.py",
            "inference.py",
            "audio.py",
            "contour.py",
            "catalog.py",
            "decision_v3.py",
            "pitch_v2.py",
            "pitch_swift.py",
        )
    }


def _model_snapshot(directory: Path) -> dict:
    metadata_path = directory / "model.json"
    metadata = json.loads(metadata_path.read_text())
    files = {"model.json": fingerprint(metadata_path)}
    for key in ("file", "catalogFile"):
        if metadata.get(key):
            path = (directory / metadata[key]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("MODEL_PATH_INVALID")
            files[metadata[key]] = fingerprint(path)
    if metadata.get("pitchTone"):
        filename = metadata["pitchTone"]["file"]
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("MODEL_PATH_INVALID")
        files[filename] = fingerprint(path)
        if metadata["pitchTone"].get("tracker"):
            tracker = metadata["pitchTone"]["tracker"]
            tracker_path = (directory / tracker["file"]).resolve()
            if not tracker_path.is_relative_to(directory.resolve()):
                raise ValueError("MODEL_PATH_INVALID")
            digest = fingerprint(tracker_path)
            if digest != tracker["sha256"]:
                raise ValueError("PITCH_TRACKER_DIGEST_MISMATCH")
            files[tracker["file"]] = digest
            if tracker.get("licenseFile"):
                license_path = (directory / tracker["licenseFile"]).resolve()
                if (
                    not license_path.is_relative_to(directory.resolve())
                    or fingerprint(license_path) != tracker["licenseSha256"]
                ):
                    raise ValueError("PITCH_TRACKER_LICENSE_DIGEST_MISMATCH")
                files[tracker["licenseFile"]] = fingerprint(license_path)
    return {
        "files": files,
        "version": metadata["version"],
        "coveredTargetIds": metadata["coveredTargetIds"],
        "thresholds": metadata["thresholds"],
    }


def _lineage(row: dict) -> set[tuple[str, str]]:
    return {
        (
            "wave"
            if field
            in {"sha256", "referenceSha256", "parentSha256", "sourceSha256", "sourceWavSha256"}
            else "root"
            if field in {"referenceRootId", "sourceRootId", "parentRootId"}
            else field,
            str(row[field]),
        )
        for field in (
            "sha256",
            "voiceFamilyId",
            "referenceRootId",
            "referenceSha256",
            "sourceRootId",
            "parentRootId",
            "parentSha256",
            "sourceSha256",
            "sourceWavSha256",
        )
        if row.get(field)
    }


def freeze_plan(
    model: Path,
    manifest: Path,
    *,
    calibration_manifests: list[Path],
    output: Path,
) -> dict:
    """Freeze model, cases, provenance and exclusions before looking at outputs.

    ``sources`` map source names to ``usage`` (unseen/diagnostic),
    ``labelProvenance`` and ``requireBothClasses``. A case has id, source, case,
    unitId, targetId, expectedMatch, clearAudio, file and sha256. Whether an audio
    is clear must be declared here, never inferred from model acceptance.
    """
    if output.exists():
        raise ValueError("FROZEN_PLAN_ALREADY_EXISTS")
    assert_protocol()
    data = json.loads(manifest.read_text())
    if data.get("schemaVersion") != 1 or not data.get("sources") or not data.get("cases"):
        raise ValueError("QUALITY_MANIFEST_INVALID")
    for source in data["sources"].values():
        if source.get("usage") not in {"unseen", "diagnostic"} or not source.get("labelProvenance"):
            raise ValueError("SOURCE_PROVENANCE_REQUIRED")
        if type(source.get("requireBothClasses", True)) is not bool:
            raise ValueError("SOURCE_PROVENANCE_INVALID")
    used_lineage = set()
    calibration = []
    for path in calibration_manifests:
        source = json.loads(path.read_text())
        rows = source.get("items", source.get("cases", []))
        used = [row for row in rows if row.get("split") != "test"]
        if not used:
            raise ValueError("CALIBRATION_PROVENANCE_REQUIRED")
        for row in used:
            used_lineage.update(_lineage(row))
        calibration.append(
            {"path": str(path.resolve()), "sha256": fingerprint(path), "rows": len(used)}
        )
    if not calibration:
        raise ValueError("CALIBRATION_PROVENANCE_REQUIRED")
    seen, audio_units = set(), {}
    cases = []
    for case in data["cases"]:
        if (
            not all(
                isinstance(case.get(key), str) and case[key]
                for key in ("id", "source", "case", "unitId", "targetId", "file", "sha256")
            )
            or case["source"] not in data["sources"]
            or type(case.get("expectedMatch")) is not bool
            or type(case.get("clearAudio")) is not bool
            or case["id"] in seen
            or case.get("split", "test") != "test"
        ):
            raise ValueError("QUALITY_CASE_INVALID")
        seen.add(case["id"])
        validate_case_semantics(case)
        audio_key = (case["source"], case["case"], case["sha256"])
        if audio_units.setdefault(audio_key, case["unitId"]) != case["unitId"]:
            raise ValueError("QUALITY_UNIT_IDENTITY_INVALID")
        path = (manifest.parent / case["file"]).resolve()
        if not path.is_relative_to(manifest.parent.resolve()):
            raise ValueError("QUALITY_AUDIO_PATH_INVALID")
        if fingerprint(path) != case["sha256"]:
            raise ValueError("QUALITY_AUDIO_DIGEST_MISMATCH")
        if _lineage(case) & used_lineage:
            raise ValueError("QUALITY_CALIBRATION_LINEAGE_LEAKAGE")
        cases.append({**case, "file": str(path)})
    # A positive is one specified answer per audio unit within each case group.
    # Duplicate positive pairing is an invalid denominator rather than more data.
    positive_units = [(r["source"], r["case"], r["unitId"]) for r in cases if r["expectedMatch"]]
    if len(positive_units) != len(set(positive_units)):
        raise ValueError("DUPLICATE_POSITIVE_UNIT")
    plan = {
        "schemaVersion": 1,
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": PROTOCOL_SHA256,
        "createdUtc": datetime.now(UTC).isoformat(),
        "purpose": "confirmatory"
        if all(s["usage"] == "unseen" for s in data["sources"].values())
        else "diagnostic",
        "manifestSha256": fingerprint(manifest),
        "evaluationCodeSha256": _evaluation_code(),
        "modelDirectory": str(model.resolve()),
        "model": _model_snapshot(model),
        "calibration": calibration,
        "sources": data["sources"],
        "limits": dict(LIMITS),
        "cases": cases,
        "claims": {
            "realChildAccuracyEstablished": False,
            "sourceUnseenStatusIsDeclaration": True,
            "pointEstimateGatesDoNotEstablishPopulationConfidence": True,
        },
    }
    plan["freezeSha256"] = _digest(plan)
    _write(output, plan)
    return plan


def _rate(count: int, total: int) -> dict:
    if not total:
        return {"count": count, "denominator": 0, "rate": None, "wilson95": None}
    proportion = count / total
    z = 1.959963984540054
    divisor = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / divisor
    radius = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total**2)) / divisor
    return {
        "count": count,
        "denominator": total,
        "rate": proportion,
        "wilson95": [max(0, centre - radius), min(1, centre + radius)],
    }


def _wave(record: dict):
    # Source/case/query metadata never multiplies one waveform's denominator.
    return (
        ("sha256", record["sha256"])
        if record.get("sha256")
        else ("unitId", record.get("rawAudioId") or record["unitId"])
    )


def _parent(record: dict):
    return (
        record.get("sourceRootId")
        or record.get("parentRootId")
        or record.get("parentSha256")
        or record.get("sourceSha256")
        or record.get("sourceWavSha256")
        or _wave(record)
    )


def _grouped(rows: list[dict], identity) -> dict:
    units = defaultdict(list)
    for record in rows:
        units[identity(record)].append(record)
    return units


def _events(positive, clear, negative):
    return {
        "negativeFalseAcceptance": _rate(
            sum(any(r["status"] == "matched" for r in group) for group in negative.values()),
            len(negative),
        ),
        "positiveExplicitRejection": _rate(
            sum(any(r["status"] == "retry" for r in group) for group in positive.values()),
            len(positive),
        ),
        "clearPositiveAbstention": _rate(
            sum(
                any(r["status"] in {"uncertain", "unavailable"} for r in group)
                for group in clear.values()
            ),
            len(clear),
        ),
    }


def _metrics(records: list[dict], limits: dict) -> dict:
    positive = [r for r in records if r["expectedMatch"]]
    clear = [r for r in positive if r["clearAudio"]]
    negative = [r for r in records if not r["expectedMatch"]]

    def worst(group):
        # Correct-target duplicates for one WAV should have identical outcomes;
        # preserve every adverse event in _events even if metadata is duplicated.
        return next(
            status
            for status in ("retry", "unavailable", "uncertain", "matched")
            if any(r["status"] == status for r in group)
        )

    units, positive_units, clear_units = (
        _grouped(rows, _wave) for rows in (negative, positive, clear)
    )
    positive_statuses = [worst(group) for group in positive_units.values()]
    non_speech = _grouped([r for r in negative if r["case"] == "non-speech"], _wave)
    non_speech_errors = sum(
        any(r["status"] == "retry" for r in group) for group in non_speech.values()
    )
    values = _events(positive_units, clear_units, units)
    parent_positive, parent_clear, parent_negative = (
        _grouped(rows, _parent) for rows in (positive, clear, negative)
    )
    report = {
        "protocolVersion": PROTOCOL_VERSION,
        "view": "per-wave-any-wrong-query",
        "pairs": len(records),
        "distinctAudioSha256": len({r["sha256"] for r in records if r.get("sha256")}),
        "positivePairs": len(positive),
        "negativePairs": len(negative),
        "negativeAudioUnits": len(units),
        "positiveAudioUnits": len(positive_units),
        "positiveUnitStatuses": {status: positive_statuses.count(status) for status in STATUSES},
        "statuses": {status: sum(r["status"] == status for r in records) for status in STATUSES},
        "positiveStatuses": {
            status: sum(r["status"] == status for r in positive) for status in STATUSES
        },
        "negativeStatuses": {
            status: sum(r["status"] == status for r in negative) for status in STATUSES
        },
        "reasonCounts": dict(Counter(r.get("reason") or "NONE" for r in records)),
        "gates": {
            name: {
                **value,
                "limit": limits[name],
                "passed": value["rate"] <= limits[name] if value["rate"] is not None else None,
            }
            for name, value in values.items()
        },
        "contracts": {
            "nonSpeechDoesNotJudgeChildWrong": {
                "count": non_speech_errors,
                "denominator": len(non_speech),
                "requiredCount": 0,
                "passed": non_speech_errors == 0 if non_speech else None,
            }
        },
        "parentStressView": {
            "view": "source-parent-any-adverse-derivative",
            "isAcceptanceGate": False,
            "positiveParentUnits": len(parent_positive),
            "negativeParentUnits": len(parent_negative),
            "metrics": _events(parent_positive, parent_clear, parent_negative),
            "adverseEventsAreIndependentCounters": True,
            "positiveAllDerivativesMatched": sum(
                all(r["status"] == "matched" for r in group) for group in parent_positive.values()
            ),
        },
        "intervalInterpretation": (
            "Unadjusted binomial description only; TTS/VC dependence prevents an independent "
            "population-confidence claim."
        ),
    }
    return report


def quality_metrics(records: list[dict]) -> dict:
    """Shared fixed gates for calibration diagnostics and frozen evaluations."""
    return _metrics(records, LIMITS)


def coverage_metrics(records: list[dict]) -> dict:
    """Describe data structure without mistaking correlated derivatives for people."""
    units = {_wave(r) for r in records}
    parents = {
        str(
            r.get("sourceRootId")
            or r.get("parentRootId")
            or r.get("parentSha256")
            or r.get("sourceSha256")
            or r.get("sourceWavSha256")
            or r["unitId"]
        )
        for r in records
    }
    lexical = {r["lexicalRootId"] for r in records if r.get("lexicalRootId")}
    families = {r["voiceFamilyId"] for r in records if r.get("voiceFamilyId")}
    phonetic = {r["sourcePhoneticGroup"] for r in records if r.get("sourcePhoneticGroup")}
    return {
        "pairs": len(records),
        "protocolVersion": PROTOCOL_VERSION,
        "rawAudioUnits": len(units),
        "evaluatedAudioUnits": len(units),
        "distinctWaveforms": len({r["sha256"] for r in records if r.get("sha256")}),
        "parentRootIds": sorted(parents),
        "sourceUtteranceRoots": len(parents),
        "uniqueLexicalRoots": len(lexical) if lexical else None,
        "uniquePhoneticGroups": len(phonetic) if phonetic else None,
        "voiceFamilies": len(families) if families else None,
        "minimumIndependentZeroErrorTrialsForWilson95UpperAtMostFivePercent": 73,
        "minimumTrialExampleIsAnAutomaticGate": False,
        "independentTrialsEstablished": False,
        "limitations": (
            "Word/family reuse, TTS/voice-converted derivatives and environmental augmentation "
            "are correlated. Counts and binomial intervals do not establish population accuracy."
        ),
    }


def build_report(plan: dict, results: list[dict]) -> dict:
    """Apply unchanged gates. Missing/unsupported/errors remain in the denominator."""
    unsigned = {key: value for key, value in plan.items() if key != "freezeSha256"}
    if _digest(unsigned) != plan.get("freezeSha256"):
        raise ValueError("QUALITY_PLAN_DIGEST_MISMATCH")
    if (
        plan.get("protocolVersion") != PROTOCOL_VERSION
        or plan.get("protocolSha256") != PROTOCOL_SHA256
    ):
        raise ValueError("QUALITY_PROTOCOL_CHANGED_OR_UNSUPPORTED")
    assert_protocol(plan.get("protocolSha256"))
    if plan["limits"] != LIMITS:
        raise ValueError("QUALITY_LIMITS_CHANGED")
    expected = {case["id"]: case for case in plan["cases"]}
    by_id = {}
    for result in results:
        if (
            result.get("id") not in expected
            or result["id"] in by_id
            or result.get("status") not in STATUSES
        ):
            raise ValueError("QUALITY_RESULT_INVALID")
        by_id[result["id"]] = result
    records = [
        {
            **case,
            **{key: value for key, value in by_id.get(case["id"], {}).items() if key not in case},
            "status": by_id.get(case["id"], {}).get("status", "unavailable"),
            "reason": by_id.get(case["id"], {}).get("reason", "EVALUATION_RESULT_MISSING"),
        }
        for case in plan["cases"]
    ]
    overall = _metrics(records, plan["limits"])
    by_source = {
        source: _metrics([r for r in records if r["source"] == source], plan["limits"])
        for source in plan["sources"]
    }
    by_case = {
        f"{source}/{case}": _metrics(
            [r for r in records if r["source"] == source and r["case"] == case], plan["limits"]
        )
        for source, case in sorted({(r["source"], r["case"]) for r in records})
    }
    by_generator = {
        generator: _metrics([r for r in records if r.get("generator") == generator], plan["limits"])
        for generator in sorted({r["generator"] for r in records if r.get("generator")})
    }
    by_voice_family = {
        family: _metrics([r for r in records if r.get("voiceFamilyId") == family], plan["limits"])
        for family in sorted({r["voiceFamilyId"] for r in records if r.get("voiceFamilyId")})
    }
    by_contrast = {
        f"{language}/{category}": _metrics(
            [
                r
                for r in records
                if r.get("language") == language and r.get("contrastCategory") == category
            ],
            plan["limits"],
        )
        for language, category in sorted(
            {
                (r["language"], r["contrastCategory"])
                for r in records
                if r.get("language") and r.get("contrastCategory")
            }
        )
    }
    blockers = []
    if plan["purpose"] != "confirmatory" or any(
        source["usage"] != "unseen" for source in plan["sources"].values()
    ):
        blockers.append("DIAGNOSTIC_COHORT_CANNOT_ESTABLISH_QUALITY")
    for name, metrics in {
        "overall": overall,
        **{f"source:{k}": v for k, v in by_source.items()},
        **{f"case:{k}": v for k, v in by_case.items()},
        **{f"generator:{k}": v for k, v in by_generator.items()},
        **{f"contrast:{k}": v for k, v in by_contrast.items()},
    }.items():
        for gate, value in metrics["gates"].items():
            if value["passed"] is False:
                blockers.append(f"{name}:{gate}")
        for contract, value in metrics["contracts"].items():
            if value["passed"] is False:
                blockers.append(f"{name}:{contract}")
        if (
            name == "overall"
            or name.startswith("source:")
            and plan["sources"][name[7:]].get("requireBothClasses", True)
        ):
            if (
                not metrics["gates"]["negativeFalseAcceptance"]["denominator"]
                or not metrics["gates"]["clearPositiveAbstention"]["denominator"]
            ):
                blockers.append(f"{name}:MISSING_POSITIVE_OR_NEGATIVE_COVERAGE")
    # Source and case gates keep noise/easy pairs from hiding tone/content failures.
    return {
        "schemaVersion": 1,
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": PROTOCOL_SHA256,
        "freezeSha256": plan["freezeSha256"],
        "model": plan["model"],
        "limits": plan["limits"],
        "sources": plan["sources"],
        "overall": overall,
        "bySource": by_source,
        "byCase": by_case,
        "byGenerator": by_generator,
        "byVoiceFamily": by_voice_family,
        "byLanguageAndContrastCategory": by_contrast,
        "coverage": coverage_metrics(records),
        "coverageBySource": {
            source: coverage_metrics([r for r in records if r["source"] == source])
            for source in plan["sources"]
        },
        "qualityPassed": not blockers,
        "blockers": blockers,
        "missingResults": len(expected) - len(by_id),
        "claims": plan["claims"],
        "results": records,
    }


def evaluate_plan(path: Path, output: Path) -> dict:
    from pinyin_matcher.inference import PinyinMatcher

    if output.exists():
        raise ValueError("QUALITY_REPORT_ALREADY_EXISTS")
    plan = json.loads(path.read_text())
    assert_protocol(plan.get("protocolSha256"))
    if (
        _model_snapshot(Path(plan["modelDirectory"])) != plan["model"]
        or _evaluation_code() != plan["evaluationCodeSha256"]
    ):
        raise ValueError("FROZEN_MODEL_OR_EVALUATOR_CHANGED")
    for calibration in plan["calibration"]:
        if fingerprint(Path(calibration["path"])) != calibration["sha256"]:
            raise ValueError("FROZEN_CALIBRATION_MANIFEST_CHANGED")
    # Verify digest before invoking any inference.
    build_report(plan, [])
    matcher = PinyinMatcher(plan["modelDirectory"])
    results = []
    for case in plan["cases"]:
        try:
            path = Path(case["file"])
            if fingerprint(path) != case["sha256"]:
                raise ValueError("FROZEN_AUDIO_CHANGED")
            result = matcher.match(case["targetId"], path.read_bytes(), include_evidence=True)
        except (OSError, ValueError) as error:
            result = {"status": "unavailable", "reason": str(error)}
        results.append({"id": case["id"], **result})
    report = build_report(plan, results)
    _write(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--model", type=Path, required=True)
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--calibration-manifest", type=Path, action="append", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        plan = freeze_plan(
            args.model,
            args.manifest,
            calibration_manifests=args.calibration_manifest,
            output=args.output,
        )
        print(json.dumps({"freezeSha256": plan["freezeSha256"], "cases": len(plan["cases"])}))
    else:
        report = evaluate_plan(args.plan, args.output)
        print(
            json.dumps({"qualityPassed": report["qualityPassed"], "blockers": report["blockers"]})
        )


if __name__ == "__main__":
    main()
