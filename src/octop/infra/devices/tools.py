"""Agent device tools retain user ownership, local consent and human confirmation."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError


def build_device_tools(
    service: DeviceService, agent_id: str, bound_device_id: str | None = None
) -> list[Any]:
    def task_run_id() -> str | None:
        return (get_config().get("configurable") or {}).get("octop_task_run_id")

    def identity(device_id: str = "", *, writes: bool = False) -> tuple[int, str]:
        cfg = get_config().get("configurable") or {}
        uid = int(cfg.get("user") or 0)
        if uid <= 0:
            raise OctopError(ErrorCode.FORBIDDEN, "missing authenticated user")
        if writes and cfg.get("conversation_mode") in {"ask", "plan"}:
            raise OctopError(ErrorCode.FORBIDDEN, "device changes require craft mode")
        target = cfg.get("octop_device_target")
        if bound_device_id:
            if device_id and device_id != bound_device_id:
                raise OctopError(ErrorCode.FORBIDDEN, "expert is bound to another device")
            device_id = bound_device_id
        if isinstance(target, dict):
            bound_id = str(target.get("device_id", ""))
            if device_id and bound_id != device_id:
                raise OctopError(ErrorCode.FORBIDDEN, "operation targets another selected device")
            device_id = bound_id
            row = service.owned(uid, device_id)
            if row.grant_version != target.get("grant_version"):
                raise OctopError(ErrorCode.FORBIDDEN, "selected device permissions changed")
        elif bound_device_id:
            service.owned(uid, bound_device_id)
        return uid, device_id

    async def device_list() -> str:
        """List your registered devices and authorized shared directories."""
        uid, _ = identity()
        return json.dumps({"devices": service.list_devices(uid)}, ensure_ascii=False)

    async def device_call(device_id: str, action: str, params: dict[str, Any]) -> str:
        """Read device status, shared files or desktop capture. Writes use device_run."""
        try:
            if action not in {
                "ping",
                "status",
                "files.list",
                "files.stat",
                "files.read",
                "desktop.capture",
            }:
                raise OctopError(ErrorCode.FORBIDDEN, "use device_run for device changes")
            uid, target = identity(device_id)
            return json.dumps(
                await service.call(uid, target, action, params, agent_id=agent_id),
                ensure_ascii=False,
            )
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)

    async def device_run(device_id: str, action: str, params: dict[str, Any]) -> str:
        """Submit an authorized device operation. Commands await the user's confirmation in Devices."""
        try:
            uid, target = identity(device_id, writes=True)
            return json.dumps(
                service.submit(
                    uid, target, action, params, agent_id=agent_id, task_run_id=task_run_id()
                ),
                ensure_ascii=False,
            )
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)

    async def device_operation_get(operation_id: str) -> str:
        """Read actual operation status and result; never presume a command was completed."""
        uid, _ = identity()
        return json.dumps(service.operation(uid, operation_id).public(), ensure_ascii=False)

    async def device_transfer(
        source_device_id: str,
        source_root_id: str,
        source_path: str,
        target_device_id: str,
        target_root_id: str,
        target_path: str,
    ) -> str:
        """Transfer a file between your permitted directories, with checksum verification."""
        try:
            uid, target = identity(target_device_id, writes=True)
            return json.dumps(
                service.transfer(
                    uid,
                    {
                        "source_device_id": source_device_id,
                        "source_root_id": source_root_id,
                        "source_path": source_path,
                        "target_device_id": target,
                        "target_root_id": target_root_id,
                        "target_path": target_path,
                    },
                    agent_id=agent_id,
                    task_run_id=task_run_id(),
                ),
                ensure_ascii=False,
            )
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)

    return [
        StructuredTool.from_function(coroutine=f)
        for f in (
            device_list,
            device_call,
            device_run,
            device_operation_get,
            device_transfer,
        )
    ]
