import hashlib
import json
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import build_open_voice as voice


def setup_voice(tmp_path, monkeypatch, silent=False):
    model = tmp_path / "models" / "fixture"
    model.mkdir(parents=True)
    (model / "model.onnx").write_bytes(b"explicit-test-model-fixture")
    config = {
        "directory": "fixture",
        "modelFile": "model.onnx",
        "lexicons": [],
        "ruleFiles": [],
        "files": {"model.onnx": hashlib.sha256((model / "model.onnx").read_bytes()).hexdigest()},
        "threads": 1,
        "speaker": 3,
        "speed": 0.95,
        "model": "test-fixture",
        "engineVersion": "test",
        "archiveSha256": "a" * 64,
        "license": "Apache-2.0",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(voice, "CONFIG", path)
    texts = {"ui-one": "点一下开始。", "ui-two": "点一下开始。"}
    monkeypatch.setattr(voice.learning_audio, "narration_scripts", lambda: texts)
    monkeypatch.setattr(voice.learning_audio, "lesson_recordings", lambda: {})
    monkeypatch.setattr(
        voice.learning_audio,
        "expected_assets",
        lambda: {
            key: {
                "purpose": "chinese-instruction",
                "sourceType": "local-open-tts",
                "textSha256": voice.learning_audio.text_digest(text),
            }
            for key, text in texts.items()
        },
    )
    calls = []

    def generate(text, **kwargs):
        calls.append(text)
        samples = np.zeros(1600) if silent else np.sin(np.arange(1600) / 8) * 0.1
        return SimpleNamespace(samples=samples, sample_rate=16000)

    monkeypatch.setitem(
        sys.modules,
        "sherpa_onnx",
        SimpleNamespace(
            OfflineTts=lambda _: SimpleNamespace(generate=generate),
            OfflineTtsConfig=lambda **kwargs: kwargs,
            OfflineTtsModelConfig=lambda **kwargs: kwargs,
            OfflineTtsKokoroModelConfig=lambda **kwargs: kwargs,
        ),
    )
    return model.parent, texts, calls


def test_open_voice_deduplicates_but_preserves_text_identity_and_valid_pcm(tmp_path, monkeypatch):
    model, texts, calls = setup_voice(tmp_path, monkeypatch)
    output = tmp_path / "audio"
    result = voice.generate(output, model)
    assert result["narrationIds"] == 2
    assert result["uniqueNarration"] == 1
    assert len(calls) == 1
    assets = json.loads((output / "manifest.json").read_text())["assets"]
    assert assets[0]["file"] == assets[1]["file"]
    with wave.open(str(output / assets[0]["file"])) as pcm:
        assert (pcm.getnchannels(), pcm.getsampwidth(), pcm.getframerate()) == (1, 2, 16000)
    texts["ui-one"] = "点一下下一条。"
    voice.generate(output, model)
    updated = json.loads((output / "manifest.json").read_text())["assets"]
    assert updated[0]["file"] != updated[1]["file"]
    assert updated[0]["textSha256"] != updated[1]["textSha256"]


def test_open_voice_rejects_model_tampering_and_silence_without_publishing(tmp_path, monkeypatch):
    model, _, _ = setup_voice(tmp_path, monkeypatch, silent=True)
    output = tmp_path / "audio"
    output.mkdir()
    manifest = output / "manifest.json"
    manifest.write_text("preserve-existing-manifest")
    with pytest.raises(ValueError, match="Empty/invalid"):
        voice.generate(output, model)
    assert manifest.read_text() == "preserve-existing-manifest"
    (model / "fixture" / "model.onnx").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        voice.generate(output, model)
