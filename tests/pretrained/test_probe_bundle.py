"""A failed probe must not accidentally be packaged with a different encoder."""

import json

import pytest

from pinyin_matcher.pretrained_bundle import bundle


@pytest.mark.parametrize(
    ("metadata", "error"),
    [
        ({"acousticProbe": {"selectedDepth": 20}}, "INTERMEDIATE_PROBE_REQUIRES"),
        (
            {"acousticDerivative": {"architecture": "sensevoice-70-native-sequence-v1"}},
            "NATIVE_SEQUENCE_POOLED_READOUT_REQUIRES",
        ),
    ],
)
def test_unexported_probe_cannot_be_bundled_with_original_encoder(tmp_path, metadata, error):
    heads = tmp_path / "heads"
    heads.mkdir()
    (heads / "model.json").write_text(json.dumps(metadata))
    destination = tmp_path / "package"
    with pytest.raises(ValueError, match=error):
        bundle(heads, tmp_path / "original-encoder", destination)
    assert not destination.exists()
