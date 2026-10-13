"""PDF-derived household reading content and pinned, same-origin demonstrations."""

import json
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from server import learning_audio, source_audio
from server.audio_assets import _verified_file, file_audio_response

CONTENT = Path(__file__).resolve().parents[1] / "content" / "daily-reading.json"


@lru_cache(maxsize=1)
def load() -> dict:
    data = json.loads(CONTENT.read_text())
    if data["version"] != 1 or [d["number"] for d in data["days"]] != list(range(1, 15)):
        raise ValueError("Invalid daily reading sequence")
    asset_ids = {a["id"] for a in data["assets"]}
    if len(asset_ids) != len(data["assets"]):
        raise ValueError("Duplicate daily audio")
    for a in data["assets"]:
        if (
            not re.fullmatch(r"daily-[a-z0-9]+", a["id"])
            or not re.fullmatch(r"[a-f0-9]{64}", a["sha256"])
            or Path(a["filename"]).name != a["filename"]
            or "\\" in a["filename"]
        ):
            raise ValueError("Invalid daily audio registration")
    ids = set()
    for day in data["days"]:
        for section in day["sections"]:
            for item in section["items"]:
                if (
                    item["id"] in ids
                    or not item["syllables"]
                    or unicodedata.normalize("NFC", item["display"]) != item["display"]
                    or not set(item["audioIds"]) <= asset_ids
                ):
                    raise ValueError("Invalid daily reading item")
                ids.add(item["id"])
    return data


def scripts() -> dict[str, str]:
    data = load()
    result = {f"daily-ui-{key}": text for key, text in data["ui"].items()}
    for day in data["days"]:
        for section in day["sections"]:
            result[f"daily-instruction-{section['id']}"] = section["instruction"]
            for item in section["items"]:
                if item["narrationId"]:
                    result[item["narrationId"]] = item["spokenText"]
    return result


def registered(asset_id: str) -> tuple[Path, str]:
    asset = next((a for a in load()["assets"] if a["id"] == asset_id), None)
    if asset is None or not source_audio.installed():
        raise HTTPException(404, detail={"code": "DAILY_AUDIO_NOT_FOUND"})
    root = source_audio.SOURCE_DIR.resolve()
    path = (root / "clips" / f"{asset['sha256']}.mp3").resolve()
    if root not in path.parents:
        raise HTTPException(404, detail={"code": "DAILY_AUDIO_NOT_FOUND"})
    return path, asset["sha256"]


def audio_response(asset_id: str, range_header: str | None = None):
    path, digest = registered(asset_id)
    response = file_audio_response(path, "audio/mpeg", digest, range_header)
    response.headers["Cache-Control"] = "no-store"
    return response


def status() -> dict:
    data = deepcopy(load())
    ready = set()
    for asset in data["assets"]:
        try:
            path, digest = registered(asset["id"])
            handle, size = _verified_file(path, digest)
            handle.close()
            if size:
                ready.add(asset["id"])
        except HTTPException:
            pass
    voices = learning_audio.expected_assets()
    manifest = learning_audio.read_manifest()
    for day in data["days"]:
        for section in day["sections"]:
            for item in section["items"]:
                if item["narrationId"]:
                    try:
                        asset_id = item["narrationId"]
                        path, _, digest = learning_audio.registered_file(
                            manifest.get(asset_id, {}), voices[asset_id]
                        )
                        handle, size = _verified_file(path, digest)
                        handle.close()
                        item["available"] = size > 0
                    except HTTPException:
                        item["available"] = False
                else:
                    item["available"] = (
                        not item["missingSyllables"] and set(item["audioIds"]) <= ready
                    )
    data.pop("assets")
    from server.reading_recognition import status as recognition_status

    data["assessment"] = recognition_status()
    return data
