"""Review and import a device skill using one authenticated frozen context."""

from __future__ import annotations

import base64
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.service import ExecutionService
from octop.infra.skills.external_sources import MAX_BYTES, MAX_FILES, external_package_digest
from octop.infra.skills.skill_packages import ResolvedSkillPackage, resolve_skill_package


class ExecutionSkillService:
    def __init__(self, executions: ExecutionService) -> None:
        self.executions = executions

    def _context(self, owner: int, context_id: str, agent_id: str) -> None:
        context = self.executions.get(owner, context_id)
        if context.agent_id != agent_id:
            raise OctopError(ErrorCode.FORBIDDEN, "skill source belongs to another expert context")

    async def discover(self, owner: int, context_id: str, agent_id: str) -> list[dict[str, Any]]:
        self._context(owner, context_id, agent_id)
        response = await self.executions.call(owner, context_id, "capabilities.discover", {})
        return [
            {
                **entry,
                "execution_context_id": context_id,
                "device_id": response["context"]["device_id"],
                "manifest": "",
                "files": [],
                "needs_inspection": True,
            }
            for entry in response["result"]["entries"]
            if entry["kind"] == "skill"
        ]

    async def inspect(
        self, owner: int, context_id: str, agent_id: str, source: str, slug: str, digest: str
    ) -> dict[str, Any]:
        self._context(owner, context_id, agent_id)
        response = await self.executions.call(
            owner,
            context_id,
            "capabilities.skill.inspect",
            {"source": source, "slug": slug, "digest": digest},
        )
        return {
            **response["result"],
            "execution_context_id": context_id,
            "device_id": response["context"]["device_id"],
        }

    async def package(
        self, owner: int, context_id: str, agent_id: str, source: str, slug: str, digest: str
    ) -> ResolvedSkillPackage:
        inspected = await self.inspect(owner, context_id, agent_id, source, slug, digest)
        names = inspected.get("files")
        if (
            not isinstance(names, list)
            or len(names) > MAX_FILES
            or not all(isinstance(name, str) for name in names)
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid skill snapshot file list")
        # Validate every native-relative package name before reading its bytes.
        resolve_skill_package(slug=slug, files=[(name, b"") for name in names], source=source)
        contents: list[tuple[str, bytes]] = []
        total = 0
        for name in names:
            if name.endswith("/"):
                contents.append((name, b""))
                continue
            native = str(inspected["path"]).rstrip("/\\") + "/" + name
            offset, chunks = 0, []
            while True:
                response = await self.executions.call(
                    owner,
                    context_id,
                    "fs.read",
                    {
                        "path": native,
                        "offset": offset,
                        "length": min(1048576, MAX_BYTES - total + 1),
                    },
                )
                result = response["result"]
                chunk = base64.b64decode(result["data_b64"], validate=True)
                total += len(chunk)
                if total > MAX_BYTES or (not chunk and not result["eof"]):
                    raise OctopError(ErrorCode.FORBIDDEN, "external skill exceeds transfer limit")
                chunks.append(chunk)
                offset += len(chunk)
                if result["eof"]:
                    break
            contents.append((name, b"".join(chunks)))
        package = resolve_skill_package(slug=slug, files=contents, source=source)
        if external_package_digest(package) != digest:
            raise OctopError(ErrorCode.FORBIDDEN, "external skill changed; refresh discovery")
        return package
