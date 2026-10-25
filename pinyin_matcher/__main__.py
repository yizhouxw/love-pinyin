"""Stable local CLI for future application adapters and offline verification."""

import argparse
import json
from pathlib import Path

from pinyin_matcher.audio import MAX_BYTES
from pinyin_matcher.catalog import load_catalog
from pinyin_matcher.inference import PinyinMatcher


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("targets")
    info = sub.add_parser("info")
    info.add_argument("--model", type=Path, required=True)
    match = sub.add_parser("match")
    match.add_argument("--model", type=Path, required=True)
    match.add_argument("--target", required=True)
    match.add_argument("--wav", type=Path, required=True)
    match.add_argument("--evidence", action="store_true")
    args = parser.parse_args()
    if args.action == "targets":
        print(json.dumps(load_catalog(), ensure_ascii=False))
        return 0
    if args.action == "info":
        print(json.dumps(PinyinMatcher(args.model).capabilities(), ensure_ascii=False))
        return 0
    matcher = PinyinMatcher(args.model)
    try:
        with args.wav.open("rb") as source:
            payload = source.read(MAX_BYTES + 1)
    except OSError:
        result = matcher._result("unavailable", "AUDIO_FILE_UNAVAILABLE")
    else:
        result = matcher.match(args.target, payload, include_evidence=args.evidence)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 2 if result["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
