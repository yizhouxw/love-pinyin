"""Recompile explicit target content using pinned pypinyin and checked-in teaching rules."""

import argparse
import json
import unicodedata
from pathlib import Path

from pypinyin.style._utils import get_finals, get_initials

root = Path(__file__).resolve().parents[1]
config = json.load(open(root / "content/pronunciation-training.json"))
rules = json.load(open(root / "content/pronunciation-rules.json"))
c = json.load(open(root / "content/curriculum.json"))
d = json.load(open(root / "content/daily-reading.json"))
recognition = json.load(open(root / "content/reading-recognition.json"))
challenges = json.load(open(root / "content/pronunciation-challenges.json"))["definitions"]
pilot = [x["pinyin"] for x in config["pilotDefinitions"]]
texts = {x["pinyin"]: x["ttsText"] for x in config["pilotDefinitions"] + challenges}
items = {}
for day in d["days"]:
    for section in day["sections"]:
        for item in section["items"]:
            for syllable in item["syllables"]:
                items.setdefault(syllable, {"sourceItemId": item["id"]})


def decode(py):
    tone = rules["defaultUnmarkedTone"]
    out = []
    for ch in unicodedata.normalize("NFD", py):
        if ch in rules["toneCombiningMarks"]:
            tone = rules["toneCombiningMarks"][ch]
        else:
            out.append(ch)
    return unicodedata.normalize("NFC", "".join(out)), tone


assets = {x["filename"]: x["id"] for x in d["assets"]}
targets = []
for py in sorted(set(items) | set(texts)):
    base, tone = decode(py)
    form = "whole-syllable"
    if base in c["inventory"]["initials"] + c["inventory"]["orthographicLetters"] and tone == 0:
        form = "initial-reading"
        spoken = recognition["initialReadingAliases"][base][-1]
        tone = rules["nonSyllabicReadingTone"]
    else:
        spoken = base
        if base in c["inventory"]["finals"] and get_initials(base, strict=True) == "":
            form = "isolated-final"
    onset = get_initials(spoken, strict=True)
    rime = get_finals(spoken, strict=True)
    if not rime:
        continue
    rime = rules["apicalRimes"].get(onset + ":" + rime, rime)
    phones = ([f"I_{onset}"] if onset else []) + [f"F_{rime}"]
    slug = "".join(ch if ch != "ü" else "v" for ch in base) + str(tone)
    if form == "initial-reading":
        slug = "initial-" + base
    filename = (
        base.replace("ü", "v") + (str(tone) if tone and form != "initial-reading" else "") + ".mp3"
    )
    target = {
        "id": "pm-" + slug,
        "pinyin": py,
        "form": form,
        "phones": phones,
        "onset": onset,
        "rime": rime,
        "tone": tone,
        "ttsText": texts.get(py),
        "standardAudioId": assets.get(filename),
        "sourceItemId": items.get(py, {}).get("sourceItemId"),
        "pilot": py in pilot,
    }
    targets.append(target)
# Normalize duplicated unmarked first-tone targets to separate stable IDs.
ids = set()
for x in targets:
    if x["id"] in ids:
        x["id"] += "-unmarked"
    ids.add(x["id"])
tokens = ["<blank>"] + sorted({p for t in targets for p in t["phones"]})
for x in targets:
    x["neighbors"] = [
        t["id"]
        for t in targets
        if t["id"] != x["id"]
        and (
            sum(a != b for a, b in zip(x["phones"], t["phones"], strict=False))
            + abs(len(x["phones"]) - len(t["phones"]))
            <= 1
        )
    ]
# Runtime comparison also considers the whole supported vocabulary.
for x in targets:
    x["neighbors"] = sorted(
        x["neighbors"],
        key=lambda key: (next(t["phones"] for t in targets if t["id"] == key) != x["phones"], key),
    )[:12]
compiled = {
    "version": 1,
    "contentVersion": c["contentVersion"],
    "source": "daily-reading.json and curriculum inventory; pypinyin 0.55.0 decomposition",
    "toneMarks": rules["toneMarkExamples"],
    "tokens": tokens,
    "pilotIds": [t["id"] for py in pilot for t in targets if t["pinyin"] == py],
    "targets": targets,
    "toneLabels": rules["toneLabels"],
}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=root / "content/pronunciation-targets.json")
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
if args.check:
    if json.loads(args.output.read_text()) != compiled:
        raise SystemExit("TARGET_CATALOG_STALE")
else:
    args.output.write_text(
        json.dumps(
            compiled,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
print(len(targets), len(tokens), "pilot", len(pilot))
