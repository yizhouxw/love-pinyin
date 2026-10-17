"""Compose the same-origin household API from feature routers."""

from fastapi import APIRouter

from server.routes import attempts, pairing, profiles, progress, resources, sessions
from server.routes.pairing import local_router as local_router

router = APIRouter(prefix="/api/v1")
for feature in (pairing, resources, profiles, sessions, attempts, progress):
    router.include_router(feature.router)
