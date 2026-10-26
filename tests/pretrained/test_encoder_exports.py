"""Numerical/runtime contracts, not pronunciation-accuracy evidence."""

import json
import os
import socket
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("onnxruntime")

from pinyin_matcher.pretrained_export import OnnxWav2VecEvidence  # noqa: E402
from pinyin_matcher.pretrained_sensevoice import SenseVoiceFeatures  # noqa: E402


class CapturingSession:
    def __init__(self):
        self.inputs = []

    def run(self, outputs, inputs):
        self.inputs.append(inputs["waveform"].copy())
        return [np.zeros((1, 2, 1024)), *(np.zeros((1, 2, 3)) for _ in range(3))]


def adapter_without_weights():
    adapter = OnnxWav2VecEvidence.__new__(OnnxWav2VecEvidence)
    adapter.name = "hanziflow"
    adapter.session = CapturingSession()
    return adapter


@pytest.mark.parametrize(
    "samples",
    [np.zeros((2, 400)), np.zeros(399), np.full(400, np.nan), np.full(400, np.inf)],
)
def test_invalid_audio_never_reaches_onnx(samples):
    adapter = adapter_without_weights()
    with pytest.raises(ValueError, match="INVALID_WAVEFORM"):
        adapter.evidence(samples)
    assert not adapter.session.inputs


def test_gain_and_dc_offset_leave_encoder_input_equivalent():
    adapter = adapter_without_weights()
    wave = np.random.default_rng(18).normal(0, 0.2, 1600).astype(np.float32)
    adapter.evidence(wave)
    adapter.evidence(wave * 2 + 0.1)
    np.testing.assert_allclose(adapter.session.inputs[0], adapter.session.inputs[1], atol=1e-5)


def test_derived_graph_with_wrong_parent_fails_before_native_session(tmp_path, monkeypatch):
    (tmp_path / "acoustic.onnx.json").write_text(
        json.dumps({"model": "hanziflow", "parentRevision": "wrong", "targetInput": False})
    )

    def forbid_session(*args, **kwargs):
        pytest.fail("unbound graph reached ONNX Runtime")

    monkeypatch.setattr("pinyin_matcher.pretrained_export.ort.InferenceSession", forbid_session)
    with pytest.raises(ValueError, match="INTEGRITY_MISMATCH"):
        OnnxWav2VecEvidence("hanziflow", tmp_path, check=False)


def test_source_weights_are_checked_before_safe_torch_load(tmp_path, monkeypatch):
    (tmp_path / "model.pt").write_bytes(b"not the pinned model")

    def forbid_load(*args, **kwargs):
        pytest.fail("corrupt source weights reached torch.load")

    monkeypatch.setattr("pinyin_matcher.pretrained_sensevoice.torch.load", forbid_load)
    with pytest.raises(ValueError, match="SHA256_MISMATCH"):
        SenseVoiceFeatures(tmp_path)


@pytest.mark.parametrize("name", ["sensevoice", "hanziflow", "charsiu"])
def test_actual_cpu_exports_work_offline_at_two_lengths(name, monkeypatch):
    root = os.environ.get("PRETRAINED_MODELS")
    wav = os.environ.get("PRETRAINED_TEST_WAV")
    if not root or not wav:
        pytest.skip("set PRETRAINED_MODELS and PRETRAINED_TEST_WAV for real local artifacts")
    from pinyin_matcher.audio import decode_wav

    samples = decode_wav(Path(wav).read_bytes())

    def forbid_network(*args, **kwargs):
        pytest.fail("local inference attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    directory = Path(root) / name
    if name == "sensevoice":
        adapter = SenseVoiceFeatures(directory, quantized=True)
        session = adapter.onnx
        dimensions = 512
    else:
        adapter = OnnxWav2VecEvidence(name, directory)
        session = adapter.session
        dimensions = 1024
    assert session.get_providers() == ["CPUExecutionProvider"]
    assert session.get_session_options().intra_op_num_threads == 2
    frames = []
    for length in [8000, 64000]:
        audio = np.tile(samples, int(np.ceil(length / len(samples))))[:length]
        encoded = adapter.extract(audio)
        assert encoded.ndim == 2 and encoded.shape[1] == dimensions
        assert np.isfinite(encoded).all()
        frames.append(len(encoded))
    assert frames[1] > frames[0] * 6


@pytest.mark.parametrize("name", ["hanziflow", "charsiu"])
def test_actual_assign_loaded_encoder_has_no_meta_or_gpu_parameters(name, monkeypatch):
    root = os.environ.get("PRETRAINED_MODELS")
    wav = os.environ.get("PRETRAINED_TEST_WAV")
    if not root or not wav:
        pytest.skip("set PRETRAINED_MODELS and PRETRAINED_TEST_WAV for real source artifacts")
    directory = Path(root) / name
    weight = "model.safetensors" if name == "hanziflow" else "pytorch_model.bin"
    if not (directory / weight).exists():
        pytest.skip("the slim runtime bundle intentionally excludes source weights")
    from pinyin_matcher.audio import decode_wav
    from pinyin_matcher.pretrained_wav2vec import Wav2VecEvidence

    def forbid_network(*args, **kwargs):
        pytest.fail("source encoder inference attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    adapter = Wav2VecEvidence(name, directory)
    assert all(parameter.device.type == "cpu" for parameter in adapter.model.parameters())
    samples = decode_wav(Path(wav).read_bytes())
    samples = np.tile(samples, int(np.ceil(8000 / len(samples))))[:8000]
    evidence = adapter.evidence(samples)
    assert np.isfinite(evidence["frames"]).all()
    assert evidence["native"]
