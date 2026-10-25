"""Versioned, authored routes, independent from questions and physical runtime."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Scene = Literal["runner", "boat", "drum", "space"]


class Data(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Obstacle(Data):
    id: str = Field(min_length=1, max_length=50)
    at: float = Field(ge=60, le=1800)
    lane: int = Field(ge=-1, le=3)
    kind: Literal["root", "bush", "reef", "asteroid"]
    size: float = Field(ge=20, le=60)


class Pickup(Data):
    id: str = Field(min_length=1, max_length=50)
    at: float = Field(ge=20, le=1800)
    lane: int = Field(ge=0, le=3)


class Pattern(Data):
    id: str = Field(min_length=1, max_length=60)
    scene: Scene
    length: float = Field(ge=400, le=1800)
    choiceAt: float = Field(ge=300, le=1800)
    choiceGap: float = Field(ge=100, le=220)
    currentStrength: float = Field(ge=0, le=40)
    travelScale: float = Field(ge=0.7, le=1.5)
    obstacles: list[Obstacle] = Field(max_length=12)
    pickups: list[Pickup] = Field(max_length=12)
    beats: list[float] = Field(max_length=24)

    @model_validator(mode="after")
    def route_bounds(self):
        if self.choiceAt > self.length or len({o.id for o in self.obstacles}) != len(
            self.obstacles
        ):
            raise ValueError("obstacle IDs or choice outside route")
        if len({p.id for p in self.pickups}) != len(self.pickups):
            raise ValueError("duplicate pickups")
        kinds = {"runner": {"root", "bush"}, "boat": {"reef"}, "space": {"asteroid"}, "drum": set()}
        if any(
            o.kind not in kinds[self.scene] or o.at >= self.choiceAt - 40 for o in self.obstacles
        ):
            raise ValueError("unsafe obstacle layout")
        if any(p.at >= self.choiceAt for p in self.pickups):
            raise ValueError("pickup after target")
        if self.beats != sorted(set(self.beats)) or any(
            not 0 < t < self.choiceAt for t in self.beats
        ):
            raise ValueError("beat order/bounds")
        if self.scene == "drum" and self.choiceAt + 3 * self.choiceGap > self.length:
            raise ValueError("four option notes must fit chart")
        return self


class Theme(Data):
    id: str = Field(min_length=1, max_length=60)
    sky: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    horizon: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    land: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class Segment(Data):
    id: str = Field(min_length=1, max_length=50)
    patternId: str = Field(min_length=1, max_length=60)


class Chapter(Data):
    id: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=40)
    segments: list[Segment] = Field(min_length=4, max_length=4)


class Level(Data):
    id: str = Field(min_length=1, max_length=60)
    gameId: Literal["sound", "tone", "shape", "blend"]
    scene: Scene
    number: int = Field(ge=1, le=6)
    title: str = Field(min_length=1, max_length=40)
    subtitle: str = Field(min_length=1, max_length=100)
    voiceId: str = Field(pattern=r"^ui-level_[a-z]+_[0-9]{2}$")
    recommendedDifficulty: Literal["gentle", "steady", "challenge"]
    themeId: str = Field(min_length=1, max_length=60)
    chapters: list[Chapter] = Field(min_length=3, max_length=3)


class Binding(Data):
    segmentId: str
    instanceId: str


class Run(Data):
    version: Literal[1]
    catalogVersion: Literal[1]
    level: Level
    patterns: dict[str, Pattern] = Field(min_length=1, max_length=12)
    theme: Theme
    bindings: list[Binding] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def references(self):
        segments = [s for c in self.level.chapters for s in c.segments]
        if self.level.themeId != self.theme.id:
            raise ValueError("theme reference")
        if len({c.id for c in self.level.chapters}) != 3 or len({s.id for s in segments}) != 12:
            raise ValueError("duplicate chapter/segment IDs")
        if [b.segmentId for b in self.bindings] != [s.id for s in segments]:
            raise ValueError("binding order")
        if len({b.instanceId for b in self.bindings}) != 12:
            raise ValueError("duplicate bound instance")
        if set(self.patterns) != {s.patternId for s in segments}:
            raise ValueError("pattern references")
        if any(k != p.id or p.scene != self.level.scene for k, p in self.patterns.items()):
            raise ValueError("pattern scene")
        if (
            self.level.scene
            != {"sound": "runner", "tone": "boat", "shape": "drum", "blend": "space"}[
                self.level.gameId
            ]
        ):
            raise ValueError("game scene")
        return self


CATALOG_PATH = Path(__file__).resolve().parents[1] / "content/game-levels.json"


def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def level_for(game_id: str, level_id: str | None, difficulty: str) -> dict:
    levels = [item for item in catalog()["levels"] if item["gameId"] == game_id]
    if level_id is not None:
        selected = next((item for item in levels if item["id"] == level_id), None)
        if selected is None:
            raise ValueError("GAME_LEVEL_NOT_FOUND")
        return selected
    return next(item for item in levels if item["recommendedDifficulty"] == difficulty)


def freeze_run(level: dict, tasks: list[dict]) -> dict:
    source = catalog()
    segments = [segment for chapter in level["chapters"] for segment in chapter["segments"]]
    value = {
        "version": 1,
        "catalogVersion": source["version"],
        "level": level,
        "patterns": {s["patternId"]: source["patterns"][s["patternId"]] for s in segments},
        "theme": source["themes"][level["themeId"]],
        "bindings": [
            {"segmentId": s["id"], "instanceId": t["instanceId"]}
            for s, t in zip(segments, tasks, strict=True)
        ],
    }
    return Run.model_validate(value).model_dump()


def valid_run(value: object, game_id: str | None, instances: list[str] | None = None) -> bool:
    if value == {}:
        return True
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or type(value.get("catalogVersion")) is not int
    ):
        return False
    try:
        run = Run.model_validate(value)
        return run.level.gameId == game_id and (
            instances is None or [b.instanceId for b in run.bindings] == instances
        )
    except (ValidationError, ValueError, TypeError):
        return False


def validate_catalog() -> dict:
    source = catalog()
    if set(source) != {"version", "themes", "patterns", "levels"} or source["version"] != 1:
        raise ValueError("catalog version/fields")
    if len(source["levels"]) != 24 or len({level["id"] for level in source["levels"]}) != 24:
        raise ValueError("24 unique levels required")
    for game in ("sound", "tone", "shape", "blend"):
        if sorted(level["number"] for level in source["levels"] if level["gameId"] == game) != list(
            range(1, 7)
        ):
            raise ValueError("six levels per game")
    for level in source["levels"]:
        freeze_run(level, [{"instanceId": f"check-{i}"} for i in range(12)])
    # Validate even unused patterns/themes so dead data cannot hide a broken route.
    for key, value in source["patterns"].items():
        if Pattern.model_validate(value).id != key:
            raise ValueError("pattern ID")
    for key, value in source["themes"].items():
        if Theme.model_validate(value).id != key:
            raise ValueError("theme ID")
    return {"levels": 24, "chapters": 72, "slots": 288, "patterns": len(source["patterns"])}
