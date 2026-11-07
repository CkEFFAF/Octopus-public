"""HTTP client for cloud Octop APIs used by the remote ACP adapter."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)


class CloudClient:
    def __init__(self, server: str, token: str, *, timeout: float = 60.0) -> None:
        self.server = server.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=self.server,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_thread(self, expert_id: str, *, title: str = "ACP remote") -> dict[str, Any]:
        del title  # API creates untitled dashboard threads; title kept for call-site clarity.
        r = await self._client.post(f"/api/agents/{expert_id}/threads")
        r.raise_for_status()
        return r.json()

    async def create_work_item(
        self,
        *,
        expert_id: str,
        origin_thread_id: str,
        title: str,
        instructions: str,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "command_id": command_id or new_ulid(),
            "agent_id": expert_id,
            "origin_thread_id": origin_thread_id,
            "title": title[:200] or "ACP task",
            "instructions": instructions,
            "schema_version": 1,
        }
        r = await self._client.post("/api/work-items", json=body)
        r.raise_for_status()
        return r.json()

    async def add_input(self, task_id: str, text: str, *, command_id: str) -> dict[str, Any]:
        r = await self._client.post(
            f"/api/work-items/{task_id}/inputs",
            json={"command_id": command_id, "text": text, "schema_version": 1},
        )
        if r.status_code == 409:
            return {"idempotent": True, **(r.json() if r.content else {})}
        r.raise_for_status()
        return r.json()

    async def progress(self, task_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/work-items/{task_id}/progress")
        r.raise_for_status()
        return r.json()

    async def cancel(self, task_id: str, *, command_id: str) -> dict[str, Any]:
        r = await self._client.post(
            f"/api/work-items/{task_id}/cancel",
            json={"command_id": command_id, "scope": "task", "schema_version": 1},
        )
        r.raise_for_status()
        return r.json()

    async def probe(self) -> None:
        r = await self._client.get("/api/health")
        r.raise_for_status()
