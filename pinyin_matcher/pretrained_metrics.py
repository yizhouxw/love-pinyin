"""Frozen, full-denominator evaluation and lineage audit for SPEC-018.

The unit is an original audio root, never the number of target comparisons.
Missing/unknown results remain abstentions. Ambiguous labels remain visible and
cannot establish quality. This module deliberately has no ML/runtime imports.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from random import Random
from typing import Any

GATE_LIMITS = {
    "nearNeighborFalseAccept": 0.05,
    "positiveExplicitReject": 0.10,
    "clearPositiveAbstention": 0.20,
}
MIN_ROOTS = 100
MIN_SPEAKERS = 5
STATUSES = frozenset({"matched", "retry", "uncertain", "unavailable"})


def _first(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return str(value)
    return ""


def _source(row: Mapping[str, Any]) -> str:
    return _first(row, "source", "dataset", "corpus") or "unspecified"


def _root(row: Mapping[str, Any], index: int) -> tuple[str, str]:
    root = _first(row, "root_id", "original_id", "source_audio_id", "audio_id", "source_sha", "id")
    # Unidentifiable records must not disappear or merge with one another.
    return (_source(row), root or f"missing-root-{index}")


def _label(row: Mapping[str, Any]) -> str:
    value = _first(row, "label", "expected", "kind").lower()
    if value in {"positive", "correct", "match", "matched", "accept", "true"}:
        return "positive"
    if value in {"negative", "incorrect", "mismatch", "reject", "false"}:
        return "negative"
    return "ambiguous"


def _status(row: Mapping[str, Any]) -> str:
    result = row.get("result")
    status = _first(row, "status", "decision")
    if not status and isinstance(result, Mapping):
        status = _first(result, "status", "decision")
    return status if status in STATUSES else "unavailable"


def wilson(successes: int, total: int) -> dict[str, Any]:
    """Two-sided Wilson 95% interval; zero denominator is explicitly undefined."""
    if total < 0 or not 0 <= successes <= total:
        raise ValueError("Wilson counts must satisfy 0 <= successes <= total")
    if total == 0:
        return {"n": 0, "count": 0, "rate": None, "low": None, "high": None}
    z = 1.959963984540054
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total**2)) / denom
    return {
        "n": total,
        "count": successes,
        "rate": p,
        "low": max(0.0, center - radius),
        "high": min(1.0, center + radius),
    }


def _collapse(rows: list[Mapping[str, Any]], label: str) -> dict[str, Any]:
    statuses = [_status(row) for row in rows]
    if label == "negative":
        # One accepted wrong target invalidates the entire original audio root.
        outcome = (
            "falseAccept"
            if "matched" in statuses
            else ("explicitReject" if all(s == "retry" for s in statuses) else "abstention")
        )
    elif label == "positive":
        # Repeated augmentations/runs cannot dilute one observed failure.
        outcome = (
            "explicitReject"
            if "retry" in statuses
            else ("accepted" if all(s == "matched" for s in statuses) else "abstention")
        )
    else:
        outcome = "unverifiable"
    speakers = {
        _first(row, "speaker_id", "speakerId", "speaker")
        for row in rows
        if _first(row, "speaker_id", "speakerId", "speaker")
    }
    families = {
        _first(row, "voice_family", "voiceFamilyId", "voiceFamily", "family")
        for row in rows
        if _first(row, "voice_family", "voiceFamilyId", "voiceFamily", "family")
    }
    return {
        "outcome": outcome,
        "speaker": next(iter(speakers)) if len(speakers) == 1 else "",
        "speakers": speakers,
        "families": families,
        "clear": all(row.get("clear", row.get("is_clear", True)) is True for row in rows),
        "comparisons": len(rows),
    }


def _cluster_interval(
    roots: list[dict[str, Any]], outcome: str, *, repetitions: int = 1000
) -> dict[str, Any]:
    by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for root in roots:
        if root["speaker"]:
            by_speaker[root["speaker"]].append(root)
    if len(by_speaker) < 2 or sum(map(len, by_speaker.values())) != len(roots):
        return {
            "method": "speaker-cluster-bootstrap",
            "low": None,
            "high": None,
            "reason": "At least two known speaker clusters and complete speaker IDs required",
        }
    clusters = [by_speaker[k] for k in sorted(by_speaker)]
    rng = Random(18009)
    rates = []
    for _ in range(repetitions):
        chosen = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        n = sum(map(len, chosen))
        rates.append(sum(r["outcome"] == outcome for c in chosen for r in c) / n)
    rates.sort()
    return {
        "method": "speaker-cluster-bootstrap",
        "repetitions": repetitions,
        "seed": 18009,
        "low": rates[int(0.025 * (repetitions - 1))],
        "high": rates[int(0.975 * (repetitions - 1))],
    }


def _summary(roots: list[dict[str, Any]], *, positive: bool) -> dict[str, Any]:
    counts = Counter(root["outcome"] for root in roots)
    names = (
        ("accepted", "explicitReject", "abstention")
        if positive
        else ("falseAccept", "explicitReject", "abstention")
    )
    result: dict[str, Any] = {
        "n": len(roots),
        "comparisons": sum(r["comparisons"] for r in roots),
        "speakers": len(set().union(*(r["speakers"] for r in roots))) if roots else 0,
        "voiceFamilies": len(set().union(*(r["families"] for r in roots))) if roots else 0,
        "missingSpeakerRoots": sum(not r["speaker"] for r in roots),
    }
    for name in names:
        result[name] = wilson(counts[name], len(roots))
        result[name]["speakerCluster95"] = _cluster_interval(roots, name)
    return result


def metrics(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate already selected data; callers must select the frozen split.

    Canonical fields are source, root_id/audio_id, speaker_id, voice_family,
    label (positive/negative/ambiguous), error_type, status and clear. Duplicate
    target comparisons and augmentations sharing a root never increase n.
    """
    rows = list(records)
    positive: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    negative: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    strata: dict[str, dict[tuple[str, str], list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    origins: dict[str, dict[tuple[str, str], list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    ambiguous: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for i, row in enumerate(rows):
        key = _root(row, i)
        label = _label(row)
        if label == "positive":
            positive[key].append(row)
        elif label == "negative":
            negative[key].append(row)
            error = _first(row, "error_type", "errorType", "stratum") or "unspecified"
            strata[error][key].append(row)
            origin = _first(row, "negative_origin", "negativeOrigin")
            if not origin:
                origin = (
                    "expert"
                    if error.startswith(("expert-", "expert_"))
                    else "counterfactual"
                    if error.startswith(("counterfactual-", "counterfactual_"))
                    else "unspecified"
                )
            origins[origin][key].append(row)
        else:
            ambiguous[key].append(row)
    pos_roots = [_collapse(v, "positive") for v in positive.values()]
    neg_roots = [_collapse(v, "negative") for v in negative.values()]
    pos = _summary(pos_roots, positive=True)
    clear = _summary([r for r in pos_roots if r["clear"]], positive=True)
    neg = _summary(neg_roots, positive=False)
    neg_strata = {
        key: _summary([_collapse(v, "negative") for v in groups.values()], positive=False)
        for key, groups in sorted(strata.items())
    }
    neg_origins = {
        key: _summary([_collapse(v, "negative") for v in groups.values()], positive=False)
        for key, groups in sorted(origins.items())
    }
    checks: list[dict[str, Any]] = []
    for name, summary, count_key, limit in [
        ("positiveExplicitReject", pos, "explicitReject", 0.10),
        ("clearPositiveAbstention", clear, "abstention", 0.20),
        ("nearNeighborFalseAccept", neg, "falseAccept", 0.05),
    ]:
        stat = summary[count_key]
        checks.append(
            {
                "name": name,
                "rate": stat["rate"],
                "limit": limit,
                "passesPointEstimate": stat["rate"] is not None and stat["rate"] <= limit,
            }
        )
    for error, summary in {
        **neg_strata,
        **{"origin:" + key: value for key, value in neg_origins.items()},
    }.items():
        rate = summary["falseAccept"]["rate"]
        checks.append(
            {
                "name": "nearNeighborFalseAccept:" + error,
                "rate": rate,
                "limit": 0.05,
                "passesPointEstimate": rate is not None and rate <= 0.05,
            }
        )
    sample_audit = {}
    for key, summary in {
        "positive": pos,
        "clearPositive": clear,
        "negative": neg,
        **{"negative:" + k: v for k, v in neg_strata.items()},
        **{"negativeOrigin:" + k: v for k, v in neg_origins.items()},
    }.items():
        sample_audit[key] = {
            "n": summary["n"],
            "speakers": summary["speakers"],
            "minimumRoots": MIN_ROOTS,
            "minimumSpeakers": MIN_SPEAKERS,
            "adequateForDescriptiveGate": summary["n"] >= MIN_ROOTS
            and summary["speakers"] >= MIN_SPEAKERS
            and summary["missingSpeakerRoots"] == 0,
        }
    enough = all(v["adequateForDescriptiveGate"] for v in sample_audit.values())
    point_pass = all(c["passesPointEstimate"] for c in checks)
    return {
        "schemaVersion": 1,
        "unit": "original audio root; any accepted wrong target fails that root",
        "inputRecords": len(rows),
        "positive": pos,
        "clearPositive": clear,
        "negative": neg,
        "negativeStrata": neg_strata,
        "negativeOriginStrata": neg_origins,
        "ambiguous": {
            "roots": len(ambiguous),
            "records": sum(map(len, ambiguous.values())),
            "statusCounts": dict(Counter(_status(r) for v in ambiguous.values() for r in v)),
            "qualityVerifiable": False,
        },
        "missingOrUnknownResults": sum(
            _first(r, "status", "decision") not in STATUSES
            and not isinstance(r.get("result"), Mapping)
            for r in rows
        ),
        "sampleSizeAudit": sample_audit,
        "gates": {
            "limits": dict(GATE_LIMITS),
            "checks": checks,
            "passesPointEstimates": point_pass,
            "sampleSizeAdequate": enough,
            "descriptiveGatePassed": point_pass and enough,
            "populationOrChildValidationPassed": False,
        },
    }


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_records(paths: Iterable[str | Path] | Mapping[str, str | Path]) -> list[dict[str, Any]]:
    items = paths.items() if isinstance(paths, Mapping) else ((str(p), p) for p in paths)
    result = []
    for name, path in items:
        p = Path(path)
        digest = hashlib.sha256()
        with p.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        result.append(
            {
                "name": str(name),
                "path": str(p),
                "sizeBytes": p.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    return sorted(result, key=lambda row: (row["name"], row["path"]))


def freeze(
    records: Iterable[Mapping[str, Any]],
    *,
    files: Iterable[str | Path] | Mapping[str, str | Path] = (),
    code_files: Iterable[str | Path] | Mapping[str, str | Path] = (),
    model_files: Iterable[str | Path] | Mapping[str, str | Path] = (),
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Hash a deterministic evaluation plan and reject cross-split lineage leaks.

    Every train/calibration/test root needs an explicit original identifier and
    speaker or voice family. Optional clone-reference and original SHA identities
    are also checked whenever supplied. Diagnostic data is explicitly separate.
    """
    rows = [dict(row) for row in records]
    active = {"train", "calibration", "test"}
    aliases = {
        "training": "train",
        "cal": "calibration",
        "validation": "calibration",
        "frozen_test": "test",
    }
    seen: dict[tuple[str, str], str] = {}
    split_counts: Counter[str] = Counter()
    checks = {
        "root": ("root_id", "original_id", "source_audio_id", "audio_id", "source_sha", "id"),
        "speaker": ("speaker_id", "speakerId", "speaker"),
        "voiceFamily": ("voice_family", "voiceFamilyId", "voiceFamily", "family"),
        "cloneReference": (
            "reference_id",
            "referenceSourceId",
            "clone_reference_id",
            "reference_source",
        ),
        "sourceSha": ("source_sha", "parentSha256", "original_sha256", "source_sha256", "sha256"),
    }
    for row in rows:
        split = aliases.get(str(row.get("split", "")), str(row.get("split", "")))
        if split not in active | {"diagnostic"}:
            raise ValueError("Every record needs train/calibration/test/diagnostic split")
        row["split"] = split
        split_counts[split] += 1
        if split == "diagnostic":
            continue
        if not _first(row, *checks["root"]):
            raise ValueError("Frozen records require an original root/audio identifier")
        if not _first(row, *checks["speaker"]) and not _first(row, *checks["voiceFamily"]):
            raise ValueError("Frozen records require speaker or voice-family identity")
        for category, keys in checks.items():
            # Each original identity matters; a derived waveform SHA must not hide
            # a shared speaker, original recording or cloning reference.
            for key in keys:
                value = _first(row, key)
                if not value:
                    continue
                identity = (category, _source(row) + ":" + value if category == "root" else value)
                prior = seen.get(identity)
                if prior is not None and prior != split:
                    raise ValueError(f"Cross-split {category} leakage: {value} ({prior}/{split})")
                seen[identity] = split
    canonical_rows = sorted(
        rows, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False)
    )
    plan: dict[str, Any] = {
        "schemaVersion": 1,
        "recordCount": len(rows),
        "splitCounts": dict(sorted(split_counts.items())),
        "datasetSha256": _digest(canonical_rows),
        "config": dict(config or {}),
        "configSha256": _digest(config or {}),
        "limits": dict(GATE_LIMITS),
        "minimumRootsPerStratum": MIN_ROOTS,
        "minimumSpeakers": MIN_SPEAKERS,
        "files": _file_records(files),
        "codeFiles": _file_records(code_files),
        "modelFiles": _file_records(model_files),
        "lineageDisjoint": True,
        "identitiesChecked": len(seen),
    }
    plan["planSha256"] = _digest(plan)
    return plan
