"""Infrastructure baseline only. Assessment stays unavailable until SPEC-000 passes."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Love Pinyin Local API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": "planning-baseline", "version": "0.1.0"}


@app.get("/api/v1/capabilities")
def capabilities() -> dict:
    return {
        "assessment": {"available": False, "reason": "pending-local-poc"},
        "audio": {"available": False, "reason": "pending-recording-and-review"},
        "externalAudioTransfer": False,
    }


@app.post("/api/v1/assessments")
def assessment_unavailable() -> JSONResponse:
    # Deliberately do not parse/store audio or manufacture a score in this phase.
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "ASSESSMENT_NOT_READY", "retryable": False}},
        headers={"Cache-Control": "no-store"},
    )


dist = Path(__file__).resolve().parents[1] / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
