import numpy as np
import torch

from pinyin_matcher.pretrained_experiment import calibrated_rows, component_loss, supervision


def test_expert_error_suppresses_expected_phone_without_invented_label():
    outputs = [torch.tensor([[2.0, -1.0]], requires_grad=True) for _ in range(3)]
    labels = torch.zeros((1, 3), dtype=torch.long)
    annotations = torch.tensor([[0, 1, -1]])
    loss = component_loss(outputs, labels, annotations)
    loss.backward()
    assert outputs[0].grad[0, 0] > 0
    assert outputs[1].grad[0, 0] < 0
    assert outputs[2].grad is None


def test_lexical_policy_blocks_unknown_supervision():
    rows = [
        {
            "componentExpertLabels": {
                "onset": "unanimous-correct",
                "rime": "ambiguous",
                "tone": "unanimous-error",
            }
        }
    ]
    assert supervision(rows).tolist() == [[1, -1, 0]]
    rows[0]["labelPolicyFlags"] = ["TONE_SANDHI_CONTEXT"]
    assert supervision(rows).tolist() == [[-1, -1, -1]]


def test_rare_expert_errors_cannot_be_diluted_by_easy_counterfactuals():
    positives = [{"expertLabel": "unanimous-correct"} for _ in range(100)]
    error = {"expertLabel": "unanimous-error", "componentExpertLabels": {"tone": "unanimous-error"}}
    probabilities = [[np.array([0.99, 0.01])] * 3 for _ in range(101)]
    labels = np.zeros((101, 3), dtype=np.int64)
    report = calibrated_rows(
        probabilities, labels, [*positives, error], {"probability": 0.5, "margin": 0}
    )
    assert report["pooledFalseAcceptance"] < 0.01
    assert report["falseAcceptance"] == 1
    assert report["expertErrors"]["tone"]["n"] == 1


def test_independent_heads_do_not_share_gradients_and_tone_uses_pitch():
    from pinyin_matcher.pretrained_heads import ComponentHeads

    torch.manual_seed(7)
    head = ComponentHeads(10, [3, 4, 5], variant="independent", hidden=16, dropout=0)
    acoustic = torch.randn(2, 10)
    pitch = torch.randn(2, 68)
    output = head(acoustic, pitch)
    output[0].sum().backward()
    assert all(p.grad is None for p in head.final.parameters())
    assert all(p.grad is None for p in head.tone.parameters())
    changed = head(acoustic, pitch + 1)
    torch.testing.assert_close(output[0], changed[0])
    torch.testing.assert_close(output[1], changed[1])
    assert not torch.allclose(output[2], changed[2])


def test_temporal_resampling_preserves_order_endpoints_and_single_frame():
    from pinyin_matcher.pretrained_temporal import temporal_vector

    frames = np.arange(12, dtype=np.float32).reshape(3, 4)
    sampled = temporal_vector(frames).reshape(16, 4)
    np.testing.assert_array_equal(sampled[0], frames[0])
    np.testing.assert_array_equal(sampled[-1], frames[-1])
    assert not np.array_equal(temporal_vector(frames), temporal_vector(frames[::-1]))
    np.testing.assert_array_equal(
        temporal_vector(frames[:1]).reshape(16, 4), np.repeat(frames[:1], 16, axis=0)
    )


def test_temporal_head_export_matches_cpu_and_batch_size(tmp_path):
    import onnxruntime as ort

    from pinyin_matcher.pretrained_heads import ComponentHeads

    torch.manual_seed(9)
    head = ComponentHeads(16 * 8, [3, 4, 5], variant="temporal", hidden=16, dropout=0.2).eval()
    acoustic, pitch = torch.randn(2, 128), torch.randn(2, 68)
    path = tmp_path / "heads.onnx"
    torch.onnx.export(
        head,
        (acoustic, pitch),
        str(path),
        input_names=["acoustic", "pitch"],
        output_names=["initial", "final", "tone"],
        dynamic_axes={k: {0: "batch"} for k in ("acoustic", "pitch", "initial", "final", "tone")},
        opset_version=17,
        dynamo=False,
    )
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    for count in (1, 2):
        actual = session.run(
            None, {"acoustic": acoustic[:count].numpy(), "pitch": pitch[:count].numpy()}
        )
        with torch.inference_mode():
            expected = head(acoustic[:count], pitch[:count])
        for a, b in zip(actual, expected, strict=True):
            np.testing.assert_allclose(a, b.numpy(), rtol=1e-5, atol=1e-6)


def test_mixup_excludes_unknown_and_expert_error_rows():
    from pinyin_matcher.pretrained_heads import ComponentHeads
    from pinyin_matcher.pretrained_mixup import mixup_loss

    torch.manual_seed(5)
    head = ComponentHeads(10, [3, 4, 5], variant="multihead", hidden=16, dropout=0)
    x = torch.randn(4, 10, requires_grad=True)
    pitch = torch.randn(4, 68, requires_grad=True)
    labels = torch.tensor([[0, 1, 2], [1, 2, 3], [0, 0, 0], [1, 1, 1]])
    annotations = torch.tensor([[1, 1, 1], [1, 1, 1], [0, 1, 1], [1, -1, 1]])
    loss = mixup_loss(head, x, pitch, labels, annotations, np.random.default_rng(4))
    loss.backward()
    assert x.grad[:2].abs().sum() > 0
    assert x.grad[2:].abs().sum() == 0
    assert pitch.grad[2:].abs().sum() == 0


def test_ensemble_averages_full_probabilities_not_logits():
    from pinyin_matcher.pretrained_ensemble import ReadoutEnsemble

    class FixedHead(torch.nn.Module):
        def __init__(self, logits):
            super().__init__()
            self.register_buffer("logits", torch.tensor([logits], dtype=torch.float32))

        def forward(self, acoustic, pitch):
            return (self.logits.expand(len(acoustic), -1),) * 3

    heads = [FixedHead([8, 0, -1]), FixedHead([0, 2, 1])]
    ensemble = ReadoutEnsemble(heads)
    expected = (heads[0].logits.softmax(-1) + heads[1].logits.softmax(-1)) / 2
    output = ensemble(torch.zeros(2, 10), torch.zeros(2, 68))
    for component in output:
        torch.testing.assert_close(component.softmax(-1), expected.expand(2, -1))
