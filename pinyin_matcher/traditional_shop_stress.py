"""Evaluate retained calibration challenges without treating them as acceptance."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from threadpoolctl import threadpool_limits

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.traditional_shop import load, match


def evaluate(package, manifest, output):
    if output.exists():
        raise ValueError("TRADITIONAL_STRESS_OUTPUT_EXISTS")
    model, _ = load(package)
    source = json.loads(manifest.read_text())
    ids = {t["id"] for t in model["targets"]}
    by_method = {k: defaultdict(list) for k in model["models"]}
    unsupported, queries, selected = 0, 0, 0
    for case in source["cases"]:
        wanted = [t for t in case["targetIds"] if t in ids]
        unsupported += sum(t not in ids for t in case["targetIds"])
        if not wanted:
            continue
        selected += 1
        path = Path(case["file"])
        if fingerprint(path) != case["sha256"]:
            raise ValueError("TRADITIONAL_STRESS_PAYLOAD_CHANGED")
        payload = path.read_bytes()
        for target in wanted:
            queries += 1
            for method, groups in by_method.items():
                response = match(package, method, target, payload)
                groups[(case["kind"], case["expectedBehavior"], case["sha256"])].append(
                    response["status"]
                )
    summary = {}
    for method, groups in by_method.items():
        counts = defaultdict(Counter)
        for (kind, expected, _), outcomes in groups.items():
            bucket = counts[kind]
            bucket["payloadUnits"] += 1
            bucket["anyMatched"] += int("matched" in outcomes)
            bucket["anyExplicitRetry"] += int("retry" in outcomes)
            bucket["allUncertain"] += int(all(x == "uncertain" for x in outcomes))
            bucket["expectedBehavior"] = expected
        summary[method] = {kind: dict(count) for kind, count in counts.items()}
    result = {
        "schemaVersion": 1,
        "phase": "calibration-diagnostic-not-final",
        "manifestSha256": fingerprint(manifest),
        "modelSha256": fingerprint(package / "model.json"),
        "plannedCases": len(source["cases"]),
        "casesWithSupportedTargets": selected,
        "supportedQueries": queries,
        "unsupportedQueries": unsupported,
        "methods": summary,
        "finalTestUsed": False,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    with threadpool_limits(limits=2):
        print(json.dumps(evaluate(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == "__main__":
    main()
