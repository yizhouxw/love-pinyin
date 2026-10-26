"""CPU/graph/provenance contracts; tiny tensors never prove speech quality."""

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from torch import nn

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_ctc_runtime import (
    QUANTIZED_NATIVE_PARENTS,
    is_quantized_native_architecture,
    load_encoder,
)
from pinyin_matcher.pretrained_native import native_rime_aliases
from pinyin_matcher.pretrained_native_sequence_export import (
    ARCHITECTURE,
    GRAPH,
    HEADS,
    RESOURCES,
    SOURCE_ARCHITECTURE,
    NativeSequenceGraph,
    OnnxNativeSequenceEvidence,
    verify_quantized_identity,
)
from pinyin_matcher.pretrained_sensevoice import FILES, REVISION
from pinyin_matcher.pretrained_sensevoice_export import session


def test_sequence_adapter_requires_two_cpu_threads_before_accessing_files(tmp_path):
    for options in ({"device": "mps"}, {"threads": 1}, {"threads": 4}):
        with pytest.raises(ValueError, match="CPU_TWO_THREADS"):
            OnnxNativeSequenceEvidence(tmp_path, **options)


def parent_fixture(path):
    parent = {
        "architecture": SOURCE_ARCHITECTURE,
        "sourceRevision": REVISION,
        "sourceWeightsSha256": FILES["model.pt"],
        "parentWeightSha256": FILES["model.pt"],
        "nativeRimeAliases": native_rime_aliases("hanziflow"),
        "files": {"tuned.safetensors": {"sha256": "1" * 64}},
        "sourceDirectory": "/unavailable-research-parent-must-not-be-opened",
    }
    (path / "parent-tuned.json").write_text(json.dumps(parent))
    metadata = {
        **parent,
        "architecture": ARCHITECTURE,
        "targetInput": False,
        "standaloneCpuPackage": True,
        "parentTunedMetadataSha256": fingerprint(path / "parent-tuned.json"),
        "parentTunedWeightSha256": "1" * 64,
    }
    metadata.pop("sourceDirectory")
    return parent, metadata


@pytest.mark.parametrize(
    "field,value",
    [
        ("parentTunedMetadataSha256", "changed"),
        ("parentTunedWeightSha256", "changed"),
        ("sourceRevision", "unpinned"),
        ("parentWeightSha256", "changed"),
        ("sourceWeightsSha256", "changed"),
        ("targetInput", True),
        ("standaloneCpuPackage", False),
        ("nativeRimeAliases", {}),
    ],
)
def test_parent_and_original_identity_corruption_prevents_graph_load(tmp_path, field, value):
    _, metadata = parent_fixture(tmp_path)
    metadata[field] = value
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="PARENT_IDENTITY_MISMATCH"):
        verify_quantized_identity(tmp_path)


def test_missing_or_corrupt_resources_never_fall_back_to_external_parent(tmp_path):
    _, metadata = parent_fixture(tmp_path)
    metadata["files"] = {}
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="REQUIRED_FILES_MISSING"):
        verify_quantized_identity(tmp_path)
    metadata["files"] = {GRAPH: {"sha256": "wrong", "bytes": 5}}
    metadata["files"].update(
        {name: {} for name in ["parent-tuned.json", "training-config.json", *RESOURCES]}
    )
    (tmp_path / GRAPH).write_bytes(b"bad graph")
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="RESOURCE_DIGEST_MISMATCH:encoder"):
        verify_quantized_identity(tmp_path)


def test_both_quantized_architectures_route_without_fp32_loading(tmp_path, monkeypatch):
    calls = []
    sentinel = object()

    def adapter(directory, *, threads):
        calls.append((directory, threads))
        return sentinel

    monkeypatch.setitem(
        sys.modules,
        "pinyin_matcher.pretrained_native_sequence_export",
        SimpleNamespace(OnnxNativeSequenceEvidence=adapter),
    )
    (tmp_path / "tuned.json").write_text(json.dumps({"architecture": ARCHITECTURE}))
    assert load_encoder("sensevoice", tmp_path) is sentinel
    assert calls == [(tmp_path, 2)]
    assert QUANTIZED_NATIVE_PARENTS[ARCHITECTURE] == SOURCE_ARCHITECTURE
    assert is_quantized_native_architecture("sensevoice-50-ctc-int8-v1")
    assert is_quantized_native_architecture(ARCHITECTURE)
    assert not is_quantized_native_architecture(SOURCE_ARCHITECTURE)


def test_torch_counterpart_routes_to_explicit_local_source_adapter(tmp_path, monkeypatch):
    calls = []
    sentinel = object()

    def adapter(directory, *, device, threads):
        calls.append((directory, device, threads))
        return sentinel

    monkeypatch.setitem(
        sys.modules,
        "pinyin_matcher.pretrained_native_sequence",
        SimpleNamespace(NativeSequenceEvidence=adapter),
    )
    (tmp_path / "tuned.json").write_text(json.dumps({"architecture": SOURCE_ARCHITECTURE}))
    assert load_encoder("sensevoice", tmp_path) is sentinel
    assert calls == [(tmp_path, "cpu", 2)]


class TinyEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.projection = nn.Linear(560, 512)
        self.normalization = nn.LayerNorm(512)

    def forward(self, x, lengths):
        valid = torch.arange(x.shape[1])[None, :, None] < lengths[:, None, None]
        values = self.projection(x)
        context = (values * valid).sum(1, keepdim=True) / lengths[:, None, None]
        return self.normalization(values + context)


class TinyHeads(nn.Module):
    def __init__(self):
        super().__init__()
        self.initial_head = nn.Linear(512, 24)
        self.final_head = nn.Linear(512, 44)
        self.tone_head = nn.Linear(512, 7)


def test_actual_dynamic_onnx_and_int8_graphs_preserve_shape_prompt_and_lengths(tmp_path):
    from onnxruntime.quantization import QuantType, quantize_dynamic

    torch.manual_seed(32)
    torch.set_num_threads(2)
    model = NativeSequenceGraph(TinyEncoder(), nn.Embedding(20, 560), TinyHeads()).eval()
    fp32, int8 = tmp_path / "numeric.fp32.onnx", tmp_path / "numeric.int8.onnx"
    outputs = ["frames", *HEADS]
    torch.onnx.export(
        model,
        (torch.randn(1, 4, 560), torch.tensor([4])),
        str(fp32),
        input_names=["features", "lengths"],
        output_names=outputs,
        dynamic_axes={
            "features": {0: "batch", 1: "time"},
            "lengths": {0: "batch"},
            **{key: {0: "batch", 1: "time"} for key in outputs},
        },
        opset_version=17,
        dynamo=False,
    )
    quantize_dynamic(
        str(fp32),
        str(int8),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul", "Gemm"],
        per_channel=True,
    )
    floating, quantized = session(fp32), session(int8)
    assert floating.get_providers() == quantized.get_providers() == ["CPUExecutionProvider"]
    assert quantized.get_session_options().intra_op_num_threads == 2
    for lengths in ([2], [11], [2, 7, 11]):
        x = torch.randn(len(lengths), max(lengths), 560)
        n = torch.tensor(lengths)
        with torch.inference_mode():
            expected = model(x, n)
        actual = floating.run(None, {"features": x.numpy(), "lengths": n.numpy()})
        compressed = quantized.run(None, {"features": x.numpy(), "lengths": n.numpy()})
        for ref, fp, q, width in zip(expected, actual, compressed, (512, 24, 44, 7), strict=True):
            assert q.shape == (len(lengths), max(lengths), width)
            assert np.isfinite(q).all()
            np.testing.assert_allclose(fp, ref.numpy(), atol=1e-5, rtol=1e-5)
            assert np.max(np.abs(q - ref.numpy())) < 0.1
        # The valid frames of a short item must not use the padded tail as context.
        with torch.inference_mode():
            single = model(x[:1, : lengths[0]], n[:1])
        for a, b in zip(expected, single, strict=True):
            torch.testing.assert_close(a[:1, : lengths[0]], b, atol=1e-6, rtol=1e-5)


