"""Graph/runtime contracts and optional real-wave numerical parity, not quality."""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from pinyin_matcher.catalog import fingerprint
from pinyin_matcher.pretrained_native import native_rime_aliases, single_label_ctc
from pinyin_matcher.pretrained_sensevoice import FILES, REVISION
from pinyin_matcher.pretrained_sensevoice_export import (
    ARCHITECTURE,
    HEADS,
    OnnxSenseVoiceEvidence,
    session,
)


def test_quantized_adapter_requires_explicit_cpu_two_threads(tmp_path):
    for options in ({"device": "mps"}, {"threads": 1}, {"threads": 4}):
        with pytest.raises(ValueError, match="CPU_TWO_THREADS"):
            OnnxSenseVoiceEvidence(tmp_path, **options)


def test_parent_fp32_metadata_is_bound_before_opening_graph(tmp_path):
    parent = {
        "architecture": "sensevoice-50-ctc-v1",
        "sourceRevision": REVISION,
        "parentWeightSha256": FILES["model.pt"],
        "files": {"tuned.safetensors": {"sha256": "0" * 64}},
    }
    (tmp_path / "parent-tuned.json").write_text(json.dumps(parent))
    metadata = {
        "architecture": ARCHITECTURE,
        "sourceRevision": REVISION,
        "parentWeightSha256": FILES["model.pt"],
        "targetInput": False,
        "nativeRimeAliases": native_rime_aliases("hanziflow"),
        "parentTunedMetadataSha256": "wrong",
        "parentTunedWeightSha256": "0" * 64,
    }
    (tmp_path / "tuned.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="PARENT_IDENTITY_MISMATCH"):
        OnnxSenseVoiceEvidence(tmp_path)


def test_opt_in_actual_variable_length_fp32_and_int8_native_parity():
    import torch

    from pinyin_matcher.audio import decode_wav, trim_silence
    from pinyin_matcher.pretrained_sensevoice_finetune import (
        TunedSenseVoiceEvidence,
        _frontend,
    )

    root, waveform = os.environ.get("PRETRAINED_MODELS"), os.environ.get("PRETRAINED_TEST_WAV")
    if not root or not waveform:
        pytest.skip("Explicit local derivative weights and licensed real waveform required")
    source = Path(root) / "sensevoice-finetuned-v1"
    exported = Path(root) / "sensevoice-finetuned-v1-int8"
    if not (exported / "tuned.json").is_file():
        pytest.skip("Explicit ONNX export required")
    model = TunedSenseVoiceEvidence(source, device="cpu", threads=2)
    quantized = OnnxSenseVoiceEvidence(exported)
    assert quantized.session.get_providers() == ["CPUExecutionProvider"]
    options = quantized.session.get_session_options()
    assert options.intra_op_num_threads == 2 and options.inter_op_num_threads == 1
    assert fingerprint(exported / "encoder.fp32.onnx") == quantized.metadata["fp32Export"]["sha256"]
    fp32 = session(exported / "encoder.fp32.onnx")
    sample = trim_silence(decode_wav(Path(waveform).read_bytes()))
    short = np.resize(sample, 2400).astype(np.float32)
    half = np.resize(sample, 8000).astype(np.float32)
    four = np.resize(sample, 64000).astype(np.float32)
    results = []
    for title, waves in (
        ("short150ms", [short]),
        ("halfSecond", [half]),
        ("fourSeconds", [four]),
        ("variableLengthBatch", [short, half]),
    ):
        features = [_frontend(model.model, wave) for wave in waves]
        lengths = np.asarray([len(item) for item in features], dtype=np.int64)
        padded = np.zeros((len(features), int(lengths.max()), 560), dtype=np.float32)
        for index, item in enumerate(features):
            padded[index, : len(item)] = item.numpy()
        with torch.inference_mode():
            reference = [
                item.numpy()
                for item in model.model(torch.from_numpy(padded), torch.from_numpy(lengths))
            ]
        floating = fp32.run(None, {"features": padded, "lengths": lengths})
        actual = quantized.evidence_batch(waves)
        case = {"name": title, "frameCounts": lengths.tolist(), "native": {}}
        for output, key in enumerate(("frames", *HEADS)):
            expected = [reference[output][i, :length] for i, length in enumerate(lengths)]
            exported_values = [floating[output][i, :length] for i, length in enumerate(lengths)]
            values = [item["frames"] if key == "frames" else item["native"][key] for item in actual]
            maximum = max(
                float(np.abs(a - b).max()) for a, b in zip(expected, exported_values, strict=True)
            )
            assert maximum < 1e-3
            assert all(
                a.shape == b.shape and np.isfinite(b).all()
                for a, b in zip(expected, values, strict=True)
            )
            a, b = np.concatenate(expected), np.concatenate(values)
            if key == "frames":
                cosine = float(
                    np.dot(a.ravel(), b.ravel()) / (np.linalg.norm(a) * np.linalg.norm(b))
                )
                assert cosine > 0.97  # Catastrophic numerical degradation guard only.
                case.update(fp32FrameMaxAbs=maximum, int8FrameCosine=cosine)
            else:
                event_differences = [
                    np.abs(single_label_ctc(a)[0] - single_label_ctc(b)[0]).max()
                    for a, b in zip(expected, values, strict=True)
                ]
                case["native"][key] = {
                    "fp32MaxAbs": maximum,
                    "int8LogitMaxAbs": float(np.abs(a - b).max()),
                    "int8FrameArgmaxAgreement": float((a.argmax(-1) == b.argmax(-1)).mean()),
                    "int8SingleLabelMassMaxAbs": float(max(event_differences)),
                }
        results.append(case)
    assert not (exported / "model.pt").exists()
    assert not (exported / "tuned.safetensors").exists()
    destination = os.environ.get("PRETRAINED_PARITY_OUTPUT")
    if destination:
        Path(destination).write_text(
            json.dumps(
                {
                    "sourceWaveformSha256": fingerprint(Path(waveform)),
                    "sourceTunedMetadataSha256": fingerprint(source / "tuned.json"),
                    "quantizedMetadataSha256": fingerprint(exported / "tuned.json"),
                    "construction": (
                        "Real licensed waveform resized/repeated solely for numerical parity; "
                        "no pronunciation labels assigned"
                    ),
                    "cases": results,
                    "qualityPreservationEstablished": False,
                    "fullCpuCalibrationRequired": True,
                    "performanceBenchmark": False,
                    "finalTestRead": False,
                },
                indent=2,
            )
            + "\n"
        )
