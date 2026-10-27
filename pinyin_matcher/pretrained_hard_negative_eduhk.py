"""Add source-annotated real mispronunciations, using train-only candidate clips."""

import argparse
import json
from pathlib import Path

from pinyin_matcher import pretrained_factorized as original
from pinyin_matcher import pretrained_hard_negative as hard
from pinyin_matcher import pretrained_hard_negative_native as native
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_eduhk_clips import SOURCE, replacements
from pinyin_matcher.pretrained_experiment import read_rows, write

CONFIG = ROOT / "content/pronunciation-pretrained-hard-negative-eduhk.json"


def verify_manifest(manifest, parent, candidates, parsed, data_config):
    policy = json.loads(CONFIG.read_text())
    data, old = json.loads(manifest.read_text()), json.loads(parent.read_text())
    if (
        fingerprint(manifest) != policy["mixedManifestSha256"]
        or fingerprint(parent) != policy["parentTrainingManifestSha256"]
        or fingerprint(candidates) != policy["eduhkCandidateManifestSha256"]
        or fingerprint(data_config) != policy["eduhkDataConfigurationSha256"]
        or data["eduhkTrainingSource"]["generatorSha256"] != policy["eduhkGeneratorSha256"]
        or fingerprint(parsed) != data["eduhkTrainingSource"]["metadataSha256"]
        or data["items"][: len(old["items"])] != old["items"]
        or data["eduhkTrainingSource"]["audioOutsideTrainingDownloaded"] is not False
        or data["eduhkTrainingSource"]["finalTestRead"] is not False
    ):
        raise ValueError("EDUHK_TRAIN_MANIFEST_OR_SOURCE_CHANGED")
    source = json.loads(parsed.read_text())
    records = json.loads(data_config.read_text())
    speakers = {entry["speakerId"]: entry for entry in records["files"]}
    lookup = {
        (r["speakerId"], r["canonicalTaskIndex"]): r
        for r in source["roots"]
        if r["task"] == 1 and r["canonicalTaskIndex"] is not None
    }
    candidate_map = {item["id"]: item for item in json.loads(candidates.read_text())["items"]}
    rows = read_rows(manifest)
    extras = rows[len(old["items"]) :]
    seen = set()
    for row in extras:
        if (
            row["source"] != SOURCE
            or row["split"] != "train"
            or row["speakerId"] not in speakers
            or row["speakerId"] != row["voiceFamilyId"]
            or row["speakerId"] != row["referenceSourceId"]
            or row["parentSha256"] != speakers[row["speakerId"]]["sha256"]
            or row["alignmentFlags"] != ["UNVERIFIED_VAD_ORDER"]
            or row["labelPolicyFlags"]
            or row["numericalQualityFlags"]
        ):
            raise ValueError("EDUHK_TRAIN_ROW_LINEAGE_INVALID")
        root = row["sourceRootId"]
        candidate = candidate_map.get(root)
        if (
            candidate is None
            or candidate["status"] != "CANDIDATE_NOT_HUMAN_VERIFIED"
            or candidate["sha256"] != row["sha256"]
            or candidate["sourceAudioSha256"] != row["parentSha256"]
            or candidate["boundaryVerified"] is not False
        ):
            raise ValueError("EDUHK_TRAIN_CANDIDATE_CHANGED")
        parts = root.split("-")
        if len(parts) != 4 or parts[0] != "eduhk" or parts[2] != "task1":
            raise ValueError("EDUHK_TRAIN_ROOT_ID_INVALID")
        speaker, index = int(parts[1]), int(parts[3])
        record = lookup.get((speaker, index))
        if record is None or not record["eligibleAdult"] or record["age"] < 18:
            raise ValueError("EDUHK_TRAIN_ANNOTATION_SOURCE_INVALID")
        edits, _ = replacements(record["annotations"])
        labels = row["componentExpertLabels"]
        active = [(key, value) for key, value in labels.items() if value != "ambiguous"]
        if len(active) != 1:
            raise ValueError("EDUHK_TRAIN_UNKNOWN_COMPONENT_INVENTED")
        component, value = active[0]
        kind = (
            "expected"
            if value == "source-annotated-error"
            else "realized"
            if value == "source-provided-realized"
            else None
        )
        if kind is None or row["id"] != root + "-" + component + "-" + kind:
            raise ValueError("EDUHK_TRAIN_LABEL_INVALID")
        options = {(a, b) for c, a, b in edits if c == component}
        if len(options) != 1:
            raise ValueError("EDUHK_TRAIN_LABEL_CONFLICT")
        before, after = next(iter(options))
        expected = before if kind == "expected" else after
        if tuple(str(row[k]) for k in hard.COMPONENTS) != expected:
            raise ValueError("EDUHK_TRAIN_PINYIN_CHANGED")
        seen.add((root, component, kind))
    groups = {(root, component) for root, component, _ in seen}
    if len(seen) != len(extras) or any(
        (root, component, kind) not in seen
        for root, component in groups
        for kind in ("expected", "realized")
    ):
        raise ValueError("EDUHK_TRAIN_PAIR_INCOMPLETE")
    if len(groups) != data["eduhkTrainingSource"]["counts"]["annotatedComponents"]:
        raise ValueError("EDUHK_TRAIN_PAIR_COUNT_CHANGED")
    return data["eduhkTrainingSource"]


