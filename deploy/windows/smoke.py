"""Exercise the built bundle's own Python and HTTP server with disposable data."""

import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

bundle = Path("build/windows/app").resolve()
root = bundle / "app"
python = bundle / "python/python.exe"
subprocess.run([str(python), "-c", "import numpy; import pywhispercpp.model"], check=True)
with tempfile.TemporaryDirectory() as directory:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.update(LOVE_PINYIN_DATA_DIR=directory, LOVE_PINYIN_MODEL_PATH=f"{directory}/model.bin")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    log = tempfile.TemporaryFile()
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-proxy-headers",
        ],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=log,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Bundled server exited early")
            try:
                with opener.open(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as response:
                    assert response.status == 200
                with opener.open(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    assert b"<!doctype html>" in response.read().lower()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Bundled server did not start")
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.seek(0)
        print(log.read().decode("utf-8", errors="replace"))
        log.close()
print("Bundled Python, HTTP health and frontend passed.")
