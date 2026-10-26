"""Frozen context lexical phones for OMPAL, independent of acoustic predictions.

Expert ratings decide correctness; this module only defines intended phones.
Flagged entries retain alignment anchors but cannot establish unambiguous
four-tone correctness. word.text alternatives are never concatenated.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from pypinyin import Style, pinyin
from pypinyin.style._utils import get_finals, get_initials

from pinyin_matcher.catalog import ROOT


@lru_cache(maxsize=1)
def _policy() -> dict:
    return json.loads((ROOT / "content/pronunciation-ompal-policy.json").read_text())


@lru_cache(maxsize=1)
def _rules() -> dict:
    return json.loads((ROOT / "content/pronunciation-rules.json").read_text())


def _components(syllable: str) -> dict:
    match = re.fullmatch(r"([a-züv]+)([1-5])", syllable)
    if match is None:
        return {"onset": None, "rime": None, "tone": None}
    base, tone = match.groups()
    base = base.replace("v", "ü")
    initial = get_initials(base, strict=True)
    final = get_finals(base, strict=True)
    final = _rules()["apicalRimes"].get(initial + ":" + final, final)
    return {"onset": initial, "rime": final or None, "tone": int(tone)}


def annotate_prompt(text: str, words: list[dict]) -> list[dict]:
    """Return the same annotation-word count/order with alignment-ready phones.

    No model agreement, inferred learner pronunciation or correctness rating
    participates in expected-label selection. All unsupported contexts remain
    flagged; unknown prompts use G2P only as a visibly unreviewed anchor.
    """
    policy = _policy()
    prompts = {p["text"]: p for p in policy["prompts"]}
    primary = []
    for word in words:
        value = word.get("text", [])
        if isinstance(value, str):
            value = [value]
        primary.append(str(value[0]) if value else "")
    joined = "".join(primary)
    reviewed = prompts.get(text)
    match = joined == text
    if reviewed is not None and match:
        expected = reviewed["lexicalPinyin"]
        prompt_flags = reviewed["labelPolicyFlagsByIndex"]
    else:
        expected = [
            part[0] for part in pinyin(joined, style=Style.TONE3, neutral_tone_with_five=True)
        ]
        prompt_flags = [[] for _ in joined]
    result = []
    offset = 0
    for word, token in zip(words, primary, strict=True):
        alternatives = word.get("text", [])
        if isinstance(alternatives, str):
            alternatives = [alternatives]
        flags = set()
        if not match:
            flags.add("PROMPT_WORD_TEXT_MISMATCH")
        if reviewed is None:
            flags.add("PROMPT_NOT_CONTEXT_REVIEWED")
        if len(alternatives) != 1:
            flags.add("WORD_TEXT_ALTERNATIVES")
        if len(token) != 1:
            flags.add("NON_SINGLE_CHARACTER_WORD")
        parts = expected[offset : offset + len(token)]
        for local in prompt_flags[offset : offset + len(token)]:
            flags.update(local)
        syllable = parts[0] if len(parts) == 1 else None
        components = (
            _components(syllable)
            if syllable is not None
            else {"onset": None, "rime": None, "tone": None}
        )
        if components["rime"] is None:
            flags.add("NO_SUPPORTED_PHONETIC_DECOMPOSITION")
        result.append(
            {
                "text": token,
                "textAlternatives": list(alternatives),
                "expectedPinyin": syllable,
                "alignmentPinyin": parts,
                **components,
                "labelPolicyFlags": sorted(flags),
                "pinyinProvenance": {
                    "policy": policy["policyVersion"],
                    "tool": "pypinyin==0.55.0",
                    "contextReviewed": reviewed is not None and match,
                    "realizedPhoneticTranscription": False,
                    "expertCorrectnessUsedToChoosePinyin": False,
                },
            }
        )
        offset += len(token)
    return result