def eduhk_pairs(rows):
    yield from native.mixed_pairs(rows)
    vocab = {key: sorted({str(row[key]) for row in rows}) for key in hard.COMPONENTS}
    for row in sorted(rows, key=lambda item: item["id"]):
        if row.get("source") != SOURCE:
            continue
        for component in hard.COMPONENTS:
            if row["componentExpertLabels"].get(component) != "source-provided-realized":
                continue
            actual = str(row[component])
            for target in vocab[component]:
                if target != actual:
                    yield {
                        "rootId": row["id"],
                        "sourceRootId": row["sourceRootId"],
                        "audioSha256": row["sha256"],
                        "parentSha256": row["parentSha256"],
                        "speakerId": row["speakerId"],
                        "voiceFamilyId": row["voiceFamilyId"],
                        "referenceSourceId": row["referenceSourceId"],
                        "component": component,
                        "sourceProvidedActual": actual,
                        "incorrectTarget": target,
                        "label": "component-mismatch",
                        "labelBasis": "source-explicit-error-realization-unverified-vad-boundary",
                        "sourceSplit": "train",
                    }


def eduhk_supervision(rows):
    values = native.mixed_supervision(rows)
    mapping = {"source-provided-realized": 1, "source-annotated-error": 0}
    for index, row in enumerate(rows):
        if row.get("source") == SOURCE and row["split"] == "train":
            if row.get("labelPolicyFlags") or row.get("numericalQualityFlags"):
                values[index] = -1
            else:
                values[index] = [
                    mapping.get(row["componentExpertLabels"].get(c), -1) for c in hard.COMPONENTS
                ]
    return values


def run(
    action, manifest, parent, candidates, parsed, data_config, output, *, cache=None, evidence=None
):
    source = verify_manifest(manifest, parent, candidates, parsed, data_config)
    old_config, old_pairs, old_supervision = hard.CONFIG, hard.pairs, original.supervision
    try:
        hard.CONFIG, hard.pairs, original.supervision = CONFIG, eduhk_pairs, eduhk_supervision
        if action == "prepare":
            result = hard.prepare(manifest, output)
            result["eduhkPairCodeSha256"] = fingerprint(Path(__file__))
            result["distinctTrainingComparisonRows"] = result["distinctSourceRoots"]
            rows = hard.training_rows(manifest)
            # EdUHK's expected/realized rows share one physical candidate root.
            ed_rows = [
                r
                for r in rows
                if r.get("source") == SOURCE
                and "source-provided-realized" in r["componentExpertLabels"].values()
            ]
            result["distinctSourceRoots"] -= len(ed_rows)
            result["distinctSourceRoots"] += len({r["sourceRootId"] for r in ed_rows})
            result["eduhkSourceRecordings"] = source["sourceRecordingCount"]
            result["eduhkCandidateSpeakers"] = source["counts"]["trainingSpeakerIds"]
            result["eduhkCandidateAudioRoots"] = source["counts"]["uniqueTrainingAudioRoots"]
            result["eduhkExplicitWrongComponents"] = source["counts"]["annotatedComponents"]
            result["limitations"] = (
                "OMPAL expert votes, AISHELL source human pinyin and EdUHK explicit "
                "human error annotations. EdUHK word order and boundaries are not "
                "independently verified. Research use only."
            )
            write(output / "metadata.json", result)
            return result
        evidence_metadata = json.loads((evidence / "metadata.json").read_text())
        if evidence_metadata.get("eduhkPairCodeSha256") != fingerprint(Path(__file__)):
            raise ValueError("EDUHK_PAIR_CODE_CHANGED")
        result = hard.train(manifest, cache, evidence, output)
        path = output / "model.json"
        metadata = json.loads(path.read_text())
        metadata["eduhkTrainingCodeSha256"] = fingerprint(Path(__file__))
        metadata["eduhkDataConfigurationSha256"] = fingerprint(data_config)
        metadata["eduhkSourceRights"] = source["license"]
        metadata["eduhkSourceUrl"] = source["source"]
        metadata["eduhkCandidateAudioRoots"] = source["counts"]["uniqueTrainingAudioRoots"]
        metadata["eduhkBoundaryStatus"] = "Candidate VAD order; no individual human verification."
        metadata["researchUseOnly"] = True
        write(path, metadata)
        return result
    finally:
        hard.CONFIG, hard.pairs, original.supervision = old_config, old_pairs, old_supervision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "train"))
    for name in ("manifest", "parent", "candidates", "parsed", "data-config", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = vars(parser.parse_args())
    if args["action"] == "train" and (args["cache"] is None or args["evidence"] is None):
        parser.error("train requires --cache and --evidence")
    print(json.dumps(run(**args), ensure_ascii=False))


if __name__ == "__main__":
    main()
