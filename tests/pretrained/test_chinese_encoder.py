import numpy as np
import pytest
import torch
from transformers import Wav2Vec2Config, Wav2Vec2ForCTC, Wav2Vec2Model

from pinyin_matcher.pretrained_chinese_tail import differentiable_pool, masked_frames, select_rows
from pinyin_matcher.pretrained_features import pool_frames
from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence


def test_masked_batch_matches_unpadded_single_utterances():
    torch.manual_seed(3182026)
    config = Wav2Vec2Config(
        hidden_size=16,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=32,
        conv_dim=(16, 16),
        conv_stride=(5, 2),
        conv_kernel=(10, 3),
        num_conv_pos_embeddings=16,
        num_conv_pos_embedding_groups=2,
        feat_extract_norm="group",
        hidden_dropout=0,
        attention_dropout=0,
        activation_dropout=0,
        feat_proj_dropout=0,
        layerdrop=0,
        apply_spec_augment=False,
    )
    adapter = Wav2VecEvidence.__new__(Wav2VecEvidence)
    adapter.name, adapter.device = "tencent-zh-base", "cpu"
    adapter.model = Wav2Vec2Model(config).eval()
    rng = np.random.default_rng(2026)
    samples = [rng.normal(size=n).astype(np.float32) for n in (401, 632, 899)]
    singles = [adapter.evidence(sample)["frames"] for sample in samples]
    batch = [entry["frames"] for entry in adapter.evidence_batch(samples)]
    for first, second in zip(singles, batch, strict=True):
        np.testing.assert_allclose(first, second, atol=2e-5, rtol=2e-5)
    trained_frames, lengths = masked_frames(adapter.model, samples, "cpu")
    for index, first in enumerate(singles):
        np.testing.assert_allclose(
            first,
            trained_frames[index, : lengths[index]].detach().numpy(),
            atol=2e-5,
            rtol=2e-5,
        )
    adapter.name = "tencent-zh-raw"
    raw_samples = [
        sample * scale + 0.1 for sample, scale in zip(samples, (0.1, 0.2, 0.3), strict=True)
    ]
    raw_single = [adapter.evidence(sample)["frames"] for sample in raw_samples]
    raw_batch = [entry["frames"] for entry in adapter.evidence_batch(raw_samples)]
    for first, second in zip(raw_single, raw_batch, strict=True):
        np.testing.assert_allclose(first, second, atol=2e-5, rtol=2e-5)
    assert not np.allclose(raw_single[0], singles[0])


def test_tail_training_selection_excludes_other_splits_and_unknown_labels():
    rows = []
    for speaker in ("a", "b"):
        for index in range(3):
            rows.append(
                {
                    "id": f"{speaker}-{index}",
                    "speakerId": speaker,
                    "split": "train",
                    "componentExpertLabels": {"onset": "unanimous-correct"},
                }
            )
    rows.append({"id": "test", "speakerId": "c", "split": "test"})
    rows.append({"id": "missing", "speakerId": "c", "split": "train"})
    rows.append(
        {
            "id": "unknown",
            "speakerId": "c",
            "split": "train",
            "componentExpertLabels": {"onset": "ambiguous"},
        }
    )
    selected = select_rows(rows, limit=4)
    assert [r["speakerId"] for r in selected] == ["a", "b", "a", "b"]
    assert selected == select_rows(rows, limit=4)
    assert "missing" not in {row["id"] for row in select_rows(rows, limit=99)}
    from pinyin_matcher.pretrained_xlsr_tail import select_rows as xlsr_select_rows

    assert "missing" not in {row["id"] for row in xlsr_select_rows(rows, limit=99)}


def test_train_pool_matches_runtime_pool_and_propagates_gradients():
    rng = np.random.default_rng(123)
    frames = rng.normal(size=(2, 11, 4)).astype(np.float32)
    tensor = torch.tensor(frames, requires_grad=True)
    result = differentiable_pool(tensor, torch.tensor([7, 11]))
    for index, length in enumerate((7, 11)):
        np.testing.assert_allclose(
            result[index].detach().numpy(), pool_frames(frames[index, :length]), atol=1e-6
        )
    result.sum().backward()
    assert tensor.grad is not None and torch.isfinite(tensor.grad).all()


def test_chinese_asr_encoder_discards_character_head():
    torch.manual_seed(100)
    config = Wav2Vec2Config(
        hidden_size=16,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=32,
        conv_dim=(16, 16),
        conv_stride=(5, 2),
        conv_kernel=(10, 3),
        num_conv_pos_embeddings=16,
        num_conv_pos_embedding_groups=2,
        feat_extract_norm="layer",
        hidden_dropout=0,
        attention_dropout=0,
        activation_dropout=0,
        feat_proj_dropout=0,
        layerdrop=0,
        apply_spec_augment=False,
        vocab_size=9,
    )
    adapter = Wav2VecEvidence.__new__(Wav2VecEvidence)
    adapter.name, adapter.device = "chinese-xlsr-asr", "cpu"
    adapter.model = Wav2Vec2ForCTC(config).eval()
    rng = np.random.default_rng(99)
    samples = [rng.normal(size=n).astype(np.float32) for n in (501, 790)]
    singles = [adapter.evidence(sample) for sample in samples]
    batched = adapter.evidence_batch(samples)
    for first, second in zip(singles, batched, strict=True):
        assert first["native"] == second["native"] == {}
        np.testing.assert_allclose(first["frames"], second["frames"], atol=2e-5, rtol=2e-5)
    adapter.model.gradient_checkpointing_enable()
    encoder = adapter.model.wav2vec2
    encoder.gradient_checkpointing_disable()
    for parameter in encoder.parameters():
        parameter.requires_grad_(False)
    tail = encoder.encoder.layers[-1]
    tail.requires_grad_(True)
    tail.train()
    from pinyin_matcher.pretrained_xlsr_tail import masked_frames as xlsr_masked_frames

    frames, _ = xlsr_masked_frames(encoder, samples, "cpu")
    frames.square().sum().backward()
    assert any(parameter.grad is not None for parameter in tail.parameters())
    assert all(
        parameter.grad is None for parameter in encoder.parameters() if not parameter.requires_grad
    )


def test_result_collector_rejects_mismatched_calibration_manifest(tmp_path, monkeypatch):
    import json

    from pinyin_matcher import pretrained_chinese_report as report

    monkeypatch.setattr(report, "NAMES", ("sample",))
    root, bundles = tmp_path / "records", tmp_path / "bundles"
    root.mkdir()
    (root / "stress-match13-v2").mkdir()
    (root / "stress-match13-v2/manifest.json").write_text(json.dumps({"cases": []}))
    (bundles / "sample").mkdir(parents=True)
    (bundles / "sample/model.json").write_text("{}")
    (root / "sample-full-calibration.json").write_text(json.dumps({"manifestSha256": "wrong"}))
    for kind in ("stress", "cpu", "cold"):
        (root / f"sample-{kind}.json").write_text("{}")
    with pytest.raises(ValueError, match="CHINESE_REPORT_INPUT_MISMATCH"):
        report.collect(root, bundles, tmp_path / "result.json")
    assert not (tmp_path / "result.json").exists()
