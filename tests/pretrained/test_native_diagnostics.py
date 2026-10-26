import hashlib
import json

import numpy as np
import pytest

from pinyin_matcher.audio import encode_wav
from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_experiment import save_cached
from pinyin_matcher.pretrained_native_diagnostics import report


@pytest.mark.parametrize("name", ["hanziflow", "sensevoice"])
def test_calibration_native_diagnostics_retain_flagged_human_rows(tmp_path, monkeypatch, name):
    model, cache = tmp_path / "model", tmp_path / "cache"
    model.mkdir()
    cache.mkdir()
    vocabularies = {
        "initial": {"<blank>": 0, "<unk>": 1, "m": 2, "ZERO": 3},
        "final": {"<blank>": 0, "<unk>": 1, "a": 2, "o": 3},
        "tone": {"<blank>": 0, "<unk>": 1, "T1": 2, "T2": 3},
    }
    for head, vocabulary in vocabularies.items():
        (model / f"v2_1_{head}_vocabulary.json").write_text(json.dumps(vocabulary))
    identity = {"explicitNumericFixture": True}
    if name == "sensevoice":
        identity["derivative"] = {"architecture": "sensevoice-50-ctc-v1"}
    (cache / "identity.json").write_text(json.dumps(identity))
    monkeypatch.setattr("pinyin_matcher.pretrained_experiment.cache_identity", lambda *_: identity)
    rows = []
    for index in range(3):
        payload = encode_wav(np.random.default_rng(index).normal(0, 0.1, 3200).astype(np.float32))
        path = tmp_path / (str(index) + ".wav")
        path.write_bytes(payload)
        labels = dict.fromkeys(("onset", "rime", "tone"), "unanimous-correct")
        if index == 1:
            labels["tone"] = "unanimous-error"
        row = {
            "id": str(index),
            "file": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "split": "calibration",
            "speakerId": "speaker",
            "onset": "m",
            "rime": "a",
            "tone": 2 if index == 1 else 1,
            "expertLabel": "unanimous-error" if index == 1 else "unanimous-correct",
            "componentExpertLabels": labels,
            "labelPolicyFlags": ["CONTEXT_UNASSESSED"] if index == 2 else [],
        }
        rows.append(row)
        if index != 2:
            logits = np.full((3, 4), -8.0)
            logits[:, 2] = 8
            save_cached(
                cache / (row["sha256"] + ".npz"),
                {"native_" + key: logits for key in vocabularies},
                fingerprint(cache / "identity.json"),
            )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"frozenTestIncluded": False, "items": rows}))
    (cache / "cache.json").write_text(
        json.dumps({"model": name, "manifestSha256": fingerprint(manifest), "testIncluded": False})
    )
    result = report(manifest, cache, model)
    assert result["allCalibrationRows"] == 3
    assert result["availableRows"] == 2
    assert result["unavailableReasons"] == {"PREDECLARED_UNASSESSABLE": 1}
    assert len(result["records"]) == 3
    correct = result["components"]["tone"]["unanimous-correct"]
    assert correct["allExpertRows"] == 2
    assert correct["available"] == correct["unassessable"] == 1
    assert correct["greedyExactlyExpected"] == 1
    error = result["components"]["tone"]["unanimous-error"]
    assert error["allExpertRows"] == 1
    assert error["expectedIsBestSingleLabel"] == 0
    assert result["finalTestRead"] is False
    assert result["model"] == name
    if name == "sensevoice":
        assert "not original SenseVoice outputs" in result["phoneticHeadOrigin"]
