"""Complete four-tone target coverage without changing learned model weights.

Recomparison is allowed only for target-independent component probabilities from
an actual complete CPU calibration run. Target-conditioned heads require fresh
inference. Existing packages and reports are never overwritten.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_evaluate import compare_targets
from pinyin_matcher.pretrained_experiment import covered_targets, read_rows, write
from pinyin_matcher.pretrained_metrics import metrics
from pinyin_matcher.pretrained_runtime import COMPONENTS, component_decision

PROTOCOL = "declared-syllable-bases-all-four-tones-v2"


def expanded_metadata(metadata, manifest):
    rows = read_rows(manifest)
    training = [
        r
        for r in rows
        if r["split"] == "train"
        and not r.get("labelPolicyFlags")
        and not r.get("numericalQualityFlags")
        and not r.get("placeholder")
    ]
    vocabulary = metadata.get("vocabulary") or {
        key: sorted({str(r[key]) for r in training}) for key in COMPONENTS
    }
    if not {"1", "2", "3", "4"}.issubset(vocabulary["tone"]):
        raise ValueError("COVERAGE_REQUIRES_ALL_FOUR_TONE_CLASSES")
    declared = [{**target, "syllable": target["id"][3:]} for target in metadata["coveredTargets"]]
    targets = covered_targets(vocabulary, [*training, *declared])
    by_id = {target["id"]: target for target in targets}
    if any(
        target["id"] not in by_id
        or any(str(target[key]) != str(by_id[target["id"]][key]) for key in COMPONENTS)
        for target in metadata["coveredTargets"]
    ):
        raise ValueError("COVERAGE_EXISTING_TARGET_COMPONENT_CHANGED")
    return {
        **metadata,
        "vocabulary": vocabulary,
        "coveredTargets": targets,
        "coverageProtocol": PROTOCOL,
        "coverageSourceManifestSha256": fingerprint(manifest),
        "coverageCodeSha256": fingerprint(Path(__file__)),
        "previousCoveredTargetCount": len(metadata["coveredTargets"]),
        "compositionalTargetsOutsideTrainingAreExperimental": True,
    }


def verify_resources(package, metadata):
    if not metadata.get("packageFiles"):
        raise ValueError("COVERAGE_REQUIRES_COMPLETE_BOUND_CPU_PACKAGE")
    for relative, entry in metadata["packageFiles"].items():
        path = (package / relative).resolve()
        if (
            not path.is_relative_to(package.resolve())
            or not path.is_file()
            or fingerprint(path) != entry["sha256"]
            or ("bytes" in entry and path.stat().st_size != entry["bytes"])
        ):
            raise ValueError("COVERAGE_SOURCE_PACKAGE_CHANGED")


def _probabilities(evidence, vocabulary):
    result = []
    try:
        for key in COMPONENTS:
            values = np.asarray(evidence[key]["probabilities"], dtype=np.float64)
            if (
                values.shape != (len(vocabulary[key]),)
                or not np.isfinite(values).all()
                or (values < 0).any()
                or (values > 1).any()
                or not np.isclose(values.sum(), 1, atol=1e-4, rtol=0)
            ):
                raise ValueError("invalid distribution")
            result.append(values)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("COVERAGE_COMPONENT_EVIDENCE_INVALID") from error
    return result


def expand(package: Path, manifest: Path, output: Path):
    if output.exists():
        raise ValueError("COVERAGE_OUTPUT_ALREADY_EXISTS")
    metadata = json.loads((package / "model.json").read_text())
    if metadata.get("manifestSha256") != fingerprint(manifest):
        raise ValueError("COVERAGE_TRAINING_MANIFEST_MISMATCH")
    verify_resources(package, metadata)
    updated = expanded_metadata(metadata, manifest)
    updated["previousModelSha256"] = fingerprint(package / "model.json")
    updated["learnedResourcesUnchanged"] = True
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="coverage-", dir=output.parent) as temporary:
        stage = Path(temporary) / "package"
        # Resources are immutable and bound by SHA. Atomic metadata replacement
        # below deliberately breaks its hard link, preserving the original.
        shutil.copytree(package, stage, copy_function=os.link)
        write(stage / "model.json", updated)
        stage.rename(output)
    return {
        "directory": str(output.resolve()),
        "coveredTargets": len(updated["coveredTargets"]),
        "previousModelSha256": updated["previousModelSha256"],
        "modelSha256": fingerprint(output / "model.json"),
    }


def reassess(manifest: Path, package: Path, cpu_results: Path, output: Path):
    if output.exists():
        raise ValueError("COVERAGE_REASSESSMENT_OUTPUT_ALREADY_EXISTS")
    metadata = json.loads((package / "model.json").read_text())
    original = json.loads(cpu_results.read_text())
    if (
        metadata.get("coverageProtocol") != PROTOCOL
        or original.get("split") != "calibration"
        or original.get("manifestSha256") != fingerprint(manifest)
        or original.get("modelSha256") != metadata.get("previousModelSha256")
    ):
        raise ValueError("COVERAGE_CPU_SOURCE_OR_MANIFEST_MISMATCH")
    if metadata.get("headKind"):
        raise ValueError("TARGET_CONDITIONED_OR_NATIVE_HEAD_REQUIRES_FRESH_INFERENCE")
    verify_resources(package, metadata)
    rows = [r for r in read_rows(manifest) if r["split"] == "calibration"]
    predictions = original["predictions"]
    by_id = {r["id"]: r for r in predictions}
    if (
        original.get("rows") != len(rows)
        or len(predictions) != len(by_id)
        or set(by_id) != {r["id"] for r in rows}
    ):
        raise ValueError("COVERAGE_REQUIRES_ALL_ORIGINAL_CPU_CALIBRATION_ROOTS")
    matcher = SimpleNamespace(
        metadata=metadata, targets={t["id"]: t for t in metadata["coveredTargets"]}
    )
    records, reassessed = [], []
    for row in rows:
        result = dict(by_id[row["id"]])
        if result.get("syllable") != row["syllable"]:
            raise ValueError("COVERAGE_CPU_ROOT_TARGET_MISMATCH")
        evidence = result.get("internalEvidence") or result.get("comparisonEvidence")
        if evidence and "targetDecisions" in evidence:
            raise ValueError("TARGET_CONDITIONED_HEAD_REQUIRES_FRESH_INFERENCE")
        if row.get("numericalQualityFlags") or row.get("placeholder"):
            result.update(status="uncertain", reason="PREDECLARED_DATA_QUALITY_FLAG")
            evidence = None
        elif evidence and evidence.get("forceUncertain"):
            result["status"] = "uncertain"
            result["reason"] = "SOURCE_EVIDENCE_FORCED_UNCERTAIN"
            evidence = None
        elif result.get("reason") not in {
            None,
            "TARGET_NOT_TRAINED",
            "COMPONENT_EVIDENCE_INSUFFICIENT",
        }:
            if result["status"] in {"matched", "retry"}:
                result["status"] = "uncertain"
            evidence = None
        if evidence is None:
            result.pop("internalEvidence", None)
            result.pop("comparisonEvidence", None)
        else:
            _probabilities(evidence, metadata["vocabulary"])
        if evidence and result.get("reason") == "TARGET_NOT_TRAINED":
            target = next(
                (
                    target
                    for target in matcher.targets.values()
                    if all(str(target[key]) == str(row[key]) for key in COMPONENTS)
                ),
                None,
            )
            if target:
                ps = _probabilities(evidence, metadata["vocabulary"])
                expected = [metadata["vocabulary"][k].index(str(target[k])) for k in COMPONENTS]
                result["status"] = component_decision(ps, expected, metadata["thresholds"])
                result["internalEvidence"] = evidence
                result["reason"] = "RECOMPARED_ACTUAL_CPU_COMPONENT_EVIDENCE"
        records.extend(compare_targets(row, matcher, result))
        reassessed.append(result)
    report = {
        "schemaVersion": 1,
        "split": "calibration",
        "rows": len(rows),
        "manifestSha256": fingerprint(manifest),
        "modelSha256": fingerprint(package / "model.json"),
        "actualCpuResultsSha256": fingerprint(cpu_results),
        "originalModelSha256": original["modelSha256"],
        "coverageProtocol": PROTOCOL,
        "encoderAndHeadReexecuted": False,
        "method": (
            "Unchanged learned resources and thresholds; new target comparisons use the "
            "complete target-independent probabilities from each actual CPU inference. "
            "Original signal guards and missing evidence remain abstentions."
        ),
        "metrics": metrics(records),
        "records": records,
        "predictions": reassessed,
        "testRead": False,
    }
    write(output, report)
    return {k: report[k] for k in ("rows", "coverageProtocol", "metrics")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["expand", "reassess"])
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-results", type=Path)
    args = parser.parse_args()
    if args.action == "expand":
        result = expand(args.model, args.manifest, args.output)
    else:
        if args.cpu_results is None:
            parser.error("reassess requires --cpu-results")
        result = reassess(args.manifest, args.model, args.cpu_results, args.output)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
