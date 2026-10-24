import hashlib
import json
import wave

import numpy as np
import pytest

from scripts import build_open_voice as voice


def setup_voice(tmp_path, monkeypatch, silent=False):
    model = tmp_path / "models" / "fixture"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"explicit-test-model-fixture")
    config = {
        "directory": "fixture",
        "instruct": "test fixture guidance",
        "files": {
            "model.safetensors": hashlib.sha256(
                (model / "model.safetensors").read_bytes()
            ).hexdigest()
        },
        "revision": "fixed-test-revision",
        "speaker": "Serena",
        "model": "test-fixture",
        "engineVersion": "test",
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
        return samples, 16000

    monkeypatch.setattr(voice, "create_engine", lambda model, config: generate)
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
    (model / "fixture" / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        voice.generate(output, model)


def test_qwen_adapter_passes_chinese_style_and_rejects_truncated_speech(tmp_path, monkeypatch):
    import os
    import sys
    from types import SimpleNamespace

    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    config = {
        "seed": 42,
        "speaker": "Serena",
        "language": "Chinese",
        "instruct": "清晰自然。",
        "generation": {"max_tokens": 512, "temperature": 0.7},
    }
    calls = []
    seed_calls = []
    tokens = [10]

    def generated(**kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(audio=np.ones(1600) * 0.1, sample_rate=24000, token_count=tokens[0])

    monkeypatch.setitem(
        sys.modules,
        "mlx",
        SimpleNamespace(
            core=SimpleNamespace(
                random=SimpleNamespace(seed=seed_calls.append), clear_cache=lambda: None
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "mlx.core",
        SimpleNamespace(random=SimpleNamespace(seed=seed_calls.append), clear_cache=lambda: None),
    )
    monkeypatch.setitem(sys.modules, "mlx_audio", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "mlx_audio.tts", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "mlx_audio.tts.utils",
        SimpleNamespace(load_model=lambda path: SimpleNamespace(generate_custom_voice=generated)),
    )
    synthesize = voice.create_engine(tmp_path, config)
    samples, rate = synthesize("点一下开始。")
    assert rate == 24000 and samples.size == 1600
    assert calls[0] == {
        "text": "点一下开始。",
        "speaker": "Serena",
        "language": "Chinese",
        "instruct": "清晰自然。",
        "max_tokens": 512,
        "temperature": 0.7,
    }
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    synthesize("点一下开始。")
    assert seed_calls[0] == seed_calls[1]
    tokens[0] = 512
    with pytest.raises(ValueError, match="truncated"):
        synthesize("点一下开始。")


def test_sentence_voice_profile_does_not_reuse_generic_same_text_audio(tmp_path, monkeypatch):
    model, texts, calls = setup_voice(tmp_path, monkeypatch)
    texts["daily-sentence-example"] = texts["ui-one"]
    result = voice.generate(tmp_path / "audio", model)
    manifest = json.loads((tmp_path / "audio/manifest.json").read_text())["assets"]
    files = {item["id"]: item["file"] for item in manifest}
    assert result["uniqueNarration"] == 2
    assert len(calls) == 2
    assert files["ui-one"] == files["ui-two"]
    assert files["daily-sentence-example"] != files["ui-one"]
