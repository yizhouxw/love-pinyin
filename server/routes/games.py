"""Household game budget and learning evidence."""

from fastapi import APIRouter, Depends, HTTPException

from server.api_dependencies import mutable, paired
from server.content import load_curriculum
from server.game_adaptation import recommend
from server.game_service import clock_status, game_report
from server.learning_state import _mastery
from server.storage import connect, transaction

router = APIRouter()


@router.get("/games")
def games(device: dict = Depends(paired)) -> dict:
    with connect() as db:
        content = load_curriculum()
        order = next(
            (
                lesson["order"]
                for lesson in content["lessons"]
                if lesson["id"] == device["selected_lesson_id"]
            ),
            0,
        )
        allowed = {
            k["id"]
            for k in content["knowledgeItems"]
            if any(
                lesson["id"] == k["lessonId"] and lesson["order"] <= order
                for lesson in content["lessons"]
            )
        }
        mastery = {
            key: item
            for key, item in _mastery(db, device["household_id"]).items()
            if key in allowed
        }
        return {
            "recommendation": recommend(mastery),
            "clock": clock_status(db, device["household_id"]),
            "report": game_report(db, device["household_id"]),
        }


@router.post("/games/{action}")
def game_clock(action: str, device: dict = Depends(mutable)) -> dict:
    if action not in {"heartbeat", "pause"}:
        raise HTTPException(404, detail={"code": "GAME_ACTION_INVALID"})
    with transaction() as db:
        return clock_status(db, device["household_id"], action)
