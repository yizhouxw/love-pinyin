"""Target-independent native phonetic readouts, without text or subset renormalization.

HanziFlow uses complete single-label CTC event probabilities. Charsiu is a
frame classifier: its tone-bearing final phones are acoustic evidence, never
CTC labels. Returned auxiliary evidence MUST be checked before classification;
forceUncertain prevents an out-of-vocabulary prediction becoming a known label.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from pinyin_matcher.catalog import ROOT
from pinyin_matcher.pretrained_features import configuration


def native_rime_aliases(name: str, config: dict | None = None) -> dict[str, str]:
    """Explicit model-native tokens; ii/iii have opposite upstream meanings.

    HanziFlow's pinned target schema defines retroflex=ii, dental=iii;
    Charsiu's pinned processor defines retroflex=iii, dental=ii. A shared
    fallback would silently exchange these phonetic classes, so fail closed.
    """
    if name not in {"hanziflow", "charsiu"}:
        raise ValueError("NATIVE_MODEL_UNKNOWN")
    cfg = configuration() if config is None else config
    aliases = cfg.get("nativeRimeAliasesByModel", {}).get(name)
    if not isinstance(aliases, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in aliases.items()
    ):
        raise ValueError("NATIVE_MODEL_RIME_ALIASES_REQUIRED")
    required = {"i-retroflex": "ii", "i-dental": "iii"}
    if name == "charsiu":
        required = {"i-retroflex": "iii", "i-dental": "ii"}
    if any(aliases.get(key) != value for key, value in required.items()):
        raise ValueError("NATIVE_MODEL_APICAL_ALIAS_SCHEMA_MISMATCH")
    return dict(aliases)


def _probabilities(logits: np.ndarray) -> np.ndarray:
    values = np.array(logits, dtype=np.float64, copy=True)
    if values.ndim != 2 or not len(values) or not np.isfinite(values).all():
        raise ValueError("NATIVE_LOGITS_INVALID")
    values -= values.max(-1, keepdims=True)
    exp = np.exp(values)
    return exp / exp.sum(-1, keepdims=True)


def single_label_ctc(logits: np.ndarray, blank: int = 0) -> tuple[np.ndarray, float, float]:
    """Exact P(CTC collapse=[class]), P(empty), P(two-or-more labels).

    A repeated label after an intervening blank is a TWO-label event. No
    length-normalization or conditioning on the expected label is applied.
    """
    probabilities = _probabilities(logits)
    logp = np.log(np.maximum(probabilities, np.finfo(np.float64).tiny))
    classes = probabilities.shape[1]
    before = np.zeros(classes)
    during = np.full(classes, -np.inf)
    after = np.full(classes, -np.inf)
    for frame in logp:
        after = np.logaddexp(after, during) + frame[blank]
        during = np.logaddexp(during, before) + frame
        before = before + frame[blank]
    scores = np.exp(np.logaddexp(during, after))
    scores[blank] = 0
    empty = float(np.exp(before[0]))
    multiple = float(max(0.0, 1 - empty - scores.sum()))
    return scores, empty, multiple


def _runs(
    probabilities: np.ndarray, vocabulary: Mapping[str, int], resolution: float
) -> list[dict]:
    inverse = {value: key for key, value in vocabulary.items()}
    ids = probabilities.argmax(-1)
    result = []
    start = 0
    for i in range(1, len(ids) + 1):
        if i == len(ids) or ids[i] != ids[start]:
            result.append(
                {
                    "phone": inverse[int(ids[start])],
                    "start": start * resolution,
                    "end": i * resolution,
                    "frames": i - start,
                }
            )
            start = i
    return result


def _source_vocab(name: str) -> dict:
    directory = ROOT / "models" / "pinyin-pretrained" / name
    if name == "hanziflow":
        return {
            k: json.loads((directory / f"v2_1_{k}_vocabulary.json").read_text())
            for k in ("initial", "final", "tone")
        }
    return {"phone": json.loads((directory / "vocab.json").read_text())}


def _map_mass(distribution: Mapping[str, float], targets: list[str]) -> tuple[np.ndarray, float]:
    result = np.array([distribution.get(str(t), 0.0) for t in targets], dtype=np.float64)
    return result, float(max(0.0, 1 - result.sum()))


def native_probabilities(
    name: str,
    evidence: Mapping[str, Any] | Path | str,
    vocab: dict,
    *,
    native_vocab: dict | None = None,
    config: dict | None = None,
) -> tuple[list[np.ndarray], dict]:
    """Return generic onset/rime/tone arrays and mandatory availability evidence.

    `evidence` is a cache mapping/npz with native_initial/final/tone or native_phone.
    Values do not sum to one if mass belongs to native unknown/outside classes.
    `native_vocab` is injectable for testing or alternate fixed local packages.
    """
    if isinstance(evidence, (str, Path)):
        with np.load(evidence, allow_pickle=False) as loaded:
            return native_probabilities(
                name, dict(loaded), vocab, native_vocab=native_vocab, config=config
            )
    targets = [[str(v) for v in vocab[k]] for k in ("onset", "rime", "tone")]
    empty = [np.zeros(len(v), dtype=np.float64) for v in targets]
    if name == "sensevoice":
        return empty, {
            "unavailable": True,
            "forceUncertain": True,
            "reason": "NO_NATIVE_PHONETIC_OR_TONE_HEAD",
        }
    if name not in {"hanziflow", "charsiu"}:
        raise ValueError("NATIVE_MODEL_UNKNOWN")
    source = native_vocab if native_vocab is not None else _source_vocab(name)
    cfg = config if config is not None else configuration()
    aliases = native_rime_aliases(name, cfg)
    if name == "hanziflow":
        distributions, extra, greedy = [], [], []
        force = False
        for key, target in zip(("initial", "final", "tone"), targets, strict=True):
            logits = evidence["native_" + key]
            table = source[key]
            probs = _probabilities(logits)
            if probs.shape[1] != len(table) or set(table.values()) != set(range(len(table))):
                raise ValueError("NATIVE_VOCABULARY_SHAPE_MISMATCH")
            scores, blank_mass, multi_mass = single_label_ctc(logits, table["<blank>"])
            native = {token: float(scores[index]) for token, index in table.items()}
            mapped = {}
            for token, value in native.items():
                canonical = "" if key == "initial" and token == "ZERO" else token
                if key == "tone" and token.startswith("T"):
                    canonical = token[1:]
                mapped[canonical] = mapped.get(canonical, 0.0) + value
            native_targets = [aliases.get(t, t) if key == "final" else t for t in target]
            values, unmapped = _map_mass(mapped, native_targets)
            distributions.append(values)
            best = max(native, key=native.get)
            best_canonical = "" if key == "initial" and best == "ZERO" else best
            if key == "tone" and best.startswith("T"):
                best_canonical = best[1:]
            runs = _runs(probs, table, 0.02)
            sequence = [r["phone"] for r in runs if r["phone"] != "<blank>"]
            greedy.append(sequence)
            outside = best_canonical not in native_targets
            force |= (
                outside or blank_mass >= max(native.values()) or multi_mass >= max(native.values())
            )
            force |= len(sequence) != 1 or "<unk>" in sequence
            extra.append(
                {
                    "singleLabelMass": float(scores.sum()),
                    "unknownMass": native.get("<unk>", 0.0),
                    "blankMass": blank_mass,
                    "multipleLabelMass": multi_mass,
                    "unmappedMass": unmapped,
                    "nativeBest": best,
                    "nativeBestOutsideCoverage": outside,
                }
            )
        return distributions, {
            "unavailable": False,
            "forceUncertain": bool(force),
            "componentEvidence": extra,
            "componentGreedy": greedy,
            "multipleRead": any(len(s) > 1 for s in greedy),
            "method": "exact-all-native-single-label-CTC-events",
        }

    table = source["phone"]
    probabilities = _probabilities(evidence["native_phone"])
    if probabilities.shape[1] != len(table) or set(table.values()) != set(range(len(table))):
        raise ValueError("NATIVE_VOCABULARY_SHAPE_MISMATCH")
    final_tokens = {
        token: (match[1], match[2])
        for token in table
        if (match := re.fullmatch(r"(.+)([1-5])", token))
    }
    initial_tokens = [t for t in table if t not in final_tokens and not t.startswith("[")]
    final_indices = [table[t] for t in final_tokens]
    initial_indices = [table[t] for t in initial_tokens]
    final_mass = probabilities[:, final_indices].sum()
    final_presence = float(probabilities[:, final_indices].sum(-1).max())
    initial_mass = probabilities[:, initial_indices].sum()
    initial_presence = float(probabilities[:, initial_indices].sum(-1).max())
    onset = {"": 1 - initial_presence}
    if initial_mass > 0:
        onset.update(
            {
                t: float(probabilities[:, table[t]].sum() / initial_mass * initial_presence)
                for t in initial_tokens
            }
        )
    rime: dict[str, float] = {}
    tone: dict[str, float] = {}
    final_phone = {}
    if final_mass > 0:
        for token, (r, t) in final_tokens.items():
            value = float(probabilities[:, table[token]].sum() / final_mass * final_presence)
            rime[r] = rime.get(r, 0) + value
            tone[t] = tone.get(t, 0) + value
            final_phone[token] = value
    mapped_rimes = [aliases.get(t, t) for t in targets[1]]
    outputs, masses = [], []
    for distribution, target in zip(
        (onset, rime, tone), (targets[0], mapped_rimes, targets[2]), strict=True
    ):
        values, missing = _map_mass(distribution, target)
        outputs.append(values)
        masses.append(missing)
    runs = _runs(probabilities, table, 0.01)
    spoken = [r for r in runs if r["phone"] not in {"[SIL]", "[PAD]"}]
    final_runs = [r for r in spoken if r["phone"] in final_tokens]
    pause = cfg.get("features", {}).get("extraSyllablePauseSeconds", 0.18)
    syllables = 0
    previous = None
    for run in final_runs:
        base, _ = final_tokens[run["phone"]]
        if previous is None or base != previous[0] or run["start"] - previous[1] >= pause:
            syllables += 1
        previous = (base, run["end"])
    best_onset = max(onset, key=onset.get)
    best_rime = max(rime, key=rime.get) if rime else None
    best_tone = max(tone, key=tone.get) if tone else None
    best_final = max(final_phone, key=final_phone.get) if final_phone else None
    consistent = best_final is not None and final_tokens[best_final] == (best_rime, best_tone)
    outside = [
        best_onset not in targets[0],
        best_rime not in mapped_rimes,
        best_tone not in targets[2],
    ]
    unknown = any(r["phone"] == "[UNK]" for r in spoken)
    force = syllables != 1 or unknown or any(outside) or not consistent
    return outputs, {
        "unavailable": bool(final_mass <= 0),
        "forceUncertain": bool(force),
        "unmappedMass": masses,
        "finalGroupPresence": final_presence,
        "meanUnknownFrameMass": float(probabilities[:, table["[UNK]"]].mean())
        if "[UNK]" in table
        else 0.0,
        "phoneRuns": runs,
        "componentGreedy": [r["phone"] for r in spoken],
        "syllableRuns": syllables,
        "multipleRead": syllables > 1,
        "nativeBest": [best_onset, best_rime, best_tone],
        "nativeBestFinalPhone": best_final,
        "jointFinalToneConsistent": consistent,
        "nativeBestOutsideCoverage": outside,
        "method": "full-native-framephone-group-marginals",
    }


def calibration_report(name: str, manifest: Path, cache: Path) -> dict:
    """Run native heads on every calibration root; never reads the test split.

    The hard-negative unit asks whether ANY alternate complete component tuple
    would be accepted. This is conservative over the full component vocabulary;
    it includes tuples absent from the task lexicon and is labelled accordingly.
    """
    from collections import Counter

    from pinyin_matcher.catalog import fingerprint
    from pinyin_matcher.pretrained_experiment import classify
    from pinyin_matcher.pretrained_metrics import metrics

    data = json.loads(manifest.read_text())
    training = [r for r in data["items"] if r["split"] == "train"]
    rows = [r for r in data["items"] if r["split"] == "calibration"]
    vocab = {k: sorted({str(r[k]) for r in training}) for k in ("onset", "rime", "tone")}
    cfg = configuration()
    prepared = []
    for row in rows:
        file = cache / (row["sha256"] + ".npz")
        if not file.is_file():
            raise FileNotFoundError(f"Calibration cache incomplete: {file}")
        try:
            ps, evidence = native_probabilities(name, file, vocab)
        except (ValueError, KeyError, OSError) as exc:
            ps = [np.zeros(len(vocab[k])) for k in vocab]
            evidence = {
                "unavailable": True,
                "forceUncertain": True,
                "reason": type(exc).__name__ + ":" + str(exc),
            }
        truth = [vocab[k].index(str(row[k])) for k in vocab]
        prepared.append((row, ps, evidence, truth))

    def records_for(threshold):
        result = []
        for row, ps, evidence, truth in prepared:
            if evidence["unavailable"]:
                status = "unavailable"
            elif evidence["forceUncertain"]:
                status = "uncertain"
            else:
                status = classify(ps, truth, threshold)
            negative_status = {"matched": "retry", "retry": "matched"}.get(status, status)
            shared = {
                "root_id": row["id"],
                "speaker_id": row["speakerId"],
                "source": row["source"],
                "clear": not row.get("numericalQualityFlags"),
            }
            result.append({**shared, "label": "positive", "status": status})
            result.append(
                {
                    **shared,
                    "label": "negative",
                    "status": negative_status,
                    "error_type": "any-alternative-component-tuple",
                }
            )
        return result

    candidates = []
    for probability in cfg["acceptProbabilities"]:
        for margin in cfg["acceptMargins"]:
            threshold = {"probability": probability, "margin": margin}
            records = records_for(threshold)
            positive = Counter(r["status"] for r in records if r["label"] == "positive")
            n = len(rows)
            rates = {
                "falseAcceptance": positive["retry"] / n,
                "explicitRejection": positive["retry"] / n,
                "abstention": (positive["uncertain"] + positive["unavailable"]) / n,
            }
            violation = sum(
                max(0, rates[key] / limit - 1)
                for key, limit in (
                    ("falseAcceptance", 0.05),
                    ("explicitRejection", 0.1),
                    ("abstention", 0.2),
                )
            )
            candidates.append(
                {
                    "threshold": threshold,
                    "counts": dict(positive),
                    "rates": rates,
                    "violation": violation,
                }
            )
    selected = min(
        candidates,
        key=lambda c: (c["violation"], c["rates"]["abstention"], c["rates"]["falseAcceptance"]),
    )
    return {
        "schemaVersion": 1,
        "model": name,
        "split": "calibration",
        "testRead": False,
        "n": len(rows),
        "speakers": len({r["speakerId"] for r in rows}),
        "negativePolicy": "Any alternate component tuple, including non-lexical tuples",
        "manifestSha256": fingerprint(manifest),
        "nativeCodeSha256": fingerprint(Path(__file__)),
        "cacheMetadataSha256": fingerprint(cache / "cache.json"),
        "vocabulary": vocab,
        "selected": selected,
        "candidates": candidates,
        "metrics": metrics(records_for(selected["threshold"])),
        "diagnostics": [
            {
                "id": row["id"],
                "sha256": row["sha256"],
                "componentProbabilities": [p.tolist() for p in ps],
                "evidence": ev,
            }
            for row, ps, ev, _ in prepared
        ],
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", choices=["hanziflow", "charsiu"], required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = calibration_report(args.name, args.manifest, args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("model", "n", "speakers", "selected")}))


if __name__ == "__main__":
    main()
