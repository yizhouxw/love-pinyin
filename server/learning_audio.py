"""Private, pre-generated Chinese instructions and user-imported lesson recordings.

These resources never enter the reviewed standard-pinyin asset registry. No text
or file path supplied by a browser can trigger synthesis or select a disk file.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from server.audio_assets import _byte_range, _chunks, _verified_file
from server.content import load_writing

ROOT = Path(__file__).resolve().parents[1]
NARRATION_PATH = ROOT / "content" / "narration.json"
RECORDINGS_PATH = ROOT / "content" / "lesson-recordings.json"
LEARNING_AUDIO_DIR = (
    Path(os.environ.get("LOVE_PINYIN_LEARNING_AUDIO_DIR", ROOT / "private" / "learning-audio"))
    .expanduser()
    .resolve()
)
_ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff]")
_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg"}


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def narration_scripts() -> dict[str, str]:
    data = json.loads(NARRATION_PATH.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("unsupported narration version")
    scripts = {f"ui-{key}": value["text"] for key, value in data["ui"].items()}
    for question_id, item in data["exercises"].items():
        scripts[f"prompt-{question_id}"] = item["text"]
        scripts[f"hint-{question_id}"] = item["hint"]
        for option_id, text in item.get("options", {}).items():
            scripts[f"option-{question_id}-{option_id}"] = text
    writing = load_writing()
    scripts.update({f"writing-ui-{key}": text for key, text in writing["ui"].items()})
    for glyph_id, glyph in writing["glyphs"].items():
        scripts[f"writing-{glyph_id}-placement"] = glyph["description"]
        for i, stroke in enumerate(glyph["strokes"], 1):
            scripts[f"writing-{glyph_id}-stroke-{i}"] = stroke["instruction"]
    for mark_id, mark in writing.get("marks", {}).items():
        scripts[f"writing-{mark_id}"] = mark["stroke"]["instruction"]
    for targets in writing.get("lessons", {}).values():
        for target in targets:
            if "tone" in target:
                scripts[f"writing-{target['id']}-tone"] = target["note"]
    for asset_id, text in scripts.items():
        if not _ID.fullmatch(asset_id) or not isinstance(text, str) or not text.strip():
            raise ValueError(f"invalid narration script: {asset_id}")
        if _LATIN.search(text):
            raise ValueError(f"Latin/pinyin text is not permitted in narration: {asset_id}")
    return scripts


def lesson_recordings() -> dict[str, dict]:
    data = json.loads(RECORDINGS_PATH.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("unsupported lesson recording version")
    lessons = data["lessons"]
    for lesson_id, item in lessons.items():
        filename = item["file"]
        if (
            not _ID.fullmatch(lesson_id)
            or not isinstance(filename, str)
            or Path(filename).name != filename
            or "\\" in filename
            or Path(filename).suffix.lower() != ".mp3"
        ):
            raise ValueError(f"invalid lesson recording: {lesson_id}")
    return lessons


def expected_assets() -> dict[str, dict]:
    expected = {
        asset_id: {
            "sourceType": "macos-local-narration",
            "purpose": "chinese-instruction",
            "textSha256": text_digest(text),
        }
        for asset_id, text in narration_scripts().items()
    }
    for lesson_id, item in lesson_recordings().items():
        expected[f"lesson-{lesson_id}"] = {
            "sourceType": "user-provided-recording",
            "purpose": "whole-lesson-recording",
            "sourceFilename": item["file"],
        }
    return expected


def read_manifest() -> dict[str, dict]:
    try:
        path = LEARNING_AUDIO_DIR / "manifest.json"
        if path.stat().st_size > 4 * 1024 * 1024:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("assets"), list):
            return {}
        assets = data["assets"]
        if any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in assets
        ):
            return {}
        result = {item["id"]: item for item in assets}
        return result if len(result) == len(assets) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "LEARNING_AUDIO_NOT_FOUND"})


def registered_file(asset: dict, expected: dict) -> tuple[Path, str, str]:
    if any(asset.get(key) != value for key, value in expected.items()):
        raise _not_found()
    relative = asset.get("file")
    digest = asset.get("sha256")
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or Path(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
    ):
        raise _not_found()
    mime_type = _MIME.get(Path(relative).suffix.lower())
    if not mime_type:
        raise _not_found()
    if expected["sourceType"] == "macos-local-narration" and mime_type != "audio/wav":
        raise _not_found()
    if expected["sourceType"] == "user-provided-recording" and mime_type != "audio/mpeg":
        raise _not_found()
    root = LEARNING_AUDIO_DIR.resolve()
    try:
        path = (root / relative).resolve(strict=True)
        if root not in path.parents or not path.is_file():
            raise _not_found()
    except (OSError, RuntimeError):
        raise _not_found() from None
    return path, mime_type, digest


def available_assets() -> dict[str, bool]:
    manifest = read_manifest()
    result = {}
    for asset_id, expected in expected_assets().items():
        try:
            path, _, digest = registered_file(manifest.get(asset_id, {}), expected)
            handle, size = _verified_file(path, digest)
            handle.close()
            result[asset_id] = size > 0
        except HTTPException:
            result[asset_id] = False
    return result


def learning_audio_status() -> dict:
    available = available_assets()
    return {
        "narration": {asset_id: available[asset_id] for asset_id in narration_scripts()},
        "lessons": {
            lesson_id: {
                "audioId": f"lesson-{lesson_id}",
                "title": item["title"],
                "available": available[f"lesson-{lesson_id}"],
                "sourceType": "user-provided-recording",
            }
            for lesson_id, item in lesson_recordings().items()
        },
    }


def learning_audio_response(asset_id: str, range_header: str | None) -> Response:
    expected = expected_assets().get(asset_id)
    if not expected:
        raise _not_found()
    path, mime_type, digest = registered_file(read_manifest().get(asset_id, {}), expected)
    handle, size = _verified_file(path, digest)
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"sha256-{digest}"',
        "Content-Length": str(size),
    }
    if range_header is None:
        return StreamingResponse(_chunks(handle, size), media_type=mime_type, headers=headers)
    byte_range = _byte_range(range_header, size)
    if byte_range is None:
        handle.close()
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )
    start, end = byte_range
    handle.seek(start)
    headers["Content-Length"] = str(end - start + 1)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _chunks(handle, end - start + 1), status_code=206, media_type=mime_type, headers=headers
    )
