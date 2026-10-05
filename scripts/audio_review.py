"""Loopback-only authoring workbench for user-provided course recordings."""

import argparse
import csv
import hashlib
import io
import ipaddress
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import wave
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from server import private_standard_audio as standard
from server.audio_assets import _verified_file, file_audio_response
from server.content import load_curriculum
from server.learning_audio import lesson_recordings

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = ROOT / "private" / "audio-review"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value: dict) -> None:
    write_private(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def read_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.exists() else default


def import_sources(source: Path, candidates: Path, work: Path) -> dict:
    source = source.resolve(strict=True)
    candidates = candidates.resolve(strict=True)
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous = {
        row["file"]: row for row in read_json(work / "catalog.json", {"sources": []})["sources"]
    }
    sources = []
    for filename in dict.fromkeys(item["file"] for item in lesson_recordings().values()):
        original = (source / filename).resolve(strict=True)
        if source not in original.parents:
            raise ValueError("source must stay inside the explicitly selected directory")
        source_hash = digest(original)
        relative = f"sources/{source_hash}.wav"
        target = work / relative
        if not target.exists() or digest(target) != previous.get(relative, {}).get("sha256"):
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(suffix=".wav", dir=target.parent)
            os.close(fd)
            try:
                subprocess.run(
                    [
                        "/usr/bin/afconvert",
                        "-f",
                        "WAVE",
                        "-d",
                        "LEI16@16000",
                        "-c",
                        "1",
                        str(original),
                        temporary,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        with wave.open(str(target), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        sources.append(
            {
                "id": source_hash[:16],
                "name": filename,
                "sourceSha256": source_hash,
                "file": relative,
                "sha256": digest(target),
                "duration": duration,
            }
        )
    by_name = {row["name"]: row for row in sources}
    transcripts = {}
    transcript_file = candidates / "asr-transcripts.csv"
    if transcript_file.is_file():
        with transcript_file.open(encoding="utf-8-sig", newline="") as handle:
            transcripts = {row["candidate_id"]: row for row in csv.DictReader(handle)}
    rows = []
    with (candidates / "candidate-index.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            origin = by_name.get(row["source_file"])
            if not origin or row["source_sha256"] != origin["sourceSha256"]:
                raise ValueError(
                    f"candidate source does not match imported recording: {row['candidate_id']}"
                )
            start, end = float(row["start_seconds"]), float(row["end_seconds"])
            if not 0 <= start < end <= origin["duration"]:
                raise ValueError("candidate has invalid source boundaries")
            transcript = transcripts.get(row["candidate_id"], {})
            text = (
                transcript.get("transcript_draft", "")
                if transcript.get("clip_sha256") == row["clip_sha256"]
                else ""
            )
            rows.append(
                {
                    "id": row["candidate_id"],
                    "sourceId": origin["id"],
                    "start": start,
                    "end": end,
                    "transcriptDraft": text,
                }
            )
    catalog = {"version": 1, "sources": sources, "candidates": rows}
    write_json(work / "catalog.json", catalog)
    return catalog


class Clip(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sourceId: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class Draft(Clip):
    targetId: str
    expectedRevision: str | None = None


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targetId: str
    sha256: str
    revision: str
    teachingReviewer: str = Field(min_length=1, max_length=100)
    qualityReviewer: str = Field(min_length=1, max_length=100)
    targetAndPronunciationConfirmed: bool
    qualityAndBoundariesConfirmed: bool
    privateUseOnly: bool


class Remove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targetId: str
    sha256: str


def create_app(work: Path = DEFAULT_WORK) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    app.state.review_token = token
    work = work.resolve()

    @app.middleware("http")
    async def protect(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        try:
            local = bool(request.client) and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if (
            not local
            or not re.fullmatch(r"127\.0\.0\.1(?::\d+)?", host)
            or (origin is not None and origin != f"http://{host}")
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return Response("Local authoring access only", status_code=403)
        if request.method != "GET" and request.headers.get("x-review-token") != token:
            return Response("Missing authoring token", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; media-src 'self' blob:; frame-ancestors 'none'"
        )
        return response

    def catalog():
        return read_json(work / "catalog.json", {"version": 1, "sources": [], "candidates": []})

    def target(target_id):
        matches = [
            a
            for a in load_curriculum()["audioRequirements"]
            if a["id"] == target_id and a["kind"] != "instruction"
        ]
        if len(matches) != 1:
            raise HTTPException(404, "unknown standard-audio target")
        return matches[0]

    def source(source_id):
        matches = [row for row in catalog()["sources"] if row["id"] == source_id]
        if len(matches) != 1:
            raise HTTPException(404, "unknown recording")
        row = matches[0]
        try:
            path = (work / row["file"]).resolve(strict=True)
        except (OSError, RuntimeError):
            raise HTTPException(404, "recording missing") from None
        if (work / "sources").resolve() not in path.parents:
            raise HTTPException(404, "invalid recording path")
        return row, path

    def clip_bytes(body: Clip):
        row, path = source(body.sourceId)
        if not 0.1 <= body.end - body.start <= 20 or body.end > row["duration"]:
            raise HTTPException(
                422, "Choose a complete 0.1–20 second segment inside this recording"
            )
        verified, _ = _verified_file(path, row["sha256"])
        with verified, wave.open(verified, "rb") as original:
            first = round(body.start * original.getframerate())
            last = round(body.end * original.getframerate())
            if last > original.getnframes():
                raise HTTPException(422, "segment outside recording")
            original.setpos(first)
            data = original.readframes(last - first)
            out = io.BytesIO()
            with wave.open(out, "wb") as clipped:
                clipped.setparams(original.getparams())
                clipped.writeframes(data)
        return out.getvalue(), row

    @app.get("/")
    def index():
        html = (ROOT / "tools/audio-review/index.html").read_text()
        return HTMLResponse(html.replace("__TOKEN__", token))

    @app.get("/review.js")
    def script():
        return Response(
            (ROOT / "tools/audio-review/review.js").read_text(), media_type="text/javascript"
        )

    @app.get("/review.css")
    def css():
        return Response((ROOT / "tools/audio-review/review.css").read_text(), media_type="text/css")

    @app.get("/api/catalog")
    def get_catalog():
        data = catalog()
        data["drafts"] = read_json(work / "drafts.json", {})
        active = standard.read_assets()
        data["targets"] = [
            {
                "id": a["id"],
                "label": a["transcript"],
                "kind": a["kind"],
                "available": standard.available(a),
                "activeSha256": active.get(a["id"], {}).get("sha256"),
            }
            for a in load_curriculum()["audioRequirements"]
            if a["kind"] != "instruction"
        ]
        return data

    @app.get("/api/source/{source_id}")
    def get_source(source_id: str, request: Request):
        row, path = source(source_id)
        return file_audio_response(path, "audio/wav", row["sha256"], request.headers.get("range"))

    @app.post("/api/preview")
    def preview(body: Clip):
        data, _ = clip_bytes(body)
        return Response(data, media_type="audio/wav")

    @app.post("/api/draft")
    def save_draft(body: Draft):
        wanted = target(body.targetId)
        data, origin = clip_bytes(body)
        sha = hashlib.sha256(data).hexdigest()
        with lock:
            drafts = read_json(work / "drafts.json", {})
            current = drafts.get(body.targetId)
            if body.expectedRevision != (current["revision"] if current else None):
                raise HTTPException(409, "Draft changed; reload before saving")
            row = {
                "id": body.targetId,
                "targetSignature": standard.target_signature(wanted),
                "file": f"clips/{sha}.wav",
                "sha256": sha,
                "sourceId": body.sourceId,
                "sourceFilename": origin["name"],
                "sourceSha256": origin["sourceSha256"],
                "start": body.start,
                "end": body.end,
            }
            row["revision"] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            write_private(work / row["file"], data)
            drafts[body.targetId] = row
            write_json(work / "drafts.json", drafts)
        return row

    @app.post("/api/activate")
    def activate(body: Confirm):
        wanted = target(body.targetId)
        teaching, quality = body.teachingReviewer.strip(), body.qualityReviewer.strip()
        if (
            not teaching
            or not quality
            or teaching.casefold() == quality.casefold()
            or not body.targetAndPronunciationConfirmed
            or not body.qualityAndBoundariesConfirmed
            or not body.privateUseOnly
        ):
            raise HTTPException(422, "Two distinct reviewers and all confirmations are required")
        with lock:
            draft = read_json(work / "drafts.json", {}).get(body.targetId)
            if (
                not draft
                or draft["sha256"] != body.sha256
                or draft["revision"] != body.revision
                or draft["targetSignature"] != standard.target_signature(wanted)
            ):
                raise HTTPException(409, "Draft or target changed; listen and confirm again")
            path = (work / draft["file"]).resolve(strict=True)
            if (work / "clips").resolve() not in path.parents:
                raise HTTPException(404, "invalid clip path")
            handle, _ = _verified_file(path, draft["sha256"])
            with handle:
                write_private(standard.STANDARD_DIR / draft["file"], handle.read())
            at = datetime.now(UTC).isoformat()
            asset = {
                **draft,
                "usage": "private-household",
                "distribution": "not-for-redistribution",
                "reviews": [
                    {"role": "teaching", "reviewer": teaching, "at": at, "confirmed": True},
                    {"role": "quality", "reviewer": quality, "at": at, "confirmed": True},
                ],
            }
            assets = standard.read_assets()
            assets[body.targetId] = asset
            write_json(
                standard.STANDARD_DIR / "manifest.json",
                {"version": 1, "assets": list(assets.values())},
            )
        return {"available": True}

    @app.post("/api/deactivate")
    def deactivate(body: Remove):
        with lock:
            assets = standard.read_assets()
            if assets.get(body.targetId, {}).get("sha256") != body.sha256:
                raise HTTPException(409, "Active clip changed; reload before removing")
            del assets[body.targetId]
            write_json(
                standard.STANDARD_DIR / "manifest.json",
                {"version": 1, "assets": list(assets.values())},
            )
        return {"available": False}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--port", type=int, default=8019)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if bool(args.source) != bool(args.candidates):
        parser.error("--source and --candidates must be supplied together")
    if args.source:
        data = import_sources(args.source, args.candidates, args.work)
        print(
            f"Imported {len(data['sources'])} recordings and "
            f"{len(data['candidates'])} candidates; none approved."
        )
    if not args.prepare_only:
        uvicorn.run(
            create_app(args.work),
            host="127.0.0.1",
            port=args.port,
            proxy_headers=False,
            access_log=False,
        )


if __name__ == "__main__":
    main()
