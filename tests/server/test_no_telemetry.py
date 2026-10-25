"""Dependency upgrades must preserve local-only operation despite host OTEL settings."""

import os
import subprocess
import sys
from pathlib import Path


def test_host_telemetry_settings_cannot_enable_export_or_collect_requests(tmp_path):
    script = """
import logging
import socket
import sys

from opentelemetry import _logs, metrics, trace

def forbidden(*args, **kwargs):
    raise AssertionError("Local learning must not use telemetry or network connections")

socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
trace.get_tracer_provider = forbidden
metrics.get_meter_provider = forbidden
_logs.get_logger_provider = forbidden

from fastapi.testclient import TestClient
from server.main import app

class NoTelemetryWarnings(logging.Handler):
    def emit(self, record):
        if "telemetry" in record.getMessage().lower():
            raise AssertionError(record.getMessage())

logging.getLogger("fastapi").addHandler(NoTelemetryWarnings())
with TestClient(app, base_url="http://127.0.0.1") as client:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["storage"] == "sqlite"

assert not any(
    name.startswith(("opentelemetry.sdk", "opentelemetry.exporter"))
    for name in sys.modules
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "LOVE_PINYIN_DATA_DIR": str(tmp_path / "data"),
            "FASTAPI_OTEL_AUTO_CONFIGURE": "true",
            "OTEL_SDK_DISABLED": "false",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://telemetry.invalid",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_LOGS_EXPORTER": "otlp",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
