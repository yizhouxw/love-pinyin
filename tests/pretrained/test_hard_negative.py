import json

import pytest
import torch

from pinyin_matcher import pretrained_hard_negative as hard
from pinyin_matcher.catalog import fingerprint


def row(identifier, onset, rime, tone, labels):
    return {
        "id": identifier,
        "sha256": identifier * 64,
        "parentSha256": "b" * 64,
        "speakerId": "adult-" + identifier,
        "voiceFamilyId": "adult-" + identifier,
        "referenceSourceId": "adult-" + identifier,
        "onset": onset,
        "rime": rime,
        "tone": tone,
        "componentExpertLabels": labels,
    }


def test_generated_pairs_require_expert_confirmed_component():
    rows = [
        row(
            "a",
            "b",
            "a",
            1,
            {"onset": "unanimous-correct", "rime": "ambiguous", "tone": "unanimous-error"},
        ),
        row(
            "c",
            "p",
            "i",
            2,
            {"onset": "unanimous-error", "rime": "unanimous-correct", "tone": "unanimous-correct"},
        ),
    ]
    generated = list(hard.pairs(rows))
    assert {(x["rootId"], x["component"]) for x in generated} == {
        ("a", "onset"),
        ("c", "rime"),
        ("c", "tone"),
    }
    assert all(
        x["expertActual"] != x["incorrectTarget"] and x["sourceSplit"] == "train" for x in generated
    )


def test_hard_loss_focuses_confusable_alternatives_and_masks_unknown():
    identities = [torch.zeros(2, 5, requires_grad=True) for _ in range(3)]
    validities = [
        torch.tensor([[0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 2.0, 3.0, 4.0]], requires_grad=True)
        for _ in range(3)
    ]
    labels = torch.tensor([[0, 0, 0], [0, 0, 0]])
    annotations = torch.tensor([[1, -1, -1], [-1, -1, -1]])
    hard.hard_loss(identities, validities, labels, annotations)[0].backward()
    assert validities[0].grad[0, 0] < 0
    assert torch.count_nonzero(validities[0].grad[0, 1:]) == 3
    assert torch.count_nonzero(validities[0].grad[1]) == 0
    assert all(torch.count_nonzero(v.grad) == 0 for v in validities[1:])


def test_pair_manifest_recomputed_and_tampering_fails(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    rows = [row("a", "b", "a", 1, {"onset": "unanimous-correct"}), row("c", "p", "i", 2, {})]
    monkeypatch.setattr(hard, "training_rows", lambda _: rows)
    directory = tmp_path / "pairs"
    data = hard.prepare(manifest, directory)
    assert data["pairCount"] == 1
    assert hard.verify(manifest, directory)["pairCount"] == 1
    path = directory / "pairs.jsonl"
    item = json.loads(path.read_text())
    item["incorrectTarget"] = item["expertActual"]
    path.write_text(json.dumps(item) + "\n")
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        hard.verify(manifest, directory)
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["pairsSha256"] = fingerprint(path)
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="PAIR_CONTENT_MISMATCH"):
        hard.verify(manifest, directory)
