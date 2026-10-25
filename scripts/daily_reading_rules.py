"""Source-aware DAILY-12 rules shared by maintenance and full-catalogue validation.

The supplied PDF (and possibly its original Word) itself contains repetitions.
Deduplicate each section independently, never by hard-coded positions from one Word
revision. Capture a new source ledger and review it whenever the source changes.
"""

import unicodedata

MARKS = {"\u0304": 1, "\u0301": 2, "\u030c": 3, "\u0300": 4}


def key(item: dict) -> tuple[str, ...]:
    # Preserve tone marks and repeated syllables *inside* a word or sentence.
    return tuple(unicodedata.normalize("NFC", s) for s in item["syllables"])


def unique_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        identity = key(item)
        if identity not in seen:
            result.append(item)
            seen.add(identity)
    return result


def pronunciation(syllable: str, *, neutral: bool, consonants: set[str]) -> str:
    decomposed = unicodedata.normalize("NFD", syllable)
    tone = next((MARKS[c] for c in decomposed if c in MARKS), None)
    base = unicodedata.normalize("NFC", "".join(c for c in decomposed if c not in MARKS))
    base = base.replace("ü", "v")
    suffix = "" if neutral or syllable in consonants else str(tone or 1)
    return f"daily-{base}{suffix}"


def expected_audio(item: dict, policy: dict, consonants: set[str]) -> list[str]:
    neutral = policy["neutralSyllableIndices"].get(item["id"], [])
    missing = set(item["missingSyllables"])
    return [
        pronunciation(s, neutral=n in neutral, consonants=consonants)
        for n, s in enumerate(item["syllables"])
        if s not in missing
    ]
