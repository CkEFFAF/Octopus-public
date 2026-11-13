"""Thin HTTP adapters for an expert owner's persistent file bookmarks."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from octop.api.deps import current_user, get_server
from octop.infra.agents.pinned_files import PinnedFiles, PinnedFilesService

router = APIRouter()


@router.get(
    "/agents/{agent_id}/pinned-files",
    summary="List an expert owner's pinned files",
    description="Persistent across conversations. Shared-expert access does not grant access to these bookmarks.",
    response_model=PinnedFiles,
)
async def get_pinned_files(
    agent_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> PinnedFiles:
    service = PinnedFilesService(server.app_runtime.agent_registry, server.services.settings_repo)
    return await asyncio.get_running_loop().run_in_executor(
        None, service.get, agent_id, int(user.id), bool(user.is_admin)
    )


@router.put(
    "/agents/{agent_id}/pinned-files",
    summary="Replace an expert owner's pinned files",
    description="Uses the loaded revision to reject concurrent edits. Bookmarks do not grant file or device access.",
    response_model=PinnedFiles,
)
async def put_pinned_files(
    agent_id: str,
    body: PinnedFiles,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> PinnedFiles:
    service = PinnedFilesService(server.app_runtime.agent_registry, server.services.settings_repo)
    return await asyncio.get_running_loop().run_in_executor(
        None, service.save, agent_id, int(user.id), bool(user.is_admin), body
    )
