"""Single-process B/S application for the private Mac Studio server."""

import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.api import local_router, router
from server.content import load_curriculum
from server.guest import router as guest_router
from server.storage import ensure_household, migrate
from server.text_compression import TextCompressionMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    ensure_household(load_curriculum()["contentVersion"])
    yield


app = FastAPI(
    title="Love Pinyin local API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    telemetry={
        "tracing": False,
        "metrics": False,
        "logs": False,
        "operation_spans": False,
        "auto_configure": False,
    },
)


app.add_middleware(TextCompressionMiddleware)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    path = request.url.path
    if response.status_code == 200 and re.fullmatch(
        r"/assets/[^/]+-[A-Za-z0-9_-]{8,}\.(?:js|css)", path
    ):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif (
        response.status_code in {200, 304}
        and path.startswith("/fonts/")
        and response.headers.get("Content-Type", "").startswith("font/")
    ):
        response.headers["Cache-Control"] = "public, max-age=86400"
    else:
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(local_router)
app.include_router(guest_router)
app.include_router(router)

DIST = Path(__file__).resolve().parents[1] / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str):
        candidate = DIST / path
        if path and candidate.is_file() and DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
