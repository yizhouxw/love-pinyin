"""Evaluate previously observed input challenges for GMM research only."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from threadpoolctl import threadpool_limits

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.gmm_shop import match


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("OUTPUT_EXISTS")
    model = json.loads((args.package / "model.json").read_text())
    ids = {t["id"] for t in model["targets"]}
    source = json.loads(args.manifest.read_text())
    groups = defaultdict(list)
    queries = selected = unsupported = 0
    with threadpool_limits(limits=2):
        for case in source["cases"]:
            wanted = [t for t in case["targetIds"] if t in ids]
            unsupported += len(case["targetIds"]) - len(wanted)
            if not wanted:
                continue
            selected += 1
            path = Path(case["file"])
            if fingerprint(path) != case["sha256"]:
                raise ValueError("STRESS_PAYLOAD_CHANGED")
            payload = path.read_bytes()
            for target in wanted:
                queries += 1
                groups[(case["kind"], case["expectedBehavior"], case["sha256"])].append(
                    match(args.package, target, payload)["status"]
                )
    buckets = defaultdict(Counter)
    for (kind, expected, _), outcomes in groups.items():
        bucket = buckets[kind]
        bucket["payloadUnits"] += 1
        bucket["anyMatched"] += int("matched" in outcomes)
        bucket["anyRetry"] += int("retry" in outcomes)
        bucket["allUncertain"] += int(all(s == "uncertain" for s in outcomes))
        bucket["expectedBehavior"] = expected
    result = {
        "phase": "diagnostic-not-final",
        "manifestSha256": fingerprint(args.manifest),
        "modelSha256": fingerprint(args.package / "model.json"),
        "plannedCases": len(source["cases"]),
        "selectedCases": selected,
        "supportedQueries": queries,
        "unsupportedQueries": unsupported,
        "groups": {k: dict(v) for k, v in buckets.items()},
        "finalTestUsed": False,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
