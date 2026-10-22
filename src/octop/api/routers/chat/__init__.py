"""Dashboard chat routers — WebSocket turns, thread CRUD, polish, HITL."""

from __future__ import annotations

from fastapi import APIRouter

from octop.api.routers.chat.activity import router as activity_router
from octop.api.routers.chat.annotations import router as annotations_router
from octop.api.routers.chat.collaboration import router as collaboration_router
from octop.api.routers.chat.file_sources import router as file_sources_router
from octop.api.routers.chat.history import router as history_router
from octop.api.routers.chat.inputs import router as inputs_router
from octop.api.routers.chat.inspection import router as inspection_router
from octop.api.routers.chat.metadata import router as metadata_router
from octop.api.routers.chat.notify_ws import router as notify_ws_router
from octop.api.routers.chat.routes import router as routes_router
from octop.api.routers.chat.shares import router as shares_router
from octop.api.routers.chat.trajectory import router as trajectory_router
from octop.api.routers.chat.ws import router as ws_router

router = APIRouter()
router.include_router(collaboration_router)
router.include_router(annotations_router)
router.include_router(activity_router)
router.include_router(file_sources_router)
router.include_router(shares_router)
router.include_router(routes_router)
router.include_router(history_router)
router.include_router(inspection_router)
router.include_router(inputs_router)
router.include_router(metadata_router)
router.include_router(trajectory_router)
router.include_router(ws_router)
router.include_router(notify_ws_router)

__all__ = ["router"]
