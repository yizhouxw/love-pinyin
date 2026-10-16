"""Exercise lifecycle commands against real local listeners without setup/network."""

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS launcher")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def instance(tmp_path):
    shutil.copy2(ROOT / "run.sh", tmp_path / "run.sh")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = str(sock.getsockname()[1])
    env = {**os.environ, "LOVE_PINYIN_PORT": port}

    def run(*args):
        return subprocess.run(
            [str(tmp_path / "run.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    return tmp_path, port, run


def listener(directory, port, application):
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import socket,sys; s=socket.socket(); "
            "s.bind(('127.0.0.1',int(sys.argv[-1]))); s.listen(); "
            "print('ready',flush=True); s.accept()",
            "uvicorn",
            application,
            "--port",
            port,
        ],
        cwd=directory,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout.readline().strip() == "ready"
    return process


def test_stopped_status_and_idempotent_stop(instance):
    directory, _, run = instance
    assert run("status").returncode == 3
    assert run("stop").returncode == 0
    assert run("top").returncode == 0
    assert not (directory / "private").exists()


@pytest.mark.parametrize("action", ["stop", "top", "restart"])
def test_stop_real_service_and_restart_reaches_setup(instance, action):
    directory, port, run = instance
    process = listener(directory, port, "server.main:app")
    try:
        assert run("status").returncode == 0
        assert "already running" in run("start").stdout
        # Stop restart at the setup lock, before dependencies can be installed.
        (directory / "private/setup.lock").mkdir(parents=True)
        result = run(action)
        process.wait(timeout=3)
        assert "stopped" in result.stdout
        if action == "restart":
            assert result.returncode == 1
            assert "Another setup" in result.stderr
        else:
            assert result.returncode == 0
        assert run("status").returncode == 3
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait()


@pytest.mark.parametrize("other_directory", [False, True])
def test_refuse_foreign_service(instance, tmp_path, other_directory):
    directory, port, run = instance
    foreign = directory / "foreign"
    foreign.mkdir()
    process = listener(
        foreign if other_directory else directory,
        port,
        "server.main:app" if other_directory else "other:app",
    )
    try:
        for action in ("status", "stop", "restart", "start"):
            assert run(action).returncode == 1
            assert process.poll() is None
    finally:
        process.terminate()
        process.wait()


def test_invalid_port_and_arguments(instance):
    _, _, run = instance
    assert run("unknown").returncode == 1
    assert run("stop", "extra").returncode == 1
    for port in ("0", "65536", "08000", "bad"):
        result = subprocess.run(
            [str(ROOT / "run.sh"), "stop"],
            env={**os.environ, "LOVE_PINYIN_PORT": port},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Invalid LOVE_PINYIN_PORT" in result.stderr
