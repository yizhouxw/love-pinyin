"""Native label integrity and sequence mechanics, not pronunciation validation."""

import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import pytest
import torch

from pinyin_matcher import pretrained_native_sequence as native
from pinyin_matcher.catalog import fingerprint


def test_provided_pinyin_retains_neutral_umlaut_and_both_apical_vowels():
    vocab = {
        "initial": {"<blank>": 0, "<unk>": 1, "ZERO": 2, "sh": 3, "z": 4, "n": 5},
        "final": {"<blank>": 0, "<unk>": 1, "ii": 2, "iii": 3, "v": 4, "vn": 5, "o": 6},
        "tone": {"<blank>": 0, "<unk>": 1, "T1": 2, "T2": 3, "T3": 4, "T4": 5, "T5": 6},
    }
    targets, excluded = native.provided_sequences(["shi4", "zi3", "nv3", "yun2", "o5"], vocab)
    assert excluded == []
    assert targets == [[3, 4, 5, 2, 2], [2, 3, 4, 5, 6], [5, 4, 4, 3, 6]]
    targets, excluded = native.provided_sequences(["shi4", "hair2", "nv3"], vocab)
    assert targets is None
    assert excluded[0]["pinyin"] == "hair2"
    assert excluded[0]["index"] == 1


def test_repeated_native_tokens_need_intervening_ctc_frames():
    assert native.minimum_ctc_frames([2, 2, 3]) == 4
    logits = [torch.zeros(1, 2, 5, requires_grad=True) for _ in range(3)]
    with pytest.raises(ValueError, match="NATIVE_CTC_PATH_IMPOSSIBLE"):
        native.sequence_ctc_loss(logits, torch.tensor([2]), [[[2, 2]] * 3])
    logits = [torch.randn(1, 4, 5, requires_grad=True) for _ in range(3)]
    loss = native.sequence_ctc_loss(logits, torch.tensor([4]), [[[2, 2]] * 3])
    assert torch.isfinite(loss)
    loss.backward()
    assert all(
        x.grad is not None and torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0
        for x in logits
    )


def test_audio_derivation_resamples_once_and_verifies_existing_payload(tmp_path, monkeypatch):
    original = tmp_path / "source.wav"
    samples = (np.sin(np.arange(8820) * 0.03) * 4000).astype("<i2")
    with wave.open(str(original), "wb") as target:
        target.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        target.writeframes(samples.tobytes())
    row = {"id": "aishell3-SSB00010001", "file": str(original), "sha256": fingerprint(original)}
    calls = []
    resample = native.resample_poly

    def tracked(*args):
        calls.append(args[1:])
        return resample(*args)

    monkeypatch.setattr(native, "resample_poly", tracked)
    first, a = native.derive_audio(row, tmp_path / "derived")
    second, b = native.derive_audio(row, tmp_path / "derived")
    np.testing.assert_array_equal(first, second)
    assert calls == [(160, 441)]
    assert a == b and a["sampleRate"] == 16000 and a["sourceSha256"] == row["sha256"]
    Path(a["file"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="NATIVE_DERIVED_AUDIO_CHANGED"):
        native.derive_audio(row, tmp_path / "derived")


def test_pinyin_tampering_with_unchanged_source_line_digest_fails(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    line = "SSB00010001.wav\t妈 ma1"
    (metadata / "train-content.txt").write_text(line + "\n")
    (metadata / "train-labels.txt").write_text("SSB00010001|ma1 $|妈$\n")
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"source-audio-inventory-fixture")
    record = {
        "id": "aishell3-SSB00010001",
        "file": str(audio),
        "sha256": fingerprint(audio),
        "speakerId": "aishell3-SSB0001",
        "path": "train/wav/SSB0001/SSB00010001.wav",
        "pinyinSourceLineSha256": hashlib.sha256(line.encode()).hexdigest(),
    }
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "files": [record],
                "metadataFiles": [
                    {"localName": name, "sha256": fingerprint(metadata / name)}
                    for name in ("train-content.txt", "train-labels.txt")
                ],
            }
        )
    )
    monkeypatch.setattr(native, "DATA_CONFIG", config)
    manifest = tmp_path / "manifest.json"
    data = {
        "complete": True,
        "trainingOnly": True,
        "finalTestRead": False,
        "configSha256": fingerprint(config),
        "verifiedFiles": 1,
        "files": [{**record, "status": "downloaded-verified", "split": "train", "pinyin": ["ma1"]}],
    }
    manifest.write_text(json.dumps(data))
    assert native._native_manifest(manifest)[0]["pinyin"] == ["ma1"]
    data["files"][0]["pinyin"] = ["ma2"]
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="AISHELL_PINYIN_SOURCE_MISMATCH"):
        native._native_manifest(manifest)
    data["complete"] = False
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="NATIVE_COMPLETE_PINNED_TRAINING_DATA_REQUIRED"):
        native._native_manifest(manifest)


