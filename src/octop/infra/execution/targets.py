"""Explicit local and device transports for the same native operation contract."""

from __future__ import annotations

import asyncio
import getpass
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

from octop.infra.db.repos.execution import ExecutionContext
from octop.infra.devices.executor import CAPABILITIES, DeviceExecutionError, DeviceExecutor
from octop.infra.devices.protocol import JOB_READ_ACTIONS, validate_action
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.devices.service import DeviceService


class DeviceExecutionBackend:
    def __init__(self, devices: DeviceService) -> None:
        self.devices = devices

    async def call(
        self, context: ExecutionContext, operation_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if context.target_kind != "device" or not context.device_id:
            raise OctopError(ErrorCode.FORBIDDEN, "device target required")
        return await self.devices.call(
            context.owner_user_id,
            context.device_id,
            action,
            params,
            request_id=operation_id,
            record_operation=True,
            allow_acp=action.startswith("acp.") and context.agent_id is not None,
            agent_id=context.agent_id,
            expected_version=None if action in JOB_READ_ACTIONS else context.grant_version,
            execution_context_id=context.context_id,
        )


class LocalExecutionBackend:
    """Control-center OS execution, available only after explicit admin selection.

    Account/role checks belong to ExecutionService and run before every call.
    Each account has separate interactive sessions and durable runtime state.
    """

    revision = 1

    def __init__(self, state_dir: Path, devices: DeviceService) -> None:
        self.state_dir = state_dir
        self.devices = devices
        self._runtimes: dict[int, DeviceExecutor] = {}

    def runtime(self, owner: int) -> DeviceExecutor:
        if owner not in self._runtimes:
            self._runtimes[owner] = DeviceExecutor(
                sorted(CAPABILITIES),
                [],
                state_dir=self.state_dir / str(owner),
                trust_mode="owner",
                working_dir=str(Path.home()),
            )
            self._runtimes[owner].grant_version = self.revision
        return self._runtimes[owner]

    @property
    def active(self) -> bool:
        return bool(self._runtimes)

    @property
    def owners(self) -> tuple[int, ...]:
        return tuple(self._runtimes)

    def metadata(self, owner: int) -> dict[str, Any]:
        runtime = self.runtime(owner)
        return {
            "target_kind": "local",
            "device_id": None,
            "name": platform.node(),
            "platform": platform.system().lower(),
            "permissions": sorted(runtime.permissions),
            "capabilities": runtime.capabilities,
            "online": True,
            "revoked_at": None,
            "working_dir": str(runtime.working_dir),
            "policy_revision": self.revision,
            "grant_version": self.revision,
            "runtime": {
                "os_user": getpass.getuser(),
                "working_dir": str(runtime.working_dir),
                "job_protocol_version": 1,
                "transfer_protocol_version": 1,
                "desktop_protocol_version": 1,
            },
        }

    async def call(
        self, context: ExecutionContext, operation_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if action.startswith("browser."):
            from octop.infra.execution.service import ExecutionService

            context, params = ExecutionService(self.devices)._prepare(
                context.owner_user_id,
                context.context_id,
                action,
                params,
                actor_agent_id=context.agent_id,
            )
        if context.target_kind != "local" or context.device_id is not None:
            raise OctopError(ErrorCode.FORBIDDEN, "explicit local target required")
        permission = validate_action(action, params)
        runtime = self.runtime(context.owner_user_id)
        if permission and permission not in runtime.permissions:
            raise OctopError(ErrorCode.FORBIDDEN, "local execution capability unavailable")
        try:
            return await runtime.execute(
                operation_id,
                action,
                params,
                grant_version=self.revision,
                permissions=sorted(runtime.permissions),
            )
        except DeviceExecutionError as exc:
            raise OctopError(ErrorCode.DEVICE_INVALID, str(exc)) from exc

    async def close(self) -> None:
        await asyncio.gather(*(runtime.close() for runtime in self._runtimes.values()))
        self._runtimes.clear()

    async def revoke(self, owner: int) -> None:
        """Withdraw a former host administrator's active OS execution authority."""
        runtime = self._runtimes.get(owner)
        if runtime is None:
            return
        await asyncio.to_thread(runtime.update_grants, self.revision + 1, [], [])
        await runtime.close()
        self._runtimes.pop(owner, None)
