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
