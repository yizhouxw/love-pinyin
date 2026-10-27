"""Supplement training with human-transcribed real speech and candidate boundaries."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_align import align_components
from pinyin_matcher.pretrained_experiment import read_rows, write
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_native_sequence import (
    _native_manifest,
    _read_pcm,
    validate_cached_labels,
    vocabularies,
)
from pinyin_matcher.pretrained_ompal_clips import word_audio
from pinyin_matcher.pretrained_ompal_policy import _components
from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

CONFIG = ROOT / "content/pronunciation-pretrained-native-clips.json"
SOURCE = "aishell3-supplementary-native-2000-v1"


def selected_items(items, seed, per_speaker):
    grouped = defaultdict(list)
    for item in items:
        grouped[item["speakerId"]].append(item)
    if len(grouped) != 20 or any(len(value) < per_speaker for value in grouped.values()):
        raise ValueError("NATIVE_CLIPS_SPEAKER_INVENTORY_CHANGED")
    result = []
    for speaker, values in sorted(grouped.items()):
        values = sorted(
            values,
            key=lambda item: hashlib.sha256(f"{seed}:{speaker}:{item['id']}".encode()).hexdigest(),
        )
        result.extend(values[:per_speaker])
    return result


def prepare(source_manifest, native_cache, ompal_manifest, model, output, *, device="mps"):
    if output.exists():
        raise ValueError("NATIVE_CLIPS_OUTPUT_EXISTS")
    config = json.loads(CONFIG.read_text())
    if (
        config["seed"] != 20261027
        or config["utterancesPerSpeaker"] != 25
        or config["trainingOnly"] is not True
        or config["finalTestUsed"] is not False
        or fingerprint(source_manifest) != config["nativeManifestSha256"]
        or fingerprint(native_cache / "cache.json") != config["nativeCacheMetadataSha256"]
        or fingerprint(ompal_manifest) != config["ompalManifestSha256"]
    ):
        raise ValueError("NATIVE_CLIPS_PROTOCOL_OR_INPUT_CHANGED")
    metadata = json.loads((native_cache / "cache.json").read_text())
    source_rows = _native_manifest(source_manifest)
    validate_cached_labels(metadata, source_rows, vocabularies(model), native_cache)
    items = selected_items(metadata["items"], config["seed"], config["utterancesPerSpeaker"])
    roots = {row["id"]: row for row in source_rows}
    old_rows = read_rows(ompal_manifest)
    teacher = Wav2VecEvidence("hanziflow", model, device=device)
    aliases = native_rime_aliases("hanziflow")
    output.mkdir(parents=True)
    clips = output / "clips"
    clips.mkdir()
    generated, counts = [], Counter()
    for offset in range(0, len(items), 4):
        batch = items[offset : offset + 4]
        waves = []
        for item in batch:
            audio = item["audio"]
            source = roots[item["id"]]
            if (
                audio["sourceSha256"] != source["sha256"]
                or fingerprint(Path(audio["file"])) != audio["sha256"]
            ):
                raise ValueError("NATIVE_CLIPS_AUDIO_PROVENANCE_CHANGED")
            waves.append(_read_pcm(Path(audio["file"]), rate=16000)[0])
        for item, samples, result in zip(batch, waves, teacher.evidence_batch(waves), strict=True):
            labels = [
                {"id": f"{item['id']}-s{index:03d}", "syllable": syllable, **_components(syllable)}
                for index, syllable in enumerate(item["providedPinyin"])
            ]
            bounds = align_components(
                result["native"], labels, len(samples) / 16000, directory=model, aliases=aliases
            )
            for index, label in enumerate(labels):
                audio, window, numeric_flags = word_audio(samples, bounds, index)
                alignment_flags = bounds[index]["flags"]
                label_flags = []
                if label["tone"] not in (1, 2, 3, 4):
                    label_flags.append("SOURCE_NEUTRAL_TONE_OUTSIDE_FOUR_TONE_EXPERIMENT")
                if alignment_flags:
                    label_flags.append("SOURCE_BOUNDARY_UNVERIFIED")
                path = clips / (label["id"] + ".wav")
                path.write_bytes(encode_wav(audio))
                row = {
                    **label,
                    "file": str(path.resolve()),
                    "sha256": fingerprint(path),
                    "split": "train",
                    "speakerId": item["speakerId"],
                    "voiceFamilyId": item["speakerId"],
                    "referenceSourceId": item["speakerId"],
                    "source": SOURCE,
                    "parentSha256": item["audio"]["sourceSha256"],
                    "parentFile": roots[item["id"]]["file"],
                    "sourceUtteranceId": item["id"],
                    "labelProvenance": (
                        "source-human-listened-realized-pinyin-not-independent-clip-review"
                    ),
                    "expertLabel": "source-provided-realized",
                    "componentExpertLabels": {
                        c: "source-provided-realized" for c in ("onset", "rime", "tone")
                    },
                    "alignment": bounds[index],
                    "alignmentFlags": alignment_flags,
                    "alignmentIsCorrectnessEvidence": False,
                    "numericalQualityFlags": numeric_flags,
                    "labelPolicyFlags": label_flags,
                    "bounds": window,
                    "placeholder": window["placeholder"],
                    "durationSeconds": len(audio) / 16000,
                }
                generated.append(row)
                counts["generatedWords"] += 1
                counts["trainingEligible"] += not (
                    numeric_flags or label_flags or window["placeholder"]
                )
                counts["weakOrOverlapping"] += bool(alignment_flags)
                counts["numericalFlags"] += bool(numeric_flags)
                counts["neutralTone"] += label["tone"] not in (1, 2, 3, 4)
        if offset % 20 == 0:
            print(
                json.dumps(
                    {"utterances": min(offset + 4, len(items)), "total": len(items), **counts}
                ),
                flush=True,
            )
    result = {
        "schemaVersion": 1,
        "items": old_rows + generated,
        "nativeTrainingSource": {
            "manifestSha256": fingerprint(source_manifest),
            "cacheSha256": fingerprint(native_cache / "cache.json"),
            "configurationSha256": fingerprint(CONFIG),
            "generatorSha256": fingerprint(Path(__file__)),
            "sourceCorpus": SOURCE,
            "license": "Apache-2.0",
            "sourceUtterances": len(items),
            "sourceSpeakers": len({x["speakerId"] for x in items}),
            "counts": dict(counts),
            "alignmentModelRevision": json.loads(
                (ROOT / "content/pronunciation-pretrained-models.json").read_text()
            )["models"]["hanziflow"]["revision"],
            "alignmentModelWeightsSha256": fingerprint(model / "model.safetensors"),
            "selection": "Fixed hash ordering, 25 utterances per speaker before reading samples.",
            "limitations": (
                "Source pinyin was human-listened; candidate boundaries were not "
                "individually human verified. Training only."
            ),
            "finalTestRead": False,
        },
    }
    write(output / "manifest.json", result)
    read_rows(output / "manifest.json")
    return result["nativeTrainingSource"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-manifest", "native-cache", "ompal-manifest", "model", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    print(json.dumps(prepare(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == "__main__":
    main()
