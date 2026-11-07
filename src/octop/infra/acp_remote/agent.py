"""ACP Agent implementation that proxies to cloud work-items."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from octop.infra.acp_remote.cloud import CloudClient
from octop.infra.acp_remote.sessions import SessionStore
from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({"completed", "failed", "cancelled", "unknown"})


def _prompt_text(prompt: Any) -> str:
    parts: list[str] = []
    for block in prompt or []:
        text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
        if text:
            parts.append(str(text))
    return "\n".join(parts)


class RemoteAcpAgent:
    """Stdio ACP agent — no local OctopServer."""

    def __init__(
        self,
        *,
        cloud: CloudClient,
        expert_id: str,
        credential_id: str,
        store: SessionStore | None = None,
        poll_interval: float = 0.5,
        poll_timeout: float = 120.0,
    ) -> None:
        self._cloud = cloud
        self._expert_id = expert_id
        self._credential_id = credential_id
        self._store = store or SessionStore()
        self._conn: Any = None
        self._cancel: dict[str, asyncio.Event] = {}
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._version = "0.0.0"
        try:
            from importlib.metadata import version as pkg_version

            self._version = pkg_version("octop")
        except Exception:
            pass

    def on_connect(self, conn: Any) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> Any:
        from acp.schema import (
            AgentCapabilities,
            Implementation,
            InitializeResponse,
            PromptCapabilities,
        )

        try:
            await self._cloud.probe()
        except Exception as exc:  # noqa: BLE001 — soft probe; sessions fail clearly later
            logger.warning("acp-remote probe failed: %s", type(exc).__name__)
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=False, audio=False, embedded_context=False
                ),
            ),
            agent_info=Implementation(
                name="octop-acp-remote",
                title="Octop Remote Expert",
                version=self._version,
            ),
        )

    async def new_session(self, cwd: str, **kwargs: Any) -> Any:
        from acp.schema import NewSessionResponse

        thread = await self._cloud.create_thread(self._expert_id, title="ACP remote session")
        thread_id = str(thread.get("thread_id") or thread.get("id") or "")
        if not thread_id:
            raise RuntimeError("cloud thread create missing thread_id")
        session_id = new_ulid()
        self._store.put(
            session_id,
            {
                "server": self._cloud.server,
                "expert_id": self._expert_id,
                "remote_thread_id": thread_id,
                "remote_task_id": None,
                "last_command_id": None,
                "credential_id": self._credential_id,
                "cwd": cwd,
            },
        )
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd: str, session_id: str, **kwargs: Any) -> Any:
        from acp import RequestError
        from acp.schema import LoadSessionResponse

        row = self._store.get(session_id)
        if row is None:
            raise RequestError.invalid_params({"sessionId": session_id, "reason": "unknown session"})
        if row.get("credential_id") != self._credential_id:
            self._store.delete(session_id)
            raise RequestError.invalid_params({"sessionId": session_id, "reason": "credential mismatch"})
        if row.get("expert_id") != self._expert_id:
            raise RequestError.invalid_params({"sessionId": session_id, "reason": "expert mismatch"})
        row["cwd"] = cwd
        self._store.put(session_id, row)
        return LoadSessionResponse()

    async def resume_session(self, session_id: str, cwd: str, **kwargs: Any) -> Any:
        from acp.schema import ResumeSessionResponse

        await self.load_session(cwd=cwd, session_id=session_id)
        return ResumeSessionResponse()

    async def close_session(self, session_id: str, **kwargs: Any) -> Any:
        self._store.delete(session_id)
        self._cancel.pop(session_id, None)
        return None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        event = self._cancel.get(session_id)
        if event is not None:
            event.set()
        row = self._store.get(session_id)
        if row and row.get("remote_task_id"):
            try:
                await self._cloud.cancel(row["remote_task_id"], command_id=new_ulid())
            except Exception as exc:  # noqa: BLE001
                logger.warning("cancel failed: %s", type(exc).__name__)

    async def prompt(self, session_id: str, prompt: Any, **kwargs: Any) -> Any:
        from acp import RequestError, update_agent_message_text
        from acp.schema import PromptResponse

        row = self._store.get(session_id)
        if row is None:
            raise RequestError.invalid_params({"sessionId": session_id, "reason": "unknown session"})
        text = _prompt_text(prompt)
        if not text:
            return PromptResponse(stop_reason="end_turn")

        command_id = new_ulid()
        cancel_event = asyncio.Event()
        self._cancel[session_id] = cancel_event

        task_id = row.get("remote_task_id")
        if not task_id:
            created = await self._cloud.create_work_item(
                expert_id=self._expert_id,
                origin_thread_id=row["remote_thread_id"],
                title=text[:80] or "ACP task",
                instructions=text,
                command_id=command_id,
            )
            task_id = created["task_id"]
            row["remote_task_id"] = task_id
            row["last_command_id"] = command_id
            self._store.put(session_id, row)
        else:
            # Continuations use a new command_id (DEC-0045-13)
            await self._cloud.add_input(task_id, text, command_id=command_id)
            row["last_command_id"] = command_id
            self._store.put(session_id, row)

        if self._conn is not None:
            await self._conn.session_update(
                session_id=session_id,
                update=update_agent_message_text("Task accepted; waiting for progress…"),
            )

        deadline = asyncio.get_event_loop().time() + self._poll_timeout
        last_status = ""
        while asyncio.get_event_loop().time() < deadline:
            if cancel_event.is_set():
                return PromptResponse(stop_reason="cancelled")
            try:
                prog = await self._cloud.progress(task_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("progress poll failed: %s", type(exc).__name__)
                await asyncio.sleep(self._poll_interval)
                continue
            status = str(prog.get("status") or "")
            summary = str(prog.get("summary") or prog.get("title") or status)
            if status and status != last_status and self._conn is not None:
                await self._conn.session_update(
                    session_id=session_id,
                    update=update_agent_message_text(f"[{status}] {summary}"),
                )
                last_status = status
            if status in _TERMINAL:
                if self._conn is not None and summary:
                    await self._conn.session_update(
                        session_id=session_id,
                        update=update_agent_message_text(summary),
                    )
                reason = "cancelled" if status == "cancelled" else "end_turn"
                if status == "failed":
                    reason = "end_turn"
                return PromptResponse(stop_reason=reason)
            await asyncio.sleep(self._poll_interval)

        return PromptResponse(stop_reason="max_tokens")
