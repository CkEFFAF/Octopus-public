"""HTTP client for cloud Octop APIs used by the remote ACP adapter."""

from __future__ import annotations

import ipaddress
from typing import Any, cast
from urllib.parse import quote, urlsplit

import httpx

from octop.i18n import tr
from octop.infra.utils.locale import DEFAULT_LOCALE, normalize_locale
from octop.infra.utils.ulid import new_ulid


class CloudClient:
    def __init__(self, server: str, token: str, *, timeout: float = 60.0) -> None:
        parts = urlsplit(server)
        host = parts.hostname or ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"
        if (
            parts.scheme not in {"https", "http"}
            or not host
            or (parts.scheme == "http" and not loopback)
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError(tr("acp_remote.https_required", DEFAULT_LOCALE))
        self.server = server.rstrip("/")
        self.locale = DEFAULT_LOCALE
        self._client = httpx.AsyncClient(
            base_url=self.server,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_thread(self, expert_id: str, *, title: str = "ACP remote") -> dict[str, Any]:
        del title  # API creates untitled dashboard threads; title kept for call-site clarity.
        r = await self._client.post(f"/api/agents/{quote(expert_id, safe='')}/threads")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

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
        return cast(dict[str, Any], r.json())

    async def add_input(self, task_id: str, text: str, *, command_id: str) -> dict[str, Any]:
        r = await self._client.post(
            f"/api/work-items/{quote(task_id, safe='')}/inputs",
            json={"command_id": command_id, "text": text, "schema_version": 1},
        )
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    async def progress(self, task_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/work-items/{quote(task_id, safe='')}/progress")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    async def cancel(self, task_id: str, *, command_id: str) -> dict[str, Any]:
        r = await self._client.post(
            f"/api/work-items/{quote(task_id, safe='')}/cancel",
            json={"command_id": command_id, "scope": "task", "schema_version": 1},
        )
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    async def probe(self) -> None:
        await self.identity()

    async def identity(self) -> dict[str, Any]:
        r = await self._client.get("/api/auth/agent-access-keys/identity")
        r.raise_for_status()
        payload = cast(dict[str, Any], r.json())
        self.locale = normalize_locale(payload.get("locale"))
        return payload

    async def detail(self, task_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/work-items/{quote(task_id, safe='')}")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    async def lookup_command(self, command_id: str) -> dict[str, Any] | None:
        r = await self._client.get(
            "/api/work-items", params={"command_id": command_id, "status_group": "all"}
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        return cast(dict[str, Any], items[0]) if items else None

    async def history(self, expert_id: str, thread_id: str) -> dict[str, Any]:
        r = await self._client.get(
            f"/api/agents/{quote(expert_id, safe='')}/threads/{quote(thread_id, safe='')}/history",
            params={"limit": 100},
        )
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    async def input_receipt(self, task_id: str, command_id: str) -> dict[str, Any] | None:
        r = await self._client.get(
            f"/api/work-items/{quote(task_id, safe='')}/inputs", params={"command_id": command_id}
        )
        r.raise_for_status()
        return cast(dict[str, Any] | None, r.json()["receipt"])

    async def permission(
        self,
        task_id: str,
        *,
        pending_id: str,
        attempt_id: str,
        decisions: list[str],
        command_id: str,
    ) -> dict[str, Any]:
        r = await self._client.post(
            f"/api/work-items/{quote(task_id, safe='')}/permissions",
            json={
                "pending_id": pending_id,
                "attempt_id": attempt_id,
                "decisions": decisions,
                "command_id": command_id,
            },
        )
        r.raise_for_status()
        return cast(dict[str, Any], r.json())
