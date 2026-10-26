"""All-row direct phonetic-head diagnostics on calibration only.

These are direct acoustic event diagnostics, never a pronunciation quality gate.
Every expert row remains visible, including ambiguity and predeclared exclusions.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_comparison import (
    COMPONENTS,
    HEADS,
    _tokens,
    native_summary,
    source_vocabularies,
)
from pinyin_matcher.pretrained_native import native_rime_aliases


def report(manifest: Path, cache: Path, model_directory: Path) -> dict:
    from pinyin_matcher.pretrained_experiment import cache_identity, read_cached, read_rows

    document = json.loads(manifest.read_text())
    if document.get("frozenTestIncluded") is not False:
        raise ValueError("NATIVE_DIAGNOSTICS_REQUIRE_NONFINAL_MANIFEST")
    cache_metadata = json.loads((cache / "cache.json").read_text())
    name = cache_metadata.get("model", "hanziflow")
    identity = json.loads((cache / "identity.json").read_text())
    architecture = (identity.get("derivative") or {}).get("architecture")
    if name not in {"hanziflow", "sensevoice"} or (
        name == "sensevoice" and architecture != "sensevoice-50-ctc-v1"
    ):
        raise ValueError("PHONETIC_DIAGNOSTIC_MODEL_UNSUPPORTED")
    if identity != cache_identity(name, model_directory):
        raise ValueError("NATIVE_DIAGNOSTIC_CACHE_IDENTITY_MISMATCH")
    if cache_metadata["manifestSha256"] != fingerprint(manifest) or cache_metadata["testIncluded"]:
        raise ValueError("NATIVE_DIAGNOSTIC_CACHE_MANIFEST_MISMATCH")
    identity_sha = fingerprint(cache / "identity.json")
    vocabularies = source_vocabularies(model_directory)
    aliases = native_rime_aliases("hanziflow")
    rows = [row for row in read_rows(manifest) if row["split"] == "calibration"]
    records = []
    for row in rows:
        record = {
            key: row.get(key)
            for key in (
                "id",
                "sha256",
                "speakerId",
                "expertLabel",
                "componentExpertLabels",
                "labelPolicyFlags",
                "numericalQualityFlags",
            )
        }
        record.update({"available": False, "components": {}})
        if (
            row.get("labelPolicyFlags")
            or row.get("numericalQualityFlags")
            or row.get("placeholder")
        ):
            record["reason"] = "PREDECLARED_UNASSESSABLE"
        else:
            with read_cached(cache / (row["sha256"] + ".npz"), identity_sha) as item:
                if "error" in item:
                    record["reason"] = "ACOUSTIC_CACHE_ERROR"
                else:
                    summary = native_summary(dict(item), vocabularies)
                    tokens = _tokens(row, aliases)
                    record["available"] = True
                    for component, head, token, evidence in zip(
                        COMPONENTS, HEADS, tokens, summary, strict=True
                    ):
                        table = vocabularies[head]
                        if token not in table:
                            record["available"] = False
                            record["reason"] = "NATIVE_TARGET_UNSUPPORTED"
                            record["components"] = {}
                            break
                        inverse = {index: phone for phone, index in table.items()}
                        expected = table[token]
                        scores = evidence["scores"]
                        best = int(scores.argmax())
                        other = scores.copy()
                        other[expected] = 0
                        record["components"][component] = {
                            "expectedToken": token,
                            "expectedSingleLabelMass": float(scores[expected]),
                            "bestOtherSingleLabelMass": float(other.max()),
                            "bestNativeToken": inverse[best],
                            "expectedIsBestSingleLabel": best == expected,
                            "greedyTokens": [inverse[index] for index in evidence["sequence"]],
                            "greedyExactlyExpected": evidence["sequence"] == [expected],
                            "emptyMass": evidence["empty"],
                            "multipleLabelMass": evidence["multiple"],
                            "unknownMass": float(scores[table["<unk>"]]),
                        }
        records.append(record)
    components = {}
    for component in COMPONENTS:
        classes = {}
        for label in ("unanimous-correct", "unanimous-error", "ambiguous"):
            selected = [
                row
                for row in records
                if (row.get("componentExpertLabels") or {}).get(component) == label
            ]
            available = [row["components"][component] for row in selected if row["available"]]
            masses = [row["expectedSingleLabelMass"] for row in available]
            classes[label] = {
                "allExpertRows": len(selected),
                "available": len(available),
                "unassessable": len(selected) - len(available),
                "expectedIsBestSingleLabel": sum(
                    row["expectedIsBestSingleLabel"] for row in available
                ),
                "greedyExactlyExpected": sum(row["greedyExactlyExpected"] for row in available),
                "expectedMassQuantiles": np.quantile(masses, [0, 0.1, 0.5, 0.9, 1]).tolist()
                if masses
                else None,
            }
        components[component] = classes
    return {
        "schemaVersion": 1,
        "model": name,
        "architecture": architecture,
        "phoneticHeadOrigin": (
            "New random-initialized Sense50 phonetic CTC heads; not original SenseVoice outputs"
            if name == "sensevoice"
            else "Original HanziFlow phonetic CTC heads, possibly fine-tuned"
        ),
        "split": "calibration",
        "finalTestRead": False,
        "allCalibrationRows": len(records),
        "availableRows": sum(row["available"] for row in records),
        "unavailableReasons": dict(
            Counter(row.get("reason") for row in records if not row["available"])
        ),
        "manifestSha256": fingerprint(manifest),
        "cacheIdentitySha256": identity_sha,
        "nativeDiagnosticCodeSha256": fingerprint(Path(__file__)),
        "acousticDerivative": identity.get("derivative"),
        "components": components,
        "claim": (
            "Direct all-native single-label CTC diagnostics only; no accept/reject gate, "
            "no exclusion of abstentions from quality accuracy, no child-validation claim."
        ),
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = report(args.manifest, args.cache, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}))


if __name__ == "__main__":
    main()
