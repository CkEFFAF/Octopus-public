"""Standard harness project tools routed through an immutable request context."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Coroutine
from typing import Any, TypeVar, cast

from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    ExecuteResponse,
    FileInfo,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)
from langgraph.config import get_config

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.service import ExecutionService

T = TypeVar("T")


class RequestExecutionBackend(SandboxBackendProtocol):
    def __init__(self, executions: ExecutionService, agent_id: str) -> None:
        self.executions = executions
        self.agent_id = agent_id
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    @property
    def id(self) -> str:
        return f"execution-{self.agent_id}"

    def _sync(self, task: Coroutine[Any, Any, T], *, timeout: int = 80) -> T:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if self._loop is None or current is self._loop:
            task.close()
            raise RuntimeError("use asynchronous project backend operations")
        future = asyncio.run_coroutine_threadsafe(task, self._loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise

    async def _call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        try:
            cfg = get_config().get("configurable") or {}
        except RuntimeError as exc:
            raise OctopError(
                ErrorCode.FORBIDDEN, "project tools require an execution context"
            ) from exc
        owner = int(cfg.get("user") or 0)
        context = cfg.get("octop_execution_context")
        if owner <= 0 or not isinstance(context, dict) or not context.get("context_id"):
            raise OctopError(
                ErrorCode.FORBIDDEN, "choose an execution device before using project tools"
            )
        value = await self.executions.call(
            owner, context["context_id"], action, params, actor_agent_id=self.agent_id
        )
        return cast(dict[str, Any], value["result"])

    async def call_operation(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Invoke an execution extension with the same authenticated context."""
        return await self._call(action, params)

    def ls(self, path: str) -> LsResult:
        return self._sync(self.als(path))

    async def als(self, path: str) -> LsResult:
        try:
            value = await self._call("fs.list", {"path": path})
            if value.get("next_offset") is not None:
                return LsResult(
                    error="directory has additional pages; use the device file API to page the listing",
                    entries=cast(list[FileInfo], value["entries"]),
                )
            return LsResult(entries=cast(list[FileInfo], value["entries"]))
        except (OctopError, ValueError) as exc:
            return LsResult(error=str(exc))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return self._sync(self.aread(file_path, offset, limit))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if offset < 0:
            return ReadResult(error="line offset must be nonnegative")
        if limit <= 0:
            return ReadResult(
                file_data={"content": "", "encoding": "utf-8"}, no_lines_requested=True
            )
        try:
            value = await self._call("fs.read", {"path": file_path})
            if not value["eof"]:
                return ReadResult(
                    error="file exceeds inline read limit; use the device file API or command"
                )
            text = base64.b64decode(value["data_b64"]).decode("utf-8")
            lines = text.splitlines()
            selected = lines[offset : offset + limit]
            first = offset + 1 if selected else None
            last = offset + len(selected) if selected else None
            return ReadResult(
                file_data={"content": "\n".join(selected), "encoding": "utf-8"},
                total_lines=len(lines),
                start_line=first,
                end_line=last,
                next_offset=last if last is not None and last < len(lines) else None,
            )
        except (OctopError, ValueError) as exc:
            return ReadResult(error=str(exc))

    def write(self, file_path: str, content: str) -> WriteResult:
        return self._sync(self.awrite(file_path, content))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        try:
            value = await self._call(
                "fs.write",
                {
                    "path": file_path,
                    "data_b64": base64.b64encode(content.encode()).decode(),
                    "create_only": True,
                },
            )
            return WriteResult(path=value["path"])
        except (OctopError, ValueError) as exc:
            return WriteResult(error=str(exc))

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        return self._sync(self.aedit(file_path, old_string, new_string, replace_all))

    async def aedit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        try:
            value = await self._call(
                "fs.edit",
                {
                    "path": file_path,
                    "old_string": old_string,
                    "new_string": new_string,
                    "replace_all": replace_all,
                },
            )
            return EditResult(path=value["path"], occurrences=value["occurrences"])
        except (OctopError, ValueError) as exc:
            return EditResult(error=str(exc))

    async def adelete(self, file_path: str) -> DeleteResult:
        try:
            value = await self._call("fs.remove", {"path": file_path})
            return DeleteResult(path=value["path"])
        except (OctopError, ValueError) as exc:
            return DeleteResult(error=str(exc))

    def delete(self, file_path: str) -> DeleteResult:
        return self._sync(self.adelete(file_path))

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return self._sync(self.aglob(pattern, path))

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        return self._sync(self.agrep(pattern, path, glob, max_count=max_count))

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            value = await self._call("fs.glob", {"pattern": pattern, "path": path or "."})
            return GlobResult(
                matches=cast(list[FileInfo], value["entries"]), truncated=value["truncated"]
            )
        except (OctopError, ValueError) as exc:
            return GlobResult(error=str(exc))

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        try:
            value = await self._call(
                "fs.grep",
                {"pattern": pattern, "path": path or ".", "glob": glob, "max_count": max_count},
            )
            return GrepResult(
                matches=cast(list[GrepMatch], value["matches"]), truncated=value["truncated"]
            )
        except (OctopError, ValueError) as exc:
            return GrepResult(error=str(exc))

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return self._sync(self.aexecute(command, timeout=timeout), timeout=(timeout or 60) + 20)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        try:
            cfg = get_config().get("configurable") or {}
            context = cfg.get("octop_execution_context")
            if not isinstance(context, dict):
                raise OctopError(ErrorCode.FORBIDDEN, "choose an execution device")
            row = self.executions.devices.owned(int(cfg.get("user") or 0), context["device_id"])
            argv = (
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
                if row.platform == "windows"
                else ["/bin/sh", "-c", command]
            )
            value = await self._call(
                "command.run", {"argv": argv, "timeout": timeout if timeout is not None else 60}
            )
            return ExecuteResponse(
                output=value["stdout"] + value["stderr"],
                exit_code=value["returncode"],
                truncated=value["truncated"],
            )
        except (OctopError, ValueError) as exc:
            return ExecuteResponse(output=str(exc), exit_code=None)