def test_opt_in_real_native_sequence_fp32_and_int8_parity():
    import os
    from pathlib import Path

    from pinyin_matcher.audio import decode_wav
    from pinyin_matcher.pretrained_native import single_label_ctc
    from pinyin_matcher.pretrained_native_sequence import NativeSequenceEvidence

    model_path = os.environ.get("PRETRAINED_NATIVE_SEQUENCE_MODEL")
    export_path = os.environ.get("PRETRAINED_NATIVE_SEQUENCE_EXPORT")
    waveform = os.environ.get("PRETRAINED_TEST_WAV")
    if not model_path or not export_path or not waveform:
        pytest.skip("Explicit trained native-sequence model/export and licensed waveform required")
    original, exported = Path(model_path), Path(export_path)
    reference = NativeSequenceEvidence(original, device="cpu", threads=2)
    quantized = OnnxNativeSequenceEvidence(exported)
    assert fingerprint(exported / "encoder.fp32.onnx") == quantized.metadata["fp32Export"]["sha256"]
    floating = session(exported / "encoder.fp32.onnx")
    graph = NativeSequenceGraph(reference.encoder, reference.embed, reference.heads).eval()
    wave = decode_wav(Path(waveform).read_bytes())
    assert len(wave) >= 64000, "Use at least four seconds of actual licensed speech"
    samples = {"short150ms": wave[:2400], "halfSecond": wave[:8000], "fourSeconds": wave[:64000]}
    cases = []
    for name, batch in [
        *((k, [v]) for k, v in samples.items()),
        ("variableLengthBatch", [samples["short150ms"], samples["halfSecond"]]),
    ]:
        features = [reference.frontend(v).numpy() for v in batch]
        lengths = np.asarray([len(v) for v in features], dtype=np.int64)
        padded = np.zeros((len(batch), int(lengths.max()), 560), dtype=np.float32)
        for i, value in enumerate(features):
            padded[i, : len(value)] = value
        with torch.inference_mode():
            expected = [
                v.numpy() for v in graph(torch.from_numpy(padded), torch.from_numpy(lengths))
            ]
        float_values = floating.run(None, {"features": padded, "lengths": lengths})
        actual = quantized.evidence_batch(batch)
        case = {"name": name, "frameCounts": lengths.tolist(), "native": {}}
        for output, key in enumerate(("frames", *HEADS)):
            refs = [expected[output][i, :length] for i, length in enumerate(lengths)]
            floats = [float_values[output][i, :length] for i, length in enumerate(lengths)]
            compressed = [v["frames"] if key == "frames" else v["native"][key] for v in actual]
            maximum = max(float(np.abs(a - b).max()) for a, b in zip(refs, floats, strict=True))
            assert maximum < 1e-3
            assert all(
                a.shape == b.shape and np.isfinite(b).all()
                for a, b in zip(refs, compressed, strict=True)
            )
            a, b = np.concatenate(refs), np.concatenate(compressed)
            if key == "frames":
                cosine = float(
                    np.dot(a.ravel(), b.ravel()) / (np.linalg.norm(a) * np.linalg.norm(b))
                )
                assert cosine > 0.95  # Detect catastrophic graph damage, not pronunciation quality.
                case.update(fp32FrameMaxAbs=maximum, int8FrameCosine=cosine)
            else:
                changes = [
                    float(np.abs(single_label_ctc(x)[0] - single_label_ctc(y)[0]).max())
                    for x, y in zip(refs, compressed, strict=True)
                ]
                case["native"][key] = {
                    "fp32MaxAbs": maximum,
                    "int8LogitMaxAbs": float(np.abs(a - b).max()),
                    "int8FrameArgmaxAgreement": float((a.argmax(-1) == b.argmax(-1)).mean()),
                    "int8SingleLabelMassMaxAbs": max(changes),
                }
        cases.append(case)
    assert "sourceDirectory" not in quantized.metadata
    assert not (exported / "model.pt").exists()
    assert not (exported / "tuned.safetensors").exists()
    destination = os.environ.get("PRETRAINED_NATIVE_SEQUENCE_PARITY_OUTPUT")
    if destination:
        Path(destination).write_text(
            json.dumps(
                {
                    "sourceWaveformSha256": fingerprint(Path(waveform)),
                    "sourceTunedMetadataSha256": fingerprint(original / "tuned.json"),
                    "quantizedMetadataSha256": fingerprint(exported / "tuned.json"),
                    "construction": (
                        "First 0.15,0.5,4 seconds of the same licensed four-second waveform "
                        "for numerical dynamic-shape verification only."
                    ),
                    "cases": cases,
                    "qualityPreservationEstablished": False,
                    "fullCpuCalibrationRequired": True,
                    "performanceBenchmark": False,
                    "finalTestRead": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


def test_all_parent_provenance_is_retained_except_the_delta_checkpoint():
    from pinyin_matcher.pretrained_native_sequence_export import source_resource_records

    files = {
        name: {"sha256": name, "bytes": 1}
        for name in (
            "tuned.safetensors",
            "MODEL_LICENSE",
            "training-data.json",
            "adaptation-config.json",
            "native-parent/tuned-source.json",
        )
    }
    assert source_resource_records({"files": files}) == {
        name: record for name, record in files.items() if name != "tuned.safetensors"
    }


@pytest.mark.parametrize(
    "name",
    [
        "encoder.int8.onnx",
        "encoder.int8.onnx/nested.json",
        "ENCODER.INT8.ONNX",
        "./encoder.int8.onnx",
        "parent-tuned.json",
        "training-config.json",
        "tuned.json",
        "../escape.json",
        "/absolute.json",
    ],
)
def test_parent_resources_cannot_replace_export_graph_or_identity(name):
    from pinyin_matcher.pretrained_native_sequence_export import source_resource_records

    with pytest.raises(ValueError, match="RESOURCE_NAME_COLLISION"):
        source_resource_records({"files": {name: {"sha256": "0" * 64, "bytes": 1}}})


def test_quantized_identity_cannot_drop_parent_training_data_provenance(tmp_path):
    parent, metadata = parent_fixture(tmp_path)
    parent["files"]["training-data.json"] = {"sha256": "2" * 64, "bytes": 1}
    (tmp_path / "parent-tuned.json").write_text(json.dumps(parent))
    metadata["parentTunedMetadataSha256"] = fingerprint(tmp_path / "parent-tuned.json")
    metadata["files"] = {
        name: {} for name in [GRAPH, "parent-tuned.json", "training-config.json", *RESOURCES]
    }
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="PARENT_RESOURCE_MISMATCH:training-data"):
        verify_quantized_identity(tmp_path)
