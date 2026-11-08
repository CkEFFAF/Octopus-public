"""Managed stream adapter for the embedded stdio ACP server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from octop.infra.conversations.activity import record_user_request
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager


class ManagedACPStream:
    def __init__(self, manager: AgentManager, agent_id: str) -> None:
        self.manager = manager
        self.agent_id = agent_id

    def _owned_request(self, request: dict[str, Any]) -> dict[str, Any]:
        row = self.manager.get_row(self.agent_id)
        if row is None or row.user_id is None:
            raise OctopError(ErrorCode.NOT_FOUND, "ACP expert unavailable")
        thread_id = str(request.get("thread_id") or "").strip()
        if not thread_id or len(thread_id) > 200:
            raise OctopError(ErrorCode.NOT_FOUND, "ACP session unavailable")
        threads = self.manager._repos.thread_repo
        existing = threads.get(thread_id)
        if existing is None:
            threads.insert(
                thread_id=thread_id,
                agent_id=self.agent_id,
                user_id=row.user_id,
                channel_type="acp",
                session_key=f"acp:{self.agent_id}:{thread_id}",
                last_active=0,
            )
        elif existing.user_id != row.user_id or existing.agent_id != self.agent_id:
            raise OctopError(ErrorCode.NOT_FOUND, "ACP session unavailable")
        return {**request, "thread_id": thread_id, "user": str(row.user_id)}

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[Any]:
        owned = await asyncio.to_thread(self._owned_request, request)
        await asyncio.to_thread(
            record_user_request,
            self.manager._repos,
            int(owned["user"]),
            self.agent_id,
            str(owned["thread_id"]),
            owned,
        )
        async for chunk in self.manager.stream(self.agent_id, owned):
            yield chunk
