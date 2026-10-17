"""Resolve a target once and reuse that fact in tools and workbench panels."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from octop.infra.db.repos.execution import ExecutionContext, ExecutionContextRepo
from octop.infra.devices.protocol import JOB_READ_ACTIONS, result_status
from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.events import STREAM_ACTIONS, RunInspectionService
from octop.infra.execution.targets import LocalExecutionBackend
from octop.infra.users.preferences import parse_preferences_json
from octop.infra.utils.ulid import new_ulid

WORK_MODES = frozenset(
    {
        "agentic",
        "plan",
        "ask",
        "debug",
        "multitask",
        "cowork",
        "computer_use",
        "deep_research",
        "team",
    }
)
READ_ACTIONS = frozenset(
    {
        "ping",
        "status",
        "fs.list",
        "fs.stat",
        "fs.read",
        "fs.glob",
        "fs.grep",
        "fs.download.begin",
        "fs.download.chunk",
        "fs.download.close",
        "fs.upload.status",
        "files.list",
        "files.stat",
        "files.read",
        "desktop.capture",
        "jobs.list",
        "jobs.status",
        "jobs.logs",
        "git.snapshot",
        "terminal.poll",
        "capabilities.discover",
        "capabilities.skill.inspect",
        "browser.state",
        "browser.capture",
        "browser.observe",
    }
)


class ExecutionService:
    def __init__(self, devices: DeviceService) -> None:
        self.devices = devices

    @property
    def contexts(self) -> ExecutionContextRepo:
        return ExecutionContextRepo(self.devices.repos.db)

    def local_backend(self, owner: int) -> LocalExecutionBackend:
        user = self.devices.repos.user_repo.get(owner)
        if user is None or user.disabled or user.role != "admin":
            raise OctopError(
                ErrorCode.FORBIDDEN, "control-center execution requires an administrator"
            )
        if self.devices.local_execution is None:
            raise OctopError(ErrorCode.FORBIDDEN, "control-center execution is unavailable")
        return self.devices.local_execution

    def target(self, owner: int, context_id: str) -> dict[str, Any]:
        context = self.get(owner, context_id)
        if context.target_kind == "local":
            return self.local_backend(owner).metadata(owner)
        assert context.device_id is not None
        return {**self.devices.owned(owner, context.device_id).public(), "target_kind": "device"}

    def default_target(self, owner: int) -> dict[str, Any]:
        user = self.devices.repos.user_repo.get(owner)
        if user is None or user.disabled:
            raise OctopError(ErrorCode.FORBIDDEN, "execution account unavailable")
        preferences = parse_preferences_json(user.preferences_json)
        value = preferences.get("execution_default") or {}
        if not isinstance(value, dict):
            value = {}
        return {
            "device_id": value.get("device_id"),
            "working_dir": value.get("working_dir"),
            "target_kind": value.get("target_kind", "device"),
        }

    def save_default_target(
        self,
        owner: int,
        device_id: str | None,
        working_dir: str | None,
        target_kind: str = "device",
    ) -> dict[str, Any]:
        self._validate_target(owner, target_kind, device_id)
        if device_id:
            self.devices.owned(owner, device_id)
        if working_dir is not None and (
            not isinstance(working_dir, str) or "\x00" in working_dir or len(working_dir) > 4096
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid execution working directory")
        value = {
            "device_id": device_id or None,
            "working_dir": working_dir if device_id or target_kind == "local" else None,
            "target_kind": target_kind,
        }
        # Merge only this account setting. Concurrent preference writers must
        # not silently overwrite one another's fields.
        for _ in range(3):
            user = self.devices.repos.user_repo.get(owner)
            if user is None or user.disabled:
                raise OctopError(ErrorCode.FORBIDDEN, "execution account unavailable")
            preferences = parse_preferences_json(user.preferences_json)
            preferences["execution_default"] = value
            with self.devices.repos.db.transaction() as connection:
                changed = connection.execute(
                    "UPDATE users SET preferences_json = ? WHERE id = ? AND preferences_json = ?",
                    (json.dumps(preferences, ensure_ascii=False), owner, user.preferences_json),
                ).rowcount
            if changed:
                return value
        raise OctopError(
            ErrorCode.WORKFLOW_CONFLICT, "account preferences changed; refresh and retry"
        )

    def _validate_target(self, owner: int, kind: str, device_id: str | None) -> None:
        if kind == "local":
            if device_id:
                raise OctopError(ErrorCode.FORBIDDEN, "local target cannot also select a device")
            self.local_backend(owner)
        elif kind != "device":
            raise OctopError(ErrorCode.FORBIDDEN, "invalid execution target kind")

    @staticmethod
    def has_target(value: dict[str, Any] | None) -> bool:
        return bool(value and (value.get("device_id") or value.get("target_kind") == "local"))

    def resolve(
        self,
        owner: int,
        *,
        device_id: str | None = None,
        target_kind: str | None = None,
        agent_id: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        working_dir: str | None = None,
        work_mode: str | None = None,
        binding: dict[str, Any] | None = None,
    ) -> ExecutionContext:
        if thread_id is not None:
            thread = self.devices.repos.thread_repo.get(thread_id)
            if (
                thread is None
                or thread.user_id != owner
                or (agent_id and thread.agent_id != agent_id)
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "execution thread unavailable")
            agent_id = agent_id or thread.agent_id
        if agent_id is not None:
            agent = self.devices.repos.agent_repo.get(agent_id)
            if agent is None or agent.user_id != owner:
                raise OctopError(ErrorCode.FORBIDDEN, "expert cannot use this execution target")
            if binding is None:
                binding = json.loads(agent.config_json or "{}").get("device_binding") or {}
        saved = self.contexts.selection(owner, thread_id) if thread_id else {}
        work_mode = work_mode or saved.get("work_mode") or "agentic"
        if work_mode not in WORK_MODES:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid execution mode")
        binding = binding or {}
        defaults = self.default_target(owner)
        explicit = {"device_id": device_id, "target_kind": target_kind or "device"}
        if target_kind is not None:
            self._validate_target(owner, target_kind, device_id)
        candidates = [
            (explicit, "session_selection"),
            (saved, "session_selection"),
            (binding, "expert_default"),
            (defaults, "account_default"),
        ]
        choice = next(
            ((value, source) for value, source in candidates if self.has_target(value)), None
        )
        if choice is None:
            raise OctopError(ErrorCode.FORBIDDEN, "choose an execution device")
        chosen, source = choice
        kind = chosen.get("target_kind", "device")
        selected = chosen.get("device_id")
        self._validate_target(owner, kind, selected)
        row = self.devices.owned(owner, selected) if selected else None
        inherited = source == "expert_default" or (
            self.has_target(binding)
            and selected == binding.get("device_id")
            and kind == binding.get("target_kind", "device")
        )
        session_directory = (
            saved.get("working_dir")
            if (
                not self.has_target(explicit)
                or (
                    device_id == saved.get("device_id")
                    and kind == saved.get("target_kind", "device")
                )
            )
            else None
        )
        directory = (
            working_dir
            or session_directory
            or (
                binding.get("working_dir")
                if inherited
                else defaults.get("working_dir")
                if source == "account_default"
                else None
            )
        )
        if directory is None and inherited and binding.get("root_id") and row is not None:
            root = next((r for r in row.roots if r["id"] == binding["root_id"]), None)
            directory = root["path"] if root else None
        directory = directory or (
            row.working_dir or (row.runtime_metadata or {}).get("working_dir")
            if row is not None
            else self.local_backend(owner).metadata(owner)["working_dir"]
        )
        if directory is not None and (not isinstance(directory, str) or "\x00" in directory):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid execution working directory")
        return self.contexts.create(
            owner_user_id=owner,
            device_id=row.device_id if row else None,
            target_kind=kind,
            working_dir=directory,
            policy_revision=row.policy_revision if row else self.local_backend(owner).revision,
            grant_version=row.grant_version if row else self.local_backend(owner).revision,
            work_mode=work_mode,
            source=source,
            agent_id=agent_id,
            thread_id=thread_id,
            run_id=run_id,
        )

    def validate_expert_binding(self, owner: int, binding: dict[str, Any]) -> dict[str, Any]:
        """Validate a bounded default target without creating an execution or changing grants."""
        if not isinstance(binding, dict) or not set(binding) <= {
            "device_id",
            "target_kind",
            "root_id",
            "working_dir",
        }:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid expert device binding")
        if not binding:
            return {}
        device_id, root_id = binding.get("device_id"), binding.get("root_id")
        kind = binding.get("target_kind", "device")
        if root_id is not None and not isinstance(root_id, str):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid expert device binding")
        if kind == "local":
            if device_id or root_id:
                raise OctopError(ErrorCode.FORBIDDEN, "local target cannot select a device root")
            self.local_backend(owner)
        elif kind == "device" and isinstance(device_id, str) and device_id.strip():
            device = self.devices.owned(owner, device_id)
            root = next((r for r in device.roots if r["id"] == root_id), None)
            if device.trust_mode != "owner" and (root is None or not root.get("read")):
                raise OctopError(
                    ErrorCode.FORBIDDEN, "expert device requires a readable shared root"
                )
        else:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid expert target kind")
        directory = binding.get("working_dir")
        if directory is not None and (
            not isinstance(directory, str)
            or not directory.strip()
            or "\x00" in directory
            or len(directory) > 4096
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid expert working directory")
        return {**binding, "target_kind": kind}

    def get(self, owner: int, context_id: str) -> ExecutionContext:
        context = self.contexts.get(owner, context_id)
        if context is None:
            raise OctopError(ErrorCode.NOT_FOUND, "execution context not found")
        if context.target_kind == "local":
            self._validate_target(owner, "local", context.device_id)
        elif context.target_kind == "device" and context.device_id:
            self.devices.owned(owner, context.device_id)
        else:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid persisted execution target")
        if context.agent_id:
            agent = self.devices.repos.agent_repo.get(context.agent_id)
            if agent is None or agent.user_id != owner:
                raise OctopError(ErrorCode.NOT_FOUND, "execution expert unavailable")
        if context.thread_id:
            thread = self.devices.repos.thread_repo.get(context.thread_id)
            if thread is None or thread.user_id != owner or thread.agent_id != context.agent_id:
                raise OctopError(ErrorCode.NOT_FOUND, "execution thread unavailable")
        return context

    def selection(self, owner: int, thread_id: str) -> dict[str, Any]:
        thread = self.devices.repos.thread_repo.get(thread_id)
        if thread is None or thread.user_id != owner:
            raise OctopError(ErrorCode.NOT_FOUND, "execution thread unavailable")
        return self.contexts.selection(owner, thread_id)

    def for_run(
        self,
        owner: int,
        context_id: str,
        *,
        agent_id: str,
        thread_id: str | None,
        run_id: str,
        observe_mode: str | None = None,
    ) -> ExecutionContext:
        """Bind one run/peer without mutating its inherited target or policy."""
        origin = self.get(owner, context_id)
        agent = self.devices.repos.agent_repo.get(agent_id)
        if agent is None or agent.user_id != owner:
            raise OctopError(ErrorCode.FORBIDDEN, "execution expert unavailable")
        if thread_id:
            thread = self.devices.repos.thread_repo.get(thread_id)
            if thread is None or thread.user_id != owner or thread.agent_id != agent_id:
                raise OctopError(ErrorCode.FORBIDDEN, "execution thread unavailable")
        mode = observe_mode if observe_mode in {"ask", "plan"} else origin.work_mode
        context = origin
        if (origin.run_id, origin.agent_id, origin.thread_id, origin.work_mode) != (
            run_id,
            agent_id,
            thread_id,
            mode,
        ):
            context = self.contexts.create(
                owner_user_id=owner,
                device_id=origin.device_id,
                target_kind=origin.target_kind,
                working_dir=origin.working_dir,
                policy_revision=origin.policy_revision,
                grant_version=origin.grant_version,
                work_mode=mode,
                source="parent_run" if origin.agent_id != agent_id else origin.source,
                agent_id=agent_id,
                thread_id=thread_id,
                run_id=run_id,
            )
        RunInspectionService(self.devices.repos).events.save(
            event_id=f"context:{context.context_id}",
            owner=owner,
            agent_id=agent_id,
            thread_id=thread_id,
            run_id=run_id,
            context_id=context.context_id,
            kind="target",
            status="bound",
            created_at=context.created_at,
            payload={
                "device_id": context.device_id,
                "target_kind": context.target_kind,
                "working_dir": context.working_dir,
                "work_mode": context.work_mode,
                "policy_revision": context.policy_revision,
                "grant_version": context.grant_version,
                "parent_context_id": origin.context_id
                if origin.context_id != context.context_id
                else None,
                "os_user": self.target(owner, context.context_id).get("runtime", {}).get("os_user"),
            },
        )
        return context

    def save_selection(self, owner: int, thread_id: str, values: dict[str, Any]) -> dict[str, Any]:
        current = self.selection(owner, thread_id)
        merged = {**current, **values}
        if "device_id" in values and "target_kind" not in values:
            merged["target_kind"] = "device"
        self._validate_target(owner, merged.get("target_kind", "device"), merged.get("device_id"))
        if merged.get("device_id"):
            self.devices.owned(owner, merged["device_id"])
        if merged["work_mode"] not in WORK_MODES:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid execution mode")
        directory = merged.get("working_dir")
        if directory is not None and (not isinstance(directory, str) or "\x00" in directory):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid execution working directory")
        self.contexts.save_selection(owner, thread_id, merged)
        return merged

    def _prepare(
        self,
        owner: int,
        context_id: str,
        action: str,
        params: dict[str, Any],
        *,
        actor_agent_id: str | None = None,
    ) -> tuple[ExecutionContext, dict[str, Any]]:
        context = self.get(owner, context_id)
        if actor_agent_id is not None and context.agent_id != actor_agent_id:
            raise OctopError(ErrorCode.FORBIDDEN, "execution context belongs to another expert")
        if context.work_mode in {"ask", "plan"} and action not in READ_ACTIONS:
            raise OctopError(ErrorCode.FORBIDDEN, "execution mode only permits observation")
        row = self.devices.owned(owner, context.device_id) if context.device_id else None
        if (
            row is not None
            and action not in JOB_READ_ACTIONS
            and (
                row.policy_revision != context.policy_revision
                or row.grant_version != context.grant_version
            )
        ):
            raise OctopError(
                ErrorCode.FORBIDDEN, "execution policy changed; start a new execution context"
            )
        if context.target_kind == "local" and (
            context.policy_revision != self.local_backend(owner).revision
            or context.grant_version != self.local_backend(owner).revision
        ):
            raise OctopError(
                ErrorCode.FORBIDDEN, "local execution policy changed; start a new context"
            )
        prepared = dict(params)
        prepared["execution_context_id"] = context.context_id
        prepared["policy_revision"] = context.policy_revision
        prepared["grant_version"] = context.grant_version
        if action.startswith("browser."):
            prepared["browser_lane"] = hashlib.sha256(
                json.dumps([owner, context.agent_id, context.thread_id]).encode()
            ).hexdigest()
        if context.working_dir:
            prepared.setdefault("cwd", context.working_dir)
        return context, prepared

    def submit(
        self,
        owner: int,
        context_id: str,
        action: str,
        params: dict[str, Any],
        *,
        actor_agent_id: str,
        task_run_id: str | None = None,
    ) -> dict[str, Any]:
        context, prepared = self._prepare(
            owner, context_id, action, params, actor_agent_id=actor_agent_id
        )
        if context.target_kind == "local":
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "use the execution call or persistent Job interface for a local target",
            )
        assert context.device_id is not None
        operation = self.devices.submit(
            owner,
            context.device_id,
            action,
            prepared,
            agent_id=actor_agent_id,
            task_run_id=task_run_id,
        )
        if action not in STREAM_ACTIONS:
            RunInspectionService(self.devices.repos).device_receipt(
                context, operation["operation_id"], action, operation["status"], prepared
            )
        return operation

    async def call(
        self,
        owner: int,
        context_id: str,
        action: str,
        params: dict[str, Any],
        *,
        actor_agent_id: str | None = None,
    ) -> dict[str, Any]:
        context, prepared = self._prepare(
            owner, context_id, action, params, actor_agent_id=actor_agent_id
        )
        operation_id = new_ulid()
        inspect = RunInspectionService(self.devices.repos)
        trace = action not in STREAM_ACTIONS
        if trace:
            inspect.device_receipt(context, operation_id, action, "started", prepared)
        try:
            from octop.infra.execution.targets import DeviceExecutionBackend

            backend = (
                self.local_backend(owner)
                if context.target_kind == "local"
                else DeviceExecutionBackend(self.devices)
            )
            result = await backend.call(context, operation_id, action, prepared)
        except asyncio.CancelledError:
            if trace:
                inspect.device_receipt(context, operation_id, action, "unknown", prepared)
            raise
        except Exception as exc:
            if trace:
                state = (
                    "unknown"
                    if isinstance(exc, (TimeoutError, OSError))
                    or isinstance(exc, OctopError)
                    and exc.code == ErrorCode.DEVICE_OFFLINE
                    else "failed"
                )
                receipt = self.devices.repos.device_repo.get_operation(operation_id, owner)
                inspect.device_receipt(
                    context, operation_id, action, receipt.status if receipt else state, prepared
                )
            raise
        if trace:
            inspect.device_receipt(
                context, operation_id, action, result_status(action, result), prepared, result
            )
        if action in {"jobs.status", "jobs.start", "jobs.cancel"}:
            inspect.job_observation(context, result)
        elif action in {"desktop.capture", "desktop.input", "browser.capture"} or (
            action == "browser.action" and prepared.get("command") != "reset_input"
        ):
            inspect.interaction_observation(
                context,
                action,
                {**prepared, "session_id": result.get("session_id") or prepared.get("session_id")},
            )
        elif action == "jobs.list":
            for job in result.get("jobs", []):
                inspect.job_observation(context, job)
        return {
            "context": context.public(),
            "result": result,
            "operation_id": operation_id,
            "status": result_status(action, result),
        }
