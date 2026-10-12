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
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

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
        self, *, runner_name: str, runner_config: ACPRunnerConfig, cwd: str, platform: str
    ) -> None:
        self._platform = platform
        super().__init__(runner_name=runner_name, runner_config=runner_config, cwd=cwd)
        self.update_cwd(cwd)

    def update_cwd(self, cwd: str) -> None:
        self._permission_adapter = _RemotePermissionAdapter(cwd, self._platform)


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
        device_id: str,
        root_id: str,
    ) -> None:
        super().__init__(config=config)
        self.devices = devices
        self.owner = owner
        self.agent_id = agent_id
        self.device_id = device_id
        self.root_id = root_id

    def _binding(self) -> tuple[str, str, int]:
        row = self.devices.owned(self.owner, self.device_id)
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
        return await self.devices.call(
            self.owner,
            self.device_id,
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


def bind_remote_acp_service(service_key: str, service: RemoteACPService) -> None:
    """Install before harness builds its ACP tool for this agent workspace."""
    from octop_harness.acp import service as harness_service

    previous = harness_service._services.get(service_key)
    harness_service._services[service_key] = service
    if previous is not None:
        harness_service._schedule_close(previous)
