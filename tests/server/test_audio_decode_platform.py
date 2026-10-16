"""Both resource-build platforms enforce the same real PCM checks."""

import struct
import subprocess
import wave

import pytest

from scripts import prepare_pinyin_source as source


@pytest.mark.parametrize(
    "platform,executable", [("darwin", "/usr/bin/afconvert"), ("linux", "ffmpeg")]
)
@pytest.mark.parametrize("silent", [False, True])
def test_decoder_output_is_checked(tmp_path, monkeypatch, platform, executable, silent):
    monkeypatch.setattr(source.sys, "platform", platform)
    output = tmp_path / "decoded.wav"

    def decode(command, **kwargs):
        assert command[0] == executable
        assert kwargs["check"] is True and kwargs["timeout"] == 30
        with wave.open(str(output), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(struct.pack("<h", 0 if silent else 1000) * 16000)

    monkeypatch.setattr(source.subprocess, "run", decode)
    if silent:
        with pytest.raises(ValueError, match="Silent"):
            source.check_recording(tmp_path / "source.mp3", output)
    else:
        assert source.check_recording(tmp_path / "source.mp3", output)["seconds"] == 1


def test_decoder_failure_is_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(source.sys, "platform", "linux")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(source.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        source.check_recording(tmp_path / "bad.mp3", tmp_path / "out.wav")
