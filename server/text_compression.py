"""Compress text responses without transforming byte-addressed media."""

from pathlib import PurePosixPath

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


class TextCompressionMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1024, compresslevel=5)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        ranged = any(key.lower() == b"range" for key, _ in scope.get("headers", []))
        media = any(part in path.split("/") for part in ("voice", "audio", "daily-audio"))
        text = path.startswith("/api/") or (
            path.startswith("/assets/") and PurePosixPath(path).suffix in {".js", ".css"}
        )
        app = (
            self.compressed
            if scope["type"] == "http" and text and not ranged and not media
            else self.app
        )
        await app(scope, receive, send)
