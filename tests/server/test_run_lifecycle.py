"""Exercise launcher ownership and cleanup against real processes, without downloads."""

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS launcher")
ROOT = Path(__file__).resolve().parents[2]
ENDPOINT_ENV = (
    "LOVE_PINYIN_PORT",
    "LOVE_PINYIN_HTTPS_PORT",
    "LOVE_PINYIN_BIND_IP",
    "LOVE_PINYIN_TLS_CERT",
    "LOVE_PINYIN_TLS_KEY",
)
LISTENER = """
import os, signal, socket, sys
args = sys.argv
host = args[args.index('--host') + 1]
port = int(args[args.index('--port') + 1])
if os.environ.get('FAIL_TEST_PORT') == str(port):
    sys.exit(7)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((host, port))
s.listen()
print('ready', flush=True)
while True:
    signal.pause()
"""


def free_port(host="127.0.0.1"):
    with socket.socket() as sock:
        sock.bind((host, 0))
        return str(sock.getsockname()[1])


def write_executable(path, source):
    path.write_text(source)
    path.chmod(0o700)


@dataclass
class Instance:
    directory: Path
    env: dict[str, str]

    @property
    def port(self):
        return self.env["LOVE_PINYIN_PORT"]

    def run(self, *args):
        return subprocess.run(
            [str(self.directory / "run.sh"), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def save_config(self, text):
        private = self.directory / "private"
        private.mkdir(exist_ok=True)
        (private / "server.env").write_text(text)


@pytest.fixture
def instance(tmp_path):
    shutil.copy2(ROOT / "run.sh", tmp_path / "run.sh")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("service-config.sh", "service-lifecycle.sh", "serve-lan.mjs"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    env = {key: value for key, value in os.environ.items() if key not in ENDPOINT_ENV}
    env["LOVE_PINYIN_PORT"] = free_port()
    # Lifecycle checks must never reach dependency installation or a network fetch.
    guard = tmp_path / "guard-bin"
    guard.mkdir()
    env["PATH"] = f"{guard}:{env['PATH']}"
    marker = shlex.quote(str(tmp_path / "unexpected-setup"))
    for name in ("npm", "uv", "curl"):
        write_executable(guard / name, f"#!/bin/sh\necho {name} >> {marker}\nexit 97\n")
    yield Instance(tmp_path, env)
    assert not (tmp_path / "unexpected-setup").exists()


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [
            node,
            "-e",
            "console.log(JSON.stringify(Object.values(require('node:os').networkInterfaces())"
            ".flat().filter(x=>x.family==='IPv4'&&!x.internal).map(x=>x.address)))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    addresses = json.loads(result.stdout)
    if not addresses:
        pytest.skip("TLS launch preflight needs a local LAN IPv4 address")
    directory = tmp_path_factory.mktemp("launcher-tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=Temporary launcher test",
            "-addext",
            f"subjectAltName=IP:{addresses[0]}",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        capture_output=True,
        check=True,
    )
    return {
        "LOVE_PINYIN_BIND_IP": addresses[0],
        "LOVE_PINYIN_TLS_CERT": str(cert),
        "LOVE_PINYIN_TLS_KEY": str(key),
    }


@pytest.fixture
def dual(instance, tls):
    instance.env.update(tls)
    certificate_directory = instance.directory / "temporary TLS files"
    certificate_directory.mkdir()
    for setting in ("LOVE_PINYIN_TLS_CERT", "LOVE_PINYIN_TLS_KEY"):
        target = certificate_directory / Path(tls[setting]).name
        shutil.copy2(tls[setting], target)
        instance.env[setting] = str(target)
    instance.env["LOVE_PINYIN_HTTPS_PORT"] = free_port(tls["LOVE_PINYIN_BIND_IP"])
    while instance.env["LOVE_PINYIN_HTTPS_PORT"] == instance.port:
        instance.env["LOVE_PINYIN_HTTPS_PORT"] = free_port(tls["LOVE_PINYIN_BIND_IP"])
    return instance


@contextmanager
def listener(
    instance,
    *,
    https=False,
    application="server.main:app",
    directory=None,
    include_tls=True,
    host=None,
):
    host = host or (instance.env["LOVE_PINYIN_BIND_IP"] if https else "127.0.0.1")
    port = instance.env["LOVE_PINYIN_HTTPS_PORT"] if https else instance.port
    args = ["uvicorn", application, "--host", host, "--port", port]
    if https and include_tls:
        args += [
            "--ssl-certfile",
            instance.env["LOVE_PINYIN_TLS_CERT"],
            "--ssl-keyfile",
            instance.env["LOVE_PINYIN_TLS_KEY"],
        ]
    process = subprocess.Popen(
        [sys.executable, "-c", LISTENER, *args],
        cwd=directory or instance.directory,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()


def test_stopped_status_and_idempotent_stop(instance):
    assert instance.run("status").returncode == 3
    assert instance.run("stop").returncode == 0
    assert instance.run("top").returncode == 0
    assert not (instance.directory / "private").exists()


@pytest.mark.parametrize("action", ["stop", "top", "restart"])
def test_stop_real_service_and_restart_reaches_setup(instance, action):
    with listener(instance) as process:
        assert instance.run("status").returncode == 0
        assert "already running" in instance.run("start").stdout
        # Stop restart at the setup lock, before dependencies can be installed.
        (instance.directory / "private/setup.lock").mkdir(parents=True)
        result = instance.run(action)
        process.wait(timeout=3)
        assert "stopped" in result.stdout
        if action == "restart":
            assert result.returncode == 1
            assert "Another setup" in result.stderr
        else:
            assert result.returncode == 0
        assert instance.run("status").returncode == 3


@pytest.mark.parametrize("other_directory", [False, True])
def test_refuse_foreign_service(instance, other_directory):
    foreign = instance.directory / "foreign"
    foreign.mkdir()
    with listener(
        instance,
        directory=foreign if other_directory else instance.directory,
        application="server.main:app" if other_directory else "other:app",
    ) as process:
        for action in ("status", "stop", "restart", "start"):
            assert instance.run(action).returncode == 1
            assert process.poll() is None


def test_invalid_port_and_arguments(instance):
    assert instance.run("unknown").returncode == 1
    assert instance.run("stop", "extra").returncode == 1
    for port in ("0", "65536", "08000", "bad"):
        instance.env["LOVE_PINYIN_PORT"] = port
        result = instance.run("stop")
        assert result.returncode == 1
        assert "Invalid LOVE_PINYIN_PORT" in result.stderr


def test_http_only_does_not_report_configured_https_running(dual):
    with listener(dual):
        result = dual.run("status")
        assert result.returncode == 3
        assert f"http://127.0.0.1:{dual.port}" in result.stdout
        assert dual.env["LOVE_PINYIN_HTTPS_PORT"] in result.stdout


@pytest.mark.parametrize("action", ["stop", "top"])
def test_both_endpoints_are_managed_together(dual, action):
    with listener(dual) as http, listener(dual, https=True) as https:
        status = dual.run("status")
        assert status.returncode == 0
        assert f"http://127.0.0.1:{dual.port}" in status.stdout
        assert f"https://{dual.env['LOVE_PINYIN_BIND_IP']}:" in status.stdout
        assert dual.run("start").returncode == 0
        assert dual.run(action).returncode == 0
        http.wait(timeout=3)
        https.wait(timeout=3)
        assert dual.run("status").returncode == 3
        assert dual.run(action).returncode == 0


@pytest.mark.parametrize("foreign_tls", [False, True])
def test_https_conflict_preflight_never_stops_http(dual, foreign_tls):
    with (
        listener(dual) as http,
        listener(
            dual,
            https=True,
            application="other:app" if foreign_tls else "server.main:app",
            include_tls=foreign_tls,
        ) as foreign,
    ):
        for action in ("status", "start", "stop", "top", "restart"):
            assert dual.run(action).returncode == 1
            assert http.poll() is None
            assert foreign.poll() is None


@pytest.mark.parametrize(
    "missing", ["LOVE_PINYIN_TLS_CERT", "LOVE_PINYIN_TLS_KEY", "LOVE_PINYIN_BIND_IP"]
)
def test_partial_https_configuration_preserves_running_http(dual, missing):
    with listener(dual) as http:
        dual.env.pop(missing)
        for action in ("start", "restart"):
            assert dual.run(action).returncode != 0
            assert http.poll() is None


def test_invalid_certificate_preflight_preserves_both_services(dual):
    with listener(dual) as http, listener(dual, https=True) as https:
        Path(dual.env["LOVE_PINYIN_TLS_CERT"]).unlink()
        for action in ("start", "restart"):
            result = dual.run(action)
            assert result.returncode != 0
            assert http.poll() is None
            assert https.poll() is None
        # Stop must remain available when a certificate is lost or expires.
        assert dual.run("stop").returncode == 0
        http.wait(timeout=3)
        https.wait(timeout=3)


def test_changed_bind_address_reports_incomplete_but_can_stop_old_services(dual):
    with listener(dual) as http, listener(dual, https=True) as https:
        dual.env["LOVE_PINYIN_BIND_IP"] = "192.0.2.123"
        result = dual.run("status")
        assert result.returncode == 3
        assert "different address" in result.stdout
        assert "restart" in result.stdout
        assert dual.run("stop").returncode == 0
        http.wait(timeout=3)
        https.wait(timeout=3)


def test_start_recheck_reuses_endpoints_filled_by_another_launcher(dual):
    with listener(dual) as http, listener(dual, https=True) as https:
        result = subprocess.run(
            [
                "/bin/bash",
                "-euc",
                "source scripts/service-config.sh; source scripts/service-lifecycle.sh; "
                "load_service_config; start_services; "
                "started_pids=(); cleanup_started_services",
            ],
            cwd=dual.directory,
            env=dual.env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        assert "Love Pinyin is ready." in result.stdout
        assert http.poll() is None
        assert https.poll() is None


@pytest.mark.parametrize("port", ["0", "65536", "08443", "bad", "same-as-http"])
def test_invalid_https_port_preserves_running_http(dual, port):
    with listener(dual) as http:
        dual.env["LOVE_PINYIN_HTTPS_PORT"] = dual.port if port == "same-as-http" else port
        for action in ("start", "restart"):
            assert dual.run(action).returncode != 0
            assert http.poll() is None


def test_saved_config_environment_precedence_and_literal_values(dual):
    saved = dict(dual.env)
    dual.save_config(
        "# Local endpoint configuration\n"
        f"LOVE_PINYIN_PORT={free_port()}\n"
        f"LOVE_PINYIN_HTTPS_PORT={saved['LOVE_PINYIN_HTTPS_PORT']}\n"
        f"LOVE_PINYIN_BIND_IP={saved['LOVE_PINYIN_BIND_IP']}\n"
        f"LOVE_PINYIN_TLS_CERT={saved['LOVE_PINYIN_TLS_CERT']}\n"
        f"LOVE_PINYIN_TLS_KEY={saved['LOVE_PINYIN_TLS_KEY']}\n"
    )
    with listener(dual) as http, listener(dual, https=True) as https:
        for name in ENDPOINT_ENV[1:]:
            dual.env.pop(name)
        assert dual.run("status").returncode == 0
        assert dual.run("stop").returncode == 0
        http.wait(timeout=3)
        https.wait(timeout=3)
    marker = dual.directory / "must-not-execute"
    dual.save_config(f"LOVE_PINYIN_TLS_CERT=$(touch {marker})\n")
    assert dual.run("start").returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize("text", ["PATH=/tmp/unsafe\n", "source /tmp/unsafe\n"])
def test_saved_config_rejects_unsupported_keys_or_shell(instance, text):
    instance.save_config(text)
    assert instance.run("start").returncode != 0


def prepare_fake_runtime(instance):
    """Skip dependency work, while exercising the actual shell supervisor and sockets."""
    guard = instance.directory / "guard-bin"
    actual_node = shlex.quote(shutil.which("node"))
    write_executable(
        guard / "node",
        '#!/bin/sh\nif [ "$1" = --version ]; then echo v24.18.1; exit 0; fi\n'
        f'exec {actual_node} "$@"\n',
    )
    for command, version in (("npm", "11.16.0"), ("uv", "uv 0.12.5")):
        write_executable(
            guard / command,
            f'#!/bin/sh\nif [ "$1" = --version ]; then echo "{version}"; fi\nexit 0\n',
        )
    runtime = instance.directory / ".venv/bin"
    runtime.mkdir(parents=True)
    write_executable(runtime / "uvicorn", f"#!{sys.executable}\n{LISTENER}")
    (instance.directory / "dist").mkdir()
    (instance.directory / "dist/index.html").write_text("temporary launcher test")


@contextmanager
def launch(instance):
    log_path = instance.directory / "launcher.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [str(instance.directory / "run.sh")],
            env=instance.env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            yield process, log_path
        finally:
            # Only this test's new process group is signalled, including stray children
            # if a regression prevents the launcher from cleaning them up.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            process.wait(timeout=15)


def wait_for_ready(process, log_path):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        log = log_path.read_text()
        if "Love Pinyin is ready." in log:
            return
        assert process.poll() is None, log
        time.sleep(0.05)
    pytest.fail(f"Launcher never became ready: {log_path.read_text()}")


def test_start_both_endpoints_and_ctrl_c_cleans_up(dual):
    prepare_fake_runtime(dual)
    with launch(dual) as (process, log):
        wait_for_ready(process, log)
        assert dual.run("status").returncode == 0
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=15) == 130, log.read_text()
        assert dual.run("status").returncode == 3
        # Neither endpoint may remain alive even when the combined status is 3.
        with socket.socket() as http, socket.socket() as https:
            assert http.connect_ex(("127.0.0.1", int(dual.port))) != 0
            assert (
                https.connect_ex(
                    (dual.env["LOVE_PINYIN_BIND_IP"], int(dual.env["LOVE_PINYIN_HTTPS_PORT"]))
                )
                != 0
            )


def test_failed_https_start_cleans_up_new_http_sibling(dual):
    prepare_fake_runtime(dual)
    dual.env["FAIL_TEST_PORT"] = dual.env["LOVE_PINYIN_HTTPS_PORT"]
    with launch(dual) as (process, log):
        assert process.wait(timeout=15) != 0, log.read_text()
        with socket.socket() as http:
            assert http.connect_ex(("127.0.0.1", int(dual.port))) != 0
        assert dual.run("status").returncode == 3


def test_endpoint_exit_after_ready_stops_new_sibling(dual):
    prepare_fake_runtime(dual)
    with launch(dual) as (process, log):
        wait_for_ready(process, log)
        status = dual.run("status")
        assert status.returncode == 0
        https_pid = re.search(r"HTTPS is running \(PID ([0-9]+)\)", status.stdout)
        assert https_pid is not None, status.stdout
        os.kill(int(https_pid.group(1)), signal.SIGTERM)
        assert process.wait(timeout=15) != 0, log.read_text()
        assert dual.run("status").returncode == 3
        with socket.socket() as http, socket.socket() as https:
            assert http.connect_ex(("127.0.0.1", int(dual.port))) != 0
            assert (
                https.connect_ex(
                    (dual.env["LOVE_PINYIN_BIND_IP"], int(dual.env["LOVE_PINYIN_HTTPS_PORT"]))
                )
                != 0
            )


@pytest.mark.parametrize("existing_https", [False, True])
def test_start_repairs_missing_endpoint_preserves_existing_on_ctrl_c(dual, existing_https):
    prepare_fake_runtime(dual)
    with listener(dual, https=existing_https) as existing, launch(dual) as (process, log):
        wait_for_ready(process, log)
        assert dual.run("status").returncode == 0
        assert existing.poll() is None
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=15) == 130, log.read_text()
        assert existing.poll() is None
        assert dual.run("status").returncode == 3
        new_host = "127.0.0.1" if existing_https else dual.env["LOVE_PINYIN_BIND_IP"]
        new_port = dual.port if existing_https else dual.env["LOVE_PINYIN_HTTPS_PORT"]
        with socket.socket() as new_endpoint:
            assert new_endpoint.connect_ex((new_host, int(new_port))) != 0
