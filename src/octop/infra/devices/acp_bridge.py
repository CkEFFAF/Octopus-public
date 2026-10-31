"""Bridge harness ACP JSON-RPC to one authenticated, bound device.

The ACP process and its credentials stay on the device. Only stdio bytes cross
the existing authenticated device socket; they are never persisted in a ledger.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

from langgraph.config import get_config
from octop_harness.acp.client import ACPHostedClient
from octop_harness.acp.models import ACPConfig, ACPRunnerConfig, ACPSessionError
from octop_harness.acp.permissions import BLOCKED_COMMAND_PATTERNS, ACPPermissionAdapter
from octop_harness.acp.service import ACPService, _Conversation

from octop.infra.devices.service import DeviceService


class _RemotePermissionAdapter(ACPPermissionAdapter):
    """Evaluate ACP path prompts using the device OS, not the manager OS."""

    def __init__(self, cwd: str, platform: str) -> None:
        self.cwd = cwd
        self._path_type = PureWindowsPath if platform == "windows" else PurePosixPath

    def _display_path(self, value: str) -> str:
        path = self._path_type(value)
        root = self._path_type(self.cwd)
        if path.is_absolute():
            try:
                return str(path.relative_to(root))
            except ValueError:
                return value
        return value

    def _is_hard_blocked(self, tool_call: dict[str, Any]) -> bool:
        command = str(self._command(tool_call) or "").lower()
        if any(pattern in command for pattern in BLOCKED_COMMAND_PATTERNS):
            return True
        root = self._path_type(self.cwd)
        for value in self._paths(tool_call):
            path = self._path_type(value)
            if not path.is_absolute():
                path = root / path
            parts: list[str] = []
            for part in path.parts:
                if part == "..":
                    if not parts:
                        return True
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            try:
                self._path_type(*parts).relative_to(root)
            except ValueError:
                return True
        return False


class _RemoteHostedClient(ACPHostedClient):
    def __init__(
        self,
        *,
        runner_name: str,
        runner_config: ACPRunnerConfig,
        cwd: str,
        platform: str,
        owner_trusted: bool = False,
        validate: Any = None,
    ) -> None:
        self._platform = platform
        self._owner_trusted = owner_trusted
        self._validate = validate
        super().__init__(runner_name=runner_name, runner_config=runner_config, cwd=cwd)
        self.update_cwd(cwd)

    def update_cwd(self, cwd: str) -> None:
        self._permission_adapter = _RemotePermissionAdapter(cwd, self._platform)

    async def request_permission(
        self, options: list[Any], session_id: str, tool_call: Any, **kwargs: Any
    ) -> Any:
        if not self._owner_trusted:
            return await super().request_permission(options, session_id, tool_call, **kwargs)
        # The owner policy has already authorized execution on this device.
        # ACP's tool prompts must not introduce a second cwd sandbox or popup.
        if self._validate is not None:
            self._validate()
        request = self._permission_adapter.build_suspended_permission(
            runner=self.runner_name, tool_call=tool_call, options=options
        )
        selected = next(
            (item for item in request.options if item.get("kind") == "allow_once"), None
        )
        selected = selected or next(
            (item for item in request.options if item.get("kind") == "allow_always"), None
        )
        return self._permission_adapter.selected_response(selected)


class _RemoteProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None


class RemoteACPService(ACPService):
    """Use the harness ACP workflow while the subprocess lives on a device."""

    def __init__(
        self,
        *,
        config: ACPConfig,
        devices: DeviceService,
        owner: int,
        agent_id: str,
        device_id: str | None,
        root_id: str | None = None,
        working_dir: str | None = None,
        context_id: str | None = None,
    ) -> None:
        super().__init__(config=config)
        self.devices = devices
        self.owner = owner
        self.agent_id = agent_id
        self.device_id = device_id
        self.root_id = root_id
        self.working_dir = working_dir
        self.context_id = context_id

    def _binding(self) -> tuple[str, str, int]:
        if self.context_id is not None:
            from octop.infra.execution.service import ExecutionService

            context = ExecutionService(self.devices).get(self.owner, self.context_id)
            if context.target_kind == "local":
                if context.work_mode in {"ask", "plan"}:
                    raise ACPSessionError("execution mode only permits observation")
                target = ExecutionService(self.devices).target(self.owner, self.context_id)
                return (
                    str(self.working_dir or target["working_dir"]),
                    target["platform"],
                    context.grant_version,
                )
            assert self.device_id is not None
            current = self.devices.owned(self.owner, self.device_id)
            if (
                current.policy_revision != context.policy_revision
                or current.grant_version != context.grant_version
            ):
                raise ACPSessionError("device execution policy changed")
            if context.work_mode in {"ask", "plan"}:
                raise ACPSessionError("execution mode only permits observation")
        assert self.device_id is not None
        row = self.devices.owned(self.owner, self.device_id)
        if self.devices.owner_trusted(row):
            if "acp_run" not in row.permissions:
                raise ACPSessionError("device ACP capability is disabled")
            directory = (
                self.working_dir
                or row.working_dir
                or (row.runtime_metadata or {}).get("working_dir")
            )
            if not directory:
                raise ACPSessionError("device working directory unavailable")
            return str(directory), row.platform, row.grant_version
        root = next((item for item in row.roots if item["id"] == self.root_id), None)
        if root is None or not root.get("read") or not root.get("write"):
            raise ACPSessionError("bound device no longer shares a writable ACP directory")
        if "acp_run" not in row.permissions or "acp_run" not in row.capabilities:
            raise ACPSessionError("bound device has not authorized ACP execution")
        return str(root["path"]), row.platform, row.grant_version

    async def run_turn(self, **kwargs: Any) -> dict[str, Any]:
        cwd, _, _ = self._binding()
        return await super().run_turn(**{**kwargs, "cwd": cwd})

    async def _call(self, action: str, params: dict[str, Any], version: int) -> dict[str, Any]:
        if self.context_id:
            from octop.infra.execution.service import ExecutionService

            response = await ExecutionService(self.devices).call(
                self.owner, self.context_id, action, params, actor_agent_id=self.agent_id
            )
            return cast(dict[str, Any], response["result"])
        return await self.devices.call(
            self.owner,
            self.device_id or "",
            action,
            params,
            agent_id=self.agent_id,
            expected_version=version,
            allow_acp=True,
        )

    @asynccontextmanager
    async def _transport(
        self,
        runner_config: ACPRunnerConfig,
        version: int,
        runner_name: str = "",
    ) -> Any:
        opened = await self._call(
            "acp.open",
            {
                "root_id": self.root_id,
                "cwd": self._binding()[0],
                "runner": runner_name,
                "command": runner_config.command,
                "args": list(runner_config.args),
            },
            version,
        )
        session_id = str(opened["session_id"])
        process = _RemoteProcess()
        tasks: list[asyncio.Task[None]] = []
        try:
            manager_sock, bridge_sock = socket.socketpair()
            manager_reader, manager_writer = await asyncio.open_connection(sock=manager_sock)
            bridge_reader, bridge_writer = await asyncio.open_connection(sock=bridge_sock)

            async def to_device() -> None:
                while data := await bridge_reader.read(65536):
                    await self._call(
                        "acp.write",
                        {
                            "session_id": session_id,
                            "data_b64": base64.b64encode(data).decode("ascii"),
                        },
                        version,
                    )

            async def from_device() -> None:
                while True:
                    response = await self._call("acp.poll", {"session_id": session_id}, version)
                    data = base64.b64decode(response["data_b64"], validate=True)
                    if data:
                        bridge_writer.write(data)
                        await bridge_writer.drain()
                    if response["eof"]:
                        process.returncode = 0
                        bridge_writer.close()
                        break

            async def run_pump(pump: Any) -> None:
                try:
                    await pump
                except (Exception, asyncio.CancelledError):
                    process.returncode = 1
                    bridge_writer.close()

            tasks = [
                asyncio.create_task(run_pump(to_device())),
                asyncio.create_task(run_pump(from_device())),
            ]
            yield manager_reader, manager_writer, process
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for writer in (locals().get("manager_writer"), locals().get("bridge_writer")):
                if writer is not None:
                    writer.close()
                    with contextlib.suppress(OSError, RuntimeError):
                        await writer.wait_closed()
            if not tasks:
                for sock in (locals().get("manager_sock"), locals().get("bridge_sock")):
                    if sock is not None:
                        sock.close()
            with contextlib.suppress(Exception):
                await self._call("acp.close", {"session_id": session_id}, version)
            process.returncode = 0

    async def _open_conversation(
        self,
        *,
        thread_id: str,
        runner: str,
        cwd: str,
        runner_config: ACPRunnerConfig,
    ) -> _Conversation:
        from acp import PROTOCOL_VERSION
        from acp.client.connection import ClientSideConnection
        from acp.schema import ClientCapabilities, Implementation

        remote_cwd, platform, version = self._binding()
        client = _RemoteHostedClient(
            runner_name=runner,
            runner_config=runner_config,
            cwd=remote_cwd,
            platform=platform,
            owner_trusted=self.device_id is None
            or self.devices.owner_trusted(self.devices.owned(self.owner, self.device_id)),
            validate=self._binding,
        )
        stack = AsyncExitStack()
        try:
            reader, writer, process = await stack.enter_async_context(
                self._transport(runner_config, version, runner)
            )
            conn = ClientSideConnection(client, writer, reader)  # type: ignore[arg-type]
            stack.push_async_callback(conn.close)
            initialized = await conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                capabilities=ClientCapabilities(),
                client_info=Implementation(name="octop-device-acp", version="1.0"),
            )
            if initialized.protocol_version != PROTOCOL_VERSION:
                raise ACPSessionError("remote ACP protocol mismatch")
            new_session = await conn.new_session(cwd=remote_cwd)
            return _Conversation(
                thread_id=thread_id,
                runner=runner,
                acp_session_id=new_session.session_id,
                cwd=remote_cwd,
                conn=conn,
                process=process,
                client=client,
                exit_stack=stack,
                turn_lock=asyncio.Lock(),
            )
        except BaseException:
            await stack.aclose()
            raise

    async def _close_conversation(self, conversation: _Conversation) -> None:
        if conversation.prompt_task is not None:
            conversation.prompt_task.cancel()
            await asyncio.gather(conversation.prompt_task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                conversation.conn.close_session(session_id=conversation.acp_session_id), 5
            )
        await conversation.exit_stack.aclose()


class RequestACPService(ACPService):
    """Select ACP transport per authenticated request, retaining session targets."""

    def __init__(
        self, *, config: ACPConfig, devices: DeviceService, owner: int, agent_id: str
    ) -> None:
        super().__init__(config=config)
        self.devices, self.owner, self.agent_id = devices, owner, agent_id
        self._targets: dict[tuple[Any, ...], RemoteACPService] = {}
        self._session_targets: dict[tuple[str, str], RemoteACPService] = {}

    def resolve_cwd(self, cwd: str, workspace_dir: Any) -> str:
        # Remote native paths must never be expanded with the controller OS.
        return cwd

    def _selected(self, cwd: str | None = None) -> RemoteACPService:
        from octop.infra.execution.service import ExecutionService

        cfg = get_config().get("configurable") or {}
        supplied = cfg.get("octop_execution_context")
        if int(cfg.get("user") or 0) != self.owner or not isinstance(supplied, dict):
            raise ACPSessionError("choose an execution target for ACP")
        context = ExecutionService(self.devices).get(
            self.owner, str(supplied.get("context_id") or "")
        )
        import json

        from octop.infra.devices.acp_settings import DeviceACPSettings

        effective = self.config
        if context.device_id:
            effective = ACPConfig.from_dict(
                {
                    "runners": DeviceACPSettings(
                        self.devices, self.owner, context.device_id
                    ).runners()
                }
            )
        directory = context.working_dir if not cwd or cwd == "." else cwd
        key = (
            context.device_id,
            directory,
            context.policy_revision,
            context.grant_version,
            context.work_mode,
            context.context_id,
            json.dumps(
                {name: vars(runner) for name, runner in effective.runners.items()}, sort_keys=True
            ),
        )
        if key not in self._targets:
            self._targets[key] = RemoteACPService(
                config=effective,
                devices=self.devices,
                owner=self.owner,
                agent_id=self.agent_id,
                device_id=context.device_id,
                working_dir=directory,
                context_id=context.context_id,
            )
        service = self._targets[key]
        service._binding()
        return service

    async def run_turn(self, **kwargs: Any) -> dict[str, Any]:
        key = (str(kwargs["thread_id"]), str(kwargs["runner"]))
        service = self._session_targets.get(key) if kwargs.get("require_existing") else None
        service = service or self._selected(str(kwargs.get("cwd") or "."))
        self._session_targets[key] = service
        # Each service retains the device/default cwd that created its sessions.
        if kwargs.get("cwd"):
            kwargs["cwd"] = str(kwargs["cwd"])
        return await service.run_turn(**kwargs)

    async def get_session(self, thread_id: str, runner: str) -> _Conversation | None:
        service = self._session_targets.get((thread_id, runner))
        return await service.get_session(thread_id, runner) if service else None

    async def get_pending_permission(self, *, thread_id: str, runner: str) -> Any | None:
        service = self._session_targets.get((thread_id, runner))
        return (
            await service.get_pending_permission(thread_id=thread_id, runner=runner)
            if service
            else None
        )

    async def close_thread_session(self, *, thread_id: str, runner: str) -> None:
        service = self._session_targets.pop((thread_id, runner), None)
        if service:
            await service.close_thread_session(thread_id=thread_id, runner=runner)

    async def cancel_turn(self, *, thread_id: str, runner: str) -> bool:
        service = self._session_targets.get((thread_id, runner))
        return await service.cancel_turn(thread_id=thread_id, runner=runner) if service else False

    async def resume_permission(self, **kwargs: Any) -> dict[str, Any]:
        # Harness resumes by the ACP session id, without thread or runner keys.
        for service in set(self._session_targets.values()):
            if await service._find_session_by_acp_id(str(kwargs["acp_session_id"])) is not None:
                return await service.resume_permission(**kwargs)
        raise ACPSessionError("ACP session unavailable")

    async def close_all_sessions(self) -> None:
        for service in self._targets.values():
            await service.close_all_sessions()
        self._targets.clear()
        self._session_targets.clear()


def bind_remote_acp_service(service_key: str, service: ACPService) -> None:
    """Install before harness builds its ACP tool for this agent workspace."""
    from octop_harness.acp.service import register_acp_service

    register_acp_service(service_key, service)


def build_request_acp_tool(service_key: str, config: ACPConfig, workspace_dir: Path) -> Any:
    """Resolve templates on each request and keep device errors inside tool results."""
    from langchain_core.tools import tool
    from octop_harness.acp.service import get_acp_service
    from octop_harness.builtin.tools.acp_runner import build_acp_runner_tool

    from octop.i18n import tr
    from octop.infra.errors import OctopError

    @tool
    async def acp_runner(
        action: str,
        runner: str = "",
        message: str = "",
        cwd: str = "",
        max_runtime: float | None = 300,
    ) -> str:
        """Use an ACP agent on the selected execution device. Actions: list, status, start, message, respond, close. Credentials stay on the device. List checks configuration, not authentication. Close a session before switching its device."""
        service = get_acp_service(service_key)
        try:
            effective = config
            if not isinstance(service, RequestACPService):
                raise ACPSessionError("choose an execution target for ACP")
            if isinstance(service, RequestACPService):
                bound = service._session_targets.get(
                    (str((get_config().get("configurable") or {}).get("thread_id")), runner)
                )
                selected = (
                    bound
                    if action in {"message", "respond", "status", "close"} and bound
                    else service._selected(cwd or ".")
                )
                effective = selected.config
                cwd = selected._binding()[0]
            delegate = build_acp_runner_tool(
                service_key=service_key, config=effective, workspace_dir=workspace_dir
            )
            return str(
                await delegate.ainvoke(
                    {
                        "action": action,
                        "runner": runner,
                        "message": message,
                        "cwd": cwd,
                        "max_runtime": max_runtime,
                    }
                )
            )
        except Exception as exc:
            text = str(exc).lower()
            kind = (
                "subscription"
                if "subscription" in text
                else "auth"
                if any(
                    word in text for word in ("unauthorized", "authentication", "login", "api key")
                )
                else "missing"
                if "not installed" in text or "not found" in text or "executable_not_found" in text
                else "offline"
                if isinstance(exc, OctopError) and exc.code.value == "DEVICE_OFFLINE"
                else "failed"
            )
            cfg = get_config().get("configurable") or {}
            return tr("acp_runtime." + kind, cfg.get("locale") or "zh")

    return acp_runner
