import json

import pytest

from pinyin_matcher import pretrained_sequence_protocol as protocol
from pinyin_matcher.catalog import fingerprint


def fixture(tmp_path, monkeypatch):
    initializer = tmp_path / "initializer"
    initializer.mkdir()
    native, ompal = tmp_path / "native.json", tmp_path / "ompal.json"
    native.write_text('{"train": true}')
    ompal.write_text('{"trainAndCalibration": true}')
    (initializer / "tuned.safetensors").write_bytes(b"fixed-test-checkpoint")
    metadata = {
        "architecture": "sensevoice-70-native-sequence-v1",
        "testUsed": False,
        "configurationSha256": fingerprint(protocol.NATIVE_CONFIG),
        "manifestSha256": fingerprint(ompal),
        "files": {"tuned.safetensors": {"sha256": fingerprint(initializer / "tuned.safetensors")}},
    }
    (initializer / "tuned.json").write_text(json.dumps(metadata))
    return initializer, native, ompal, tmp_path / "new-protocol.json"


def test_rebuilt_input_binding_preserves_budget_and_never_overwrites(tmp_path, monkeypatch):
    args = fixture(tmp_path, monkeypatch)
    original = json.loads(protocol.CONFIG.read_text())
    protocol.freeze_inputs(*args)
    rebuilt = json.loads(args[-1].read_text())
    assert rebuilt["initializerMetadataSha256"] == fingerprint(args[0] / "tuned.json")
    assert rebuilt["nativeManifestSha256"] == fingerprint(args[1])
    assert {k: v for k, v in rebuilt.items() if not k.endswith("Sha256")} == {
        k: v for k, v in original.items() if not k.endswith("Sha256")
    }
    before = args[-1].read_bytes()
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        protocol.freeze_inputs(*args)
    assert args[-1].read_bytes() == before


@pytest.mark.parametrize("corruption", ["weights", "manifest", "testUsed", "trainingRecipe"])
def test_initializer_change_requires_new_training_not_silent_binding(
    tmp_path, monkeypatch, corruption
):
    args = fixture(tmp_path, monkeypatch)
    if corruption == "weights":
        (args[0] / "tuned.safetensors").write_bytes(b"tampered")
    elif corruption == "manifest":
        args[2].write_text('{"changed": true}')
    else:
        path = args[0] / "tuned.json"
        metadata = json.loads(path.read_text())
        metadata[corruption] = True
        path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="INITIALIZER_PROTOCOL_MISMATCH"):
        protocol.freeze_inputs(*args)
    assert not args[-1].exists()
