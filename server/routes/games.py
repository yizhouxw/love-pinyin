"""Household game budget and learning evidence."""

from fastapi import APIRouter, Depends, HTTPException

from server.api_dependencies import mutable, paired
from server.game_service import clock_status, game_report
from server.storage import connect, transaction

router = APIRouter()


@router.get("/games")
def games(device: dict = Depends(paired)) -> dict:
    with connect() as db:
        return {
            "clock": clock_status(db, device["household_id"]),
            "report": game_report(db, device["household_id"]),
        }


@router.post("/games/{action}")
def game_clock(action: str, device: dict = Depends(mutable)) -> dict:
    if action not in {"heartbeat", "pause"}:
        raise HTTPException(404, detail={"code": "GAME_ACTION_INVALID"})
    with transaction() as db:
        return clock_status(db, device["household_id"], action)
