"""Standard ACP sessions backed by credential-scoped cloud work items."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
from typing import Any

import httpx

from octop.i18n import tr
from octop.infra.acp_remote.cloud import CloudClient
from octop.infra.acp_remote.sessions import SessionStore
from octop.infra.utils.locale import DEFAULT_LOCALE
from octop.infra.utils.ulid import new_ulid

_TERMINAL = frozenset({"completed", "failed", "cancelled"})


def _prompt_text(prompt: Any) -> str:
    from acp import RequestError

    parts = []
    for block in prompt or []:
        kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if kind != "text":
            raise RequestError.invalid_params({"reason": "unsupported_content_type"})
        text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
        parts.append(str(text))
    return "\n".join(parts)


def _assistant_text(history: dict[str, Any]) -> str:
    parts = []
    for message in history.get("messages", []):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.append(
                "".join(
                    str(block.get("text") or "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            )
    return "\n".join(part for part in parts if part)


class RemoteAcpAgent:
    def __init__(
        self,
        *,
        cloud: CloudClient,
        expert_id: str,
        credential_id: str,
        store: SessionStore | None = None,
        poll_interval: float = 1.0,
        poll_timeout: float | None = None,
    ) -> None:
        self._cloud = cloud
        self._expert_id = expert_id
        self._credential_id = credential_id
        self._store = store or SessionStore()
        self._conn: Any = None
        self._cancel: dict[str, asyncio.Event] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    def on_connect(self, conn: Any) -> None:
        self._conn = conn

    async def _put(self, session_id: str, row: dict[str, Any]) -> None:
        await asyncio.to_thread(self._store.put, session_id, row)

    async def _row(self, session_id: str) -> dict[str, Any]:
        from acp import RequestError

        row = await asyncio.to_thread(self._store.get, session_id)
        if row is None:
            raise RequestError.resource_not_found()
        if (row.get("server"), row.get("expert_id"), row.get("credential_id")) != (
            self._cloud.server,
            self._expert_id,
            self._credential_id,
        ):
            raise RequestError.invalid_params({"reason": "session_identity_mismatch"})
        identity = await self._cloud.identity()
        if identity["credential_id"] != self._credential_id:
            raise RequestError.auth_required()
        # Recheck remote authority before disclosing any cached conversation.
        await self._cloud.history(self._expert_id, row["remote_thread_id"])
        return row

    async def initialize(self, protocol_version: int, *args: Any, **kwargs: Any) -> Any:
        from acp import PROTOCOL_VERSION
        from acp.schema import (
            AgentCapabilities,
            Implementation,
            InitializeResponse,
            PromptCapabilities,
        )

        await self._cloud.probe()
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=False, audio=False, embedded_context=False
                ),
            ),
            agent_info=Implementation(
                name="octop-acp-remote", title="Octop Remote Expert", version=version("octop")
            ),
        )

    @staticmethod
    def _check_mcp(kwargs: dict[str, Any]) -> None:
        from acp import RequestError

        if kwargs.get("mcp_servers"):
            raise RequestError.invalid_params({"reason": "client_mcp_servers_not_supported"})

    async def new_session(
        self, cwd: str, additional_directories: Any = None, mcp_servers: Any = None, **kwargs: Any
    ) -> Any:
        from acp.schema import NewSessionResponse

        self._check_mcp({"mcp_servers": mcp_servers, **kwargs})
        thread = await self._cloud.create_thread(self._expert_id)
        session_id = new_ulid()
        await self._put(
            session_id,
            {
                "server": self._cloud.server,
                "expert_id": self._expert_id,
                "credential_id": self._credential_id,
                "remote_thread_id": thread["thread_id"],
                "remote_task_id": None,
                "pending": None,
                "history": [],
                "cwd": cwd,
            },
        )
        return NewSessionResponse(session_id=session_id)

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: Any = None,
        additional_directories: Any = None,
        **kwargs: Any,
    ) -> Any:
        from acp import update_agent_message_text, update_user_message_text
        from acp.schema import LoadSessionResponse

        self._check_mcp({"mcp_servers": mcp_servers, **kwargs})
        row = await self._row(session_id)
        for message in row.get("history", []):
            if self._conn is not None:
                update = (
                    update_user_message_text
                    if message["role"] == "user"
                    else update_agent_message_text
                )(message["text"])
                await self._conn.session_update(session_id=session_id, update=update)
        row["cwd"] = cwd  # Local metadata only, never a remote execution target.
        await self._put(session_id, row)
        return LoadSessionResponse()

    async def resume_session(
        self,
        session_id: str,
        cwd: str,
        additional_directories: Any = None,
        mcp_servers: Any = None,
        **kwargs: Any,
    ) -> Any:
        from acp.schema import ResumeSessionResponse

        self._check_mcp({"mcp_servers": mcp_servers, **kwargs})
        await self._row(session_id)
        return ResumeSessionResponse()

    async def close_session(self, session_id: str, **kwargs: Any) -> Any:
        from acp import RequestError

        if await asyncio.to_thread(self._store.get, session_id) is None:
            return None
        row = await self._row(session_id)
        if row.get("remote_task_id"):
            result = await self._cloud.cancel(row["remote_task_id"], command_id=new_ulid())
            if result.get("status") not in _TERMINAL:
                raise RequestError.internal_error({"reason": "cancellation_pending"})
        await asyncio.to_thread(self._store.delete, session_id)
        return None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        row = await self._row(session_id)
        if event := self._cancel.get(session_id):
            event.set()
        task_id = row.get("remote_task_id")
        if not task_id and row.get("pending"):
            match = await self._cloud.lookup_command(row["pending"]["command_id"])
            task_id = match["task_id"] if match else None
        if task_id:
            await self._cloud.cancel(task_id, command_id=new_ulid())

    async def prompt(self, session_id: str, prompt: Any, **kwargs: Any) -> Any:
        from acp import RequestError

        lock = self._locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise RequestError.invalid_params({"reason": "session_busy"})
        async with lock:
            event = asyncio.Event()
            self._cancel[session_id] = event
            try:
                return await self._prompt(session_id, prompt, event)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise RequestError.auth_required() from None
                raise RequestError.internal_error(
                    {"reason": "cloud_request_rejected", "status": exc.response.status_code}
                ) from None
            except httpx.RequestError:
                raise RequestError.internal_error({"reason": "cloud_request_unconfirmed"}) from None
            finally:
                self._cancel.pop(session_id, None)

    async def _prompt(self, session_id: str, prompt: Any, event: asyncio.Event) -> Any:
        from acp import RequestError
        from acp.schema import PromptResponse

        row = await self._row(session_id)
        text = _prompt_text(prompt)
        if not text:
            return PromptResponse(stop_reason="end_turn")
        if row.get("pending"):
            pending = row["pending"]
            if pending["text"] != text:
                raise RequestError.invalid_params({"reason": "previous_prompt_unconfirmed"})
            # A previous POST may already have had effects. Recovery is GET-only.
            if pending["kind"] == "input":
                match = await self._cloud.input_receipt(
                    row["remote_task_id"], pending["command_id"]
                )
            else:
                match = await self._cloud.lookup_command(pending["command_id"])
            if not match:
                raise RequestError.internal_error({"reason": "previous_prompt_unconfirmed"})
            row["remote_task_id"] = match["task_id"]
        else:
            current = (
                await self._cloud.detail(row["remote_task_id"])
                if row.get("remote_task_id")
                else None
            )
            if current and current["status"] == "unknown":
                raise RequestError.internal_error({"reason": "remote_status_unknown"})
            command_id = new_ulid()
            row["pending"] = {
                "command_id": command_id,
                "text": text,
                "kind": "input" if current and current["status"] not in _TERMINAL else "create",
            }
            # Persist before dispatch, including when HTTP response is lost.
            await self._put(session_id, row)
            if current and current["status"] not in _TERMINAL:
                await self._cloud.add_input(current["task_id"], text, command_id=command_id)
            else:
                context = "\n".join(
                    f"{item['role']}: {item['text']}" for item in row.get("history", [])
                )[-24000:]
                instructions = (
                    f"Previous conversation:\n{context}\n\nCurrent request:\n{text}"
                    if context
                    else text
                )
                created = await self._cloud.create_work_item(
                    expert_id=self._expert_id,
                    origin_thread_id=row["remote_thread_id"],
                    title=text[:80],
                    instructions=instructions,
                    command_id=command_id,
                )
                row["remote_task_id"] = created["task_id"]
            await self._put(session_id, row)
        return await self._poll(session_id, row, event)

    async def _poll(self, session_id: str, row: dict[str, Any], cancelled: asyncio.Event) -> Any:
        from acp import RequestError, update_agent_message_text, update_agent_thought_text
        from acp.schema import PromptResponse

        task_id = row["remote_task_id"]
        deadline = (
            asyncio.get_running_loop().time() + self._poll_timeout
            if self._poll_timeout is not None
            else None
        )
        emitted, last_status = "", ""
        while deadline is None or asyncio.get_running_loop().time() < deadline:
            task = await self._cloud.detail(task_id)
            status = task["status"]
            if status == "unknown":
                raise RequestError.internal_error({"reason": "remote_status_unknown"})
            if cancelled.is_set() and status not in _TERMINAL and not task.get("cancel_requested"):
                await self._cloud.cancel(task_id, command_id=new_ulid())
            if status != last_status and self._conn is not None:
                await self._conn.session_update(
                    session_id=session_id,
                    update=update_agent_thought_text(
                        tr(
                            f"acp_remote.status.{status}",
                            getattr(self._cloud, "locale", DEFAULT_LOCALE),
                        )
                    ),
                )
                last_status = status
            history_text = str(task.get("progress", {}).get("output_text") or "")
            if worker := task.get("worker_thread_id"):
                history_text = history_text or _assistant_text(
                    await self._cloud.history(self._expert_id, worker)
                )
            if history_text and history_text != emitted and self._conn is not None:
                delta = (
                    history_text[len(emitted) :]
                    if history_text.startswith(emitted)
                    else history_text
                )
                await self._conn.session_update(
                    session_id=session_id, update=update_agent_message_text(delta)
                )
                emitted = history_text
            if status in _TERMINAL:
                final = history_text or str(task.get("reported_outcome") or "")
                if final and final != emitted and self._conn is not None:
                    await self._conn.session_update(
                        session_id=session_id, update=update_agent_message_text(final)
                    )
                row.setdefault("history", []).extend(
                    [
                        {"role": "user", "text": row["pending"]["text"]},
                        {"role": "assistant", "text": final or status},
                    ]
                )
                row["pending"] = None
                await self._put(session_id, row)
                if status == "failed":
                    raise RequestError.internal_error({"reason": "remote_task_failed"})
                return PromptResponse(
                    stop_reason="cancelled" if status == "cancelled" else "end_turn"
                )
            permission = task.get("progress", {}).get("permission_request")
            if permission and not cancelled.is_set():
                await self._permission(session_id, task, permission, cancelled)
            await asyncio.sleep(self._poll_interval)
        raise RequestError.internal_error({"reason": "remote_still_running"})

    async def _permission(
        self,
        session_id: str,
        task: dict[str, Any],
        permission: dict[str, Any],
        cancelled: asyncio.Event,
    ) -> None:
        from acp import RequestError
        from acp.schema import PermissionOption, ToolCallUpdate

        if self._conn is None:
            raise RequestError.internal_error({"reason": "permission_client_unavailable"})
        history = await self._cloud.history(self._expert_id, task["worker_thread_id"])
        pending = history.get("hitl_pending") or {}
        if pending.get("pending_id") != permission["pending_id"]:
            raise RequestError.internal_error({"reason": "permission_request_changed"})
        actions = pending.get("action_requests", [])
        if len(actions) != len(permission["actions"]):
            raise RequestError.internal_error({"reason": "permission_request_changed"})
        decisions: list[str] = []
        for index, action in enumerate(permission["actions"]):
            allowed = action["allowed_decisions"]
            if "reject" not in allowed:
                raise RequestError.invalid_params({"reason": "unsupported_permission_type"})
            locale = getattr(self._cloud, "locale", DEFAULT_LOCALE)
            options = [
                PermissionOption(
                    option_id="reject", name=tr("acp_remote.reject", locale), kind="reject_once"
                )
            ]
            if "approve" in allowed:
                options.insert(
                    0,
                    PermissionOption(
                        option_id="approve",
                        name=tr("acp_remote.allow_once", locale),
                        kind="allow_once",
                    ),
                )
            request = asyncio.create_task(
                self._conn.request_permission(
                    session_id=session_id,
                    tool_call=ToolCallUpdate(
                        tool_call_id=f"{permission['pending_id']}:{index}",
                        title=action["name"],
                        status="pending",
                        raw_input=actions[index].get("args"),
                    ),
                    options=options,
                )
            )
            cancellation = asyncio.create_task(cancelled.wait())
            try:
                done, _ = await asyncio.wait(
                    {request, cancellation}, timeout=60, return_when=asyncio.FIRST_COMPLETED
                )
                if cancelled.is_set():
                    return
                if request not in done:
                    # Timeout is an explicit rejection, never an automatic allow.
                    decisions.extend("reject" for _ in permission["actions"][index:])
                    break
                result = request.result()
            finally:
                for pending in (request, cancellation):
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(request, cancellation, return_exceptions=True)
            decision = getattr(result.outcome, "option_id", None)
            decisions.append(
                "approve" if decision == "approve" and "approve" in allowed else "reject"
            )
        if cancelled.is_set():
            return
        await self._cloud.permission(
            task["task_id"],
            pending_id=permission["pending_id"],
            attempt_id=task["current_attempt_id"],
            decisions=decisions,
            command_id=new_ulid(),
        )

    async def _unsupported(self, *args: Any, **kwargs: Any) -> Any:
        from acp import RequestError

        raise RequestError.method_not_found("unsupported")

    authenticate = _unsupported
    list_sessions = _unsupported
    set_session_mode = _unsupported
    set_config_option = _unsupported
    fork_session = _unsupported

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        from acp import RequestError

        raise RequestError.method_not_found(method)

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        pass
