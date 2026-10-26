"""Separate content/tone decisions and calibration under fixed quality constraints.

The decision never reads truth labels. Calibration only accepts records explicitly
marked ``split=calibration`` and cannot produce a test-quality pass. There is no
fallback to a weaker threshold when the three original quality limits conflict.
"""

import hashlib
import itertools
import json
import math
from collections import Counter

from pinyin_matcher.quality import (
    LIMITS,
    PROTOCOL_SHA256,
    PROTOCOL_VERSION,
    assert_protocol,
    quality_metrics,
    validate_case_semantics,
)

THRESHOLD_GRID = {
    "minimumContentMargin": [0, 0.25, 0.5, 1, 1.5, 2, 3, 4],
    "maximumFreeCtcAdvantage": [0, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
    "minimumToneProbability": [0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95],
}


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _thresholds(values: dict):
    if set(values) != set(THRESHOLD_GRID) or any(not _finite(v) for v in values.values()):
        raise ValueError("DECISION_THRESHOLDS_INVALID")
    if (
        values["minimumContentMargin"] < 0
        or values["maximumFreeCtcAdvantage"] < 0
        or not 0 <= values["minimumToneProbability"] <= 1
    ):
        raise ValueError("DECISION_THRESHOLDS_INVALID")


def _phones(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


def decide(evidence: dict, thresholds: dict) -> dict:
    """Return matched/retry/uncertain/unavailable from independent branch evidence.

    Required evidence: targetPhones, targetTone, predictedPhones, predictedTone,
    contentMargin, freeCtcAdvantage, toneProbability and pitchReliable. An optional
    available=false or evidenceError returns unavailable. Truth/provenance fields
    (expectedMatch, contentCorrect, source, language) never affect this function.
    """
    _thresholds(thresholds)
    if evidence.get("available") is False or evidence.get("evidenceError"):
        return {"status": "unavailable", "reason": "ACOUSTIC_EVIDENCE_UNAVAILABLE"}
    if (
        not _phones(evidence.get("targetPhones"))
        or type(evidence.get("targetTone")) is not int
        or evidence["targetTone"] not in {1, 2, 3, 4}
    ):
        return {"status": "unavailable", "reason": "TARGET_EVIDENCE_INVALID"}
    if not _phones(evidence.get("predictedPhones")):
        return {"status": "uncertain", "reason": "NO_RELIABLE_PHONE_EVIDENCE"}
    if not _finite(evidence.get("contentMargin")) or not _finite(evidence.get("freeCtcAdvantage")):
        return {"status": "unavailable", "reason": "CONTENT_EVIDENCE_INVALID"}
    if evidence["contentMargin"] < thresholds["minimumContentMargin"]:
        return {"status": "uncertain", "reason": "CONTENT_CONFIDENCE_INSUFFICIENT"}
    if evidence["freeCtcAdvantage"] > thresholds["maximumFreeCtcAdvantage"]:
        return {"status": "uncertain", "reason": "EXTRA_OR_UNSUPPORTED_PHONE_EVIDENCE"}
    # Confidently different phonemes independently refute the requested syllable.
    # A pitch failure must not force a content error to masquerade as a tone error.
    if evidence["predictedPhones"] != evidence["targetPhones"]:
        return {"status": "retry", "reason": "OTHER_PHONEMES_DETECTED"}
    if evidence.get("pitchReliable") is not True:
        return {"status": "uncertain", "reason": "NO_RELIABLE_TONE_EVIDENCE"}
    if (
        type(evidence.get("predictedTone")) is not int
        or evidence["predictedTone"] not in {1, 2, 3, 4}
        or not _finite(evidence.get("toneProbability"))
        or not 0 <= evidence["toneProbability"] <= 1
    ):
        return {"status": "unavailable", "reason": "TONE_EVIDENCE_INVALID"}
    if evidence["toneProbability"] < thresholds["minimumToneProbability"]:
        return {"status": "uncertain", "reason": "TONE_CONFIDENCE_INSUFFICIENT"}
    if evidence["predictedTone"] != evidence["targetTone"]:
        return {"status": "retry", "reason": "OTHER_TONE_DETECTED"}
    return {"status": "matched", "reason": None}


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return f"nonfinite:{value}"
    return value


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _validate_records(records: list[dict]):
    if not records:
        raise ValueError("CALIBRATION_RECORDS_REQUIRED")
    seen, positive_units, audio_units = set(), set(), {}
    for row in records:
        if row.get("split") != "calibration":
            raise ValueError("CALIBRATION_SPLIT_REQUIRED_NO_TEST_TUNING")
        if (
            any(
                not isinstance(row.get(k), str) or not row[k]
                for k in ("id", "unitId", "source", "case")
            )
            or type(row.get("expectedMatch")) is not bool
            or type(row.get("clearAudio")) is not bool
            or row["id"] in seen
        ):
            raise ValueError("CALIBRATION_RECORD_INVALID")
        seen.add(row["id"])
        validate_case_semantics(row)
        unit = (row["source"], row["case"], row["unitId"])
        if row["expectedMatch"]:
            if unit in positive_units:
                raise ValueError("DUPLICATE_POSITIVE_UNIT")
            positive_units.add(unit)
        if row.get("sha256"):
            key = (row["source"], row["case"], row["sha256"])
            if audio_units.setdefault(key, row["unitId"]) != row["unitId"]:
                raise ValueError("CALIBRATION_UNIT_IDENTITY_INVALID")


def _groups(records: list[dict]) -> dict[str, list[dict]]:
    groups = {"overall": records}
    for field, prefix in (("source", "source"), ("generator", "generator")):
        for value in sorted({r[field] for r in records if r.get(field)}):
            groups[f"{prefix}:{value}"] = [r for r in records if r.get(field) == value]
    for source, case in sorted({(r["source"], r["case"]) for r in records}):
        groups[f"case:{source}/{case}"] = [
            r for r in records if r["source"] == source and r["case"] == case
        ]
    for language, category in sorted(
        {
            (r["language"], r["contrastCategory"])
            for r in records
            if r.get("language") and r.get("contrastCategory")
        }
    ):
        groups[f"contrast:{language}/{category}"] = [
            r
            for r in records
            if r.get("language") == language and r.get("contrastCategory") == category
        ]
    return groups


def _assess(records: list[dict], source_policies: dict) -> tuple[dict, list[str]]:
    metrics = {key: quality_metrics(group) for key, group in _groups(records).items()}
    blockers = []
    for name, value in metrics.items():
        for gate, result in value["gates"].items():
            if result["passed"] is False:
                blockers.append(f"{name}:{gate}")
        for contract, result in value["contracts"].items():
            if result["passed"] is False:
                blockers.append(f"{name}:{contract}")
        if (
            name == "overall"
            or name.startswith("source:")
            and source_policies.get(name[7:], {}).get("requireBothClasses", True)
        ):
            if (
                not value["gates"]["negativeFalseAcceptance"]["denominator"]
                or not value["gates"]["clearPositiveAbstention"]["denominator"]
            ):
                blockers.append(f"{name}:MISSING_POSITIVE_OR_NEGATIVE_COVERAGE")
    return metrics, blockers


def calibrate(
    records: list[dict], *, grid: dict | None = None, source_policies: dict | None = None
) -> dict:
    """Choose exactly three thresholds only when every calibration gate is feasible.

    Every unavailable/uncertain clear positive remains an abstention. Each source,
    generator and counterexample case must pass independently. Pairing the same
    audio with many easy negative targets never increases its trial denominator.
    """
    _validate_records(records)
    assert_protocol()
    source_policies = source_policies or {}
    if any(
        type(policy.get("requireBothClasses", True)) is not bool
        for policy in source_policies.values()
    ):
        raise ValueError("CALIBRATION_SOURCE_POLICY_INVALID")
    candidates = grid if grid is not None else THRESHOLD_GRID
    if set(candidates) != set(THRESHOLD_GRID) or any(
        not isinstance(v, list) or not v for v in candidates.values()
    ):
        raise ValueError("CALIBRATION_GRID_INVALID")
    names = list(THRESHOLD_GRID)
    for name, values in candidates.items():
        for value in values:
            _thresholds({key: value if key == name else THRESHOLD_GRID[key][0] for key in names})
    selected = None
    closest = None
    feasible = 0
    for combination in itertools.product(*(candidates[name] for name in names)):
        thresholds = dict(zip(names, combination, strict=True))
        outcomes = [{**row, **decide(row, thresholds)} for row in records]
        metrics, blockers = _assess(outcomes, source_policies)
        overall = metrics["overall"]
        positive = max(overall["positiveAudioUnits"], 1)
        matched = overall["positiveUnitStatuses"]["matched"] / positive
        negative = max(
            (m["gates"]["negativeFalseAcceptance"]["rate"] or 0 for m in metrics.values()),
            default=0,
        )
        key = (
            matched,
            -negative,
            thresholds["minimumContentMargin"],
            -thresholds["maximumFreeCtcAdvantage"],
            thresholds["minimumToneProbability"],
        )
        if closest is None or (len(blockers), -matched) < closest[0]:
            closest = ((len(blockers), -matched), metrics, blockers)
        if blockers:
            continue
        feasible += 1
        if selected is None or key > selected[0]:
            selected = (key, thresholds, metrics, Counter(r["reason"] or "NONE" for r in outcomes))
    report = {
        "schemaVersion": 1,
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": PROTOCOL_SHA256,
        "split": "calibration",
        "decisionVersion": 3,
        "calibrationRecordsSha256": _digest(records),
        "gridSha256": _digest(candidates),
        "qualityLimits": dict(LIMITS),
        "records": len(records),
        "sources": sorted({r["source"] for r in records}),
        "sourcePolicies": source_policies,
        "caseTypes": sorted({r["case"] for r in records}),
        "combinations": math.prod(len(candidates[name]) for name in names),
        "feasibleCombinations": feasible,
        "calibrationPassed": selected is not None,
        "qualityPassed": False,
        "thresholds": selected[1] if selected else None,
        "selectionRule": (
            "Maximize positive acceptance among feasible candidates; "
            "then minimize worst-group false acceptance; conservative deterministic threshold ties."
        ),
        "testUsedForCalibration": False,
        "realChildAccuracyEstablished": False,
    }
    if selected:
        report["groups"] = selected[2]
        report["reasonCounts"] = dict(selected[3])
        report["blockers"] = []
    else:
        report["groups"] = closest[1]
        report["blockers"] = closest[2]
        report["failure"] = "NO_THRESHOLDS_SATISFY_ORIGINAL_QUALITY_LIMITS"
    assert_protocol()
    return report
