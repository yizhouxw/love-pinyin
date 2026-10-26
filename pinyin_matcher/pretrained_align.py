"""Known phonetic sequence CTC alignment for corpus word boundaries only.

The supplied word sequence comes from corpus/expert metadata. A forced path is
never evidence that a speaker pronounced those phones or tones correctly. All
words remain in the result when alignment fails; none are silently dropped.
"""

from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path

import numpy as np
from scipy.special import log_softmax

HEADS = ("initial", "final", "tone")


class AlignmentUnavailable(ValueError):
    """A sequence has no usable full CTC alignment."""


def ctc_viterbi(logits: np.ndarray, tokens: list[int], *, blank: int = 0) -> dict:
    """Best full CTC path, including the required blank between repeated labels."""
    logits = np.asarray(logits, dtype=np.float64)
    if logits.ndim != 2 or not all(logits.shape):
        raise AlignmentUnavailable("NATIVE_SHAPE_INVALID")
    if not np.isfinite(logits).all():
        raise AlignmentUnavailable("NATIVE_NONFINITE")
    frames, classes = logits.shape
    if (
        not tokens
        or not 0 <= blank < classes
        or any(isinstance(token, bool) or not isinstance(token, int) for token in tokens)
        or any(not 0 <= token < classes or token == blank for token in tokens)
    ):
        raise AlignmentUnavailable("CTC_LABEL_INVALID")
    minimum_frames = len(tokens) + sum(a == b for a, b in zip(tokens, tokens[1:], strict=False))
    if frames < minimum_frames:
        raise AlignmentUnavailable("CTC_ALIGNMENT_IMPOSSIBLE")
    log_probs = log_softmax(logits, axis=-1)
    expanded = np.full(len(tokens) * 2 + 1, blank, dtype=np.int64)
    expanded[1::2] = tokens
    states = len(expanded)
    allowed_skip = np.zeros(states, dtype=bool)
    allowed_skip[2:] = (expanded[2:] != blank) & (expanded[2:] != expanded[:-2])
    previous = np.full(states, -np.inf)
    previous[:2] = log_probs[0, expanded[:2]]
    back = np.zeros((frames, states), dtype=np.int32)
    state_indices = np.arange(states)
    for frame in range(1, frames):
        choices = np.stack(
            (
                previous,
                np.r_[-np.inf, previous[:-1]],
                np.r_[-np.inf, -np.inf, previous[:-2]],
            )
        )
        choices[2, ~allowed_skip] = -np.inf
        transition = choices.argmax(axis=0)
        previous = choices[transition, state_indices] + log_probs[frame, expanded]
        back[frame] = state_indices - transition
    final_state = states - 1 if previous[-1] >= previous[-2] else states - 2
    path_score = float(previous[final_state])
    if not math.isfinite(path_score):
        raise AlignmentUnavailable("CTC_ALIGNMENT_IMPOSSIBLE")
    path = np.empty(frames, dtype=np.int32)
    path[-1] = final_state
    for frame in range(frames - 1, 0, -1):
        path[frame - 1] = back[frame, path[frame]]
    word_frames = [np.flatnonzero(path == 2 * index + 1) for index in range(len(tokens))]
    if any(not len(indices) for indices in word_frames):
        raise AlignmentUnavailable("CTC_WORD_MISSING")
    return {
        "states": path,
        "path": expanded[path],
        "wordFrames": word_frames,
        "logProbability": path_score,
        "meanLogProbability": path_score / frames,
        "unconstrainedGapPerFrame": float((log_probs.max(axis=1).sum() - path_score) / frames),
        "logPosteriors": log_probs,
    }


def _vocabularies(directory: Path) -> dict:
    return {
        head: json.loads((directory / f"v2_1_{head}_vocabulary.json").read_text()) for head in HEADS
    }


def _failure(labels: list[dict], reason: str) -> list[dict]:
    return [
        {
            "index": index,
            "id": label.get("id"),
            "available": False,
            "startSeconds": None,
            "endSeconds": None,
            "boundaryOnly": True,
            "correctnessFromForcedAlignment": False,
            "flags": [reason],
            "heads": {head: {"available": False, "flags": [reason]} for head in HEADS},
        }
        for index, label in enumerate(labels)
    ]


def _word_tokens(label: dict, aliases: dict) -> dict:
    onset = label.get("onset", label.get("initial"))
    rime = label.get("rime", label.get("final"))
    tone = label.get("tone")
    if onset is None or rime is None or tone is None:
        raise AlignmentUnavailable("WORD_COMPONENT_MISSING")
    if not isinstance(onset, str) or not isinstance(rime, str) or not rime:
        raise AlignmentUnavailable("WORD_COMPONENT_INVALID")
    onset = unicodedata.normalize("NFC", onset)
    rime = unicodedata.normalize("NFC", rime)
    if isinstance(tone, bool):
        raise AlignmentUnavailable("WORD_COMPONENT_INVALID")
    if isinstance(tone, int) or (isinstance(tone, str) and tone.isdigit()):
        tone = f"T{tone}"
    if not isinstance(tone, str):
        raise AlignmentUnavailable("WORD_COMPONENT_INVALID")
    return {"initial": onset or "ZERO", "final": aliases.get(rime, rime), "tone": tone}


