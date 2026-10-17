"""Verify the desktop command delegates readiness to the unified launcher."""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def command(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    shutil.copy2(ROOT / "scripts/lovepinyin.sh", scripts / "lovepinyin.sh")
    (scripts / "service-config.sh").write_text(
        'load_service_config() { app_port="${LOVE_PINYIN_PORT:-8000}"; }\n'
    )
    (tmp_path / "run.sh").write_text(
        """#!/bin/bash
set -eu
echo "$1" >> actions
case "$1" in
  --prepare-only)
    mkdir -p .venv/bin
    ln -s "$TEST_PYTHON" .venv/bin/python
    exit 0 ;;
  status)
    if [[ "$SCENARIO" == lost && ! -f initial_checked ]]; then
      touch initial_checked
      echo 'HTTP and HTTPS running'
      exit 0
    fi
    case "$SCENARIO" in
      conflict) exit 1 ;;
      ready|restart|expired) echo 'HTTP and HTTPS running'; exit 0 ;;
    esac
    [[ -f ready ]] && { echo 'HTTP and HTTPS running'; exit 0; }
    echo 'HTTP running; HTTPS not running'
    exit 3 ;;
  stop|top) exit 7 ;;
  start|restart)
    [[ "$SCENARIO" != ready ]] || { echo 'Love Pinyin is ready.'; exit 0; }
    [[ "$SCENARIO" != expired ]] || { echo 'HTTPS certificate expired' >&2; exit 1; }
    echo $$ > launcher.pid
    [[ "$SCENARIO" != failure ]] || { echo 'HTTPS certificate invalid' >&2; exit 1; }
    sleep 0.2
    touch ready
    echo 'Love Pinyin is ready.'
    trap 'exit 0' TERM
    while true; do sleep 1; done ;;
esac
"""
    )
    (tmp_path / "run.sh").chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text("#!/bin/bash\nexit 0\n")
    (fake_bin / "open").write_text(
        '#!/bin/bash\n[[ "$SCENARIO" == ready || -f ready ]] || exit 9\necho "$1" > opened\n'
    )
    for script in fake_bin.iterdir():
        script.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOVE_PINYIN_PORT": "8123",
        "LOVE_PINYIN_LOG_DIR": str(tmp_path / "logs"),
        "TEST_PYTHON": sys.executable,
    }

    def run(scenario, *args):
        return subprocess.run(
            ["/bin/bash", str(scripts / "lovepinyin.sh"), *args],
            env={**env, "SCENARIO": scenario},
            capture_output=True,
            text=True,
            timeout=10,
        )

    yield tmp_path, run
    pid_file = tmp_path / "launcher.pid"
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text()), signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize("action", ["status", "stop", "top"])
def test_management_commands_delegate_exit_status(command, action):
    directory, run = command
    result = run("ready", action)
    assert result.returncode == (0 if action == "status" else 7)
    assert (directory / "actions").read_text().splitlines() == [action]
    assert not (directory / "opened").exists()


def test_start_reuses_both_ready_endpoints(command):
    directory, run = command
    assert run("ready").returncode == 0
    actions = (directory / "actions").read_text().splitlines()
    assert actions[:2] == ["status", "start"]
    assert actions.count("start") == 1
    assert (directory / "opened").read_text().strip() == "http://127.0.0.1:8123"


def test_endpoint_lost_after_status_restarts_in_background(command):
    directory, run = command
    result = run("lost", "start")
    assert result.returncode == 0, result.stderr
    assert (directory / "launcher.pid").exists()
    assert (directory / "ready").exists()
    assert (directory / "opened").exists()


def test_service_runs_in_a_separate_session_and_process_group(command):
    directory, run = command
    assert run("partial", "start").returncode == 0
    pid = int((directory / "launcher.pid").read_text())
    assert os.getpgid(pid) == pid
    assert os.getsid(pid) == pid
    assert os.getpgid(pid) != os.getpgrp()
    assert os.getsid(pid) != os.getsid(0)


def test_first_start_prepares_pinned_python_before_detaching(command):
    directory, run = command
    (directory / ".venv/bin/python").unlink()
    result = run("partial", "start")
    assert result.returncode == 0, result.stderr
    assert (directory / "actions").read_text().splitlines()[:3] == [
        "status",
        "--prepare-only",
        "start",
    ]
    assert (directory / "opened").exists()


def test_start_repairs_missing_https_before_opening(command):
    directory, run = command
    result = run("partial", "start")
    assert result.returncode == 0, result.stderr
    assert "start" in (directory / "actions").read_text().splitlines()
    assert (directory / "ready").exists()
    assert (directory / "opened").exists()


def test_restart_waits_for_current_launch_even_when_old_status_is_ready(command):
    directory, run = command
    result = run("restart", "restart")
    assert result.returncode == 0, result.stderr
    actions = (directory / "actions").read_text().splitlines()
    assert actions[0] == "restart"
    assert "stop" not in actions
    assert (directory / "ready").exists()
    assert (directory / "opened").exists()


def test_failed_launch_surfaces_error_without_opening_browser(command):
    directory, run = command
    result = run("failure", "start")
    assert result.returncode == 1
    assert "HTTPS certificate invalid" in result.stderr
    assert not (directory / "opened").exists()


def test_running_service_still_checks_tls_before_opening_browser(command):
    directory, run = command
    result = run("expired", "start")
    assert result.returncode == 1
    assert "HTTPS certificate expired" in result.stderr
    assert not (directory / "opened").exists()


def test_conflicting_service_is_not_restarted(command):
    directory, run = command
    assert run("conflict", "start").returncode == 1
    assert (directory / "actions").read_text().splitlines() == ["status"]
    assert not (directory / "opened").exists()


@pytest.mark.parametrize("args", [("unknown",), ("start", "extra")])
def test_invalid_arguments_do_not_start_anything(command, args):
    directory, run = command
    assert run("ready", *args).returncode == 1
    assert not (directory / "actions").exists()
