"""Exercise the built bundle's own Python and HTTP server with disposable data."""

import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

bundle = Path("build/macos/爱拼音.app/Contents/Resources").resolve()
root = bundle / "app"
python = bundle / "python/bin/python3"
assert not list(root.rglob("*.safetensors"))
subprocess.run(
    [str(python), "-c", "from server.qwen_recognition import supported; assert supported()"],
    cwd=root,
    check=True,
)
with tempfile.TemporaryDirectory() as directory:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update(LOVE_PINYIN_DATA_DIR=directory)
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
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode())
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/v1/health", timeout=1
                ) as response:
                    assert response.status == 200
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    assert b"<!doctype html>" in response.read().lower()
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/v1/shop-recognition", timeout=1
                ) as response:
                    assert b'"available":false' in response.read()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Bundled server did not start")
    finally:
        process.terminate()
        process.wait(timeout=10)
print("Bundled Python, HTTP health and frontend passed.")
