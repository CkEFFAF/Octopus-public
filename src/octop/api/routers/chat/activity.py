"""Owner-authorized factual activity projection."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query

from octop.api.deps import current_user, get_server
from octop.infra.execution.activity import ActivityService

router = APIRouter()


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/activity",
    summary="Inspect current task, subagent and job observations",
)
async def activity(
    agent_id: str,
    thread_id: str,
    before: int | None = Query(None, ge=1),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await asyncio.to_thread(
        ActivityService(server.app_runtime.agent_registry).snapshot,
        int(user.id),
        agent_id,
        thread_id,
        before,
    )
