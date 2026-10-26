"""Opt-in integration against the actual local trained artifact; no fixture weights."""

import os
import socket
import threading
from pathlib import Path

import pytest

from pinyin_matcher.data import read_manifest
from pinyin_matcher.inference import PinyinMatcher
from pinyin_matcher.package import install


@pytest.fixture
def artifact():
    if not os.environ.get("MATCHER_MODEL") or not os.environ.get("MATCHER_MANIFEST"):
        pytest.skip("set MATCHER_MODEL and MATCHER_MANIFEST to verify actual trained weights")
    directory = Path(os.environ["MATCHER_MODEL"])
    manifest = Path(os.environ["MATCHER_MANIFEST"])
    row = next(row for row in read_manifest(manifest) if row["split"] == "test")
    return directory, row["targetId"], (manifest.parent / row["file"]).read_bytes()


def test_actual_cpu_artifact_works_offline_and_cancelled_results_are_discarded(
    artifact, monkeypatch
):
    directory, target, wav = artifact

    def no_network(*args, **kwargs):
        pytest.fail("inference attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    matcher = PinyinMatcher(directory)
    assert matcher.capabilities()["providers"] == ["CPUExecutionProvider"]
    result = matcher.match(target, wav, include_evidence=True)
    assert result["status"] in {"matched", "retry", "uncertain"}
    assert "candidateId" in result
    assert result["toneAssessed"] is False
    assert "score" not in result
    cancel = threading.Event()
    method = "_branch_evidence" if matcher.metadata.get("decisionVersion") == 3 else "_scores"
    original = getattr(matcher, method)

    def cancel_after_native_run(*args, **kwargs):
        scores = original(*args, **kwargs)
        cancel.set()
        return scores

    monkeypatch.setattr(matcher, method, cancel_after_native_run)
    assert matcher.match(target, wav, cancel=cancel)["reason"] == "MATCH_CANCELLED"
    assert matcher.lock.acquire(blocking=False)
    matcher.lock.release()


def test_actual_bundle_installs_idempotently_without_training_framework(artifact, tmp_path):
    directory, target, wav = artifact
    destination = tmp_path / "runtime-model"
    first = install(directory, destination)
    assert first["available"]
    assert install(directory, destination) == first
    assert not (destination / "checkpoint.pt").exists()
    result = PinyinMatcher(destination).match(target, wav)
    assert result["status"] in {"matched", "retry", "uncertain"}


def test_corrupt_actual_tone_branch_never_falls_back_to_shared_head(artifact, tmp_path):
    directory, target, wav = artifact
    destination = tmp_path / "corrupt-tone"
    install(directory, destination)
    matcher = PinyinMatcher(destination)
    (destination / matcher.metadata["pitchTone"]["file"]).write_bytes(b"corrupt tone model")
    result = PinyinMatcher(destination).match(target, wav)
    assert result["status"] == "unavailable"
    assert result["reason"] == "PITCH_MODEL_DIGEST_MISMATCH"
