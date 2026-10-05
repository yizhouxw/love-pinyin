"""Integrity-checked local audio streaming and byte ranges."""

import hashlib
import hmac
import re
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "AUDIO_NOT_FOUND"})


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
