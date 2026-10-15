"""Agent device tools retain account ownership and the device's applied policy."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.service import ExecutionService


def build_device_tools(
    service: DeviceService,
    agent_id: str,
    bound_device_id: str | None = None,
    bound_root_id: str | None = None,
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
        context = cfg.get("octop_execution_context")
        if isinstance(context, dict) and context.get("target_kind") == "local":
            stored = ExecutionService(service).get(uid, context["context_id"])
            if stored.target_kind != "local" or device_id:
                raise OctopError(ErrorCode.FORBIDDEN, "operation targets another execution context")
            if writes and stored.work_mode in {"ask", "plan"}:
                raise OctopError(ErrorCode.FORBIDDEN, "execution mode only permits observation")
            return uid, ""
        target = cfg.get("octop_device_target")
        if bound_device_id and not isinstance(target, dict):
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
        context = cfg.get("octop_execution_context")
        if isinstance(context, dict):
            stored = ExecutionService(service).get(uid, context["context_id"])
            assert stored.device_id is not None
            row = service.owned(uid, stored.device_id)
            if (
                row.grant_version != stored.grant_version
                or row.policy_revision != stored.policy_revision
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "execution policy changed")
            if writes and stored.work_mode in {"ask", "plan"}:
                raise OctopError(ErrorCode.FORBIDDEN, "execution mode only permits observation")
            if device_id and stored.device_id != device_id:
                raise OctopError(ErrorCode.FORBIDDEN, "operation targets another execution context")
            device_id = stored.device_id
        return uid, device_id

    def parameters(params: dict[str, Any]) -> dict[str, Any]:
        context = (get_config().get("configurable") or {}).get("octop_execution_context")
        if isinstance(context, dict) and context.get("working_dir"):
            return {"cwd": context["working_dir"], **params}
        if bound_root_id and not params.get("root_id"):
            return {**params, "root_id": bound_root_id}
        return params

    async def device_list() -> str:
        """List your devices, applied trust policies, default directories and capabilities."""
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
                "fs.list",
                "fs.stat",
                "fs.read",
            }:
                raise OctopError(ErrorCode.FORBIDDEN, "use device_run for device changes")
            uid, target = identity(device_id)
            context = (get_config().get("configurable") or {}).get("octop_execution_context")
            if isinstance(context, dict):
                return json.dumps(
                    await ExecutionService(service).call(
                        uid, context["context_id"], action, params, actor_agent_id=agent_id
                    ),
                    ensure_ascii=False,
                )
            return json.dumps(
                await service.call(uid, target, action, parameters(params), agent_id=agent_id),
                ensure_ascii=False,
            )
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)

    async def device_run(device_id: str, action: str, params: dict[str, Any]) -> str:
        """Submit an operation on the selected device and inspect its receipt.

        Owner devices execute enabled operations directly as their OS account.
        Restricted legacy devices retain their confirmation policy. Use Job
        tools for work that must survive a chat or connection ending.
        """
        try:
            uid, target = identity(device_id, writes=True)
            context = (get_config().get("configurable") or {}).get("octop_execution_context")
            if isinstance(context, dict):
                if context.get("target_kind") == "local":
                    return json.dumps(
                        await ExecutionService(service).call(
                            uid, context["context_id"], action, params, actor_agent_id=agent_id
                        ),
                        ensure_ascii=False,
                    )
                return json.dumps(
                    ExecutionService(service).submit(
                        uid,
                        context["context_id"],
                        action,
                        params,
                        actor_agent_id=agent_id,
                        task_run_id=task_run_id(),
                    ),
                    ensure_ascii=False,
                )
            return json.dumps(
                service.submit(
                    uid,
                    target,
                    action,
                    parameters(params),
                    agent_id=agent_id,
                    task_run_id=task_run_id(),
                ),
                ensure_ascii=False,
            )
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)

    async def device_operation_get(operation_id: str) -> str:
        """Read actual operation status and result; never presume a command was completed."""
        uid, _ = identity()
        return json.dumps(service.operation(uid, operation_id).public(), ensure_ascii=False)

    async def device_request_access(
        device_id: str, path: str, write: bool = False, execute: bool = False
    ) -> str:
        """Inspect owner access or propose a legacy restricted-device shared directory.

        Owner devices require no directory sharing request. Persistently disabled
        capabilities are managed in device settings; this tool does not enable
        them or elevate the OS account. Restricted clients use their legacy
        proposal flow; inspect its actual pending/applied result.
        """
        try:
            uid, target = identity(device_id, writes=True)
            device = service.owned(uid, target)
            if device.trust_mode == "owner":
                required = (
                    {"files_read"}
                    | ({"files_write"} if write else set())
                    | ({"command_exec"} if execute else set())
                )
                return json.dumps(
                    {
                        "device_id": target,
                        "trust_mode": "owner",
                        "directory_approval_required": False,
                        "policy_applied": service.owner_trusted(device),
                        "disabled_capabilities": sorted(required - set(device.permissions)),
                        "path": path,
                        "next_action": "Use native project tools and OS paths. Configure disabled capabilities in device settings; OS permission failures remain OS permission failures.",
                    },
                    ensure_ascii=False,
                )
            root_id = "requested-" + hashlib.sha256(path.encode()).hexdigest()[:16]
            existing = next((r for r in device.roots if r["path"] == path), None)
            roots = [r for r in device.roots if r["path"] != path]
            roots.append(
                {
                    "id": existing["id"] if existing else root_id,
                    "name": "Workspace",
                    "path": path,
                    "read": True,
                    "write": write or bool(existing and existing.get("write")),
                }
            )
            desired = set(device.permissions) | {"files_read"}
            if write:
                desired.add("files_write")
            if execute:
                desired.add("command_exec")
            return json.dumps(
                await service.create_grant_proposal(
                    uid,
                    target,
                    permissions=sorted(desired),
                    roots=roots,
                ),
                ensure_ascii=False,
            )
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)

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

    tools = [
        StructuredTool.from_function(coroutine=f)
        for f in (
            device_list,
            device_call,
            device_run,
            device_operation_get,
            device_transfer,
            device_request_access,
        )
    ]
    for tool in tools:
        tool.description += (
            " Project tools use the frozen execution context. Owner device paths "
            "are native OS paths: fs.list/read/stat use params={path}; command.run "
            "uses params={cwd, argv:[executable, args...], timeout:60}. Use job_start "
            "for persistent work. Legacy restricted files.* APIs use root_id and "
            "relative paths. Device policy and OS permission errors are distinct; "
            "owner devices do not need a directory-sharing proposal."
        )
        if bound_device_id:
            tool.description += (
                f" Expert target device_id={bound_device_id}; default root_id={bound_root_id}."
            )
    return tools
