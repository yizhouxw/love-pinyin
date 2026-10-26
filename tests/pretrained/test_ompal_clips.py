"""Preparation contracts using explicit numeric fixtures, never quality claims."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher.audio import decode_wav, encode_wav
from pinyin_matcher.pretrained_ompal_clips import _selection, prepare_clips, word_audio

VOCABS = {
    "initial": {"<blank>": 0, "ZERO": 1, "m": 2, "b": 3},
    "final": {"<blank>": 0, "a": 1, "iii": 2, "v": 3},
    "tone": {"<blank>": 0, "T1": 1, "T2": 2, "T5": 3},
}


class ExplicitNumericFixture:
    def __init__(self):
        self.calls = 0

    def evidence_batch(self, samples):
        self.calls += 1
        results = []
        for _ in samples:
            native = {}
            for key, tokens in {
                "initial": [0, 2, 2, 0, 0, 3, 3, 0],
                "final": [0, 1, 1, 0, 0, 2, 2, 0],
                "tone": [0, 1, 1, 0, 0, 2, 2, 0],
            }.items():
                logits = np.full((8, 4), -8.0)
                logits[np.arange(8), tokens] = 8
                native[key] = logits
            results.append({"native": native})
        return results


def fixture_manifest(tmp_path: Path, *, split="train", missing_component=False):
    model = tmp_path / "numeric-fixture-vocabulary"
    model.mkdir()
    for key, value in VOCABS.items():
        (model / f"v2_1_{key}_vocabulary.json").write_text(json.dumps(value))
    payload = encode_wav(np.random.default_rng(18).normal(0, 0.1, 8000).astype(np.float32))
    path = tmp_path / "public-fixture.wav"
    path.write_bytes(payload)
    words = [
        {
            "id": "w0",
            "onset": "m",
            "rime": "a",
            "tone": 1,
            "expectedPinyin": "ma1",
            "expertLabel": "unanimous-error",
            "componentExpertLabels": {
                "onset": "unanimous-error",
                "rime": "unanimous-correct",
                "tone": "ambiguous",
            },
            "expertRatings": {"onset": [0, 0, 0], "rime": [1, 1, 1], "tone": [0, 1, 1]},
            "labelPolicyFlags": [],
        },
        {
            "id": "w1",
            "onset": "b",
            "rime": None if missing_component else "i-dental",
            "tone": 2,
            "expectedPinyin": "bi2",
            "expertLabel": "ambiguous",
            "labelPolicyFlags": ["CONTEXT_UNASSESSED"],
        },
    ]
    document = {
        "utterances": [
            {
                "id": "utterance",
                "file": str(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "speakerId": "speaker",
                "split": split,
                "labelProvenance": "Expert votes are separate from forced boundary fixtures.",
                "words": words,
            }
        ]
    }
    manifest = tmp_path / "utterances.json"
    manifest.write_text(json.dumps(document))
    return manifest, model, document


def test_frozen_selection_never_touches_test_without_flag_and_valid_plan(tmp_path):
    document = {
        "utterances": [
            {
                "id": "never-open",
                "file": "missing.wav",
                "split": "test",
                "words": [{"id": "test-word"}],
            }
        ]
    }
    assert _selection(document, False, None)[0] == []
    with pytest.raises(ValueError, match="EXPLICIT_PLAN"):
        _selection(document, True, None)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"planSha256": "not-frozen"}))
    with pytest.raises(ValueError, match="PLAN_SHA"):
        _selection(document, True, plan)
    plan.write_text(json.dumps({"planSha256": "a" * 64}))
    with pytest.raises(ValueError, match="PLAN_SHA"):
        _selection(document, True, plan)


def test_preparation_preserves_expert_votes_and_reuses_digest_bound_native_cache(tmp_path):
    manifest, model, document = fixture_manifest(tmp_path)
    provider = ExplicitNumericFixture()
    output = tmp_path / "clips"
    first = prepare_clips(manifest, output, model_path=model, provider=provider)
    second = prepare_clips(manifest, output, model_path=model, provider=provider)
    assert provider.calls == 1
    assert first["version"] == "ompal-three-head-midpoint-v2-model-specific-apical"
    assert first["alignmentMapping"]["aliases"]["i-retroflex"] == "ii"
    assert first["alignmentMapping"]["aliases"]["i-dental"] == "iii"
    assert first["alignmentMapping"]["upstreamTargetSchemaSha256"] == (
        "1664632ace184c2851d7e6d68884225287020d913d653a0f885c41245210f433"
    )
    assert len(first["alignmentMapping"]["aliasesSha256"]) == 64
    assert len(first["alignerSha256"]) == 64
    assert first["model"] == second["model"]
    assert first["counts"]["words"] == second["counts"]["words"] == 2
    for original, row in zip(document["utterances"][0]["words"], first["items"], strict=True):
        assert row["labelProvenance"] == document["utterances"][0]["labelProvenance"]
        for field in ("expertLabel", "labelPolicyFlags"):
            assert row[field] == original[field]
        assert row["alignmentIsCorrectnessEvidence"] is False
        payload = (output / row["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == row["sha256"]
        assert len(decode_wav(payload)) >= 2400
    assert (
        first["items"][0]["componentExpertLabels"]
        == document["utterances"][0]["words"][0]["componentExpertLabels"]
    )


def test_failed_alignment_retains_every_word_and_explicit_silent_placeholder(tmp_path):
    manifest, model, _ = fixture_manifest(tmp_path, missing_component=True)
    result = prepare_clips(
        manifest, tmp_path / "clips", model_path=model, provider=ExplicitNumericFixture()
    )
    assert result["counts"]["words"] == result["counts"]["alignmentUnavailable"] == 2
    assert all(row["placeholder"] and row["numericalQualityFlags"] for row in result["items"])
    for row in result["items"]:
        audio = decode_wav((tmp_path / "clips" / row["file"]).read_bytes())
        assert len(audio) == 4000 and not audio.any()


def test_short_clip_padding_does_not_stretch_or_overlap_adjacent_speech():
    samples = np.ones(8000, dtype=np.float32) * 0.1
    bounds = [
        {"available": True, "startSeconds": 0.1, "endSeconds": 0.2, "flags": []},
        {"available": True, "startSeconds": 0.2, "endSeconds": 0.3, "flags": []},
    ]
    a, a_meta, _ = word_audio(samples, bounds, 0)
    b, b_meta, _ = word_audio(samples, bounds, 1)
    assert a_meta["endSample"] <= b_meta["startSample"]
    assert len(a) >= 2400 and len(b) >= 2400
    clip, meta, flags = word_audio(
        samples, [{"available": True, "startSeconds": 0, "endSeconds": 0.01, "flags": []}], 0
    )
    assert len(clip) == 2400
    assert meta["originalDurationSeconds"] == pytest.approx(0.05)
    assert meta["zeroPadLeftSamples"] + meta["zeroPadRightSamples"] == 1600
    assert np.count_nonzero(clip) == 800
    assert "ACOUSTIC_CONTENT_UNDER_80MS" in flags


def test_corrupt_parent_audio_aborts_instead_of_labeling_wrong_recording(tmp_path):
    manifest, model, document = fixture_manifest(tmp_path)
    Path(document["utterances"][0]["file"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="PARENT_SHA256_MISMATCH"):
        prepare_clips(
            manifest, tmp_path / "clips", model_path=model, provider=ExplicitNumericFixture()
        )
