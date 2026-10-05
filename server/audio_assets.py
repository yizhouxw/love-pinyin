"""Serve only approved, integrity-checked audio assets from the content package."""

import hashlib
import hmac
import re
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

PUBLIC_AUDIO_DIR = Path(__file__).resolve().parents[1] / "public" / "audio"
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_MIME_TYPES = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})


def _registered_path(asset: dict) -> tuple[Path, str, str]:
    if (
        asset.get("status") != "approved"
        or asset.get("reviewStatus") != "approved"
        or not asset.get("rightsEvidence")
        or not asset.get("reviewEvidence")
    ):
        raise _not_found()

    relative = asset.get("file")
    if not isinstance(relative, str) or "\\" in relative:
        raise _not_found()
    normalized = relative.lstrip("/")
    components = Path(normalized).parts
    if (
        not components
        or components[0] != "audio"
        or any(part in {"", ".", ".."} for part in components)
    ):
        raise _not_found()
    mime_type = _MIME_TYPES.get(Path(normalized).suffix.lower())
    digest = asset.get("sha256")
    if not mime_type or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise _not_found()

    root = PUBLIC_AUDIO_DIR.resolve()
    try:
        path = (root / Path(*components[1:])).resolve(strict=True)
        if root not in path.parents or not path.is_file():
            raise _not_found()
    except (OSError, RuntimeError):
        raise _not_found() from None
    return path, mime_type, digest


def _verified_file(path: Path, expected_digest: str) -> tuple[BinaryIO, int]:
    audio: BinaryIO | None = None
    try:
        audio = path.open("rb")
        size = audio.seek(0, 2)
        audio.seek(0)
        digest = hashlib.sha256()
        while chunk := audio.read(64 * 1024):
            digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), expected_digest):
            audio.close()
            raise _not_found()
        audio.seek(0)
        return audio, size
    except HTTPException:
        if audio is not None:
            audio.close()
        raise
    except OSError:
        if audio is not None:
            audio.close()
        raise _not_found() from None


def _byte_range(value: str, size: int) -> tuple[int, int] | None:
    if len(value) > 200:
        return None
    match = _RANGE.fullmatch(value.strip())
    if not match:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:
        suffix_length = int(last)
        if suffix_length <= 0:
            return None
        start = max(0, size - suffix_length)
        end = size - 1
    else:
        start = int(first)
        end = int(last) if last else size - 1
    if size == 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _chunks(audio: BinaryIO, length: int) -> Iterator[bytes]:
    remaining = length
    try:
        while remaining:
            chunk = audio.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        audio.close()


def audio_response(asset_id: str, requirements: list[dict], range_header: str | None) -> Response:
    matches = [asset for asset in requirements if asset.get("id") == asset_id]
    if len(matches) != 1:
        raise _not_found()
    path, mime_type, digest = _registered_path(matches[0])
    return file_audio_response(path, mime_type, digest, range_header)


def file_audio_response(
    path: Path, mime_type: str, digest: str, range_header: str | None
) -> Response:
    """Internal helper; callers must resolve a registered, permitted asset first."""
    audio, size = _verified_file(path, digest)
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"sha256-{digest}"',
        "Content-Length": str(size),
    }
    if range_header is None:
        return StreamingResponse(_chunks(audio, size), media_type=mime_type, headers=headers)

    byte_range = _byte_range(range_header, size)
    if byte_range is None:
        audio.close()
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )
    start, end = byte_range
    audio.seek(start)
    headers["Content-Length"] = str(end - start + 1)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _chunks(audio, end - start + 1),
        status_code=206,
        media_type=mime_type,
        headers=headers,
    )