def align_components(
    native: dict[str, np.ndarray],
    labels: list[dict],
    durationSeconds: float,
    *,
    directory: str | Path | None = None,
    vocabularies: dict | None = None,
    aliases: dict[str, str] | None = None,
) -> list[dict]:
    """Align all three native heads and return one preserved record per word.

    ``labels`` use canonical ``onset`` (or ``initial``), ``rime``, and ``tone``.
    Empty onset maps to HanziFlow ZERO. Orthographic/retroflex aliases are read
    from the frozen content configuration, never invented from expected text.
    Different head frame counts are allowed and scaled by utterance duration.
    Internal cuts are midpoints between adjacent union spans. Overlapping head
    spans are flagged and partitioned at the same midpoint, without overlaps.
    """
    if not labels:
        return []
    try:
        if not math.isfinite(durationSeconds) or durationSeconds <= 0:
            raise AlignmentUnavailable("DURATION_INVALID")
        if aliases is None:
            from pinyin_matcher.pretrained_native import native_rime_aliases

            aliases = native_rime_aliases("hanziflow")
        if vocabularies is None:
            if directory is None:
                raise AlignmentUnavailable("VOCABULARY_DIRECTORY_REQUIRED")
            vocabularies = _vocabularies(Path(directory))
        word_tokens = [_word_tokens(label, aliases) for label in labels]
        aligned = {}
        for head in HEADS:
            if head not in native or head not in vocabularies:
                raise AlignmentUnavailable("NATIVE_HEAD_MISSING:" + head)
            vocabulary = vocabularies[head]
            ids = list(vocabulary.values())
            if (
                not ids
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in ids
                )
                or len(set(ids)) != len(ids)
                or "<blank>" not in vocabulary
            ):
                raise AlignmentUnavailable("VOCABULARY_INVALID:" + head)
            data = np.asarray(native[head])
            if data.ndim != 2 or data.shape[1] != max(ids) + 1:
                raise AlignmentUnavailable("NATIVE_VOCABULARY_SHAPE_MISMATCH:" + head)
            tokens = []
            for word in word_tokens:
                token = word[head]
                if token not in vocabulary or token in {"<blank>", "<unk>"}:
                    raise AlignmentUnavailable("UNMAPPED_COMPONENT:" + head + ":" + token)
                tokens.append(vocabulary[token])
            aligned[head] = ctc_viterbi(data, tokens, blank=vocabulary["<blank>"])
        output = []
        for index, label in enumerate(labels):
            heads = {}
            for head in HEADS:
                alignment = aligned[head]
                indices = alignment["wordFrames"][index]
                count = len(alignment["path"])
                token = word_tokens[index][head]
                token_id = vocabularies[head][token]
                mean_token_log_posterior = float(
                    alignment["logPosteriors"][indices, token_id].mean()
                )
                native_support = int(
                    np.count_nonzero(
                        alignment["logPosteriors"][indices].argmax(axis=-1) == token_id
                    )
                )
                head_flags = []
                if not native_support:
                    head_flags.append("FORCED_TOKEN_HAS_NO_NATIVE_ARGMAX_SUPPORT")
                if mean_token_log_posterior < math.log(0.01):
                    head_flags.append("FORCED_TOKEN_POSTERIOR_UNDER_ONE_PERCENT")
                heads[head] = {
                    "available": True,
                    "token": token,
                    "tokenId": token_id,
                    "startFrame": int(indices[0]),
                    "endFrameExclusive": int(indices[-1] + 1),
                    "frameCount": count,
                    "startSeconds": float(indices[0] / count * durationSeconds),
                    "endSeconds": float((indices[-1] + 1) / count * durationSeconds),
                    "meanTokenLogPosterior": mean_token_log_posterior,
                    "tokenGeometricMeanPosterior": math.exp(mean_token_log_posterior),
                    "nativeArgmaxSupportFrames": native_support,
                    "pathMeanLogProbability": alignment["meanLogProbability"],
                    "unconstrainedGapPerFrame": alignment["unconstrainedGapPerFrame"],
                    "flags": head_flags,
                }
            raw_start = min(item["startSeconds"] for item in heads.values())
            raw_end = max(item["endSeconds"] for item in heads.values())
            output.append(
                {
                    "index": index,
                    "id": label.get("id"),
                    "available": True,
                    "rawStartSeconds": raw_start,
                    "rawEndSeconds": raw_end,
                    "startSeconds": raw_start,
                    "endSeconds": raw_end,
                    "boundaryOnly": True,
                    "correctnessFromForcedAlignment": False,
                    "flags": ["WEAK_CTC_SUPPORT:" + head for head in HEADS if heads[head]["flags"]],
                    "alignmentSupport": "weak"
                    if any(head["flags"] for head in heads.values())
                    else "native-supported",
                    "heads": heads,
                }
            )
        for previous, following in zip(output, output[1:], strict=False):
            midpoint = (previous["rawEndSeconds"] + following["rawStartSeconds"]) / 2
            previous["endSeconds"] = midpoint
            following["startSeconds"] = midpoint
            if previous["rawEndSeconds"] > following["rawStartSeconds"]:
                previous["flags"].append("HEAD_BOUNDARY_OVERLAP")
                following["flags"].append("HEAD_BOUNDARY_OVERLAP")
        if any(item["startSeconds"] >= item["endSeconds"] for item in output):
            raise AlignmentUnavailable("WORD_BOUNDARY_INVALID")
        return output
    except AlignmentUnavailable as error:
        return _failure(labels, str(error))
    except (KeyError, TypeError, ValueError, OSError) as error:
        return _failure(labels, "ALIGNMENT_INPUT_INVALID:" + type(error).__name__)