def test_unpinned_native_vocabulary_is_not_accepted_as_a_new_schema(tmp_path):
    for name in native.VOCAB_FILES:
        (tmp_path / name).write_text("{}\n")
    with pytest.raises(ValueError, match="NATIVE_FIXED_VOCABULARY_CHANGED"):
        native.vocabularies(tmp_path)


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason="Actual Metal required")
def test_sequence_ctc_cpu_double_copy_backpropagates_to_mps_float32():
    torch.manual_seed(28)
    logits = [torch.randn(2, 8, 7, device="mps", requires_grad=True) for _ in range(3)]
    loss = native.sequence_ctc_loss(
        logits, torch.tensor([8, 6], device="mps"), [[[2, 2, 3]] * 3, [[3, 4]] * 3]
    )
    assert loss.device.type == "cpu" and loss.dtype == torch.float64
    loss.backward()
    assert all(
        x.grad.device.type == "mps"
        and x.grad.dtype == torch.float32
        and torch.isfinite(x.grad).all()
        and x.grad.abs().sum() > 0
        for x in logits
    )


def test_training_cache_cannot_change_targets_or_silently_remove_a_source(tmp_path):
    import copy

    vocab = {
        "initial": {"<blank>": 0, "<unk>": 1, "m": 2},
        "final": {"<blank>": 0, "<unk>": 1, "a": 2},
        "tone": {"<blank>": 0, "<unk>": 1, "T1": 2},
    }
    sources = [
        {"id": "a", "pinyin": ["ma1"], "speakerId": "one"},
        {"id": "b", "pinyin": ["hair2"], "speakerId": "two"},
    ]
    targets, _ = native.provided_sequences(["ma1"], vocab)
    _, unsupported = native.provided_sequences(["hair2"], vocab)
    metadata = {
        "cachedUtterances": 1,
        "excludedUtterances": 1,
        "plannedUtterances": 2,
        "items": [{"id": "a", "providedPinyin": ["ma1"], "speakerId": "one", "targets": targets}],
        "excluded": [{"id": "b", "reason": "UNSUPPORTED_PROVIDED_PINYIN", "tokens": unsupported}],
    }
    native.validate_cached_labels(metadata, sources, vocab, tmp_path)
    changed = copy.deepcopy(metadata)
    changed["items"][0]["targets"][0][0] = 1
    with pytest.raises(ValueError, match="NATIVE_CACHED_LABEL_OR_SPEAKER_CHANGED"):
        native.validate_cached_labels(changed, sources, vocab, tmp_path)
    changed = copy.deepcopy(metadata)
    changed["excluded"] = []
    with pytest.raises(ValueError, match="NATIVE_CACHED_SOURCE_PARTITION_INVALID"):
        native.validate_cached_labels(changed, sources, vocab, tmp_path)
    changed = copy.deepcopy(metadata)
    changed["excluded"][0]["tokens"] = []
    with pytest.raises(ValueError, match="NATIVE_UNSUPPORTED_EXCLUSION_NOT_JUSTIFIED"):
        native.validate_cached_labels(changed, sources, vocab, tmp_path)
