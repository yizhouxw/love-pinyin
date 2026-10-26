"""Recover OMPAL detailed-rating IDs by exact public metadata identity.

The public aggregate uses actual audio speaker IDs; detailed JSON splits some
people into old passage-level IDs. No acoustic/model evidence enters this join.
Ambiguous identities remain unresolved rather than being assigned by filename.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

COMPONENTS = ("phoneme_consonant", "phoneme_vowel", "tone")
SENTENCE_SCORES = ("accuracy", "fluency", "prosody")
REVISION = "c3aaa9e892e4b1c2a25b637401f52f6e35b53e74"


def _speaker(identifier: str) -> str:
    match = re.fullmatch(r"002(\d{3})\d{2}", identifier)
    if match is None:
        raise ValueError("OMPAL_L2_ID_INVALID")
    return match[1]


def _aggregate(row: dict) -> dict:
    result = {"text": row["text"], "words": []}
    for score in SENTENCE_SCORES:
        votes = row[score]
        if not votes or any(type(v) not in (int, float) or not 1 <= v <= 5 for v in votes):
            raise ValueError("OMPAL_SENTENCE_RATING_INVALID")
        result[score] = round(sum(votes) / len(votes), 2)
    for word in row["words"]:
        item = {"text": word["text"]}
        for component in COMPONENTS:
            votes = [int(v) for v in word[component]]
            if not votes or any(v not in {0, 1} for v in votes):
                raise ValueError("OMPAL_COMPONENT_RATING_INVALID")
            if 2 * sum(votes) == len(votes):
                raise ValueError("OMPAL_MAJORITY_TIE_UNRESOLVED")
            item[component] = int(2 * sum(votes) > len(votes))
        result["words"].append(item)
    return result


def _signature(row: dict) -> str:
    normalized = {
        "text": row["text"],
        "words": row["words"],
        **{k: float(row[k]) for k in SENTENCE_SCORES},
    }
    return hashlib.sha256(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def build_mapping(aggregate: dict, detailed: dict) -> dict:
    """Return actual-WAV-ID -> detailed-ID only when whole-block join is unique."""
    actual = {k: _signature(v) for k, v in aggregate.items()}
    old = {k: _signature(_aggregate(v)) for k, v in detailed.items()}
    if Counter(actual.values()) != Counter(old.values()):
        raise ValueError("OMPAL_PUBLIC_METADATA_MULTISET_MISMATCH")
    actual_groups: dict[str, list[str]] = defaultdict(list)
    old_groups: dict[str, list[str]] = defaultdict(list)
    for key in actual:
        actual_groups[_speaker(key)].append(key)
    for key in old:
        old_groups[_speaker(key)].append(key)
    candidates = {}
    group_mapping = {}
    for group, keys in sorted(old_groups.items()):
        required = Counter(old[k] for k in keys)
        choices = sorted(
            g for g, ids in actual_groups.items() if not required - Counter(actual[k] for k in ids)
        )
        candidates[group] = choices
        if len(choices) == 1:
            group_mapping[group] = choices[0]
    mapping = {}
    issues = []
    for old_id, signature in sorted(old.items()):
        group = group_mapping.get(_speaker(old_id))
        matches = [key for key in actual_groups.get(group, []) if actual[key] == signature]
        if len(matches) == 1 and matches[0] not in mapping:
            mapping[matches[0]] = old_id
        else:
            issues.append({"oldDetailedId": old_id, "candidateActualIds": matches})
    same = actual.keys() & old.keys()
    return {
        "schemaVersion": 1,
        "revision": REVISION,
        "mapping": dict(sorted(mapping.items())),
        "unresolved": sorted(actual.keys() - mapping.keys()),
        "evidence": {
            "method": "Exact public metadata identity: whole detailed passage-speaker signature "
            "multiset contained uniquely in one actual speaker, then unique record "
            "signature within that speaker. No audio or model outputs.",
            "sentenceAggregation": "Arithmetic mean rounded to2decimalplaces",
            "wordAggregation": "Strict majority; ties cause failure. NOT unanimity.",
            "signatureFields": [
                "text",
                *SENTENCE_SCORES,
                "all ordered word text alternatives",
                "all ordered component majorities",
            ],
            "globalDistinctSignatures": len(set(actual.values())),
            "exactSignatureMultisetsEqual": True,
            "sameIdRecords": len(same),
            "sameIdExactSignatureMatches": sum(actual[k] == old[k] for k in same),
            "uniquelyIdentifiedDetailedSpeakerBlocks": len(group_mapping),
            "detailedSpeakerBlocks": len(old_groups),
            "actualSpeakers": len(actual_groups),
            "changedSpeakerBlockMapping": {k: v for k, v in group_mapping.items() if k != v},
            "candidateActualSpeakersByDetailedBlock": candidates,
            "mappingOneToOne": len(mapping) == len(set(mapping.values())),
            "unresolvedOrCollisionDetails": issues,
            "provenanceLimit": "Derived from exact official annotation identities, not an "
            "author-published renaming table. Rater correctness remains the "
            "joined detailed votes, never the majority aggregate alone.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--detailed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_mapping(
        json.loads(args.aggregate.read_text()), json.loads(args.detailed.read_text())
    )
    result["evidence"]["sourceSha256"] = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in (("aggregate", args.aggregate), ("detailed", args.detailed))
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"mapped": len(result["mapping"]), "unresolved": len(result["unresolved"])}))


if __name__ == "__main__":
    main()
